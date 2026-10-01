"""Importa o cadastro de pacientes exportado do sistema anterior.

    python manage.py import_pacientes_xml --clinica <slug> --arquivo <x.xml>
    python manage.py import_pacientes_xml --clinica <slug> --arquivo <x.xml> --gravar

**Ensaio por padrão, gravação só com `--gravar`.** Sem isso, o comando lê,
traduz, aponta todo conflito e não escreve nada — que é como se confere
uma migração de duas mil fichas antes de deixá-la tocar o prontuário de
produção. A assimetria é deliberada: ensaiar de novo custa um minuto,
desfazer uma importação errada custa uma restauração de backup.

**Pode ser repetido.** A ficha é casada pelo `legacy_id` (o número dela no
sistema de origem). Rodar duas vezes atualiza as mesmas fichas em vez de
duplicá-las, e é isso que permite retomar uma importação que falhou no
meio.

**O que ele nunca faz:** apagar, arquivar quem estava ativo, ou mexer em
ficha que não veio desta importação.

**E nunca cria uma segunda ficha para quem já está cadastrado.** Quando o
CPF do arquivo já pertence a uma ficha desta clínica, a ficha de lá é
**pulada** — não entra sem CPF ao lado da que existe. Dois prontuários
para a mesma pessoa partem o histórico clínico em dois, e o dano aparece
no dia em que alguém abre o errado: a consulta de março está num, a de
setembro no outro, e nenhum dos dois está errado o bastante para alguém
desconfiar.

`--conflito-cpf anotar` força o comportamento oposto, para o caso em que
se sabe que são pessoas diferentes com o mesmo CPF digitado. O padrão é
pular porque o erro de pular é recuperável (a ficha de lá continua no
arquivo, e pode ser importada depois) e o de duplicar não é.
"""
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from patients.contacts import SELF_RELATIONSHIP
from patients.importacao import CAMPOS_ESPERADOS, ler_registro
from patients.models import Patient, PatientContact, PatientStatus, RegistrationStage
from tenancy.models import Tenant

#: Quantas fichas por transação. Uma transação única de duas mil fichas
#: segura o contador de prontuário (`select_for_update`) do começo ao fim
#: e, se estourar na última, desfaz as duas mil. Em lotes, o que já entrou
#: fica — e a reexecução retoma de onde parou pelo `legacy_id`.
LOTE = 200


class Command(BaseCommand):
    help = 'Importa pacientes de um XML exportado do sistema anterior.'

    def add_arguments(self, parser):
        parser.add_argument('--clinica', required=True, help='slug da clínica de destino')
        parser.add_argument('--arquivo', required=True, help='caminho do XML')
        parser.add_argument(
            '--gravar', action='store_true',
            help='grava de verdade. Sem isto, o comando apenas ensaia.',
        )
        parser.add_argument(
            '--conflito-cpf', choices=['pular', 'anotar'], default='pular',
            help=(
                'o que fazer quando o CPF do arquivo ja pertence a uma ficha '
                'desta clinica. "pular" (padrao) nao cria a ficha de la; '
                '"anotar" cria sem CPF, com o conflito escrito.'
            ),
        )

    def handle(self, *args, **opcoes):
        tenant = Tenant.objects.filter(slug=opcoes['clinica']).first()
        if tenant is None:
            raise CommandError(f'Clínica {opcoes["clinica"]!r} não existe.')

        try:
            raiz = ET.parse(opcoes['arquivo']).getroot()
        except (OSError, ET.ParseError) as erro:
            raise CommandError(f'Não foi possível ler o XML: {erro}') from erro

        registros = list(raiz)
        if not registros:
            raise CommandError('O arquivo não tem registro nenhum.')

        presentes = {filho.tag for filho in registros[0]}
        faltando = CAMPOS_ESPERADOS - presentes
        if faltando:
            # Arquivo com outra forma importaria duas mil fichas vazias em
            # silêncio. Melhor recusar e dizer o que falta.
            raise CommandError(
                'O arquivo não tem a forma esperada. Campos ausentes: '
                + ', '.join(sorted(faltando))
            )

        self.conflito = opcoes['conflito_cpf']
        gravar = opcoes['gravar']
        self.stdout.write(
            f'Clínica : {tenant.trade_name or tenant.legal_name} ({tenant.slug})\n'
            f'Arquivo : {opcoes["arquivo"]}\n'
            f'Fichas  : {len(registros)}\n'
            f'Modo    : {"GRAVANDO" if gravar else "ENSAIO (nada será escrito)"}\n'
        )

        fichas, sem_nome = [], 0
        for registro in registros:
            ficha = ler_registro(registro)
            if ficha is None:
                sem_nome += 1
                continue
            fichas.append(ficha)

        resultado = self._conferir(tenant, fichas)
        self._relatar(resultado, sem_nome, len(registros))

        if not gravar:
            self.stdout.write(self.style.WARNING(
                '\nEnsaio: nada foi gravado. Repita com --gravar para valer.'
            ))
            return

        contagem = self._gravar(tenant, fichas, resultado)
        self.stdout.write(self.style.SUCCESS(
            f'\nGravado: {contagem["criados"]} ficha(s) nova(s), '
            f'{contagem["atualizados"]} atualizada(s), '
            f'{contagem["contatos"]} contato(s), '
            f'{contagem["pulados"]} pulada(s) por ja existirem aqui.'
        ))

    # ------------------------------------------------------------ análise

    def _conferir(self, tenant, fichas):
        """Levanta os conflitos **antes** de escrever qualquer coisa.

        Conflito descoberto no meio da gravação vira metade da clínica
        importada e metade não. Levantar antes permite relatar tudo e
        decidir de uma vez.
        """
        por_cpf = defaultdict(list)
        for ficha in fichas:
            if ficha['cpf']:
                por_cpf[ficha['cpf']].append(ficha)

        # Entre as próprias fichas do arquivo: o primeiro fica com o CPF.
        cpf_repetido = set()
        for cpf, lista in por_cpf.items():
            if len(lista) > 1:
                for ficha in lista[1:]:
                    ficha['cpf_conflitante'] = cpf
                    ficha['cpf'] = ''
                cpf_repetido.add(cpf)

        # Contra quem já está cadastrado na clínica: ficha daqui nunca é
        # sobrescrita por ficha de lá.
        ja_cadastrados = dict(
            Patient.objects.filter(
                tenant=tenant, cpf__in=[f['cpf'] for f in fichas if f['cpf']],
            ).exclude(legacy_id='').values_list('cpf', 'legacy_id')
        )
        daqui = set(
            Patient.objects.filter(
                tenant=tenant, cpf__in=[f['cpf'] for f in fichas if f['cpf']], legacy_id='',
            ).values_list('cpf', flat=True)
        )
        for ficha in fichas:
            if ficha['cpf'] and ficha['cpf'] in daqui:
                ficha['cpf_ja_de_outra_ficha'] = ficha['cpf']
                ficha['cpf'] = ''
                if self.conflito == 'pular':
                    ficha['pular'] = True

        existentes = set(
            Patient.objects.filter(tenant=tenant).exclude(legacy_id='')
            .values_list('legacy_id', flat=True)
        )
        return {
            'cpf_repetido': cpf_repetido,
            'cpf_de_ficha_daqui': daqui,
            'ja_importados': existentes,
            'ja_cadastrados': ja_cadastrados,
        }

    def _relatar(self, resultado, sem_nome, total_lido):
        linhas = [
            f'  lidas do arquivo        : {total_lido}',
            f'  sem nome (ignoradas)    : {sem_nome}',
            f'  ja importadas antes     : {len(resultado["ja_importados"])}'
            f'  (serao atualizadas)',
            f'  CPF repetido no arquivo : {len(resultado["cpf_repetido"])}'
            f'  (o 1o fica com o CPF; os outros entram sem, com observacao)',
            f'  CPF de ficha ja daqui   : {len(resultado["cpf_de_ficha_daqui"])}'
            + ('  (a ficha de la sera PULADA; a daqui nao e tocada)'
               if self.conflito == 'pular'
               else '  (a ficha de la entra SEM CPF; a daqui nao e tocada)'),
        ]
        self.stdout.write('\n'.join(linhas))

    # ----------------------------------------------------------- gravação

    def _gravar(self, tenant, fichas, resultado):
        criados = atualizados = contatos = pulados = 0
        for inicio in range(0, len(fichas), LOTE):
            lote = fichas[inicio:inicio + LOTE]
            with transaction.atomic():
                for ficha in lote:
                    if ficha.get('pular'):
                        pulados += 1
                        continue
                    novo, qtd = self._gravar_uma(tenant, ficha)
                    criados += int(novo)
                    atualizados += int(not novo)
                    contatos += qtd
            self.stdout.write(
                f'  ... {min(inicio + LOTE, len(fichas))}/{len(fichas)}'
            )

        record_audit_event(
            None, tenant.id, 'patients.bulk_import',
            object_type='tenant', object_id=tenant.id, outcome='success',
            integrity_metadata={
                'criados': criados, 'atualizados': atualizados,
                'contatos': contatos, 'pulados': pulados, 'origem': 'xml',
            },
        )
        return {'criados': criados, 'atualizados': atualizados,
                'contatos': contatos, 'pulados': pulados}

    def _gravar_uma(self, tenant, ficha):
        anotacoes = list(ficha['anotacoes'])
        if ficha.get('cpf_conflitante'):
            anotacoes.append(
                f'CPF {ficha["cpf_conflitante"]} veio repetido na importação e ficou '
                f'com a outra ficha. Confira e corrija no próximo atendimento.'
            )
        if ficha.get('cpf_ja_de_outra_ficha'):
            anotacoes.append(
                f'CPF {ficha["cpf_ja_de_outra_ficha"]} já pertencia a uma ficha '
                f'cadastrada nesta clínica. Confira se são a mesma pessoa.'
            )
        anotacoes.append(f'Ficha migrada do sistema anterior em {timezone.localdate():%d/%m/%Y}.')

        campos = {
            chave: ficha[chave] for chave in (
                'full_name', 'birth_date', 'sex_at_registration', 'marital_status',
                'occupation', 'identity_number', 'street', 'number', 'complement',
                'district', 'city', 'state', 'postal_code', 'country',
                'payment_category', 'referral_source', 'referral_details',
            )
        }
        campos['cpf'] = ficha['cpf'] or None
        campos['birth_date_unknown_reason'] = ficha.get('birth_date_unknown_reason', '')
        campos['administrative_notes'] = '\n'.join(anotacoes)[:2000]
        # Cadastro de verdade, e não pré-cadastro: tem nome, nascimento,
        # documento e endereço. Marcar como "pré" o esconderia da lista de
        # pacientes, que é onde ele precisa aparecer.
        campos['registration_stage'] = RegistrationStage.COMPLETE
        # Cancelado lá vira arquivado aqui: preserva a ficha sem poluir a
        # lista de quem a clínica acompanha, e arquivar libera a vaga do
        # plano.
        if ficha['cancelado']:
            campos['status'] = PatientStatus.ARCHIVED
            campos['archived_at'] = timezone.now()
            campos['archived_reason'] = 'Cancelado no sistema anterior.'

        paciente, criado = Patient.objects.update_or_create(
            tenant=tenant, legacy_id=ficha['legacy_id'], defaults=campos,
        )
        return criado, self._contatos(tenant, paciente, ficha)

    def _contatos(self, tenant, paciente, ficha):
        """O contato do próprio paciente e, quando houver, o do responsável.

        **Nada é autorizado a receber mensagem.** `sms_enabled`,
        `email_enabled` e `authorized_for_documents` nascem desligados: o
        sistema anterior não registrou consentimento algum, e importar um
        telefone não é a pessoa pedindo para ser chamada nele. A secretária
        liga a autorização quando falar com cada um — que é exatamente o
        momento em que ela existe.
        """
        criados = 0
        telefone = ficha['telefones'][0] if ficha['telefones'] else ''
        if telefone or ficha['email']:
            _, novo = PatientContact.objects.update_or_create(
                tenant=tenant, patient=paciente, relationship=SELF_RELATIONSHIP,
                defaults={
                    'name': paciente.full_name[:255],
                    'phone': telefone[:16],
                    'email': ficha['email'],
                    'sms_enabled': False,
                    'email_enabled': False,
                    'authorized_for_documents': False,
                },
            )
            criados += int(novo)

        responsavel = ficha['responsavel']
        # **O responsável que é o próprio paciente não vira um segundo
        # contato.** Oitenta e cinco fichas do arquivo trazem, no campo
        # "responsável", o nome do próprio paciente — o sistema anterior
        # usava aquele campo também para "responde por si".
        #
        # Sem esta guarda o estrago era duplo e silencioso: a gravação do
        # responsável casava com o contato do próprio paciente **pelo
        # nome**, trocava a relação dele de "Próprio paciente" para
        # "Responsável" e apagava o telefone que acabara de ser gravado. Na
        # segunda execução, aí sim, estourava com dois contatos de mesmo
        # nome -- e o erro aparecia longe da causa.
        if not responsavel or responsavel == paciente.full_name:
            return criados
        parentesco = (ficha['responsavel_parentesco'] or 'Responsável').strip()[:100]
        if parentesco.casefold() == SELF_RELATIONSHIP.casefold():
            return criados

        segundo = ficha['telefones'][1] if len(ficha['telefones']) > 1 else ''
        # Busca explícita em vez de `update_or_create`: é preciso **excluir**
        # o contato do próprio paciente da procura, e `update_or_create` não
        # aceita exclusão. Sem isso, um homônimo entre paciente e
        # responsável traria o problema de volta por outro caminho.
        existente = PatientContact.objects.filter(
            tenant=tenant, patient=paciente, name=responsavel,
        ).exclude(relationship=SELF_RELATIONSHIP).first()
        if existente is None:
            PatientContact.objects.create(
                tenant=tenant, patient=paciente, name=responsavel,
                relationship=parentesco, phone=segundo[:16],
                sms_enabled=False, email_enabled=False,
                authorized_for_documents=False,
            )
            criados += 1
        else:
            existente.relationship = parentesco
            existente.phone = segundo[:16]
            existente.save(update_fields=['relationship', 'phone'])
        return criados

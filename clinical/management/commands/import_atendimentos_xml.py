"""Importa o histórico de atendimentos exportado do sistema anterior (iClin).

    python manage.py import_atendimentos_xml --clinica <slug> --medico <e-mail> \\
        --arquivo <anotacoes.xml> --ate 2026-10-02
    ... --gravar

**Ensaio por padrão, gravação só com `--gravar`**, pela mesma razão do
`import_pacientes_xml`: ensaiar custa um minuto, desfazer sete mil
atendimentos finalizados custa uma restauração de backup.

**Cada anotação vira um atendimento de texto livre já finalizado**
(`clinical/importacao.py` diz o que vai para cada campo). A finalização
**não** passa por `finalize_encounter`, e isso é a decisão central do
comando: finalizar ali publica `clinical.encounter_finalized`, que cria a
**cobrança** da consulta (`finance.handlers`) e pede o **resumo à IA**
(`ai.handlers`). Pelo caminho normal seriam sete mil cobranças de consultas
pagas anos atrás e sete mil pedidos ao provedor. Aqui a linha é gravada já
fechada, com o hash calculado do mesmo jeito, uma entrada na trilha por
rodada e nenhum evento.

**O paciente é casado pelo número do iClin e conferido pelo nome.** A
migração do cadastro gravou o número em `Patient.legacy_id`; o comando
exige que o nome também bata (sem acento nem pontuação), para que um número
reaproveitado não ponha a consulta de uma pessoa na ficha de outra. Quem
não casa por número cai no nome com a data de nascimento, e só quando há
exatamente uma ficha assim. O resto é relatado e fica de fora.

**`--ate` é obrigatório.** A partir do dia em que a clínica passou a
atender no NeuroDoc, as consultas já estão aqui; a anotação do iClin do
mesmo período seria a segunda via da mesma visita. Mesmo antes do corte,
o dia em que o paciente já tem atendimento escrito no NeuroDoc é pulado.

**Pode ser repetido.** A anotação gravada carrega `iclin:<número>` em
`Encounter.legacy_id`, com unicidade no banco: a segunda rodada passa por
cima do que já entrou.

**O alerta da anotação** (o campo "alerta" do iClin, que é sobre o
paciente e não sobre a consulta) vai para as observações administrativas
da ficha, uma vez, e só se couber nelas.
"""
import hashlib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinical.importacao import CAMPOS_ESPERADOS, excede_limite, ler_anotacao, nome_comparavel
from clinical.models import Encounter, EncounterKind, EncounterStatus
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Role, Tenant

LOTE = 500
NOTAS_MAX = Patient._meta.get_field('administrative_notes').max_length


class Command(BaseCommand):
    help = 'Importa o histórico de atendimentos de um XML exportado do iClin.'

    def add_arguments(self, parser):
        parser.add_argument('--clinica', required=True, help='slug da clínica de destino')
        parser.add_argument('--medico', required=True, help='e-mail do médico autor das anotações')
        parser.add_argument('--arquivo', required=True, help='caminho do XML')
        parser.add_argument('--ate', required=True, help='último dia a migrar (AAAA-MM-DD), inclusive')
        parser.add_argument('--gravar', action='store_true', help='grava de verdade. Sem isto, apenas ensaia.')

    def handle(self, *args, **opcoes):
        tenant = Tenant.objects.filter(slug=opcoes['clinica']).first()
        if tenant is None:
            raise CommandError(f'Clínica {opcoes["clinica"]!r} não existe.')
        medico = (
            Membership.objects.select_related('user')
            .filter(tenant=tenant, user__email__iexact=opcoes['medico'], status=MembershipStatus.ACTIVE,
                    roles__contains=[Role.DOCTOR])
            .first()
        )
        if medico is None:
            raise CommandError('Esse e-mail não tem vínculo ativo de médico nesta clínica.')
        try:
            ate = date.fromisoformat(opcoes['ate'])
        except ValueError as erro:
            raise CommandError('--ate deve ser uma data AAAA-MM-DD.') from erro

        try:
            with open(opcoes['arquivo'], 'rb') as arquivo:
                conteudo = arquivo.read()
            raiz = ET.fromstring(conteudo)
        except (OSError, ET.ParseError) as erro:
            raise CommandError(f'Não foi possível ler o XML: {erro}') from erro
        registros = list(raiz)
        if not registros:
            raise CommandError('O arquivo não tem anotação nenhuma.')
        faltando = CAMPOS_ESPERADOS - {filho.tag for filho in registros[0]}
        if faltando:
            raise CommandError('O arquivo não tem a forma esperada. Campos ausentes: ' + ', '.join(sorted(faltando)))

        gravar = opcoes['gravar']
        self.stdout.write(
            f'Clínica : {tenant.trade_name or tenant.legal_name} ({tenant.slug})\n'
            f'Médico  : {medico.user.get_full_name() or medico.user.email}\n'
            f'Anotações no arquivo: {len(registros)}\n'
            f'Até     : {ate:%d/%m/%Y} (inclusive)\n'
            f'Modo    : {"GRAVANDO" if gravar else "ENSAIO (nada será escrito)"}\n'
        )

        plano = self._planejar(tenant, registros, ate)
        self._relatar(plano)
        if not gravar:
            self.stdout.write(self.style.WARNING('\nEnsaio: nada foi gravado. Repita com --gravar para valer.'))
            return

        criados, alertas = self._gravar(tenant, medico, plano)
        record_audit_event(
            medico.user_id, tenant.id, 'clinical.encounters_imported', object_type='tenant', object_id=tenant.id,
            purpose='Migração do histórico de atendimentos do iClin',
            integrity_metadata={
                'criados': criados, 'alertas_nas_observacoes': alertas, 'ate': ate.isoformat(),
                'arquivo_sha256': hashlib.sha256(conteudo).hexdigest(),
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f'\nGravado: {criados} atendimento(s) migrado(s); alerta escrito em {alertas} ficha(s).'
        ))

    # ------------------------------------------------------------ análise

    def _casar_pacientes(self, tenant):
        pacientes = list(Patient.objects.filter(tenant=tenant).values('id', 'legacy_id', 'full_name', 'birth_date'))
        por_numero = {p['legacy_id']: p for p in pacientes if p['legacy_id']}
        por_nome_nascimento = defaultdict(list)
        for p in pacientes:
            por_nome_nascimento[(nome_comparavel(p['full_name']), p['birth_date'])].append(p)

        cache = {}

        def casar(anotacao):
            chave = anotacao['cliente']
            if chave not in cache:
                p = por_numero.get(chave)
                if p and nome_comparavel(p['full_name']) == nome_comparavel(anotacao['nome']):
                    cache[chave] = (p['id'], 'número e nome')
                else:
                    candidatos = por_nome_nascimento.get(
                        (nome_comparavel(anotacao['nome']), anotacao['nascimento']), [],
                    ) if anotacao['nascimento'] else []
                    if len(candidatos) == 1:
                        cache[chave] = (candidatos[0]['id'], 'nome e nascimento')
                    elif p:
                        cache[chave] = (None, 'número com outro nome')
                    elif len(candidatos) > 1:
                        cache[chave] = (None, 'mais de uma ficha com esse nome e nascimento')
                    else:
                        cache[chave] = (None, 'sem ficha correspondente')
            return cache[chave]

        return casar

    def _planejar(self, tenant, registros, ate):
        casar = self._casar_pacientes(tenant)
        ja_migrados = set(
            Encounter.objects.filter(tenant=tenant).exclude(legacy_id='').values_list('legacy_id', flat=True)
        )
        dias_no_neurodoc = defaultdict(set)
        for paciente_id, quando in (
            Encounter.objects.filter(tenant=tenant, legacy_id='').values_list('patient_id', 'occurred_at')
        ):
            dias_no_neurodoc[paciente_id].add(timezone.localtime(quando).date())

        plano = {'entram': [], 'contagem': Counter(), 'casamento': Counter(), 'alertas': {}}
        clientes_vistos = set()
        for registro in registros:
            anotacao = ler_anotacao(registro)
            if anotacao is None:
                plano['contagem']['sem texto (fica de fora)'] += 1
                continue
            if anotacao['quando'].date() > ate:
                plano['contagem']['depois do corte (já atendido no NeuroDoc)'] += 1
                continue
            paciente_id, como = casar(anotacao)
            if anotacao['cliente'] not in clientes_vistos:
                clientes_vistos.add(anotacao['cliente'])
                plano['casamento'][como] += 1
            if paciente_id is None:
                plano['contagem'][f'paciente não casado: {como}'] += 1
                continue
            if anotacao['legacy_id'] in ja_migrados:
                plano['contagem']['já migrada numa rodada anterior'] += 1
                continue
            if anotacao['quando'].date() in dias_no_neurodoc[paciente_id]:
                plano['contagem']['mesmo dia já escrito no NeuroDoc'] += 1
                continue
            if excede_limite(anotacao):
                plano['contagem']['texto maior que o campo (fica de fora)'] += 1
                continue
            anotacao['paciente_id'] = paciente_id
            plano['entram'].append(anotacao)
            plano['contagem']['ENTRA'] += 1
            # O alerta é do paciente: vale o da anotação mais recente.
            if anotacao['alerta']:
                atual = plano['alertas'].get(paciente_id)
                if atual is None or anotacao['quando'] > atual[0]:
                    plano['alertas'][paciente_id] = (anotacao['quando'], anotacao['alerta'])
        return plano

    def _relatar(self, plano):
        self.stdout.write('Pacientes do arquivo, por como casaram:')
        for chave, valor in sorted(plano['casamento'].items()):
            self.stdout.write(f'  {chave:<48} {valor}')
        self.stdout.write('Anotações:')
        for chave, valor in sorted(plano['contagem'].items()):
            self.stdout.write(f'  {chave:<48} {valor}')
        pacientes = {a['paciente_id'] for a in plano['entram']}
        self.stdout.write(f'Pacientes que recebem histórico: {len(pacientes)}')
        self.stdout.write(f'Fichas com alerta do iClin: {len(plano["alertas"])}')

    # ------------------------------------------------------------ gravação

    def _gravar(self, tenant, medico, plano):
        agora = timezone.now()
        fuso = timezone.get_current_timezone()
        criados = 0
        entram = plano['entram']
        for inicio in range(0, len(entram), LOTE):
            linhas = []
            for anotacao in entram[inicio:inicio + LOTE]:
                quando = timezone.make_aware(anotacao['quando'], fuso)
                encounter = Encounter(
                    tenant=tenant, patient_id=anotacao['paciente_id'], physician_membership=medico,
                    occurred_at=quando,
                    kind=EncounterKind.FREE_TEXT,
                    free_text=anotacao['free_text'], impressions=anotacao['impressions'],
                    plan_text=anotacao['plan_text'],
                    status=EncounterStatus.FINALIZED,
                    # Fechado no dia em que foi escrito, no iClin — e não no
                    # dia da migração, que ordenaria 2013 acima de outubro e
                    # faria a exportação dizer "finalizado em" uma data em
                    # que nada foi escrito. A data da migração fica na
                    # justificativa (revisão de 2026-11-02, W9).
                    finalized_at=quando, finalized_by=medico,
                    finalization_justification=(
                        f'Migrado do iClin (anotação nº {anotacao["numero"]}) em {timezone.localdate():%d/%m/%Y}.'
                    ),
                    legacy_id=anotacao['legacy_id'],
                )
                encounter.content_hash = encounter.compute_content_hash()
                linhas.append(encounter)
            with transaction.atomic():
                Encounter.objects.bulk_create(linhas)
            criados += len(linhas)
            self.stdout.write(f'  ... {criados}/{len(entram)}')

        alertas = 0
        with transaction.atomic():
            for paciente in Patient.objects.select_for_update().filter(tenant=tenant, id__in=list(plano['alertas'])):
                texto = f'Alerta (iClin): {plano["alertas"][paciente.id][1]}'
                if texto in paciente.administrative_notes:
                    continue
                novo = '\n'.join(p for p in [paciente.administrative_notes.strip(), texto] if p)
                if len(novo) > NOTAS_MAX:
                    self.stdout.write(f'  alerta não coube nas observações da ficha {paciente.record_number or paciente.id}')
                    continue
                Patient.objects.filter(id=paciente.id).update(administrative_notes=novo, updated_at=agora)
                alertas += 1
        return criados, alertas

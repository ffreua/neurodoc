"""Migração do histórico de atendimentos do iClin (`import_atendimentos_xml`).

O que este roteiro tenta quebrar, com um arquivo **fictício** escrito aqui
mesmo (o real tem paciente de verdade e nunca entra no repositório):

- **as seções**: Diagnósticos vai para as impressões, Prescrição e Condutas
  para a conduta, o resto fica no corpo com os títulos e na ordem; a moldura
  `- ` do iClin sai, as listas do médico ficam; "Diagnósticos" no meio de um
  parágrafo continua texto; anexos e documentos entram como nome e endereço;
- **o casamento**: número do iClin **e** nome; sem número, nome e nascimento
  com uma ficha só; número de uma ficha com o nome de outra pessoa **não**
  casa; ficha de outra clínica com o mesmo número não recebe nada;
- **o corte**: depois de `--ate` não entra; o dia em que o paciente já tem
  atendimento escrito no NeuroDoc não entra; anotação sem texto não entra;
- **o ensaio não grava**, e a gravação deixa atendimento de texto livre
  **finalizado**, imutável, com o hash certo e a data da consulta;
- **nenhum efeito do "Finalizar"**: nenhum evento na outbox, nenhuma
  cobrança — e uma entrada na trilha por rodada;
- **repetir não duplica** (e o banco recusa o mesmo `legacy_id` duas vezes);
- o **alerta** vai às observações da ficha uma vez, o mais recente;
- o que o resto do sistema passa a ver: a **última consulta** do portal, a
  **cópia da consulta anterior** trazendo impressões e conduta, e a tela
  dizendo "migrado do iClin" em vez de "finalizado por";
- médico sem papel de médico na clínica é recusado.

Tudo dentro de uma transação desfeita no fim.
"""
import os
import tempfile
from datetime import date, datetime
from io import StringIO

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from clinical.carry_forward import carry_forward, default_source_encounter
from clinical.importacao import separar_secoes
from clinical.models import Encounter, EncounterKind, EncounterStatus
from documents.portal_retorno import ultima_consulta
from events.models import OutboxEvent
from finance.models import Receivable
from patients.models import Patient
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {str(obtido)[:60]}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.get(slug='demo-clinica-b')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').order_by('id').first()
secretaria = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
).exclude(roles__contains=['doctor']).select_related('user').first()

ESTRUTURADA = """Queixas principais ou evolução
- # RETORNO #
Melhorou da cefaleia. Diagnósticos anteriores revistos com a família.


Antecedentes pessoais e hábitos
- - HAS
- DM2


Diagnósticos
- - Enxaqueca sem aura
- Insônia

# Investigação:
- RM 2024: normal


Prescrição de medicamentos
- 1. Topiramato 25mg à noite
 (x1)


Condutas e orientações
- Retorno em 3 meses"""


def anotacao(numero, quando, cliente, nome, nasc, texto, alerta='', anexos=''):
    return f"""<anotacao>
<num_anotacao>{numero}</num_anotacao>
<data>{quando}</data>
<procedimento>consulta médica (anotação estruturada)</procedimento>
<num_cliente>{cliente}</num_cliente>
<nome_cliente>{nome}</nome_cliente>
<sexo>F</sexo>
<dt_nasc>{nasc}</dt_nasc>
<num_pront></num_pront>
<num_profissional>1</num_profissional>
<nome_profissional>MEDICO FICTICIO</nome_profissional>
<alerta>{alerta}</alerta>
<tx>{texto}</tx>
<anexos>{anexos}</anexos>
<doc_adicionais></doc_adicionais>
<completo>N</completo>
</anotacao>"""


def contexto(vinculo):
    return AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=vinculo.tenant.status, capabilities=frozenset(),
    )


def rodar(arquivo, gravar, email=None):
    saida = StringIO()
    argumentos = ['import_atendimentos_xml', '--clinica', tenant.slug, '--medico', email or medico.user.email,
                  '--arquivo', arquivo, '--ate', '2026-10-02']
    if gravar:
        argumentos.append('--gravar')
    call_command(*argumentos, stdout=saida)
    return saida.getvalue()


print('== 1. As seções da anotação')
corpo, impressoes, conduta = separar_secoes(ESTRUTURADA)
conferir('o corpo abre com a queixa, sem a moldura "- "', corpo.split('\n')[:2],
         ['Queixas principais ou evolução', '# RETORNO #'])
conferir('"Diagnósticos" no meio do parágrafo continua no corpo', 'Diagnósticos anteriores' in corpo, True)
conferir('antecedentes ficam no corpo, com a lista do médico', 'Antecedentes pessoais e hábitos\n- HAS\n- DM2' in corpo, True)
conferir('diagnósticos fora do corpo', 'Enxaqueca' in corpo, False)
conferir('impressões = a seção Diagnósticos, sem título', impressoes.split('\n')[0], '- Enxaqueca sem aura')
conferir('a investigação acompanha os diagnósticos', 'RM 2024: normal' in impressoes, True)
conferir('conduta junta prescrição e orientações, com os títulos',
         (conduta.startswith('Prescrição de medicamentos\n1. Topiramato'), 'Condutas e orientações\nRetorno em 3 meses' in conduta),
         (True, True))
conferir('evolução de texto livre vira corpo', separar_secoes('Evolução\n- Estável.\nSem queixas.'),
         ('Evolução\nEstável.\nSem queixas.', '', ''))

try:
    with transaction.atomic():
        p1 = Patient.objects.create(tenant=tenant, full_name='Paciente Migracao Um', birth_date=date(1970, 5, 1),
                                    legacy_id='T9001', administrative_notes='Prefere manhã.')
        p2 = Patient.objects.create(tenant=tenant, full_name='Paciente Migração Dois', birth_date=date(1980, 1, 1))
        p3 = Patient.objects.create(tenant=tenant, full_name='Paciente Migracao Tres', birth_date=date(1990, 2, 2),
                                    legacy_id='T9003')
        alheio = Patient.objects.create(tenant=outra, full_name='Paciente Migracao Um', birth_date=date(1970, 5, 1),
                                        legacy_id='T9001')
        fuso = timezone.get_current_timezone()
        nativo = Encounter.objects.create(
            tenant=tenant, patient=p1, physician_membership=medico,
            occurred_at=timezone.make_aware(datetime(2026, 9, 30, 15, 0), fuso), kind=EncounterKind.FREE_TEXT,
            free_text='consulta escrita no NeuroDoc',
        )
        anexo = '<link>https://exemplo.invalid/a.pdf</link><nome>laudo RM.pdf</nome>'
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n<anotacoes>' + ''.join([
            anotacao(1, '2025-03-10 14:30:00', 'T9001', 'PACIENTE MIGRACAO UM', '1970-05-01', ESTRUTURADA,
                     alerta='alerta antigo', anexos=anexo),
            anotacao(2, '2026-09-30 10:00:00', 'T9001', 'PACIENTE MIGRACAO UM', '1970-05-01', 'Evolução\n- mesmo dia'),
            anotacao(3, '2026-10-05 10:00:00', 'T9001', 'PACIENTE MIGRACAO UM', '1970-05-01', 'Evolução\n- depois'),
            anotacao(4, '2024-01-01 09:00:00', 'X555', 'PACIENTE MIGRACAO DOIS', '1980-01-01',
                     'Evolução\n- Estável.\n\n\nDiagnósticos\n- Epilepsia focal'),
            anotacao(5, '2024-02-02 09:00:00', 'T9003', 'OUTRA PESSOA QUALQUER', '1990-02-02', 'Evolução\n- x'),
            anotacao(6, '2025-06-06 09:00:00', 'T9001', 'PACIENTE MIGRACAO UM', '1970-05-01', ''),
            anotacao(7, '2026-09-01 08:00:00', 'T9001', 'PACIENTE MIGRACAO UM', '1970-05-01', 'Evolução\n- bem',
                     alerta='Irmão de outro paciente'),
        ]) + '</anotacoes>'
        descritor, arquivo = tempfile.mkstemp(suffix='.xml')
        with os.fdopen(descritor, 'w', encoding='utf-8') as f:
            f.write(xml)

        print('== 2. Recusas e ensaio')
        try:
            rodar(arquivo, False, email=secretaria.user.email)
            conferir('secretária como médico recusada', 'aceita', 'recusa')
        except CommandError:
            conferir('secretária como médico recusada', 'recusa', 'recusa')
        saida = rodar(arquivo, False)
        conferir('o ensaio não grava', Encounter.objects.filter(tenant=tenant).exclude(legacy_id='').count(), 0)
        conferir('o ensaio relata 3 que entram', 'ENTRA' in saida and ' 3' in saida.split('ENTRA')[1][:60], True)

        print('== 3. Gravação')
        eventos_antes = OutboxEvent.objects.count()
        rodar(arquivo, True)
        migrados = {e.legacy_id: e for e in Encounter.objects.filter(tenant=tenant).exclude(legacy_id='')}
        conferir('entraram as anotações 1, 4 e 7', sorted(migrados), ['iclin:1', 'iclin:4', 'iclin:7'])
        a1, a4 = migrados['iclin:1'], migrados['iclin:4']
        conferir('na ficha certa (número e nome; nome e nascimento)', (a1.patient_id, a4.patient_id), (p1.id, p2.id))
        conferir('texto livre, finalizado e imutável',
                 (a1.kind, a1.status, a1.is_editable(), bool(a1.finalized_at)),
                 (EncounterKind.FREE_TEXT, EncounterStatus.FINALIZED, False, True))
        conferir('o hash é o do conteúdo gravado', a1.content_hash, a1.compute_content_hash())
        conferir('a data e a hora são as da consulta, em Brasília',
                 timezone.localtime(a1.occurred_at).strftime('%Y-%m-%d %H:%M'), '2025-03-10 14:30')
        conferir('autor e quem fechou: o médico', (a1.physician_membership_id, a1.finalized_by_id), (medico.id, medico.id))
        conferir('impressões e conduta separadas', (a1.impressions.startswith('- Enxaqueca'), 'Topiramato' in a1.plan_text),
                 (True, True))
        conferir('o anexo entra como nome e endereço', 'laudo RM.pdf: https://exemplo.invalid/a.pdf' in a1.free_text, True)
        conferir('a justificativa diz de onde veio', 'iClin (anotação nº 1)' in a1.finalization_justification, True)
        conferir('o mesmo dia já escrito aqui ficou de fora; o nativo intacto',
                 (Encounter.objects.filter(patient=p1).count(), Encounter.objects.get(id=nativo.id).legacy_id), (3, ''))
        conferir('número de uma ficha com outro nome não casa', Encounter.objects.filter(patient=p3).count(), 0)
        conferir('a ficha de outra clínica com o mesmo número não recebe nada',
                 Encounter.objects.filter(patient=alheio).count(), 0)
        ids = [str(e.id) for e in migrados.values()]
        conferir('nenhum evento de finalização na outbox',
                 (OutboxEvent.objects.count() - eventos_antes,
                  OutboxEvent.objects.filter(aggregate_id__in=[e.id for e in migrados.values()]).count()), (0, 0))
        conferir('nenhuma cobrança criada', Receivable.objects.filter(encounter_id__in=ids).count(), 0)
        trilha = AuditEvent.objects.filter(tenant_id=tenant.id, action='clinical.encounters_imported')
        conferir('uma entrada na trilha, com a contagem', [t.integrity_metadata.get('criados') for t in trilha], [3])
        p1.refresh_from_db()
        conferir('o alerta mais recente nas observações, sem apagar o que havia',
                 p1.administrative_notes, 'Prefere manhã.\nAlerta (iClin): Irmão de outro paciente')

        print('== 4. Repetir não duplica')
        saida = rodar(arquivo, True)
        conferir('segunda rodada não cria nada',
                 Encounter.objects.filter(tenant=tenant).exclude(legacy_id='').count(), 3)
        conferir('e diz que já estavam migradas', 'já migrada numa rodada anterior' in saida, True)
        p1.refresh_from_db()
        conferir('o alerta não se repete', p1.administrative_notes.count('Alerta (iClin)'), 1)
        try:
            with transaction.atomic():
                Encounter.objects.create(tenant=tenant, patient=p1, physician_membership=medico,
                                         occurred_at=timezone.now(), legacy_id='iclin:1')
            conferir('o banco recusa o mesmo legacy_id', 'aceitou', 'recusou')
        except IntegrityError:
            conferir('o banco recusa o mesmo legacy_id', 'recusou', 'recusou')

        print('== 5. O que o resto do sistema passa a ver')
        conferir('a última consulta do portal é a migrada', ultima_consulta(p2).id, a4.id)
        novo = Encounter.objects.create(tenant=tenant, patient=p2, physician_membership=medico,
                                        occurred_at=timezone.now(), kind=EncounterKind.STRUCTURED)
        conferir('a consulta nova oferece copiar a migrada', default_source_encounter(novo).id, a4.id)
        itens = carry_forward(contexto(medico), novo)
        conferir('e traz as impressões', [i.field_path for i in itens], ['impressions'])
        cliente = Client()
        cliente.force_login(medico.user)
        sessao = cliente.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()
        pagina = cliente.get(reverse('clinical:detail', args=[a1.id]))
        html = pagina.content.decode()
        conferir('a tela do atendimento abre', pagina.status_code, 200)
        conferir('e diz "migrado", não "finalizado por"',
                 ('migrado do sistema anterior' in html, 'Registro finalizado em' in html), (True, False))
        ficha = cliente.get(reverse('patients:detail', args=[p1.id])).content.decode()
        conferir('a ficha marca os migrados', 'migrado do iClin' in ficha, True)
        os.remove(arquivo)
        raise Desfazer
except Desfazer:
    pass

if falhas:
    print('\nFALHAS:')
    for falha in falhas:
        print(' -', falha)
    raise SystemExit(1)
print('\nTudo certo.')

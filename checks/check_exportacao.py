"""O dono leva os dados embora, e so quem pode e que leva?

Tenta quebrar. As perguntas sao:

- o arquivo sai em Markdown e em JSON, com o conteudo que promete?
- a exportacao respeita o inquilino, ou varre o banco?
- quem so administra a clinica baixa prontuario?
- quem so le prontuario baixa o acervo da clinica inteira?
- da para pedir um relatorio pelo nome no POST e furar a matriz?
- o download vem com o tipo e a extensao do formato pedido?
- a versao do produto aparece onde alguem a le?
"""
import json

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from pathlib import Path

from django.utils import timezone

from accounts.models import User
from base.version import VERSION, version_display
from clinical.models import Encounter
from patients.models import Patient
from reporting import acervo
from reporting.models import ReportExport, ReportExportKind, ReportExportStatus
from reporting.services import (
    FORMATOS, ReportNotAllowed, ReportNotFound, request_export,
)
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import Capability, capabilities_for

falhas = []


def contexto_de(membership):
    """O `AccessContext` real deste vinculo, montado como o middleware monta."""
    from tenancy.context import AccessContext

    import uuid

    return AccessContext(
        user_id=membership.user_id,
        tenant_id=membership.tenant_id,
        membership_id=membership.id,
        permissions=frozenset(membership.roles),
        request_id=uuid.uuid4(),
        capabilities=capabilities_for(
            membership.roles,
            clinically_enabled=membership.can_practice_clinically(),
        ),
    )


print('=== 1. a versao do produto existe e aparece ===')
print(f'  VERSION={VERSION}  display={version_display()}')
if not VERSION or VERSION.count('.') < 1:
    falhas.append(f'a versao do produto nao parece uma versao: {VERSION!r}')
anonimo = Client()
rodape = anonimo.get('/').content.decode(errors='replace')
print(f'  a pagina publica mostra a versao -> {f"versão {VERSION}" in rodape}')
if f'versão {VERSION}' not in rodape:
    falhas.append('o rodape publico nao mostra a versao do produto')
# E ela e legivel fora do Django -- `ops/deploy.py` roda no host e precisa.
import subprocess
import sys

fora = subprocess.run(
    [sys.executable, '-c', 'from base.version import VERSION; print(VERSION)'],
    capture_output=True, text=True,
)
print(f'  legivel sem Django -> {fora.stdout.strip() or fora.stderr.strip()[:60]}')
if fora.stdout.strip() != VERSION:
    falhas.append('base/version.py nao e importavel fora do Django')

print('=== 2. quem exporta o que ===')
# A matriz, conferida no catalogo e nao na tela: e o registro que decide.
esperado = {
    'acervo_pacientes': ('manage_organization',),
    'acervo_atendimentos': ('manage_organization', 'read_clinical'),
}
from reporting.services import _REGISTRY

for nome, capacidades in esperado.items():
    if nome not in _REGISTRY:
        falhas.append(f'o relatorio {nome} nao esta registrado')
        continue
    tem = tuple(_REGISTRY[nome]['capabilities'])
    formatos = sorted(k for k in _REGISTRY[nome]['kinds'])
    print(f'  {nome:22} {tem}  {formatos}')
    if tem != capacidades:
        falhas.append(f'{nome} exige {tem}, e deveria exigir {capacidades}')
    if set(formatos) != {ReportExportKind.MD, ReportExportKind.JSON}:
        falhas.append(f'{nome} oferece {formatos}, e deveria oferecer so MD e JSON')
# Todo relatorio registrado declara capacidade. Sem isto, um relatorio
# novo nasceria aberto a quem abrir a tela de exportacao.
sem_capacidade = [n for n, r in _REGISTRY.items() if not r['capabilities']]
if sem_capacidade:
    falhas.append(f'relatorios registrados sem capacidade: {sem_capacidade}')

print('=== 3. um consultorio de verdade, para exportar ===')
clinica = Tenant.objects.exclude(status='closed').order_by('created_at').first()
if clinica is None:
    print('  (nenhuma clinica neste banco; roteiro pulado)')
    raise SystemExit(0)

dono = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
).first()
medico = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).first()
if dono is None or medico is None:
    print(f'  (a clinica {clinica.slug} nao tem dono e medico ativos; roteiro pulado)')
    raise SystemExit(0)

pacientes = Patient.objects.filter(tenant=clinica).count()
atendimentos = Encounter.objects.filter(tenant=clinica).count()
print(f'  clinica={clinica.slug}  pacientes={pacientes}  atendimentos={atendimentos}')

print('=== 4. o cadastro sai em Markdown e em JSON ===')
linhas = acervo.pacientes_rows(clinica.id)
print(f'  linhas montadas={len(linhas)}')
if len(linhas) != pacientes:
    falhas.append(f'o acervo montou {len(linhas)} linhas para {pacientes} pacientes')

md = acervo.pacientes_markdown(linhas)
from reporting.exporters import export_json

dados = json.loads(export_json(linhas))
print(f'  markdown={len(md)} caracteres  json={len(dados)} registros')
if linhas:
    primeiro = linhas[0]
    tem_nome = primeiro['nome'] in md
    # O JSON preserva as listas que a tabela nao comporta.
    tem_listas = 'contatos' in dados[0] and 'convenios' in dados[0]
    print(f'  nome no markdown={tem_nome}  listas no json={tem_listas}')
    if not tem_nome:
        falhas.append('o markdown do cadastro nao traz o nome do paciente')
    if not tem_listas:
        falhas.append('o json do cadastro perdeu contatos ou convenios')
    # E data vira texto em vez de derrubar o serializador.
    if not isinstance(dados[0]['cadastrado_em'], str):
        falhas.append('o json nao serializou a data de cadastro')

print('=== 5. o prontuario sai como documento, nao como tabela ===')
linhas_at = acervo.atendimentos_rows(clinica.id)
md_at = acervo.atendimentos_markdown(linhas_at)
print(f'  atendimentos={len(linhas_at)}  markdown={len(md_at)} caracteres')
if len(linhas_at) != atendimentos:
    falhas.append(f'o acervo montou {len(linhas_at)} atendimentos para {atendimentos}')
com_texto = [
    linha for linha in linhas_at
    if any(linha.get(rotulo) for _campo, rotulo in acervo.SECOES_CLINICAS)
]
if com_texto:
    amostra = com_texto[0]
    rotulo = next(r for _c, r in acervo.SECOES_CLINICAS if amostra.get(r))
    trecho = amostra[rotulo][:40]
    print(f'  secao "{rotulo}" no documento -> {trecho[:28]!r}')
    if f'**{rotulo}**' not in md_at:
        falhas.append(f'o documento nao tem a secao "{rotulo}"')
    if trecho not in md_at:
        falhas.append('o documento nao traz o texto da anotacao clinica')
    # Cabecalho por paciente: o prontuario se le por paciente, nao por dia.
    if f'## {amostra["paciente"]}' not in md_at and amostra['paciente'] not in md_at:
        falhas.append('o documento nao agrupa os atendimentos por paciente')
else:
    print('  (nenhum atendimento com texto nesta clinica)')

print('=== 6. a exportacao respeita o inquilino ===')
# O relacionamento reverso de `Patient` e `patient`, no singular: o modelo
# nao declara `related_name`, e o Django usa o nome da classe em minusculas.
outra = Tenant.objects.exclude(id=clinica.id).exclude(status='closed').filter(
    patient__isnull=False,
).distinct().first()
if outra is None:
    print('  (nao ha segunda clinica com paciente; secao pulada)')
else:
    nomes_daqui = {linha['nome'] for linha in linhas}
    nomes_de_la = set(
        Patient.objects.filter(tenant=outra).values_list('full_name', flat=True)
    )
    vazou = nomes_daqui & nomes_de_la
    print(f'  {clinica.slug}={len(nomes_daqui)}  {outra.slug}={len(nomes_de_la)}  '
          f'em comum={len(vazou)}')
    # Nome repetido entre clinicas e possivel; id, nao.
    ids_daqui = {linha['id'] for linha in linhas}
    ids_de_la = {str(i) for i in Patient.objects.filter(tenant=outra).values_list('id', flat=True)}
    if ids_daqui & ids_de_la:
        falhas.append('a exportacao de uma clinica trouxe paciente de outra')

print('=== 7. a porta do POST nao fura a matriz ===')
ctx_dono = contexto_de(dono)
ctx_medico = contexto_de(medico)
print(f'  dono   papeis={dono.roles} manage_org={ctx_dono.can(Capability.MANAGE_ORGANIZATION)} '
      f'read_clinical={ctx_dono.can(Capability.READ_CLINICAL)}')
print(f'  medico papeis={medico.roles} manage_org={ctx_medico.can(Capability.MANAGE_ORGANIZATION)} '
      f'read_clinical={ctx_medico.can(Capability.READ_CLINICAL)}')

criados = []


def tentar(rotulo, contexto, membership, nome, kind):
    try:
        export = request_export(contexto, membership, nome, {}, kind=kind)
    except ReportNotAllowed:
        print(f'  {rotulo:52} recusado')
        return None
    except ReportNotFound:
        print(f'  {rotulo:52} nao existe')
        return None
    criados.append(export)
    print(f'  {rotulo:52} aceito ({export.status})')
    return export


# O medico sem `manage_organization` nao leva o acervo da clinica.
if not ctx_medico.can(Capability.MANAGE_ORGANIZATION):
    if tentar('medico -> acervo de atendimentos', ctx_medico, medico,
              'acervo_atendimentos', ReportExportKind.MD) is not None:
        falhas.append('um vinculo sem manage_organization exportou o acervo clinico')
    if tentar('medico -> acervo de pacientes', ctx_medico, medico,
              'acervo_pacientes', ReportExportKind.JSON) is not None:
        falhas.append('um vinculo sem manage_organization exportou o cadastro')
else:
    print('  (o medico desta clinica tambem e dono; secao parcial)')

# O dono leva o cadastro. Leva o prontuario so se tambem for medico.
if tentar('dono -> cadastro em JSON', ctx_dono, dono,
          'acervo_pacientes', ReportExportKind.JSON) is None:
    falhas.append('o dono nao conseguiu exportar o cadastro de pacientes')

clinico = tentar('dono -> atendimentos em Markdown', ctx_dono, dono,
                 'acervo_atendimentos', ReportExportKind.MD)
if ctx_dono.can(Capability.READ_CLINICAL):
    if clinico is None:
        falhas.append('o dono que le prontuario nao conseguiu exportar os atendimentos')
elif clinico is not None:
    falhas.append('um dono que nao le prontuario exportou as anotacoes clinicas')

# Formato fora do que o relatorio declara tambem e recusado.
if tentar('dono -> cadastro em CSV (nao oferecido)', ctx_dono, dono,
          'acervo_pacientes', ReportExportKind.CSV) is not None:
    falhas.append('a exportacao aceitou um formato que o relatorio nao declara')

# E a recusa fica na trilha.
from audit.models import AuditEvent

negados = AuditEvent.objects.filter(
    tenant=clinica, action='reporting.export_denied',
).count()
print(f'  recusas na trilha de auditoria={negados}')
if negados == 0:
    falhas.append('nenhuma recusa de exportacao foi registrada na trilha')

print('=== 8. o arquivo sai com o tipo e a extensao do formato ===')
prontos = [e for e in criados if e.status == ReportExportStatus.READY]
enfileirados = [e for e in criados if e.status == ReportExportStatus.QUEUED]
print(f'  prontos na requisicao={len(prontos)}  enfileirados no worker={len(enfileirados)}')
# O acervo nao declara `count_fn`, entao vai sempre para o worker -- e e
# isso que se quer: clinica de dez anos nao se monta numa requisicao.
if prontos:
    falhas.append('o acervo foi montado dentro da requisicao em vez de ir para a fila')

for export in criados:
    extensao, tipo = FORMATOS[export.kind]
    if export.kind == ReportExportKind.MD and 'markdown' not in tipo:
        falhas.append(f'o formato {export.kind} anuncia o tipo {tipo}')
    if export.kind == ReportExportKind.JSON and 'json' not in tipo:
        falhas.append(f'o formato {export.kind} anuncia o tipo {tipo}')

# O worker escreve o arquivo, e e ele que se confere -- nao uma chamada
# direta ao escritor. `O_EXCL` recusa sobrescrever, entao refazer aqui o
# que o worker ja fez falharia por motivo certo e conclusao errada.
import time

prazo = time.monotonic() + 30
pendentes = {e.id for e in criados}
while pendentes and time.monotonic() < prazo:
    time.sleep(1)
    for export in ReportExport.objects.filter(id__in=list(pendentes)):
        if export.status in (ReportExportStatus.READY, ReportExportStatus.FAILED):
            pendentes.discard(export.id)

for export in ReportExport.objects.filter(id__in=[e.id for e in criados]):
    extensao = FORMATOS[export.kind][0]
    sufixo = export.storage_key.rsplit('.', 1)[-1] if export.storage_key else '(nenhum)'
    print(f'  {export.report_name}.{extensao} -> {export.status}  '
          f'{export.row_count} registro(s)  arquivo .{sufixo}')
    if export.status != ReportExportStatus.READY:
        falhas.append(f'o worker nao concluiu a exportacao {export.report_name}')
        continue
    if not export.storage_key.endswith(f'.{extensao}'):
        falhas.append('o arquivo gravado nao tem a extensao do formato pedido')
    if export.expires_at is None or export.expires_at <= timezone.now():
        falhas.append('a exportacao nasceu sem prazo de expiracao')
    # E o conteudo e do formato anunciado, e nao CSV com outro nome.
    conteudo = Path(export.storage_key).read_text(encoding='utf-8')
    if export.kind == ReportExportKind.JSON:
        try:
            json.loads(conteudo)
        except ValueError:
            falhas.append(f'{export.report_name}.json nao e JSON valido')
    if export.kind == ReportExportKind.MD and not conteudo.lstrip().startswith('#'):
        falhas.append(f'{export.report_name}.md nao comeca como documento Markdown')

print('=== 9. a tela da administracao ===')
usuario = User.objects.filter(id=dono.user_id).first()
cliente = Client()
cliente.force_login(usuario)
sessao = cliente.session
sessao['tenant_id'] = str(clinica.id)
sessao.save()
pagina = cliente.get('/app/reporting/acervo/')
corpo = pagina.content.decode(errors='replace')
print(f'  GET /app/reporting/acervo/ -> HTTP {pagina.status_code}')
if pagina.status_code != 200:
    falhas.append('a tela de exportacao nao abriu para o dono da clinica')
else:
    for esperado_texto in ['Cadastro de pacientes', 'Atendimentos e anota', 'Markdown', 'JSON']:
        if esperado_texto not in corpo:
            falhas.append(f'a tela de exportacao nao oferece: {esperado_texto}')
    # Nome de relatorio fora da lista fechada nao passa.
    r = cliente.post('/app/reporting/acervo/', {
        'acervo': 'patients_seen_detail', 'formato': 'json',
    })
    print(f'  POST com relatorio de fora da lista -> HTTP {r.status_code}')
    if r.status_code != 404:
        falhas.append('a tela aceitou um relatorio fora da lista fechada')
    r = cliente.post('/app/reporting/acervo/', {
        'acervo': 'acervo_pacientes', 'formato': 'csv',
    })
    print(f'  POST com formato nao oferecido -> HTTP {r.status_code}')
    if r.status_code != 404:
        falhas.append('a tela aceitou um formato que o relatorio nao declara')

# Limpeza: as exportacoes deste roteiro saem, com os arquivos.
for export in ReportExport.objects.filter(id__in=[e.id for e in criados]):
    if export.storage_key:
        Path(export.storage_key).unlink(missing_ok=True)
    export.delete()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o dono leva os dados em MD e JSON, e so quem pode e que leva.')

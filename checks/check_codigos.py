"""A busca de codigos acha o que o medico digita?

Tenta quebrar. As perguntas sao:

- termo de duas palavras acha, ou so a frase exata?
- "ressonancia cranio" acha "RM - Cranio (encefalo)"? (a tabela abrevia)
- digitar mais palavras restringe, ou amplia? (tem de restringir)
- procedimento com vigencia encerrada some da lista? (nao deve)
- a secretaria alcanca? (catalogo publico, sem dado de paciente)
- sem release sincronizada, a resposta e "nao existe" ou "nao sincronizado"?
"""
import json

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from catalogs import selectors
from catalogs.models import (
    CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode,
)
from tenancy.models import Tenant

falhas = []
tenant = Tenant.objects.get(slug='demo-clinica-a')


def entrar(email):
    u = User.objects.get(email=email)
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


medico = entrar('doctor-a@demo.neurodoc.local')
secretaria = entrar('secretary-a@demo.neurodoc.local')


def buscar(cliente, tipo, termo):
    r = cliente.get(f'/app/codigos/{tipo}/buscar/', {'q': termo})
    return json.loads(r.content)


print('=== 1. a tela abre para quem trabalha na clinica ===')
for rotulo, cli in [('medico', medico), ('secretaria', secretaria)]:
    r = cli.get('/app/codigos/')
    print(f'  {rotulo:11} -> {r.status_code}')
    if r.status_code != 200:
        falhas.append(f'{rotulo} nao alcanca a busca de codigos')

print('=== 2. CID: codigo, nome, acento e duas palavras ===')
casos_cid = [
    ('G40', 'G40'),
    ('g40.0', 'G40.0'),
    ('epilepsia', 'G40'),
    ('esclerose multipla', 'G35'),
    ('doenca parkinson', 'G20'),
]
for termo, esperado in casos_cid:
    res = buscar(medico, 'cid', termo).get('results', [])
    achou = any(x['code'] == esperado for x in res)
    print(f'  {termo:22} -> {len(res):3} resultado(s), contem {esperado}={achou}')
    if not achou:
        falhas.append(f'busca CID por {termo!r} nao encontrou {esperado}')

print('=== 3. TUSS: a tabela abrevia, e a busca sabe disso ===')
release_tuss = selectors.active_release(CatalogSystem.TUSS)
if release_tuss is None or release_tuss.version.startswith('SAMPLE'):
    print('  (TUSS ainda nao sincronizada nesta instalacao -- secao pulada)')
    print('   rode: docker compose exec celery_worker python manage.py sync_tuss')
else:
    print(f'  release: {release_tuss.version} com {ProcedureCode.objects.filter(release=release_tuss).count()}')
    casos_tuss = [
        ('ressonancia cranio', '41101014'),   # tabela escreve "RM - Cranio (encefalo)"
        ('RM cranio', '41101014'),            # e quem digita a sigla tambem acha
        ('eletroneuromiografia', '40103315'),
        ('polissonografia', '40103528'),
        ('10101012', '10101012'),             # pelo codigo
    ]
    for termo, esperado in casos_tuss:
        res = buscar(medico, 'tuss', termo).get('results', [])
        achou = any(x['code'] == esperado for x in res)
        print(f'  {termo:22} -> {len(res):3} resultado(s), contem {esperado}={achou}')
        if not achou:
            falhas.append(f'busca TUSS por {termo!r} nao encontrou {esperado}')

    print('=== 4. digitar mais palavras restringe ===')
    largo = len(buscar(medico, 'tuss', 'ressonancia').get('results', []))
    estreito = len(buscar(medico, 'tuss', 'ressonancia cranio').get('results', []))
    print(f'  "ressonancia"={largo}  "ressonancia cranio"={estreito}')
    if estreito > largo:
        falhas.append('acrescentar palavra ampliou o resultado: o filtro esta em OR')

    print('=== 5. vigencia encerrada aparece com marca, nao some ===')
    encerrados = ProcedureCode.objects.filter(release=release_tuss, active=False).count()
    print(f'  procedimentos encerrados no catalogo: {encerrados}')
    if encerrados:
        alvo = ProcedureCode.objects.filter(release=release_tuss, active=False).first()
        res = buscar(medico, 'tuss', alvo.code).get('results', [])
        presente = any(x['code'] == alvo.code for x in res)
        marcado = any(x['code'] == alvo.code and not x['in_force'] for x in res)
        print(f'  {alvo.code} aparece={presente} marcado como encerrado={marcado}')
        if not presente:
            falhas.append('procedimento com vigencia encerrada sumiu da busca')
        if not marcado:
            falhas.append('procedimento encerrado aparece sem marca de vigencia')
    else:
        print('  (nenhum encerrado nesta carga -- nada a provar)')

print('=== 6. termo curto nao varre o catalogo ===')
for tipo in ['cid', 'tuss']:
    res = buscar(medico, tipo, 'a').get('results', [])
    print(f'  {tipo}: termo de 1 caractere -> {len(res)} resultado(s)')
    if res:
        falhas.append(f'{tipo}: termo de um caractere devolveu resultado')

print('=== 7. sem release, a resposta diz o que houve ===')
ativa = CatalogRelease.objects.filter(
    system=CatalogSystem.TUSS, status=CatalogReleaseStatus.ACTIVE,
)
guardadas = list(ativa.values_list('id', flat=True))
ativa.update(status=CatalogReleaseStatus.SUPERSEDED)
try:
    d = buscar(medico, 'tuss', 'consulta')
    diz = d.get('ok') is False and 'sincroniz' in (d.get('error') or '')
    print(f'  ok={d.get("ok")}  a mensagem fala em sincronizar={diz}')
    print(f'  -> {(d.get("error") or "")[:70]}')
    if not diz:
        falhas.append('sem release, a busca devolveu lista vazia em vez de dizer o motivo')
finally:
    CatalogRelease.objects.filter(id__in=guardadas).update(status=CatalogReleaseStatus.ACTIVE)

print('=== 8. o espelho e alimentado pelo worker, nao pela view ===')
import inspect

from catalogs import views

fonte = inspect.getsource(views)
usa_rede = 'requests' in fonte or 'tuss.search(' in fonte or 'tuss.fetch' in fonte
print(f'  catalogs/views.py faz chamada externa={usa_rede} (False esperado)')
if usa_rede:
    falhas.append('a view faz chamada externa: o processo web nao tem egresso em producao')

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a busca acha pelo codigo, pelo nome e pela abreviacao da tabela.')

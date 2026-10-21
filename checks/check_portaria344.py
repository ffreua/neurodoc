"""A lista oficial das substâncias controladas (Portaria SVS/MS 344/1998).

Decisão D7 de `docs/sncr/DECISOES.md`. Tenta quebrar. As perguntas são:

- o ato vigente guardado no repositório é lido inteiro — as 16 listas,
  com o número da RDC e da atualização?
- cada lista tem o receituário que a norma fixa (C1/C5 → RCE, B1 →
  Notificação B, A → Notificação A)?
- o parser é estrito: uma lista faltando, ou um item fora de sequência,
  derrubam a leitura, e nada é gravado?
- a importação grava tudo numa transação, e a release antiga continua?
- a classificação acha o sal ("CLORIDRATO DE SERTRALINA" → C1), a redação
  com a palavra do sal ("VALPROATO DE SÓDIO" → "Valproato sódico"), as duas
  substâncias de uma associação, e **não** acha por pedaço de palavra
  ("METILTESTOSTERONA" não é "Testosterona"; "ESCETAMINA" não é "Cetamina")?
- medicamento não controlado volta vazio?
"""
from pathlib import Path

from django.conf import settings

from catalogs import controlados, portaria344
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ControlledList, ControlledSubstance

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


ATO = Path(settings.BASE_DIR) / 'catalogs' / 'data' / 'portaria344-rdc1036-2026.html'
bruto = ATO.read_bytes()

print('=== 1. o ato vigente é lido inteiro ===')
texto = portaria344.texto_do_html(bruto)
listas = portaria344.ler(texto)
por_codigo = {l.codigo: l for l in listas}
conferir('16 listas', len(listas) == 16, len(listas))
conferir('versão do ato', portaria344.versao_do_ato(texto) == ('RDC 1036/2026', '101'), portaria344.versao_do_ato(texto))
conferir('C1 com 213 substâncias', len(por_codigo['C1'].substancias) == 213, len(por_codigo['C1'].substancias))
conferir('C1 termina em Zuclopentixol', por_codigo['C1'].substancias[-1].nome == 'Zuclopentixol')
conferir('B1 tem clonazepam', any(s.nome == 'Clonazepam' for s in por_codigo['B1'].substancias))
conferir('F1 separa nome e sinônimo químico', por_codigo['F1'].substancias[0].sinonimos != [])
conferir('o adendo da C1 é guardado', 'loperamida' in por_codigo['C1'].adendo)
conferir('o rodapé da página não entra no último adendo', 'Publicação Oficial' not in listas[-1].adendo)

print('=== 2. o receituário vem da norma ===')
r = portaria344.RECEITUARIO_POR_LISTA
conferir('C1 e C5 → RCE', r['C1'] == r['C5'] == 'rce')
conferir('B1 → Notificação B', r['B1'] == 'notificacao_b')
conferir('A1 → Notificação A', r['A1'] == 'notificacao_a')
conferir('C2 → retinoide, C3 → talidomida', (r['C2'], r['C3']) == ('notificacao_retinoide', 'notificacao_talidomida'))

print('=== 3. o parser é estrito ===')
sem_c5 = texto.replace('LISTA - C5', 'LISTA REMOVIDA')
try:
    portaria344.ler(sem_c5)
    conferir('lista faltando derruba a leitura', False, 'leu')
except portaria344.ListaInvalida as e:
    conferir('lista faltando derruba a leitura', 'C5' in str(e), e)
fora_de_ordem = texto.replace('\n1.Acepromazina', '\n7.Acepromazina', 1)
try:
    lido = portaria344.ler(fora_de_ordem)
    c1 = {l.codigo: l for l in lido}['C1']
    conferir('item fora de sequência não vira substância', all(s.nome != 'Acepromazina' for s in c1.substancias)
             and len(c1.substancias) < 213, len(c1.substancias))
except portaria344.ListaInvalida:
    conferir('item fora de sequência não vira substância', True)
antes = CatalogRelease.objects.filter(system=CatalogSystem.PORTARIA_344).count()
try:
    controlados.importar(sem_c5.encode('utf-8'), versao='roteiro-invalida', ativar=False)
except portaria344.ListaInvalida:
    pass
conferir('texto inválido não grava nada',
         CatalogRelease.objects.filter(system=CatalogSystem.PORTARIA_344).count() == antes)

print('=== 4. a importação ===')
ativa_antes = controlados.release_ativa()
release, n_listas, n_subst = controlados.importar(bruto, versao='roteiro-portaria344', ativar=False)
conferir('16 listas e 780 substâncias gravadas', (n_listas, n_subst) == (16, 780), (n_listas, n_subst))
conferir('importada como rascunho, sem trocar a ativa',
         release.status == CatalogReleaseStatus.DRAFT and controlados.release_ativa() == ativa_antes)
conferir('o receituário gravado é o da norma',
         ControlledList.objects.get(release=release, code='C1').receituario == 'rce')
try:
    controlados.importar(bruto, versao='roteiro-portaria344', ativar=False)
    conferir('versão repetida recusada', False)
except controlados.VersaoRepetida:
    conferir('versão repetida recusada', True)

print('=== 5. a classificação ===')


def listas_de(texto_cmed):
    return sorted({lista.code for _s, lista in controlados.classificar(texto_cmed, release=release)})


def nomes_de(texto_cmed):
    return sorted({s.name for s, _l in controlados.classificar(texto_cmed, release=release)})


casos = [
    ('CLORIDRATO DE SERTRALINA', ['C1']),
    ('CLONAZEPAM', ['B1']),
    ('TOPIRAMATO', ['C1']),
    ('VALPROATO DE SÓDIO', ['C1']),
    ('CARBONATO DE LÍTIO', ['C1']),
    ('DIPIRONA MONOIDRATADA', []),
    ('PARACETAMOL', []),
]
for texto_cmed, esperado in casos:
    obtido = listas_de(texto_cmed)
    conferir(f'{texto_cmed} → {esperado or "não controlado"}', obtido == esperado, obtido)
assoc = nomes_de('CLORIDRATO DE BUPRENORFINA + CLORIDRATO DE NALOXONA')
conferir('associação: as duas substâncias', {'Buprenorfina', 'Naloxona'} <= set(assoc), assoc)
conferir('METILTESTOSTERONA não é Testosterona', 'Testosterona' not in nomes_de('METILTESTOSTERONA'),
         nomes_de('METILTESTOSTERONA'))
conferir('ESCETAMINA não é Cetamina', 'Cetamina' not in nomes_de('CLORIDRATO DE ESCETAMINA'),
         nomes_de('CLORIDRATO DE ESCETAMINA'))
conferir('texto vazio não classifica', controlados.classificar('', release=release) == [])
conferir('sulfato de medicamento não vira insumo da D2', listas_de('SULFATO DE MORFINA') == ['A1'],
         listas_de('SULFATO DE MORFINA'))
conferir('a D2 (insumos) fica fora da classificação', listas_de('ACETONA') == [], listas_de('ACETONA'))

print('=== limpeza ===')
ControlledSubstance.objects.filter(release=release).delete()
ControlledList.objects.filter(release=release).delete()
release.delete()
print('  release do roteiro removida')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: lista da Portaria 344 lida inteira e com o receituário da norma; parser estrito;')
print('    classificação por palavra inteira, com sal, sem pedaço de palavra.')

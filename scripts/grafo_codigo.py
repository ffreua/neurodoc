"""Reconstrói o grafo do código (graphify) em `graphify-out/`.

Uso, da raiz do repositório, com o Python que tem o graphify (instalado por
`uv tool install graphifyy`; ver `docs/GRAFO.md`):

    & "$(uv tool dir)\\graphifyy\\Scripts\\python.exe" scripts/grafo_codigo.py

Por que existe, em vez de rodar `/graphify` toda vez: o recorte é **só o
código**, lido pela árvore sintática, sem modelo de linguagem e sem custo de
tokens. Documentos, templates e imagens ficaram de fora de propósito
(2026-11-20): passavam de 450 arquivos, custariam dezenas de subagentes, e o
mapa da documentação já existe em `docs/CODEBASE_MAP.md` e no `CLAUDE.md`.
O script fixa o recorte e o nome das comunidades, para que o grafo de amanhã
seja comparável ao de hoje.

`graphify-out/` fica fora do Git pelo `.git/info/exclude` (arquivo local):
o grafo é regenerado, não versionado — e este repositório é público.

Não roda dentro do contêiner nem faz parte de nenhum roteiro: depende do
graphify, que não é dependência do produto.
"""
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / 'graphify-out'


def _nome_da_comunidade(cid, ids, nos):
    """Módulo e arquivo que mais aparecem na comunidade (ex.: `tiss: lotes`).

    O bundle minificado do tema (`design_system/refs/…`) é de terceiros e
    gera dezenas de comunidades sem significado para o produto; o nome diz
    isso, para ninguém tomá-las por código nosso.
    """
    arquivos = collections.Counter((nos.get(i, {}).get('source_file') or '').replace('\\', '/') for i in ids)
    topo = [f for f, _ in arquivos.most_common() if f]
    if not topo:
        return f'Grupo {cid}'
    if topo[0].startswith('design_system/'):
        return 'Bundle Duralux (terceiros)'
    partes = topo[0].split('/')
    return f'{partes[0] if len(partes) > 1 else "raiz"}: {Path(topo[0]).stem}'


def main():
    try:
        from graphify.analyze import god_nodes, suggest_questions, surprising_connections
        from graphify.build import build_from_json
        from graphify.cli import _stamped_manifest_files
        from graphify.cluster import cluster, score_all
        from graphify.detect import detect, save_manifest
        from graphify.diagnostics import diagnose_extraction
        from graphify.export import to_json
        from graphify.extract import collect_files, extract
        from graphify.report import generate
    except ImportError:
        sys.exit('Este Python não tem o graphify. Ver docs/GRAFO.md (uv tool install graphifyy).')

    SAIDA.mkdir(exist_ok=True)
    (SAIDA / '.graphify_root').write_text(str(RAIZ), encoding='utf-8')
    (SAIDA / '.graphify_python').write_text(sys.executable, encoding='utf-8')

    deteccao = detect(RAIZ)
    codigo = deteccao['files'].get('code', [])
    deteccao['files'] = {'code': codigo}
    deteccao['total_files'] = len(codigo)

    arquivos = []
    for f in codigo:
        arquivos.extend(collect_files(Path(f)) if Path(f).is_dir() else [Path(f)])
    bruto = extract(arquivos, cache_root=RAIZ, root=RAIZ, parallel=False)
    extracao = {'nodes': bruto['nodes'], 'edges': bruto['edges'], 'hyperedges': [],
                'input_tokens': 0, 'output_tokens': 0}

    G = build_from_json(extracao, root=str(RAIZ), directed=False)
    if G.number_of_nodes() == 0:
        sys.exit('Grafo vazio: a extração não produziu nada.')
    comunidades = cluster(G)
    coesao = score_all(G, comunidades)
    deuses = god_nodes(G)
    surpresas = surprising_connections(G, comunidades)
    # force=True: o recorte é fixo, e um arquivo apagado do repositório deve
    # sumir do grafo — a trava contra encolher protege o fluxo incremental,
    # que este script não usa.
    to_json(G, comunidades, str(SAIDA / 'graph.json'), force=True)

    nos = {n['id']: n for n in json.loads((SAIDA / 'graph.json').read_text(encoding='utf-8'))['nodes']}
    nomes = {cid: _nome_da_comunidade(cid, ids, nos) for cid, ids in comunidades.items()}
    perguntas = suggest_questions(G, comunidades, nomes)
    relatorio = generate(G, comunidades, coesao, nomes, deuses, surpresas, deteccao,
                         {'input': 0, 'output': 0}, str(RAIZ), suggested_questions=perguntas)
    (SAIDA / 'GRAPH_REPORT.md').write_text(relatorio, encoding='utf-8')
    (SAIDA / '.graphify_labels.json').write_text(
        json.dumps({str(k): v for k, v in nomes.items()}, ensure_ascii=False), encoding='utf-8')
    to_json(G, comunidades, str(SAIDA / 'graph.json'), community_labels=nomes, force=True)
    # Acima de 5.000 nós o `to_html` recusa; a linha de comando monta a visão
    # agregada (uma bolha por comunidade), que é a que serve num grafo deste
    # tamanho.
    import shutil
    import subprocess

    cli = shutil.which('graphify') or str(Path(sys.executable).with_name('graphify'))
    resultado = subprocess.run([cli, 'export', 'html'], cwd=RAIZ, capture_output=True, text=True)
    if resultado.returncode:
        print('graph.html não gerado:', (resultado.stderr or resultado.stdout).strip()[-300:])

    saude = diagnose_extraction(extracao, directed=False, root=str(RAIZ))
    avisos = [f'{saude[k]} {k}' for k in ('dangling_endpoint_edges', 'missing_endpoint_edges', 'self_loop_edges',
                                          'undirected_same_endpoint_collapsed_edges') if saude.get(k, 0)]
    manifesto = _stamped_manifest_files(deteccao['files'], extracao, RAIZ, partial_source_files=set())
    save_manifest(manifesto, root=str(RAIZ), scan_corpus=set(codigo), clear_semantic=None)
    custo = SAIDA / 'cost.json'
    registro = json.loads(custo.read_text(encoding='utf-8')) if custo.exists() else {
        'runs': [], 'total_input_tokens': 0, 'total_output_tokens': 0}
    registro['runs'].append({'date': datetime.now(timezone.utc).isoformat(), 'input_tokens': 0,
                             'output_tokens': 0, 'files': len(codigo)})
    custo.write_text(json.dumps(registro, indent=2), encoding='utf-8')

    print(f'{len(codigo)} arquivos de código, {G.number_of_nodes()} nós, {G.number_of_edges()} arestas, '
          f'{len(comunidades)} comunidades')
    print('saúde:', '; '.join(avisos) if avisos else 'sem avisos')


if __name__ == '__main__':
    main()

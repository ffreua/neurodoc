"""A leitura de laudo pela IA sobrevive a forma, e nao a conteudo.

Este roteiro existe por um defeito de 05/10/2026, em uso real: um laudo
laboratorial foi lido pelo modelo, o JSON voltou inteiro, e a extracao
foi **descartada por um campo vazio**. `unreadable_sections` -- o campo
onde o modelo diz o que NAO conseguiu ler -- veio como `[]` e o esquema
exigia `""`. Um erro de validacao, so um, e trinta e um analitos lidos
corretamente foram para o lixo.

A causa tinha tres camadas, e o roteiro cobre as tres:

1. o prompt nao declarava o tipo do campo (e o nome dele e plural);
2. nao se pedia o esquema ao provedor, so se descrevia em prosa;
3. a validacao era tudo-ou-nada e a mensagem de recusa chegava ao medico
   como o texto cru do Pydantic, em ingles.

A fronteira que este roteiro protege, e que e a parte dificil: **forma**
pode ser normalizada, **conteudo** nao. Converter `[]` em `""` nao
inventa nada; relaxar a faixa de referencia, a probabilidade numerica ou
o marcador de desidentificacao inventaria. Por isso metade das secoes
confere que a conversao funciona e a outra metade confere que ela nao
abriu porta nenhuma.
"""
import json
import re
from pathlib import Path

from django.conf import settings as dj_settings

from pydantic import ValidationError

from ai.graphs import (
    LAB_EXTRACTION_PROMPT, REPORT_TRANSCRIPTION_PROMPT, STRUCTURED_OUTPUT_TASKS, TASKS,
    _diagnostico_de_forma, _formato_de_resposta, build_graph,
)
from ai.schemas import (
    ArtifactModel, ClinicalSummaryArtifact, DiagnosticSupportArtifact, LabExtractionArtifact,
    PatientReportArtifact, ReportTranscriptionArtifact,
)

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


LAUDO_MINIMO = {
    'exam_name': 'Hemograma completo',
    'collected_on': '03/10/2026',
    'service_name': 'Laboratorio Exemplo',
    'analytes': [{
        'analyte': 'Hemoglobina', 'value_text': '13,2', 'numeric_value': 13.2,
        'unit': 'g/dL', 'reference_low': 12.0, 'reference_high': 16.0, 'reference_text': '',
    }],
    'limitations': 'Transcricao automatica; confira contra o laudo.',
    'requires_physician_review': True,
}


print('=== 1. o defeito relatado, reproduzido ===')
# Exatamente o que o modelo devolveu em 05/10/2026.
payload = dict(LAUDO_MINIMO, unreadable_sections=[])
artefato = LabExtractionArtifact.model_validate(payload)
confere(artefato.unreadable_sections == '',
        'lista vazia em unreadable_sections vira texto vazio',
        repr(artefato.unreadable_sections))
confere(len(artefato.analytes) == 1,
        'os analitos sobrevivem -- a extracao nao e mais descartada inteira')

print('=== 2. as outras formas que o mesmo campo pode chegar ===')
casos = [
    ([], '', 'lista vazia'),
    (None, '', 'null'),
    (['pagina 2 cortada'], 'pagina 2 cortada', 'lista de um item'),
    (['pagina 2 cortada', 'rodape ilegivel'],
     'pagina 2 cortada; rodape ilegivel', 'lista de dois itens'),
    ('rodape ilegivel', 'rodape ilegivel', 'texto, como sempre funcionou'),
]
for entrada, esperado, rotulo in casos:
    obtido = LabExtractionArtifact.model_validate(
        dict(LAUDO_MINIMO, unreadable_sections=entrada),
    ).unreadable_sections
    confere(obtido == esperado, f'{rotulo} -> {esperado!r}', f'veio {obtido!r}')

# Numero em campo de texto: a data escrita sem aspas e a ocorrencia provavel.
obtido = LabExtractionArtifact.model_validate(
    dict(LAUDO_MINIMO, unreadable_sections='', collected_on=2026),
).collected_on
confere(obtido == '2026', 'numero em campo de texto vira texto', f'veio {obtido!r}')

print('=== 3. a conversao vale nos esquemas aninhados ===')
# O campo fora de forma costuma estar dentro da lista, nao ao lado dela.
aninhado = dict(LAUDO_MINIMO, unreadable_sections='')
aninhado['analytes'] = [{
    'analyte': 'Hemoglobina', 'value_text': 13.2, 'unit': None,
    'numeric_value': 13.2, 'reference_low': None, 'reference_high': None,
    'reference_text': ['12,0 a 16,0'],
}]
item = LabExtractionArtifact.model_validate(aninhado).analytes[0]
confere(item.value_text == '13.2', 'numero vira texto dentro do analito', repr(item.value_text))
confere(item.unit == '', 'null vira texto vazio dentro do analito', repr(item.unit))
confere(item.reference_text == '12,0 a 16,0',
        'lista de um item vira texto dentro do analito', repr(item.reference_text))

print('=== 4. o que a conversao NAO pode engolir ===')
# Lista de objetos num campo de texto nao vira `str(dict)`: isso poria um
# repr de Python dentro do prontuario, e ai a diferenca entre o laudo e a
# tela deixaria de ser cosmetica.
try:
    LabExtractionArtifact.model_validate(
        dict(LAUDO_MINIMO, unreadable_sections=[{'pagina': 2}]),
    )
except ValidationError:
    confere(True, 'lista de objetos em campo de texto continua sendo recusada')
else:
    confere(False, 'lista de objetos em campo de texto continua sendo recusada')

# `limitations` obrigatorio continua obrigatorio: null vira '' e '' nao passa.
sem_limites = dict(LAUDO_MINIMO, unreadable_sections='')
sem_limites['limitations'] = None
try:
    LabExtractionArtifact.model_validate(sem_limites)
except ValidationError:
    confere(True, 'limitations vazio continua reprovando')
else:
    confere(False, 'limitations vazio continua reprovando')

# `numeric_value` nao e campo de texto: texto ali nao vira numero por conta
# deste roteiro, e um valor que nao e numero nao pode virar um.
nao_numerico = dict(LAUDO_MINIMO, unreadable_sections='')
nao_numerico['analytes'] = [dict(LAUDO_MINIMO['analytes'][0], numeric_value='nao reagente')]
try:
    LabExtractionArtifact.model_validate(nao_numerico)
except ValidationError:
    confere(True, 'texto em numeric_value continua reprovando')
else:
    confere(False, 'texto em numeric_value continua reprovando')

print('=== 5. as guardas de conteudo seguem valendo sobre o texto convertido ===')
# Esta e a secao que impede a correcao de virar um relaxamento geral: as
# duas guardas clinicas rodam DEPOIS da conversao de forma, e por isso uma
# lista nao e caminho para contorna-las.
try:
    ClinicalSummaryArtifact.model_validate({
        'summary': 'Caso em investigacao.',
        'qualitative_hypotheses': ['Esclerose multipla com 80% de probabilidade'],
        'limitations': 'Apoio a revisao.',
    })
except ValidationError:
    confere(True, 'probabilidade numerica continua recusada')
else:
    confere(False, 'probabilidade numerica continua recusada')

try:
    PatientReportArtifact.model_validate({
        'titulo': 'Relatorio',
        'secoes': [],
        'informacao_faltante': ['[PACIENTE] nao trouxe exames'],
        'limitations': 'Rascunho.',
    })
except ValidationError:
    confere(True, 'marcador de desidentificacao continua recusado, mesmo vindo em lista')
else:
    confere(False, 'marcador de desidentificacao continua recusado, mesmo vindo em lista')

print('=== 6. todo esquema de saida herda a normalizacao ===')
# Lista escrita a mao envelhece: a varredura procura no modulo quem
# deveria herdar e nao herda, em vez de conferir cinco nomes conhecidos.
import ai.schemas as _schemas
from pydantic import BaseModel as _BaseModel

orfaos = [
    nome for nome, obj in vars(_schemas).items()
    if isinstance(obj, type) and issubclass(obj, _BaseModel)
    and obj not in (_BaseModel, ArtifactModel)
    and obj.__module__ == 'ai.schemas'
    and not issubclass(obj, ArtifactModel)
]
confere(not orfaos, 'nenhum esquema de ai.schemas ficou fora de ArtifactModel',
        ', '.join(orfaos))

print('=== 7. os prompts declaram o tipo de cada campo ===')
# O prompt que nao declarava tipo foi metade da causa. A varredura cobra
# dos seis prompts, e nao dos dois que falharam: o proximo prompt escrito
# sem tipos seria o proximo defeito.
for kind, (template, esquema) in sorted(TASKS.items()):
    trecho = template.split('Campos:', 1)[-1]
    campos_citados = set(re.findall(r'"([a-z_]+)"', trecho))
    obrigatorios = {
        nome for nome, campo in esquema.model_fields.items()
        if campo.is_required() or campo.annotation is str
    }
    faltando = sorted(obrigatorios - campos_citados - {'source_refs', 'medical_review_notice'})
    confere(not faltando, f'{kind}: o prompt cita todos os campos de texto do esquema',
            ', '.join(faltando))
    # `(string)`/`(lista`/`(sempre true)`/`(numero` -- alguma anotacao de
    # tipo logo depois do nome.
    sem_tipo = sorted(
        nome for nome in campos_citados
        if nome in esquema.model_fields
        and not re.search(rf'"{nome}"\s*\(', trecho)
    )
    confere(not sem_tipo, f'{kind}: todo campo citado traz o tipo entre parenteses',
            ', '.join(sem_tipo))

print('=== 8. o esquema vai junto do pedido nas duas leituras de documento ===')
confere(STRUCTURED_OUTPUT_TASKS == {'lab_extraction', 'report_transcription'},
        'saida estruturada ligada exatamente nas duas tarefas de documento',
        str(sorted(STRUCTURED_OUTPUT_TASKS)))
formato = _formato_de_resposta(LabExtractionArtifact)
confere(formato['type'] == 'json_schema', 'o parametro e json_schema')
confere(formato['json_schema']['strict'] is False,
        'modo nao estrito -- o esquema tem campos com padrao e Optional')
esquema_json = formato['json_schema']['schema']
confere('unreadable_sections' in json.dumps(esquema_json),
        'o esquema enviado descreve o campo que causou o defeito')


class _ProvedorQueRecusa:
    """Provedor que rejeita `response_format` e responde bem sem ele.

    E o caso que o recuo existe para atender: o mesmo OpenRouter atende
    modelo que aceita `json_schema` e modelo que devolve 400. Sem recuo,
    ligar o esquema trocaria "as vezes sai torta" por "nunca sai".
    """

    def __init__(self, resposta):
        self.resposta = resposta
        self.tentativas = []

    def bind(self, **kwargs):
        vinculado = _ProvedorQueRecusa(self.resposta)
        vinculado.tentativas = self.tentativas
        vinculado._recusa = True
        return vinculado

    _recusa = False

    def invoke(self, prompt):
        self.tentativas.append('com esquema' if self._recusa else 'sem esquema')
        if self._recusa:
            raise RuntimeError(
                'Error code: 400 - response_format of type json_schema is not supported'
            )

        class _R:
            content = self.resposta

        return _R()


resposta_boa = json.dumps(dict(LAUDO_MINIMO, unreadable_sections=[]), ensure_ascii=False)
provedor = _ProvedorQueRecusa(resposta_boa)
estado = build_graph(provedor, 'lab_extraction').invoke({
    'prompt': 'p', 'timeout_seconds': 30, 'raw_response': None,
    'artifact': None, 'error': None, 'diagnostics': None,
})
print('   tentativas:', provedor.tentativas)
confere(provedor.tentativas == ['com esquema', 'sem esquema'],
        'o provedor que recusa o parametro e tentado de novo sem ele',
        str(provedor.tentativas))
confere(estado.get('error') is None, 'e a leitura sai mesmo assim', str(estado.get('error')))
confere((estado.get('artifact') or {}).get('unreadable_sections') == '',
        'com a forma ja normalizada')


class _ProvedorQueFalha:
    """Erro que NAO e recusa de parametro nao pode virar segunda chamada."""

    def __init__(self):
        self.chamadas = 0

    def bind(self, **kwargs):
        return self

    def invoke(self, prompt):
        self.chamadas += 1
        raise RuntimeError('Error code: 502 - upstream gateway error')


quebrado = _ProvedorQueFalha()
try:
    build_graph(quebrado, 'lab_extraction').invoke({
        'prompt': 'p', 'timeout_seconds': 30, 'raw_response': None,
        'artifact': None, 'error': None, 'diagnostics': None,
    })
except RuntimeError:
    pass
confere(quebrado.chamadas == 1,
        'falha de rede nao e confundida com recusa de parametro',
        f'{quebrado.chamadas} chamada(s)')

print('=== 9. a recusa fica diagnosticavel, e sem valor do laudo ===')


class _ProvedorTorto:
    def bind(self, **kwargs):
        return self

    def invoke(self, prompt):
        class _R:
            content = json.dumps({
                'exam_name': 'Hemograma',
                'collected_on': '03/10/2026',
                'analytes': [{'analyte': 'Hemoglobina', 'value_text': '13,2',
                              'numeric_value': 'treze virgula dois'}],
                'unreadable_sections': '',
                'limitations': 'x',
                'requires_physician_review': True,
            }, ensure_ascii=False)

        return _R()


estado = build_graph(_ProvedorTorto(), 'lab_extraction').invoke({
    'prompt': 'p', 'timeout_seconds': 30, 'raw_response': None,
    'artifact': None, 'error': None, 'diagnostics': None,
})
diag = estado.get('diagnostics') or {}
print('   diagnostico:', json.dumps(diag, ensure_ascii=False)[:300])
confere(estado.get('error') and 'formato' in estado['error'],
        'a mensagem que o medico le e em portugues', str(estado.get('error')))
confere(not re.search(r'[A-Za-z]+ output failed|validation error for',
                      estado.get('error') or ''),
        'e nao e o texto cru do Pydantic')
confere(diag.get('erros') and diag['erros'][0]['campo'].endswith('numeric_value'),
        'o diagnostico aponta o campo', json.dumps(diag.get('erros'), ensure_ascii=False)[:200])
confere(diag.get('forma_recebida', {}).get('analytes', '').startswith('list['),
        'e descreve a forma recebida', str(diag.get('forma_recebida')))

# A parte que decide: nenhum valor do laudo pode estar no diagnostico.
texto_diag = json.dumps(diag, ensure_ascii=False)
vazados = [v for v in ('Hemoglobina', '13,2', 'treze virgula dois', 'Hemograma')
           if v in texto_diag]
confere(not vazados, 'o diagnostico nao carrega nenhum valor do laudo', ', '.join(vazados))

# E o caso em que nem JSON veio.
class _ProvedorTagarela:
    def bind(self, **kwargs):
        return self

    def invoke(self, prompt):
        class _R:
            content = 'Claro! Aqui esta a leitura do laudo do paciente Joao da Silva...'

        return _R()


estado = build_graph(_ProvedorTagarela(), 'lab_extraction').invoke({
    'prompt': 'p', 'timeout_seconds': 30, 'raw_response': None,
    'artifact': None, 'error': None, 'diagnostics': None,
})
diag = estado.get('diagnostics') or {}
confere(diag.get('etapa') == 'resposta_nao_e_json', 'resposta fora de JSON e registrada como tal')
confere('Joao da Silva' not in json.dumps(diag, ensure_ascii=False),
        'e nem o inicio da resposta fora de JSON e guardado')

print('=== 10. a falha chega ao medico em portugues ===')
# A regra do repositorio vale aqui tambem, e foi aqui que ela escapou: a
# mensagem que o medico leu em 05/10 era `Model output failed schema
# validation: 1 validation error for LabExtractionArtifact`.
raiz = Path(dj_settings.BASE_DIR)
ingles = []
for arquivo in [raiz / 'ai' / 'graphs.py', raiz / 'ai' / 'services.py']:
    for numero, linha in enumerate(arquivo.read_text(encoding='utf-8').splitlines(), 1):
        if "'error':" not in linha and 'GraphTimeout(' not in linha:
            continue
        if re.search(r"(?:failed|exceeds|exceeded|invalid|error for)\b", linha, re.IGNORECASE):
            ingles.append(f'{arquivo.name}:{numero}')
confere(not ingles, 'nenhuma mensagem de recusa em ingles chega ao estado do grafo',
        ', '.join(ingles))

print('=== 11. a tela do rascunho mostra o detalhe sem mostrar o laudo ===')
detalhe = (raiz / 'templates' / 'ai' / 'job_detail.html').read_text(encoding='utf-8')
confere('failure_diagnostics' in detalhe, 'a tela do job renderiza o detalhe tecnico')
confere('<details' in detalhe, 'fechado por padrao -- nao e a primeira coisa que o medico le')

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - a leitura de laudo tolera forma, recusa conteudo, e explica a recusa.')

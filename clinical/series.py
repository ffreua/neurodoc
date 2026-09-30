"""Evolução do paciente no tempo: escalas, laboratório e medidas.

O prontuário já guarda tudo isto — Barthel de três consultas atrás, a
creatinina de cinco laudos, o peso de cada visita. O que faltava era **ver
junto**: número em linha de tabela não mostra tendência, e tendência é o
que decide conduta em doença crônica.

Mora fora da tela do atendimento de propósito. O prontuário de consulta já
carrega história, exame com quase quatrocentos itens, escalas, medicações
e laudos; acrescentar gráficos ali empurraria o que se usa todo dia para
baixo em favor do que se olha de vez em quando. A evolução abre por cima,
quando se pergunta por ela.

Três decisões que mudam o que o gráfico diz:

**O eixo do tempo é proporcional à data, e não ao número de consultas.**
Duas medidas separadas por cinco anos não podem ter o mesmo espaçamento de
duas separadas por uma semana. Distribuir os pontos por igual é o modo
mais fácil de desenhar e o mais fácil de ler errado: transforma uma piora
lenta em despencada e uma recaída aguda em declínio gradual.

**A escala pontuada usa o próprio domínio no eixo vertical.** Um Barthel
que vai de 40 para 60 numa escala de 0 a 100 é o que é. Esticar o eixo
para caber só os dois valores faria a mesma variação parecer catastrófica
— e em gráfico pequeno, sem ninguém ler o eixo, é a forma que fica.

**Série com um ponto só não é evolução.** É um número, e ele já está na
tela do atendimento. Oferecer "Creatinina (1 medida)" no seletor enche a
lista do que não responde nada.

O que este módulo **não** faz é interpretar. Não diz se subir é bom ou
ruim — depende da escala, e em algumas (Barthel, Glasgow) subir é
melhorar, enquanto em outras (NIHSS, mRS) é piorar. Quem lê é médico; o
gráfico mostra o número e a faixa de referência que o próprio laudo trouxe.
"""
from decimal import Decimal

from patients.models import Observation, ObservationKind

from .models import EncounterStatus, ExaminationFinding, LabValue

#: Abaixo de dois pontos não há linha para desenhar.
MIN_PONTOS = 2

#: Teto de pontos por série. Vinte anos de consulta trimestral dão oitenta
#: pontos; além disso o desenho vira ruído num gráfico do tamanho de um
#: modal, e o que interessa é a tendência recente.
MAX_PONTOS = 60

ESCALA = 'escala'
LAB = 'lab'
MEDIDA = 'medida'

#: Altura e largura do desenho em unidades de `viewBox`. O SVG é escalado
#: pelo CSS; estes números só fixam a proporção.
LARGURA = 720
ALTURA = 260
MARGEM_ESQ = 52
MARGEM_DIR = 16
MARGEM_TOPO = 16
MARGEM_BASE = 34


def _numero(valor):
    if valor is None:
        return None
    return float(valor) if isinstance(valor, Decimal) else float(valor)


def _escalas(context, patient):
    """Escalas aplicadas a este paciente, com o total de cada atendimento.

    O total mora em `ExaminationFinding.numeric_value`, e o `value_json`
    diz se a escala foi respondida por inteiro. **Escala incompleta fica
    de fora**: o escore parcial de uma Barthel com quatro dos dez itens não
    é comparável com o de uma respondida inteira, e plotar os dois na mesma
    linha inventa uma piora que não houve.
    """
    achados = (
        ExaminationFinding.objects
        .filter(
            tenant_id=context.tenant_id, encounter__patient=patient,
            item_code__startswith='escala.', numeric_value__isnull=False,
        )
        .select_related('encounter')
        .order_by('encounter__occurred_at')
    )
    series = {}
    for achado in achados:
        dados = achado.value_json or {}
        if dados.get('complete') is False:
            continue
        codigo = achado.item_code.split('.', 1)[1]
        entrada = series.setdefault(f'{ESCALA}:{codigo}', {
            'tipo': ESCALA, 'codigo': codigo,
            'rotulo': dados.get('name') or codigo.upper(),
            'unidade': 'pontos', 'pontos': [],
        })
        entrada['pontos'].append({
            'quando': achado.encounter.occurred_at,
            'valor': _numero(achado.numeric_value),
            'nota': dados.get('band') or '',
            'rascunho': achado.encounter.status != EncounterStatus.FINALIZED,
        })
    return series


def _laboratorio(context, patient):
    """Analitos com valor numérico, agrupados por nome e unidade.

    A unidade entra na chave porque o mesmo analito medido em unidades
    diferentes não forma uma série: creatinina em mg/dL e em µmol/L na
    mesma linha seria um salto de duas ordens de grandeza desenhado como
    piora renal.
    """
    valores = (
        LabValue.objects
        .filter(
            tenant_id=context.tenant_id, exam_result__encounter__patient=patient,
            numeric_value__isnull=False,
        )
        .select_related('exam_result__encounter')
        .order_by('exam_result__encounter__occurred_at')
    )
    series = {}
    for valor in valores:
        nome = (valor.analyte or '').strip()
        if not nome:
            continue
        unidade = (valor.unit or '').strip()
        chave = f'{LAB}:{nome.lower()}|{unidade.lower()}'
        entrada = series.setdefault(chave, {
            'tipo': LAB, 'codigo': nome,
            'rotulo': f'{nome} ({unidade})' if unidade else nome,
            'unidade': unidade, 'pontos': [],
            'referencia': (_numero(valor.reference_low), _numero(valor.reference_high)),
        })
        entrada['pontos'].append({
            'quando': valor.exam_result.encounter.occurred_at,
            'valor': _numero(valor.numeric_value),
            'nota': valor.get_flag_display() if valor.flag != 'no_reference' else '',
            'rascunho': valor.exam_result.encounter.status != EncounterStatus.FINALIZED,
        })
    return series


def _medidas(context, patient):
    """Peso e altura, que não passam por atendimento."""
    series = {}
    observacoes = (
        Observation.objects
        .filter(tenant_id=context.tenant_id, patient=patient)
        .order_by('observed_at')
    )
    rotulos = dict(ObservationKind.choices)
    for obs in observacoes:
        chave = f'{MEDIDA}:{obs.kind}'
        entrada = series.setdefault(chave, {
            'tipo': MEDIDA, 'codigo': obs.kind,
            'rotulo': f'{rotulos.get(obs.kind, obs.kind)} ({obs.unit})',
            'unidade': obs.unit, 'pontos': [],
        })
        entrada['pontos'].append({
            'quando': obs.observed_at, 'valor': _numero(obs.numeric_value),
            'nota': '', 'rascunho': False,
        })
    return series


def series_do_paciente(context, patient):
    """Todas as séries com pontos suficientes, na ordem em que a tela mostra.

    Escalas primeiro: são a medida que o médico escolheu aplicar, e a
    pergunta "como ele está evoluindo" quase sempre é sobre uma delas.
    Laboratório depois, e as medidas por último.
    """
    tudo = {}
    tudo.update(_escalas(context, patient))
    tudo.update(_laboratorio(context, patient))
    tudo.update(_medidas(context, patient))

    ordem = {ESCALA: 0, LAB: 1, MEDIDA: 2}
    resultado = []
    for chave, dados in tudo.items():
        if len(dados['pontos']) < MIN_PONTOS:
            continue
        dados['chave'] = chave
        dados['pontos'] = dados['pontos'][-MAX_PONTOS:]
        resultado.append(dados)
    resultado.sort(key=lambda d: (ordem[d['tipo']], d['rotulo'].lower()))
    return resultado


def _dominio_vertical(serie, escala_cadastrada=None):
    """Onde o eixo vertical começa e termina, e por quê.

    Para escala pontuada, o domínio é o da **própria escala** quando ela o
    declara: uma Barthel vai de 0 a 100 mesmo que este paciente só tenha
    ficado entre 40 e 60. Apertar o eixo em torno dos dados faria uma
    variação de vinte pontos ocupar o gráfico inteiro, e num desenho
    pequeno, sem ninguém ler o eixo, é a forma que fica na cabeça.

    Para laboratório e medida não há domínio natural, então é o dos dados
    com folga — e a faixa de referência entra no cálculo para que ela
    apareça inteira mesmo quando todos os valores estão fora dela.
    """
    valores = [p['valor'] for p in serie['pontos']]
    if serie['tipo'] == ESCALA and escala_cadastrada is not None:
        minimo, maximo = escala_cadastrada
        if minimo is not None and maximo is not None and maximo > minimo:
            return float(minimo), float(maximo)

    referencia = serie.get('referencia') or (None, None)
    candidatos = list(valores) + [v for v in referencia if v is not None]
    baixo, alto = min(candidatos), max(candidatos)
    if alto == baixo:
        # Série constante: sem folga, a linha cairia em cima do eixo e o
        # gráfico pareceria vazio.
        folga = abs(alto) * 0.1 or 1.0
        return baixo - folga, alto + folga
    folga = (alto - baixo) * 0.12
    return baixo - folga, alto + folga


def desenhar(serie, escala_cadastrada=None):
    """Converte a série em coordenadas de SVG. Sem biblioteca, de propósito.

    O desenho é feito aqui, em Python, e não no navegador: assim o roteiro
    de verificação confere a aritmética — inclusive a que importa, a do
    eixo do tempo proporcional — em vez de confiar que uma biblioteca
    externa fez a coisa certa. E uma tela a menos depende de script de
    terceiro, o que a política de conteúdo agradece.
    """
    pontos = serie['pontos']
    instantes = [p['quando'].timestamp() for p in pontos]
    t0, t1 = min(instantes), max(instantes)
    duracao = (t1 - t0) or 1.0

    baixo, alto = _dominio_vertical(serie, escala_cadastrada)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    largura_util = LARGURA - MARGEM_ESQ - MARGEM_DIR
    amplitude = (alto - baixo) or 1.0

    def x_de(instante):
        # Proporcional ao tempo real. Esta é a linha que separa um gráfico
        # honesto de um bonito.
        return MARGEM_ESQ + (instante - t0) / duracao * largura_util

    def y_de(valor):
        return MARGEM_TOPO + (alto - valor) / amplitude * altura_util

    desenhados = [
        {
            'x': round(x_de(p['quando'].timestamp()), 2),
            'y': round(y_de(p['valor']), 2),
            'valor': p['valor'],
            'quando': p['quando'],
            'nota': p['nota'],
            'rascunho': p['rascunho'],
        }
        for p in pontos
    ]

    faixa = None
    referencia = serie.get('referencia') or (None, None)
    if referencia[0] is not None and referencia[1] is not None:
        topo = y_de(min(referencia[1], alto))
        base = y_de(max(referencia[0], baixo))
        faixa = {
            'y': round(topo, 2), 'altura': round(max(base - topo, 1.0), 2),
            'de': referencia[0], 'ate': referencia[1],
        }

    return {
        'largura': LARGURA, 'altura': ALTURA,
        'eixo_x': MARGEM_ESQ, 'eixo_y': ALTURA - MARGEM_BASE,
        'fim_x': LARGURA - MARGEM_DIR, 'largura_util': largura_util,
        'pontos': desenhados,
        'linha': ' '.join(f'{p["x"]},{p["y"]}' for p in desenhados),
        'minimo': round(baixo, 2), 'maximo': round(alto, 2),
        'meio': round((baixo + alto) / 2, 2),
        'y_meio': round(MARGEM_TOPO + altura_util / 2, 2),
        'faixa': faixa,
        'primeiro': desenhados[0], 'ultimo': desenhados[-1],
        'variacao': round(desenhados[-1]['valor'] - desenhados[0]['valor'], 2),
    }

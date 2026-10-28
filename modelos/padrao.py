"""Os modelos do sistema: prontos em toda clínica, iguais para todas.

Moram em código, como os planos (`tenancy/plans.py`) e o contrato
(`tenancy/contract.py`), e pelo mesmo motivo: mudar um pedido que sai com
o nome de todas as clínicas é um commit com autor e data, e não uma linha
editada no banco. Não são copiados para cada clínica — o médico que quiser
mudar um deles faz **a sua cópia** em Modelos ("Copiar para meus modelos"),
e o do sistema continua igual para os outros.

As listas vieram do Dr. Fernando Freua (2026-10-27) e foram só
**reagrupadas** e postas em caixa alta, como a maioria delas já estava —
nenhum exame foi reescrito:

- imagem não fica junto com sangue: o grupo de origem que misturava as
  duas virou um **conjunto**, que abre um pedido por categoria;
- "Exames gerais" e "Reumatograma completo", citados dentro de outros
  grupos, foram **expandidos** — o pedido precisa dizer o exame, não o
  nome do grupo —, e o exame que já constava não se repete;
- "Rastreio paraneoplásico" virou dois conjuntos, homem e mulher, porque
  os exames por sexo eram parte da lista.

Nenhum código TUSS foi acrescentado: as listas não traziam, e um código
escrito de memória num pedido de convênio é pior que nenhum. O médico
acrescenta o seu ao copiar o modelo.

Cada modelo tem `slug` estável: o documento emitido registra de qual
modelo saiu (`content_snapshot['modelo']` = `s:<slug>`), e trocar o slug
apagaria esse rastro. Para aposentar um modelo, tire-o da lista; o
slug não volta a ser usado.
"""

from .estrutura import EXAMES


def _exames(*descricoes):
    return [{'codigo': '', 'descricao': d} for d in descricoes]


def _sem_repetir(*listas):
    vistos, saida = set(), []
    for lista in listas:
        for item in lista:
            chave = item['descricao'].casefold()
            if chave not in vistos:
                vistos.add(chave)
                saida.append(item)
    return saida


EXAMES_GERAIS = _exames(
    'HEMOGRAMA COMPLETO',
    'BILIRRUBINA TOTAL E FRAÇÕES',
    'PROTEÍNAS TOTAIS E FRAÇÃO',
    'FOSFATASE ALCALINA',
    'TGO',
    'TGP',
    'GAMA-GT',
    'COAGULOGRAMA (TP E TTPA)',
    'POTÁSSIO, SORO',
    'SÓDIO, SORO',
    'CÁLCIO IÔNICO, SORO',
    'CLORO, SORO',
    'MAGNÉSIO, SORO',
    'GASOMETRIA VENOSA',
    'FÓSFORO, SORO',
    'UREIA, SORO',
    'CREATININA, SORO',
    'GLICEMIA DE JEJUM',
    'HEMOGLOBINA GLICADA',
    'COLESTEROL TOTAL E FRAÇÕES (HDL, LDL)',
    'VITAMINA B12',
    '25-HIDROXIVITAMINA D — 25(OH) D (CALCIDIOL)',
    'ÁCIDO FÓLICO',
    'TSH',
    'T4 LIVRE',
)

REUMATOGRAMA = _exames(
    'ANTINEUTRÓFILOS (ANCA) P - PESQUISA E/OU DOSAGEM',
    'FATOR REUMATÓIDE, QUANTITATIVO - PESQUISA E/OU DOSAGEM',
    'COMPLEMENTO C4 - PESQUISA E/OU DOSAGEM',
    'ANTI-LA/SSB - PESQUISA E/OU DOSAGEM',
    'ANTI-RO/SSA - PESQUISA E/OU DOSAGEM',
    'ANTI-SM - PESQUISA E/OU DOSAGEM',
    'ANTI-DNA - PESQUISA E/OU DOSAGEM',
    'IMUNOFIXAÇÃO SÉRICA - CADA FRAÇÃO',
    'IMUNOFIXAÇÃO URINÁRIA',
    'ELETROFORESE DE PROTEÍNAS, SORO',
    'ANTICOAGULANTE LÚPICO, SORO',
    'ANTICARDIOLIPINA, ANTICORPOS IGG',
    'ANTICARDIOLIPINA, ANTICORPOS IGM',
    'FATOR ANTINÚCLEO, (FAN) - PESQUISA E/OU DOSAGEM',
    'PROTEÍNA C REATIVA (PCR)',
    'HEMOSSEDIMENTAÇÃO (VHS)',
    'CADEIAS LEVES LIVRES KAPPA/LAMBDA, DOSAGEM, SANGUE',
    'IMUNOCOMPLEXOS CIRCULANTES - PESQUISA E/OU DOSAGEM',
    'DOSAGEM DE IGM, SORO',
    'DOSAGEM DE IGG, SORO',
    'DOSAGEM DE IGA, SORO',
    'ANTINEUTRÓFILOS (ANCA) C - PESQUISA E/OU DOSAGEM',
    'ANTI-RNP - PESQUISA E/OU DOSAGEM',
    'ANTICORPOS ANTI PEPTÍDEO CÍCLICO CITRULINADO - IGG',
    'ANTIESCLERODERMA (SCL 70) - PESQUISA E/OU DOSAGEM',
    'COMPLEMENTO C3 - PESQUISA E/OU DOSAGEM',
    # "COMPLEMENTO C4" aparecia duas vezes na lista original.
    'COMPLEMENTO CH-50 - PESQUISA E/OU DOSAGEM',
)

PARANEOPLASICO_IMAGEM = _exames(
    'TC - ABDOME TOTAL C/ CONTRASTE',
    'TC - TÓRAX C/ CONTRASTE',
    'US - TIREOIDE',
    'PET-CT ONCOLÓGICO',
)
PARANEOPLASICO_ENDOSCOPIA = _exames(
    'ENDOSCOPIA DIGESTIVA ALTA COM BIÓPSIA E TESTE DE UREASE (PESQUISA HELICOBACTER PYLORI)',
    'COLONOSCOPIA COM BIÓPSIA E/OU CITOLOGIA',
)


def _modelo(slug, nome, grupos, indicacao='', observacoes=''):
    return {
        'slug': slug, 'tipo': EXAMES, 'nome': nome,
        'conteudo': {'grupos': grupos, 'indicacao': indicacao, 'observacoes': observacoes},
    }


MODELOS = [
    # ------------------------------------------------- laboratório (sangue)
    _modelo('exames-gerais', 'Exames gerais', {'laboratorio': EXAMES_GERAIS}),
    _modelo('trombofilias', 'Trombofilias', {'laboratorio': _exames(
        'ANTICOAGULANTE LÚPICO IGM, SORO',
        'ANTICORPOS BETA 2 GLICOPROTEINA I - IGG/IGM/IGA',
        'PROTEÍNA S, TESTE FUNCIONAL',
        'PROTROMBINA, PESQUISA DE MUTAÇÃO',
        'ANTICOAGULANTE LÚPICO IGG, SORO',
        'ANTICARDIOLIPINA, ANTICORPOS IGG',
        'HEMOGLOBINA (ELETROFORESE) - PESQUISA E/OU DOSAGEM',
        'ANTICARDIOLIPINA, ANTICORPOS IGM',
        'PROTEÍNA C, FUNCIONAL',
        'FATOR V DE LEIDEN POR PCR E MUTAÇÃO PROTROMBINA (G20210A)',
    )}),
    _modelo('sorologias', 'Sorologias', {'laboratorio': _exames(
        'HEPATITE C (ANTI-HCV)',
        'SOROLOGIA PARA SÍFILIS (VDRL) - SORO',
        'HEPATITE B (HBCAC), ANTI-CORE IGM',
        'FTA-ABS ANTICORPOS, IGG',
        'HIV-1 E HIV-2, PESQUISA DE ANTICORPOS',
        'HEPATITE B - (HBSAG) - ANTÍGENO AUSTRÁLIA',
        'HEPATITE B (HBCAC), ANTI-CORE IGG',
        'HEPATITE B (ANTI-HBS) - ANTICORPO ANTI-ANTÍGENO DE SUPERFÍCIE',
    )}),
    _modelo('reumatograma', 'Reumatograma', {'laboratorio': REUMATOGRAMA}),
    _modelo('miopatia', 'Miopatia', {'laboratorio': _sem_repetir(EXAMES_GERAIS, _exames(
        'CK (CPK) TOTAL',
        'ALDOLASE',
        'LDH',
        'TGO',
        'TGP',
        'URINA TIPO I',
        'PAINEL DE AUTOANTICORPOS ESPECÍFICOS/ASSOCIADOS À MIOSITE (ANTI-JO-1 / ANTI-PL-7 / '
        'ANTI-SRP / ANTI-HMGCR / ANTI-MI-2 / ANTI-MDA5 / ANTI-TIF1-γ)',
    ))}),
    _modelo('ataxia', 'Ataxia', {'laboratorio': _exames(
        'COBRE SÉRICO',
        'CERULOPLASMINA',
        'COBRE URINÁRIO 24 H',
        'CPK',
        'ALFA-FETOPROTEÍNA',
        'VITAMINA E (ALFA-TOCOFEROL)',
        'ANTI-TRANSGLUTAMINASE IGA',
        'DOSAGEM DE IGA TOTAL',
    )}),

    # ------------------------------------------------------------- imagem
    _modelo('tc-cranio-completa', 'TC de crânio completa', {'imagem': _exames(
        'TOMOGRAFIA COMPUTADORIZADA DE CRÂNIO',
        'TOMOGRAFIA COMPUTADORIZADA DE PESCOÇO',
        'ANGIOTOMOGRAFIA VENOSA DE PESCOÇO',
        'ANGIOTOMOGRAFIA ARTERIAL DE PESCOÇO',
        'TOMOGRAFIA COMPUTADORIZADA DE CRÂNIO COM CONTRASTE',
        'ANGIOTOMOGRAFIA ARTERIAL DE CRÂNIO',
        'ANGIOTOMOGRAFIA VENOSA DE CRÂNIO',
    )}),

    # -------------------------------------------------------------- líquor
    _modelo('liquor', 'Líquor (LCR)', {'liquor': _exames(
        'LCR AMBULATORIAL ROTINA (MANOMETRIA + ASPECTOS COR + ÍNDICE DE COR + CONTAGEM GLOBAL '
        'E ESPECÍFICA DE LEUCÓCITOS E HEMÁCIAS + CITOLOGIA ONCÓTICA + PROTEÍNA + GLICOSE + '
        'CLORO + ELETROFORESE DE PROTEÍNAS)',
        'MYCOBACTERIUM TUBERCULOSIS - PCR',
        'EXAME MICOLÓGICO - CULTURA E IDENTIFICAÇÃO DE COLÔNIA',
        'CRIPTOCOCO (TINTA DA CHINA), PESQUISA DE',
        'CRYPTOCOCCUS NEOFORMANS POR PCR, LÍQUOR',
        'CRIPTOCOCOSE, CÂNDIDA, ASPÉRGILUS (LÁTEX) - PESQUISA E/OU DOSAGEM EM LÍQUIDOS ORGÂNICOS',
        'ÍNDICE DE IMUNOPRODUÇÃO (ELETROF. E IGG EM SORO E LÍQUOR) - PESQUISA E/OU DOSAGEM',
        'PESQUISA DE BANDAS OLIGOCLONAIS POR ISOFOCALIZAÇÃO - PESQUISA E/OU DOSAGEM EM '
        'LÍQUIDOS ORGÂNICOS',
    )}),

    # ---------------------------------------------------------------- sono
    _modelo('sono', 'Sono', {'sono': _exames(
        'POLISSONOGRAFIA COMPLETA - TIPO 1 (LABORATORIAL)',
        'TESTE DE LATÊNCIAS MÚLTIPLAS DE SONO (TLMS) DIURNO PÓS PSG',
    )}),

    # ------------------------------------- conjuntos (um pedido por categoria)
    _modelo('exames-cardiologicos', 'Exames cardiológicos', {
        'cardiologia': _exames(
            'MONITORIZAÇÃO AMBULATORIAL DA PRESSÃO ARTERIAL - MAPA 24 HORAS',
            'ECODOPPLERCARDIOGRAMA TRANSTORÁCICO',
            'HOLTER DE 24 HORAS 3 CANAIS',
        ),
        'laboratorio': _exames(
            'PEPTÍDEO NATRIURÉTICO BNP/PROBNP - PESQUISA E/OU DOSAGEM',
            'CHAGAS, ANTICORPOS IGM',
            'CHAGAS, ANTICORPOS IGG',
        ),
    }),
    _modelo('queixa-cognitiva', 'Queixa cognitiva', {
        'imagem': _exames('RESSONÂNCIA MAGNÉTICA DE CRÂNIO'),
        'laboratorio': _exames(
            'HEMOGRAMA COMPLETO',
            'SÓDIO, POTÁSSIO, CÁLCIO',
            'UREIA E CREATININA',
            'GLICEMIA DE JEJUM E HBA1C',
            'TGO, TGP, FA, GGT, BILIRRUBINAS',
            'TSH, T4 LIVRE',
            'VITAMINA B12',
            'ÁCIDO FÓLICO',
            'HIV 1/2',
            'SÍFILIS: TESTE TREPONÊMICO + VDRL',
        ),
    }, indicacao='Investigação de queixa cognitiva.'),
    _modelo('neuropatia', 'Neuropatia', {
        'laboratorio': _sem_repetir(EXAMES_GERAIS, REUMATOGRAMA, _exames(
            # Eletroforese, imunofixação sérica e cadeias leves já vêm no
            # reumatograma; a imunofixação urinária ganha a amostra que a
            # lista de neuropatia especifica.
            'IMUNOFIXAÇÃO URINÁRIA EM AMOSTRA DE URINA ISOLADA',
            'DOSAGEM DE VITAMINA B6',
            'TOTG 2G (TESTE ORAL DE TOLERÂNCIA A GLICOSE)',
        )),
        'neurofisiologia': _exames(
            'ELETRONEUROMIOGRAFIA DE QUATRO MEMBROS (CONSIDERAR ESTUDO AUTONÔMICO)',
        ),
        'outros': _exames(
            'PESQUISA DE ATTR CONFORME FENÓTIPO/HISTÓRIA FAMILIAR',
            'BIÓPSIA DE PELE COM DENSIDADE DE FIBRAS NERVOSAS INTRAEPIDÉRMICAS',
        ),
    }, indicacao='Investigação de neuropatia periférica.'),
    _modelo('rastreio-paraneoplasico-homem', 'Rastreio paraneoplásico — homem', {
        'imagem': PARANEOPLASICO_IMAGEM + _exames('US - BOLSA TESTICULAR'),
        'laboratorio': _exames(
            'ANTÍGENO PROSTÁTICO ESPECÍFICO (PSA) TOTAL, SORO',
            'ANTÍGENO PROSTÁTICO ESPECÍFICO (PSA) LIVRE, SORO',
        ),
        'outros': PARANEOPLASICO_ENDOSCOPIA,
    }, indicacao='Rastreio de neoplasia oculta (investigação de síndrome paraneoplásica).'),
    _modelo('rastreio-paraneoplasico-mulher', 'Rastreio paraneoplásico — mulher', {
        'imagem': PARANEOPLASICO_IMAGEM + _exames(
            'US - TRANSVAGINAL',
            'US - MAMAS BILATERAL',
            'MAMOGRAFIA BILATERAL',
        ),
        'outros': PARANEOPLASICO_ENDOSCOPIA,
    }, indicacao='Rastreio de neoplasia oculta (investigação de síndrome paraneoplásica).'),
]

POR_SLUG = {m['slug']: m for m in MODELOS}

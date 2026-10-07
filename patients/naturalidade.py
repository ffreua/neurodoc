"""Países de nascimento, para a naturalidade do paciente.

**Em código, e não em tabela**, pela mesma razão dos planos
(`tenancy/plans.py`): é uma lista curta, estável, que muda por decisão e
não por operação — e que não vale uma migração, um comando de
importação e uma tela de manutenção.

A ordem não é alfabética pura, de propósito. Brasil primeiro porque é a
resposta de quase todo paciente, e logo depois os países de onde vem a
imigração que efetivamente aparece num consultório brasileiro. Uma lista
estritamente alfabética põe Afeganistão no topo e obriga a rolar até o B
cinquenta vezes por dia.

A lista **não é exaustiva** e não precisa ser: `birth_country` aceita
vazio, e `birth_city` é texto livre. Quem nasceu num país fora desta
lista é registrado pela cidade, que é o dado clinicamente útil.
"""

#: Os que aparecem primeiro, na ordem em que aparecem.
FREQUENTES = (
    ('BR', 'Brasil'),
    ('PT', 'Portugal'),
    ('JP', 'Japão'),
    ('IT', 'Itália'),
    ('ES', 'Espanha'),
    ('DE', 'Alemanha'),
    ('LB', 'Líbano'),
    ('SY', 'Síria'),
    ('BO', 'Bolívia'),
    ('PY', 'Paraguai'),
    ('AR', 'Argentina'),
    ('UY', 'Uruguai'),
    ('VE', 'Venezuela'),
    ('PE', 'Peru'),
    ('CO', 'Colômbia'),
    ('HT', 'Haiti'),
    ('AO', 'Angola'),
    ('CV', 'Cabo Verde'),
    ('MZ', 'Moçambique'),
    ('CN', 'China'),
    ('KR', 'Coreia do Sul'),
    ('US', 'Estados Unidos'),
)

#: O resto, em ordem alfabética.
DEMAIS = (
    ('ZA', 'África do Sul'),
    ('AU', 'Austrália'),
    ('AT', 'Áustria'),
    ('BE', 'Bélgica'),
    ('CA', 'Canadá'),
    ('CL', 'Chile'),
    ('CR', 'Costa Rica'),
    ('CU', 'Cuba'),
    ('DK', 'Dinamarca'),
    ('EC', 'Equador'),
    ('FR', 'França'),
    ('GR', 'Grécia'),
    ('GY', 'Guiana'),
    ('NL', 'Holanda'),
    ('IN', 'Índia'),
    ('ID', 'Indonésia'),
    ('IE', 'Irlanda'),
    ('IL', 'Israel'),
    ('MX', 'México'),
    ('NG', 'Nigéria'),
    ('NO', 'Noruega'),
    ('PA', 'Panamá'),
    ('PL', 'Polônia'),
    ('GB', 'Reino Unido'),
    ('RO', 'Romênia'),
    ('RU', 'Rússia'),
    ('SR', 'Suriname'),
    ('SE', 'Suécia'),
    ('CH', 'Suíça'),
    ('TR', 'Turquia'),
    ('UA', 'Ucrânia'),
)

#: O último item é a saída honesta para quem não está na lista: melhor
#: "Outro país" com a cidade escrita do que forçar uma bandeira errada.
OUTRO = ('XX', 'Outro país')

PAISES = FREQUENTES + DEMAIS + (OUTRO,)

#: `choices` do formulário, com o vazio na frente: não informar é um
#: estado legítimo, e não o mesmo que ter nascido no Brasil.
PAIS_CHOICES = (('', 'Não informado'),) + PAISES

_POR_CODIGO = dict(PAISES)


def rotulo_do_pais(codigo):
    """O nome do país, ou o próprio código quando não está na lista.

    Devolver o código cru em vez de vazio é deliberado: uma ficha antiga
    com um código que saiu da lista continua mostrando **alguma coisa**,
    e quem lê percebe que há um dado ali — em vez de ver um campo em
    branco e concluir que ninguém preencheu.
    """
    return _POR_CODIGO.get((codigo or '').upper(), codigo or '')

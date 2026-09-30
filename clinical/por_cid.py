"""Quem, na minha carteira, tem este diagnóstico.

A pergunta é de quem acompanha doença crônica: "chegou droga nova para
esclerose múltipla, quantos pacientes meus se beneficiariam?", "preciso
revisar todo mundo com epilepsia em uso de valproato". Até aqui a resposta
saía de memória, e memória de carteira de mil pacientes não existe.

**Esta é uma tela clínica, e não uma busca de cadastro.** O critério de
autorização é `READ_CLINICAL`, não `PATIENT_ADMIN` — deliberadamente. A
lista de pacientes do menu administrativo é aberta aos quatro papéis, e é
certo que seja: nome, telefone e convênio são trabalho de recepção.
Diagnóstico não é. Acrescentar CID ao filtro daquela lista custaria uma
linha de código e entregaria, a qualquer pessoa com acesso à agenda, a
resposta para "quem aqui tem B24". A separação é o recurso.

Duas decisões que mudam o resultado:

**O refutado não conta, e não basta filtrar por certeza.** `REFUTED` é o
médico dizendo "investiguei e não é". Se a hipótese foi levantada numa
consulta e descartada na seguinte, o registro antigo continua lá dizendo
"suspeita" — e uma busca que olhasse cada linha isoladamente devolveria o
paciente como se ele tivesse a doença. O que vale é a **última** palavra
sobre aquele código, por paciente. É o oposto do que se procura, e é o
erro que sairia caro: um convite para estudo de esclerose múltipla
endereçado a quem foi informado de que não tem.

**Procura pelos três caminhos.** Pelo código digitado ("G35", "g40.2",
"G402" — o ponto é pontuação de apresentação), pelo texto que o médico
gravou, e pelos códigos que o catálogo devolve para aquele termo. O
terceiro é o que faz "esclerose multipla" sem acento achar G35; o segundo
é o que acha o diagnóstico anotado à mão, sem código do catálogo, que é
coisa que existe no prontuário e sumiria de uma busca só por código.
"""
from django.core.paginator import Paginator
from django.db.models import Q

from catalogs.importers import normalize_for_search
from catalogs.selectors import search_diagnosis_codes
from patients.models import Patient, PatientStatus, RegistrationStage

from .models import DiagnosisCertainty, EncounterDiagnosis

#: Abaixo disto a busca não vale a varredura: "G" devolveria o capítulo
#: inteiro das doenças do sistema nervoso, que não é resposta para
#: pergunta nenhuma.
MIN_TERMO = 2

PAGE_SIZE = 25

#: Quantos códigos do catálogo entram na tradução do termo. Vinte é o teto
#: do próprio `search_diagnosis_codes`; mais do que isso e a busca por
#: palavra comum ("dor") passaria a varrer meio capítulo.
MAX_CODIGOS_DO_CATALOGO = 20

#: As três leituras que a tela oferece, e o que cada uma quer dizer.
#:
#: `ATIVAS` é o padrão porque é a pergunta que se faz noventa e nove vezes
#: em cem: quem tem, ou pode ter, esta doença. `REFUTADAS` existe para a
#: centésima — "de quem eu já suspeitei e descartei" — e fica atrás de uma
#: escolha explícita, com a tela dizendo o que ela significa.
ATIVAS = 'ativas'
CONFIRMADAS = 'confirmadas'
REFUTADAS = 'refutadas'

LEITURAS = {
    ATIVAS: (DiagnosisCertainty.CONFIRMED, DiagnosisCertainty.SUSPECTED),
    CONFIRMADAS: (DiagnosisCertainty.CONFIRMED,),
    REFUTADAS: (DiagnosisCertainty.REFUTED,),
}

ROTULOS = {
    ATIVAS: 'Confirmadas e suspeitas',
    CONFIRMADAS: 'Só confirmadas',
    REFUTADAS: 'Refutadas (investigadas e descartadas)',
}


def _filtro_do_termo(termo):
    """O que "procurar por isto" significa entre os diagnósticos gravados.

    Devolve `None` quando o termo é curto demais para valer a varredura —
    quem chama distingue "não procurei" de "procurei e não achei", que são
    duas telas diferentes.
    """
    termo = (termo or '').strip()
    if len(termo) < MIN_TERMO:
        return None

    alvo = normalize_for_search(termo)
    sem_ponto = alvo.replace('.', '')

    # "G40" tem de trazer G40.0, G40.1 e G40; "G40.2" só o G40.2. O
    # `startswith` faz as duas coisas sem que a tela precise de um botão
    # "incluir subcategorias" que ninguém saberia quando marcar.
    filtro = Q(code_snapshot__istartswith=alvo) | Q(code_snapshot__istartswith=sem_ponto)
    if len(sem_ponto) > 3 and sem_ponto[0].isalpha():
        # Quem digita no teclado numérico não digita o ponto, e o código
        # gravado o tem.
        filtro |= Q(code_snapshot__istartswith=f'{sem_ponto[:3]}.{sem_ponto[3:]}')

    # O texto que o médico gravou, para o diagnóstico anotado sem código.
    filtro |= Q(description_snapshot__icontains=termo)

    # E os códigos que o catálogo entende por este termo — o caminho que
    # faz "esclerose multipla", sem acento, achar G35.
    for achado in search_diagnosis_codes(termo, limit=MAX_CODIGOS_DO_CATALOGO):
        filtro |= Q(code_snapshot__iexact=achado['code'])
    return filtro


def _ultima_palavra(linhas):
    """Para cada (paciente, código), a certeza do atendimento mais recente.

    É aqui que o diagnóstico descartado deixa de contar. As linhas chegam
    ordenadas da mais antiga para a mais nova, e a última a escrever vence
    — que é como o prontuário se lê.
    """
    veredito = {}
    for paciente_id, codigo, certeza, quando in linhas:
        veredito[(paciente_id, (codigo or '').upper())] = (certeza, quando)
    return veredito


def buscar(context, termo, leitura=ATIVAS, incluir_arquivados=False, page=1):
    """Pacientes cujo diagnóstico casa com `termo`, um por linha.

    Devolve `None` quando não houve busca (termo vazio ou curto demais).
    """
    filtro = _filtro_do_termo(termo)
    if filtro is None:
        return None
    certezas = LEITURAS.get(leitura, LEITURAS[ATIVAS])

    base = (
        EncounterDiagnosis.objects
        .filter(tenant_id=context.tenant_id)
        .filter(filtro)
        # Pré-cadastro é um telefonema com nome; não tem prontuário para
        # ter diagnóstico, mas a trava fica explícita porque a lista não
        # pode passar a mostrar ficha que a de pacientes esconde.
        .filter(encounter__patient__registration_stage=RegistrationStage.COMPLETE)
    )
    if not incluir_arquivados:
        base = base.filter(encounter__patient__status=PatientStatus.ACTIVE)

    # Quatro colunas, sem instanciar modelo: é o suficiente para decidir
    # quem entra, e o que torna a varredura barata mesmo numa carteira
    # grande. Fazer isto em SQL exigiria função de janela e um subselect
    # que esconderia justamente a regra que mais importa aqui.
    linhas = list(
        base.order_by('encounter__occurred_at', 'id')
        .values_list(
            'encounter__patient_id', 'code_snapshot', 'certainty', 'encounter__occurred_at',
        )
    )
    veredito = _ultima_palavra(linhas)

    por_paciente = {}
    for (paciente_id, codigo), (certeza, quando) in veredito.items():
        if certeza not in certezas:
            continue
        atual = por_paciente.setdefault(
            paciente_id, {'codigos': set(), 'ultimo': quando, 'certezas': set()},
        )
        atual['codigos'].add(codigo)
        atual['certezas'].add(certeza)
        if quando > atual['ultimo']:
            atual['ultimo'] = quando

    ordenados = sorted(
        por_paciente.items(), key=lambda item: item[1]['ultimo'], reverse=True,
    )
    pagina = Paginator(ordenados, PAGE_SIZE).get_page(page)

    fichas = {
        p.id: p for p in Patient.objects.filter(id__in=[pid for pid, _ in pagina])
    }
    pagina.object_list = [
        {
            'patient': fichas[paciente_id],
            'codigos': sorted(dados['codigos']),
            'ultimo': dados['ultimo'],
            # Confirmada vence suspeita na etiqueta: o paciente que tem as
            # duas para códigos diferentes é, para esta lista, um caso
            # confirmado.
            'certeza': (
                DiagnosisCertainty.CONFIRMED
                if DiagnosisCertainty.CONFIRMED in dados['certezas']
                else sorted(dados['certezas'])[0]
            ),
        }
        for paciente_id, dados in pagina.object_list
        if paciente_id in fichas
    ]
    return pagina

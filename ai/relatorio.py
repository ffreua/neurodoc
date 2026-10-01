"""Relatório do paciente: a IA redige o rascunho, o médico assina.

O pedido que originou isto é concreto: o paciente precisa de um relatório
para a perícia do INSS, e escrevê-lo à mão significa reler dez anos de
prontuário atrás da data do diagnóstico, dos exames que importam e da
evolução — meia hora por relatório, com o paciente esperando.

**O que este módulo não faz, e é o mais importante.** Ele não emite
documento. Produz um *texto*, que o médico lê, corrige e só então
transforma em rascunho de `MedicalDocument` — daí em diante é o caminho
que já existe (`documents/issuance.py`): numeração, assinatura PAdES ou
impressão para assinar à caneta, QR, verificação pública. A regra está
escrita em `ai/review.py`: aceitar um rascunho de IA é juízo editorial
sobre o texto, nunca um atalho em volta da emissão. Quem assina é o autor.

Três decisões que explicam o resto do arquivo:

- **A identificação nunca chega ao modelo.** O contexto vai desidentificado,
  como todo o resto da IA aqui. O nome, o CPF e a data de nascimento são
  impressos pelo sistema no cabeçalho do PDF, que os lê da ficha. A
  consequência é a regra do prompt e a guarda de `marcadores_residuais`:
  se o modelo escrever `[PACIENTE]` no corpo, isso iria **literalmente**
  para o papel que o paciente entrega na perícia. Reinserir o nome por
  substituição cega seria pior — erraria em "a mãe do paciente".
- **Vale a última palavra sobre cada diagnóstico.** Um código refutado não
  entra como doença do paciente; ver `ai/tools/clinical.get_patient_diagnoses`.
- **O recorte é declarado.** O prontuário entra até um teto, e quando sobra
  coisa de fora a tela diz quanto e desde quando — ninguém deve assinar um
  relatório que ignora os primeiros anos sem saber disso.
"""

import dataclasses
import hashlib

from django.utils import timezone

from .tools import clinical as clinical_tools

#: O que a desidentificação deixa no texto, e que não pode sobreviver até o
#: papel. `ai/deidentification.py` é quem os escreve; esta tupla é a outra
#: ponta da mesma convenção, e as duas mudam juntas.
MARCADORES_DE_DESIDENTIFICACAO = (
    '[PACIENTE]', '[NOME_MAE]', '[CPF]', '[TELEFONE]', '[EMAIL]',
)

#: Teto de atendimentos que entram no relatório. É o mesmo de
#: `ai/tools/clinical.MAX_ENCOUNTERS`, e não um número próprio: duas
#: constantes para o mesmo limite divergem na primeira vez que alguém mexe
#: numa delas.
TETO_DE_ATENDIMENTOS = clinical_tools.MAX_ENCOUNTERS


@dataclasses.dataclass(frozen=True)
class Finalidade:
    """Para quem o relatório vai, e o que esse destinatário espera ler.

    As seções não são enfeite: são o que separa um relatório útil de um
    resumo de prontuário. Um perito procura desde quando a doença existe e
    o que ela impede; uma operadora procura a justificativa do
    procedimento; um colega procura o raciocínio. O mesmo prontuário
    responde às três, em ordens diferentes.
    """

    codigo: str
    rotulo: str
    destinatario: str
    secoes: tuple
    orientacao: str


#: Os modelos iniciais. São um ponto de partida revisável pelo médico — e é
#: por isso que moram em código, como os planos e o contrato: mudá-los é um
#: commit com autor e data, não um texto editado no banco sem rastro.
FINALIDADES = (
    Finalidade(
        codigo='inss',
        rotulo='Perícia do INSS / benefício previdenciário',
        destinatario='perito médico do INSS',
        secoes=(
            'Identificação do quadro clínico',
            'Diagnóstico e data em que foi estabelecido',
            'História e evolução clínica',
            'Exames complementares relevantes',
            'Tratamento em curso e resposta obtida',
            'Repercussão funcional',
            'Prognóstico',
        ),
        orientacao=(
            'O leitor é um perito médico. Diga desde quando o quadro existe e em que '
            'data cada diagnóstico foi estabelecido no prontuário, cite o CID quando '
            'ele estiver registrado, e descreva a repercussão funcional em termos do '
            'que foi observado e registrado — nunca conclua sobre incapacidade, '
            'aptidão para o trabalho ou concessão de benefício: isso é ato do perito, '
            'e não cabe a este relatório.'
        ),
    ),
    Finalidade(
        codigo='escola_trabalho',
        rotulo='Escola, empregador ou instituição',
        destinatario='escola, empregador ou instituição, sem formação médica',
        secoes=(
            'Situação clínica, em linguagem acessível',
            'Limitações observadas',
            'Adaptações recomendadas',
            'Período estimado',
        ),
        orientacao=(
            'O leitor não é médico e não tem direito ao detalhe clínico: descreva o '
            'que a condição exige em termos práticos — o que o paciente precisa, o '
            'que deve ser evitado, por quanto tempo. Só mencione diagnóstico ou CID '
            'se o pedido do médico pedir explicitamente.'
        ),
    ),
    Finalidade(
        codigo='plano_saude',
        rotulo='Operadora de plano de saúde',
        destinatario='auditoria médica da operadora',
        secoes=(
            'Diagnóstico e CID',
            'História clínica resumida',
            'Tratamentos já realizados e resposta',
            'Justificativa clínica do que se solicita',
        ),
        orientacao=(
            'O leitor é a auditoria médica. Seja objetivo e ancore cada afirmação no '
            'que está registrado: o que já foi tentado, por quanto tempo e com que '
            'resultado é o que sustenta a solicitação.'
        ),
    ),
    Finalidade(
        codigo='outro_medico',
        rotulo='Outro médico (encaminhamento ou segunda opinião)',
        destinatario='médico colega',
        secoes=(
            'Resumo do caso',
            'Exame e achados',
            'Exames complementares',
            'Condutas adotadas e evolução',
            'Motivo do encaminhamento',
        ),
        orientacao=(
            'O leitor é médico: pode usar terminologia técnica e não precisa de '
            'explicação de termo corrente. O que ele precisa é do raciocínio — o que '
            'já foi investigado, o que foi afastado e por quê.'
        ),
    ),
    Finalidade(
        codigo='livre',
        rotulo='Sem modelo — eu digo o que quero',
        destinatario='o destinatário que o médico indicar',
        secoes=(),
        orientacao=(
            'Não há modelo: organize o relatório conforme o pedido do médico, em '
            'seções que façam sentido para o que ele descreveu.'
        ),
    ),
)

_POR_CODIGO = {f.codigo: f for f in FINALIDADES}


def finalidade(codigo):
    """A finalidade pedida, ou a livre.

    Código desconhecido não derruba a tela nem vira erro: cai na livre, que
    é a que funciona sem modelo nenhum. É o lado seguro do erro — um
    relatório sem as seções esperadas o médico corrige lendo; uma tela que
    quebra ao receber um valor de formulário antigo não produz nada.
    """
    return _POR_CODIGO.get(codigo, _POR_CODIGO['livre'])


def escolhas():
    return [(f.codigo, f.rotulo) for f in FINALIDADES]


def marcadores_residuais(texto):
    """Marcadores de desidentificação que sobreviveram até a saída.

    Esta é a guarda que impede o defeito mais embaraçoso possível deste
    recurso: um relatório entregue na perícia dizendo "[PACIENTE] evoluiu
    com hemiparesia". Ela roda no validador do esquema, antes de o artefato
    existir — o rascunho com marcador nunca chega a ser gravado, porque um
    rascunho gravado é um rascunho que alguém pode aprovar sem reparar.
    """
    return [m for m in MARCADORES_DE_DESIDENTIFICACAO if m in (texto or '')]


def referencia_do_pedido(codigo_finalidade, pedido):
    """Identifica este pedido para a chave de idempotência do job.

    Sem ela, dois relatórios do mesmo paciente colidiriam: a chave de
    `create_job` para tarefa sem atendimento é só o paciente, e o segundo
    pedido — outra finalidade, outro texto — reaproveitaria a linha do
    primeiro e não rodaria. Com ela, o duplo clique continua protegido (o
    mesmo pedido dá a mesma chave) e o pedido diferente é outro job.
    """
    bruto = f'{codigo_finalidade}|{(pedido or "").strip()}'
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


def _idade_em(nascimento, referencia):
    return (
        referencia.year - nascimento.year
        - ((referencia.month, referencia.day) < (nascimento.month, nascimento.day))
    )


def montar_contexto(authorization, patient, teto=TETO_DE_ATENDIMENTOS):
    """O prontuário do paciente, pronto para desidentificar.

    Devolve `(contexto, source_refs, recorte)`. O `recorte` é o que a tela
    mostra ao médico antes de ele assinar: quantos atendimentos entraram,
    quantos existem e desde quando o relatório enxerga. Um relatório
    construído sobre os vinte atendimentos mais recentes de um paciente que
    tem sessenta é um documento legítimo — desde que quem assina saiba
    disso.

    Idade e sexo entram; nome, CPF e data de nascimento não. A idade é o
    que o texto clínico usa ("paciente de 42 anos"); a data de nascimento
    identifica, e o cabeçalho do PDF já a imprime a partir da ficha.
    """
    from clinical.models import Encounter

    hoje = timezone.localdate()
    demografia = {}
    if patient.birth_date:
        demografia['idade'] = _idade_em(patient.birth_date, hoje)
    if patient.sex_at_registration:
        demografia['sexo'] = patient.get_sex_at_registration_display()

    atendimentos = clinical_tools.get_patient_timeline(authorization, limit=teto)
    vigentes, refutados = clinical_tools.get_patient_diagnoses(authorization)
    medicacoes = clinical_tools.get_patient_medications(authorization)
    exames = clinical_tools.get_exam_results(authorization)

    total = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).count()
    datas = sorted(a['occurred_at'][:10] for a in atendimentos if a.get('occurred_at'))
    recorte = {
        'atendimentos_lidos': len(atendimentos),
        'atendimentos_totais': total,
        'completo': len(atendimentos) >= total,
        'desde': datas[0] if datas else '',
        'ate': datas[-1] if datas else '',
        'exames_lidos': len(exames),
        'diagnosticos_vigentes': len(vigentes),
    }

    contexto = {
        'paciente': demografia,
        'diagnosticos_vigentes': vigentes,
        'diagnosticos_refutados': refutados,
        'medicacoes': medicacoes,
        'exames_e_laudos': exames,
        'atendimentos': atendimentos,
        'recorte_do_prontuario': recorte,
    }
    source_refs = [
        {'type': 'encounter', 'id': a['encounter_id'], 'version_or_hash': a['occurred_at']}
        for a in atendimentos
    ]
    return contexto, source_refs, recorte


def texto_do_relatorio(resultado):
    """As seções do artefato, viradas no corpo de um relatório.

    O documento guarda **texto**, não a estrutura: `MedicalDocument` tem um
    campo `report_text`, e o PDF do relatório já sabe renderizá-lo. Inventar
    aqui um segundo formato estruturado obrigaria a escrever um segundo
    renderizador de PDF, que divergiria do primeiro na primeira mudança de
    cabeçalho.
    """
    partes = []
    for secao in (resultado or {}).get('secoes') or []:
        titulo = (secao.get('titulo') or '').strip()
        corpo = (secao.get('texto') or '').strip()
        if not corpo:
            continue
        partes.append(f'{titulo}\n\n{corpo}' if titulo else corpo)
    return '\n\n'.join(partes)


class RelatorioNaoAprovado(Exception):
    pass


def criar_rascunho_de_documento(artifact, physician_membership, actor_id):
    """Transforma o rascunho aprovado em rascunho de `MedicalDocument`.

    **Cria um rascunho, não emite nada.** A partir daqui o relatório segue
    o caminho que já existia antes desta funcionalidade: revisar, assinar
    com certificado ou imprimir para assinar à caneta. É de propósito que
    não haja um atalho até o PDF assinado — `ai/review.py` diz por quê, e
    a razão é que o autor do documento é quem assina, não quem revisa.

    O documento nasce **sem atendimento** (`encounter=None`), que
    `MedicalDocument` já admite: o relatório é sobre o histórico do
    paciente, não sobre uma consulta. Amarrá-lo à última consulta diria no
    papel que ele saiu dali, o que não é verdade.

    Ele fica na mesma lista dos outros documentos, e não num repositório
    separado — separá-los custaria numeração, assinatura, QR, verificação
    pública, retificação e arquivo morto, e produziria documentos de
    segunda classe. O que os distingue é a etiqueta `ai_artifact_id`, que
    é também a trilha: dado um relatório, dá para chegar ao rascunho que a
    IA escreveu, ao pedido que o originou e a quem o aprovou.
    """
    from documents.issuance import create_draft
    from documents.models import MedicalDocumentKind

    from .models import AIReviewState

    if artifact.review_state not in (AIReviewState.ACCEPTED, AIReviewState.EDITED):
        raise RelatorioNaoAprovado(
            'O rascunho precisa ser aprovado antes de virar documento.'
        )
    texto = texto_do_relatorio(artifact.result)
    if not texto.strip():
        raise RelatorioNaoAprovado('O rascunho está vazio: não há texto para o relatório.')

    job = artifact.job
    return create_draft(
        tenant=job.tenant, patient=job.patient, encounter=None,
        physician_membership=physician_membership, actor_id=actor_id,
        kind=MedicalDocumentKind.REPORT,
        content_fields={
            'report_text': texto,
            'ai_artifact_id': str(artifact.id),
            'ai_finalidade': (job.target_ref or {}).get('finalidade', ''),
        },
    )

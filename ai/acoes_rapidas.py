"""As ações rápidas do chat ligado a paciente: pedidos prontos, não um caminho novo.

Cada ação é só o **texto de um pedido**, que a tela coloca no campo de
mensagem para o médico ler, editar e enviar ele mesmo. Daí em diante a
mensagem segue o caminho de qualquer outra — mesma autorização, mesmo
recorte do prontuário, mesma desidentificação, mesmo provedor, mesmo
streaming, mesma persistência. Nada aqui é enviado sozinho, e o servidor
não sabe que a mensagem veio de um cartão.

A alternativa recusada era o backend receber um `acao_id` e montar o
prompt: daria um segundo jeito de falar com o modelo, que contornaria a
revisão do médico e pediria campo novo no `ChatMessage` só para lembrar de
onde o texto veio. Como pedido do médico, a ação fica **abaixo** das regras
de `CHAT_SYSTEM_PROMPT` — não as substitui, e o texto não tenta.

Os textos dizem o que o modelo de fato recebe: um **recorte** do prontuário
(`chat_prompt.build_patient_context` — os atendimentos mais recentes, os
exames e as medicações e diagnósticos do último atendimento, com teto de
tamanho), sem marca de qual atendimento está em rascunho. Por isso nenhum
pede "revise o prontuário inteiro", e todos mandam dizer o que faltou em
vez de completar.

Mudar um texto é um commit: o que o chat pede ao modelo em nome do médico
tem autor e data, como os preços e o contrato.
"""

from dataclasses import dataclass

#: Aviso comum, repetido em cada pedido de propósito: o médico pode apagar
#: partes do texto antes de enviar, e o aviso tem de sobreviver à edição.
_LIMITES = (
    'Considere que você recebeu apenas um recorte do prontuário (os atendimentos '
    'mais recentes, os exames e as medicações e diagnósticos do último atendimento), '
    'e não o prontuário inteiro; não diga que revisou tudo. Use somente o que está '
    'nesse recorte e nesta conversa. Quando faltar informação, diga que não está no '
    'recorte em vez de completar — dado ausente não é resultado normal.'
)


@dataclass(frozen=True)
class AcaoRapida:
    id: str
    rotulo: str
    descricao: str
    texto: str


ACOES = (
    AcaoRapida(
        id='revisao_diagnostica',
        rotulo='Revisar diagnóstico',
        descricao='Hipóteses, o que sustenta e o que contradiz cada uma, e possíveis vieses',
        texto=(
            'Revise criticamente o raciocínio diagnóstico deste paciente. Organize:\n'
            '1. O problema clínico central.\n'
            '2. As hipóteses já registradas, se houver.\n'
            '3. Os achados registrados que sustentam cada uma.\n'
            '4. Os achados registrados que as contradizem.\n'
            '5. Hipóteses alternativas plausíveis, apresentadas como possibilidades e '
            'não como diagnósticos.\n'
            '6. Os dados ausentes que mais ajudariam a distinguir entre elas.\n'
            '7. Avaliações que poderiam esclarecer as incertezas, sem prescrever conduta.\n'
            'Aponte sinais de ancoragem, fechamento prematuro ou inferência sem base. '
            'Não invente achados, não dê diagnóstico definitivo, não atribua '
            'probabilidade numérica e não prescreva tratamento.\n'
            + _LIMITES
        ),
    ),
    AcaoRapida(
        id='revisao_evolucao',
        rotulo='Revisar evolução',
        descricao='Contradições, lacunas e ambiguidades nos registros',
        texto=(
            'Revise os registros clínicos deste paciente em busca de pontos que mereçam '
            'revisão médica. Identifique:\n'
            '1. Contradições entre registros.\n'
            '2. Divergências entre história e exame.\n'
            '3. Diagnósticos que não combinam com os achados registrados.\n'
            '4. Problemas de cronologia.\n'
            '5. Informações essenciais que não estão documentadas.\n'
            '6. Trechos de redação ambígua.\n'
            '7. Conduta que não acompanha as hipóteses registradas.\n'
            'Para cada ponto, diga se é contradição demonstrada, possível inconsistência '
            'ou informação insuficiente. Você não sabe quais atendimentos estão em '
            'rascunho: se o que eu escrevi na consulta de hoje ainda não aparece no '
            'recorte, diga isso e peça que eu cole o trecho aqui. Não altere nada, não '
            'complete o exame físico e não trate dado ausente como normal.\n'
            + _LIMITES
        ),
    ),
    AcaoRapida(
        id='preparar_retorno',
        rotulo='Preparar retorno',
        descricao='Briefing do caso para a próxima consulta',
        texto=(
            'Prepare um resumo para a próxima consulta deste paciente, com:\n'
            '1. Resumo clínico objetivo.\n'
            '2. Diagnósticos e problemas ativos documentados.\n'
            '3. Tratamentos registrados.\n'
            '4. Evolução ao longo dos atendimentos disponíveis.\n'
            '5. Resultados de exames relevantes.\n'
            '6. Pendências que estejam explicitamente registradas.\n'
            '7. Informações que merecem ser atualizadas na consulta.\n'
            '8. Questões para eu revisar.\n'
            'Não diga que um exame está pendente só porque o resultado não aparece no '
            'recorte, e não presuma adesão, eficácia, efeito adverso ou estabilidade sem '
            'registro que sustente. Não sugira agendamentos.\n'
            + _LIMITES
        ),
    ),
    AcaoRapida(
        id='orientacoes_paciente',
        rotulo='Explicar ao paciente',
        descricao='Rascunho em linguagem simples, para eu revisar',
        texto=(
            'Escreva um rascunho de explicação para o paciente, em português claro e sem '
            'jargão (ou explicando o termo quando for inevitável), sobre o que já está '
            'documentado: diagnósticos, hipóteses em investigação, exames e orientações '
            'registradas. Deixe claro o que é diagnóstico estabelecido e o que ainda é '
            'hipótese. Não acrescente tratamento, não informe dose que não esteja '
            'registrada, não faça prognóstico individual e não prometa resultado. '
            'Marque o que depende da minha confirmação. Termine indicando que é um '
            'rascunho para revisão do médico, e não uma orientação já entregue.\n'
            + _LIMITES
        ),
    ),
)

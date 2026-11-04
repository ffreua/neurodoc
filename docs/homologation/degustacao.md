# Degustação de sete dias do Completo — homologação

Versão **1.35** (2026-11-04). Qualquer pessoa abre, pela página de vendas,
uma clínica no plano Completo por sete dias, sem cartão; no oitavo dia ela
volta ao Gratuito. O mecanismo inteiro está em `tenancy/degustacao.py`.

## 1. As decisões

Tomadas pelo responsável em 2026-11-04, depois de a proposta mostrar os
pontos em aberto:

| # | Pergunta | Decisão |
| --- | --- | --- |
| 1 | Médicos além do limite do Gratuito no oitavo dia | **Perdem o papel médico** até a clínica contratar. Fica o que o responsável escolher; sem escolha, o mais antigo. Nada do que escreveram some |
| 2 | Custo de IA e SMS da instalação | **Teto**: 30 pedidos de IA e 20 SMS durante a degustação. O e-mail não tem teto |
| 3 | TISS e agenda de exames | **Não** vêm liberados: seguem pelo console, como em toda clínica do Completo |
| 4 | Contrato | A pessoa **adere ao Gratuito**, e a degustação fica registrada no aceite como condição comercial. A advogada foi consultada e concorda |
| 5 | Quem pode | **Qualquer pessoa pelo site**, como o Gratuito |

A alternativa recusada na 1 era aceitar a brecha — uma degustação com cinco
médicos convidados viraria um Gratuito com cinco médicos para sempre — ou
deixar a clínica somente leitura no oitavo dia, o que tiraria o Gratuito de
quem não contratasse.

## 2. Por que a clínica fica de fato no Completo

`Tenant.plan` vale `complete` durante a degustação. O plano é lido em umas
sessenta linhas do sistema — limites, IA, SMS, menu, telas —, e nenhuma
precisou saber que degustação existe. A alternativa, um "plano efetivo"
calculado na leitura, trocaria as sessenta e deixaria a próxima, a que
alguém escrever amanhã, lendo o plano errado.

## 3. O prazo

A meia-noite de Brasília que encerra o sétimo dia de calendário
(`degustacao.prazo_a_partir_de`): quem começa às 22h de segunda tem a
segunda como primeiro dia e vai até domingo, e a tela diz "até domingo".
Não são 168 horas, que terminariam às 22h de uma segunda que a tela não
mencionou.

**O fim é aplicado em três lugares, e os três são necessários:**

- a cada requisição de `/app/` (`TenantMiddleware`, antes de montar as
  capacidades, que leem o plano);
- antes de todo trabalho de IA (`ai/context.py::build_ai_authorization`) e
  de todo SMS (`communications/smsdev.py`) — o worker não passa pelo
  middleware, e o lembrete do sétimo dia não pode sair por SMS no oitavo;
- pela tarefa `tenancy.tasks.rodada_da_degustacao`, a cada quinze minutos,
  que encerra a clínica que ninguém abriu e manda o aviso de véspera.

O encerramento trava a linha da clínica: duas abas e a tarefa chegando
juntas encerram uma vez só, e só o primeiro manda o e-mail.

## 4. Os tetos

- **IA:** tarefas (`AIJob`) e perguntas do chat (`ChatMessage` do usuário)
  criadas desde o início da degustação, contadas nas linhas que existem, e
  não num contador à parte. Conferido em três portas: `create_job` (pedido
  **novo** — pedir de novo o mesmo resumo não gasta cota), o resumo
  automático (`ai/handlers.py`, que sai por `return` para não falhar o
  evento) e o chat (a pergunta não é gravada e a tela diz por quê).
- **SMS:** só pela **chave da instalação**, contado depois do envio aceito,
  por `F()`. A clínica que trouxe a própria chave paga a própria conta e não
  tem teto. A recusa é `SmsChannelDisabled`, que todo caminho de envio já
  trata como canal indisponível — o e-mail continua.

## 5. O contrato

O aceite grava `plan='free'` e valor zero, como qualquer Gratuito, e mais
`degustacao_plano='complete'` e `degustacao_ate`. A via por e-mail traz a
linha "Condição comercial: degustação do plano Completo até dd/mm/aaaa
(último dia); depois, plano Gratuito". Nenhuma cláusula mudou: o oitavo dia
não rescinde nada — a clínica volta ao plano que contratou.

## 6. A conversão

É a troca de plano do console, a de sempre. Numa clínica que veio da
degustação, ela chama `degustacao.converter`: o prazo sai de cena e os
vínculos que perderam o papel médico no oitavo dia voltam (ativos, e com o
papel), até o limite do plano novo. O console também **estende** a
degustação em andamento por mais sete dias; a encerrada não, porque
reabri-la seria uma segunda degustação.

## 7. O que impede abuso

A porta é a do Gratuito (`StartTrialView` herda de `StartFreePlanView`): POST
com CSRF, campo-armadilha, teto de três convites por IP por hora que falha
fechado, convite de dois dias. O e-mail descartável é recusado no cadastro.
Uma degustação por conta e por documento sai do que já existia: o cadastro
cria sempre uma conta nova, e CNPJ e CPF são únicos no banco — a clínica que
terminou a degustação continua ocupando o documento. Um convite forjado com
`degustacao=True` e outro plano ainda degusta só o Completo.

## 8. Resultado do roteiro

`checks/check_degustacao.py`, doze seções, nenhuma falha:

1. a porta da vitrine (botão, GET sem efeito, campo-armadilha, o cadastro
   dizendo "degustação" e o depois, `robots.txt`);
2. o cadastro no Completo com prazo, o aceite do Gratuito com a condição, a
   via e as boas-vindas dizendo até quando; o convite forjado e o comum;
3. o prazo: segunda 22h → meia-noite da segunda seguinte, 23h59 conta,
   00h00 não, os dias que faltam;
4. a faixa, e a clínica comum sem ela;
5. o teto de IA: só a pergunta do usuário desde o início, o chat que não
   grava a pergunta, `create_job` recusando, o resumo automático por
   `return`;
6. o teto de SMS: vinte pela chave da instalação, o 21º recusado sem chegar
   ao provedor, a chave da clínica sem contar;
7. a escolha do médico: vínculo de outra clínica, quem não é médico, id
   inválido e GET recusados; a secretária não escolhe;
8. o oitavo dia pela tela: Gratuito, o escolhido mantido, quem só era médico
   suspenso, quem também era secretária mantido sem o papel, nenhum vínculo
   apagado, a trilha, o e-mail uma vez, o segundo encerramento sem efeito;
9. pelo worker e pela tarefa: o SMS do oitavo dia recusado e a clínica
   encerrada ali, o aviso de véspera uma vez em duas rodadas, a tarefa
   encerrando quem ninguém abriu, o agendamento a cada quinze minutos;
10. a conversão devolvendo os dois médicos e tirando o prazo e a faixa;
11. estender só em andamento;
12. o FAQ com os números do código, e o TISS fora da degustação.

Conferido também com o defeito injetado (o encerramento ignorando o médico
escolhido): duas reprovações, nas linhas certas.

**O roteiro cadastra de endereços de documentação** (RFC 5737) e zera os
contadores deles: o cadastro tem teto de 20 por IP por hora, e com o IP
local de sempre este roteiro, somado aos outros, estourava o teto e
reprovava os roteiros de cadastro que rodassem depois.

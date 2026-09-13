# Inativar uma organização, sem apagar nada

Console do superadministrador, `/instalacao/organizacoes/`, botão
**Estado**. Evidências: `checks/check_inativacao.py`.

## O campo existia e não fazia nada

`TenantStatus.SUSPENDED` está no modelo desde o começo. A única coisa que
o respeitava era o portal público do paciente (`documents/portal.py`), que
filtra por `status=ACTIVE`. `build_access_context` nunca olhou o estado —
então marcar uma clínica como suspensa não mudava absolutamente nada para
quem já tinha vínculo. Faltava a regra, não o campo.

## Dois desligamentos, porque são dois motivos

| Estado | Quem entra | O que pode fazer | Para quando |
| --- | --- | --- | --- |
| `active` | Todos | Tudo | — |
| `suspended` | Todos | **Só leitura**: consulta, impressão, exportação | Falta de pagamento |
| `closed` | Ninguém | Nada; a tela explica a quem recorrer | Rescisão contratual |

A separação não é preciosismo. Cortar o acesso do médico ao prontuário dos
próprios pacientes por causa de um boleto atrasado transformaria uma
questão comercial num problema de assistência — e o prontuário tem guarda
legal de vinte anos, que não é do sistema interromper. Suspensa **congela**
e se desfaz sozinha quando a fatura é paga.

Encerrada é a decisão definitiva, e mesmo ela **não apaga nada**: fecha a
porta e diz por onde pedir a exportação. `check_inativacao`, seção 5,
conta pacientes e atendimentos antes e depois de passar pelos dois estados
e falha se um número mudar.

## Onde a regra mora

`tenancy/middleware.py`, e não nas views. O critério é o **método HTTP**:
`GET`/`HEAD`/`OPTIONS` passam, o resto é recusado com 403 e uma tela que
explica.

Marcar view por view seria a alternativa óbvia e a errada: a view esquecida
é justamente a que ninguém testa. E a capacidade não serve de critério
aqui — `PATIENT_ADMIN` governa o cadastro inteiro, leitura **e** escrita,
então retirá-la esconderia o prontuário, que é o contrário do que
"congelar" significa.

Uma exceção, declarada: `/app/notifications/`. Marcar um aviso como lido é
estado do usuário, não da clínica; trancá-lo encheria o sino de avisos que
a pessoa não tem como baixar, sem proteger dado nenhum. Entrar, sair e
trocar de organização vivem em `/accounts/`, fora do alcance do
middleware — quem está numa clínica congelada continua tendo como sair.

## O usuário descobre antes de perder trabalho

Três lugares, nesta ordem:

1. **O seletor de organização** mostra `suspensa` / `encerrada` ao lado do
   nome, antes do clique.
2. **Uma faixa em toda tela** enquanto a clínica estiver suspensa, não
   dispensável — o estado dura enquanto durar, e um aviso que some com um
   clique reaparece como surpresa na tela seguinte.
3. **A tela de recusa**, se a pessoa tentar salvar assim mesmo.

A tela de encerramento herda `base_auth.html`, sem barra lateral: oferecer
navegação que responde 403 uma a uma é pior do que não oferecer nenhuma. A
de suspensão herda `base.html`, porque ali a navegação **funciona** — quem
perdeu o botão de salvar não perdeu o sistema.

## A clínica desligada para de falar com o paciente

Quase tudo que envia nasce de um `POST`, já recusado pelo middleware. O que
escapava era o que foi enfileirado **antes** do desligamento: uma campanha
em lotes, um lembrete agendado — continuariam saindo por dias, assinados
por uma clínica que já não tem acesso ao próprio sistema.

A verificação ficou em `communications/services.py::_send`, por onde os
dois canais passam, e a tentativa é registrada como `tenant_inactive` em
vez de sumir. A seção 7 do roteiro confere as duas direções: que a clínica
desligada não envia, **e** que a ativa continua enviando — sem a segunda,
a seção estaria apenas verificando que o envio falha sempre.

## Motivo obrigatório

Como na troca de plano. Um estado sem motivo escrito é indistinguível de
um erro seis meses depois, e a pergunta que se faz então — "por que esta
clínica está suspensa?" — não tem outra fonte: o e-mail que combinou se
perdeu, e quem combinou pode não estar mais aqui. O motivo entra na trilha
(`tenancy.tenant_status_changed`, com o de-para) e aparece na listagem sob
o estado.

## O que foi verificado

`checks/check_inativacao.py`, nove seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Clínica ativa funciona (linha de base)? | Lista 200, POST 200 |
| 2 | Suspensa lê e não escreve? | 200 / 200 / **403** |
| 3 | A tela avisa, e explica? | Faixa + "nada foi apagado" |
| 4 | Encerrada fecha e explica? | 403, com destino de contato |
| 5 | Algum registro sumiu? | 11 pacientes, 10 atendimentos, intactos |
| 6 | A outra clínica sentiu algo? | 200 |
| 7 | Desligada ainda envia ao paciente? | Barrado; ativa continua enviando |
| 8 | Reativar devolve tudo? | Sim, e a faixa some |
| 9 | O console exige motivo e registra? | Sem motivo não muda; trilha com de-para |

A seção 1 existe para que as seções 2 e 8 signifiquem alguma coisa: sem
uma linha de base que passa, "403" não distingue clínica congelada de rota
quebrada.

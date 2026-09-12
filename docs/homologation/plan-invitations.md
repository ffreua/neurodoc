# Convites com plano e console comercial (Entrega 2)

O código de convite passa a carregar o plano contratado, e o console da
instalação ganha as duas telas que faltavam para vender: emitir convite e
trocar o plano de uma clínica que já existe.

Especificação: [`docs/specs/2026-09-12-planos-e-limites.md`](../specs/2026-09-12-planos-e-limites.md).
Evidências: `checks/check_convite_plano.py`, contra a pilha Docker local.

## O convite carrega o que foi vendido

`Invitation` ganhou `plan`, `patient_limit_override`,
`doctor_limit_override` e `plan_note`. `accept_platform_invitation` lê do
convite em vez do `plan='free'` que estava escrito na linha 54 de
`tenancy/services.py`.

Antes, toda organização nascia no Gratuito. Quem vendesse o Completo teria
de corrigir o plano à mão depois de o cliente entrar — e ninguém saberia
dizer se um cliente está no plano certo sem perguntar a quem vendeu.

O token continua sendo 32 bytes aleatórios com hash, uso único e prazo. O
que mudou é o que ele promete.

**Vale só para `purpose='platform'`.** Convite de colaborador entra numa
clínica que já tem plano, e deixá-lo alterar isso seria uma forma
silenciosa de mudar contrato: bastaria o dono convidar uma secretária com
um convite forjado para ampliar a própria cota. `issue_invitation` ignora
plano e overrides nesse caso, em vez de aceitá-los e não usá-los —
verificado na seção 3 do roteiro.

`plan_note` viaja do convite para a organização. É o que responde "por que
esta clínica tem 1.200 pacientes?" um ano depois, quando o convite já
sumiu da vista e o e-mail que combinou se perdeu.

## O console deixa de ser só leitura

Duas escritas, e só duas: **emitir convite de plataforma** e **trocar o
plano de uma organização**. As duas são atos comerciais sobre a
instalação, não sobre pacientes, e não existem em nenhuma outra tela —
quem vende é quem opera o servidor.

Nenhuma delas toca em prontuário, que é a linha que o arquivo inteiro
protege. O resto do que exige escrita continua no admin técnico do Django.

A exigência de `is_superuser` **mais MFA verificada** já estava na base
das views e vale para as telas novas sem nada acrescentado — verificado na
seção 5: as duas respondem 404 para superadministrador sem MFA.

### `/instalacao/convites/`

Emitir escolhendo plano, limites, vínculo de e-mail, prazo e motivo. Ver
os pendentes com quem emitiu e quando. Revogar.

**O token aparece uma vez.** Guardamos o hash, nunca o valor: um convite
legível na tela depois de emitido seria um convite legível por quem
tivesse acesso de leitura ao banco. Ele é devolvido pelo próprio `POST`, e
não pela sessão nem por `messages` — que o gravariam no Redis e no cookie.
Recarregar a página não o traz de volta, verificado na seção 6.

**Convite já usado não se revoga.** Revogá-lo não desfaria a organização
criada, e daria a impressão de ter desfeito. A tela recusa e aponta para a
troca de plano, que é onde se mexe no que já existe.

### `/instalacao/organizacoes/`

Passou a mostrar **uso contra limite** — `18 / 3000`, com marca de "cheio"
ou do percentual quando passa de 80%. É o que torna a troca de plano uma
decisão em vez de um palpite: rebaixar para um teto abaixo do uso corrente
é legítimo, mas quem confirma precisa ver que é isso que vai acontecer.

A troca **exige motivo escrito**. Um plano trocado sem motivo é
indistinguível de um erro seis meses depois. O evento
`tenancy.tenant_plan_changed` grava o de-para completo e a nota — dado
administrativo, nunca clínico.

## Campo em branco não é zero

Nas duas telas, limite em branco significa "usa o plano" e `0` é um limite
de verdade — a clínica suspensa comercialmente que não deve cadastrar mais
ninguém. `int(valor or 0)` transformaria o campo vazio em zero e travaria
a clínica inteira por um campo que a pessoa só não preencheu. Verificado
nas seções 8 e 10: em branco resolve para 3000, e `0` bloqueia.

## Dois achados do caminho

**`AuditEvent.tenant` é `PROTECT`.** A limpeza do roteiro quebrou nisso, e
o comportamento está certo: auditoria que some junto com o objeto auditado
não é auditoria. Para apagar uma organização é preciso apagar a trilha
dela antes, o que é deliberadamente incômodo.

**`Membership.tenant` também é `PROTECT`**, pelo mesmo motivo.

## O que foi verificado

`checks/check_convite_plano.py`, dez seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | A organização nasce no plano do convite? | `custom` com limites nulos, e a nota junto |
| 2 | Override do convite chega? | 1200 pacientes / 3 médicos num Básico |
| 3 | Convite de colaborador mexe em plano? | Não: cai em `free` sem override |
| 4 | Plano inexistente na emissão? | Recusado |
| 5 | Console sem MFA? | 404 nas duas telas |
| 6 | Emitir, ver o token uma vez, revogar | Emite, mostra, não repete ao recarregar, revoga |
| 7 | Revogar convite já usado? | Recusado, e a clínica fica intacta |
| 8 | Trocar plano sem motivo? | Recusado; com motivo, grava |
| 9 | A troca vai para a trilha? | `tenancy.tenant_plan_changed` com de-para |
| 10 | Zero pelo console? | Vira limite de verdade e bloqueia |

O roteiro cria e apaga duas organizações sintéticas — uma delas com o CNPJ
real do consultório do responsável pelo produto, para exercitar o caminho
exato que ele vai usar — e limpa tudo ao final.

## Próximo

Entrega 3 (página de vendas e formulário de contato) e Entrega 4
(preparação final do domínio).

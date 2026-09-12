# Planos e limites (Entrega 1)

Quatro planos com limite de pacientes e de médicos, e a trava valendo nas
seis portas por onde paciente e médico entram no sistema.

Especificação: [`docs/specs/2026-09-12-planos-e-limites.md`](../specs/2026-09-12-planos-e-limites.md).
Evidências: `checks/check_planos.py`, contra a pilha Docker local.

## O catálogo

| Código | Nome | Pacientes | Médicos |
| --- | --- | --- | --- |
| `free` | Gratuito | 50 | 1 |
| `basic` | Básico | 500 | 2 |
| `complete` | Completo | 3.000 | 5 |
| `custom` | Personalizado | ilimitado | ilimitado |

Vive em **código** (`tenancy/plans.py`), não numa tabela. Um plano é o
registro do que foi vendido a alguém: numa tabela, baixar o limite do
Básico de 500 para 400 alteraria em silêncio o direito de toda clínica já
contratada, e não sobraria nada dizendo que antes era outro. Em código, a
mesma mudança é um commit — com data, autor e a chance de alguém perguntar
por quê antes de ela valer.

O texto de venda mora junto dos números, e não no template, para a página
pública e o que o sistema cumpre não poderem divergir. Anunciar "até 500"
numa tela enquanto o servidor corta em 400 é o defeito que esse
acoplamento impede.

## O que varia por cliente é o desvio, não o plano

`Tenant.patient_limit_override` e `doctor_limit_override`, nulos por
padrão. **Nulo usa o plano; preenchido, vale o valor.** A clínica que
negociou 1.200 pacientes continua no Básico com um override, em vez de
virar um quinto plano — senão o catálogo cresceria com o número de
clientes.

`plan_note` guarda por que esta clínica tem o plano que tem (contrato,
cortesia, piloto). É o que responde à pergunta um ano depois, quando quem
combinou já não lembra e o e-mail se perdeu.

**Ilimitado é `None`, nunca um número grande.** `999999` é um limite que
um dia alguém bate, e na véspera ninguém sabe que ele existe.

**Acesso irrestrito é o plano `custom` sem override** — e não um campo
`is_unlimited` nem uma exceção por e-mail. Uma exceção codificada para uma
conta específica é invisível na tela, não aparece na trilha e sobrevive à
venda da empresa. Como plano, fica visível, auditável e reversível.

### Zero é um limite, não "não configurado"

`_resolve` testa contra `None`, e não pela verdade do valor. `if override:`
trataria `0` como ausente e devolveria o limite do plano — o oposto do que
se pediu ao gravar zero, que é a clínica suspensa comercialmente que não
deve cadastrar mais ninguém. Verificado na seção 3 do roteiro.

## O que conta

**Pacientes ativos.** Arquivar libera vaga, desarquivar volta a ocupar.
Coerente com o resto do produto, onde arquivar já tira o paciente da
carteira ativa e dos indicadores, e não pune quem mantém o cadastro limpo.

**Vínculos ativos com papel médico** — não convites emitidos, não vínculos
suspensos. Suspender serve a férias e afastamento: cobrar a vaga de quem
está afastado obrigaria a clínica a revogar o vínculo, que apaga a trilha
de quem assinou o quê, só para caber no plano.

## As seis portas

Paciente nasce em **dois** lugares:

| Local | Observação |
| --- | --- |
| `patients/views.py::PatientCreateView` | Cadastro completo. A trava roda **antes** de validar o formulário — recusar depois de trinta campos preenchidos é pior — e **de novo dentro da transação**, que é o que impede duas recepcionistas de passarem juntas pela última vaga |
| `scheduling/services.py::quick_register_patient` | Pré-cadastro ao telefone. **É o que se esquece**: a secretária cria paciente marcando horário, sem nunca abrir a tela de cadastro. Fora daqui, a cota valeria só pela porta da frente |

Médico entra por **quatro**, e há uma quinta verificação, preventiva:

| Local | Observação |
| --- | --- |
| `MembershipRolesView` | A conta é sobre o **ganho** do papel: quem já era médico e está trocando de secretária para gestora não pode ser recusado por uma cota que ele próprio ocupa |
| `MembershipStatusView` (reativar) | Reativar volta a ocupar; suspender libera |
| `accept_collaborator_invitation_for_user` | Aceite por quem já tem conta |
| `accept_collaborator_invitation_new_user` | Aceite por conta nova |
| `TeamView` (emissão do convite) | **Preventiva.** Sem ela, o convidado descobriria o limite depois de clicar no link — e quem pode resolvê-lo é o dono da clínica, não ele |

O aceite continua sendo a verificação autoritativa: entre emitir e aceitar
cabem sete dias, e a última vaga pode ter sido ocupada nesse meio-tempo.
Como as duas funções de aceite são `@transaction.atomic` e a verificação
vem **depois** do consumo do convite, a recusa desfaz o consumo — o
convite continua válido, que é o que a tela promete ao convidado.

`seed_demo` e importação criam registro direto pelo modelo e não passam
por nenhuma dessas portas. É deliberado: fixture não é venda.

## Rebaixar congela, não apaga

Clínica com 700 pacientes que vai para um plano de 500 mantém os 700
acessíveis, com o prontuário intacto; o que o sistema recusa é o 701º.

Apagar ou esconder prontuário por questão comercial é o que não se faz em
sistema de saúde — a Lei 13.787/2018 fixa vinte anos de guarda, e ela não
conhece plano de assinatura. Por isso `assert_can_add_*` pergunta sobre o
**próximo** registro, nunca sobre os que já existem. Verificado na seção 7
com a clínica em 18 pacientes e limite 1: lista e ficha respondem 200, e
nenhum registro sumiu do banco.

## O bloqueio não é a primeira notícia

A partir de **80%** da cota, a lista de pacientes traz o quanto resta. A
tela de recusa (`patients/limit_reached.html`) diz, na mesma frase, que
nada foi arquivado, apagado ou escondido — quem lê "limite atingido" num
sistema de saúde precisa saber disso imediatamente — e oferece as duas
saídas reais: arquivar quem não é mais acompanhado, ou ampliar o plano.

A mensagem é montada em `PlanLimitReached.message()`, e não escrita em
cada chamador: seis textos iguais divergem no primeiro ajuste.

## O que foi verificado

`checks/check_planos.py`, nove seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | O catálogo confere com a especificação? | 50/1, 500/2, 3000/5, ilimitado |
| 2 | Override vence o plano? Nulo cai no plano? | Sim; `custom` sem override é ilimitado |
| 3 | Zero é limite ou "não configurado"? | Limite: bloqueia |
| 4 | O aviso começa em 80%? | 50% não avisa; 82% avisa |
| 5 | As duas portas de paciente recusam no limite? | Cadastro 409 sem criar; pré-cadastro levanta |
| 6 | Arquivar libera vaga? | 18 → 17 → 18 |
| 7 | Rebaixar apaga alguma coisa? | Nada: 32 no banco, lista e ficha 200 |
| 8 | Os caminhos do papel médico respeitam? | Conceder, emitir convite e aceitar recusam |
| 9 | Ilimitado bloqueia ou avisa? | Nem um nem outro; cadastro passa |

As clínicas de demonstração passaram a nascer em planos **diferentes** —
A em Completo, B em Básico —, pelo mesmo motivo que já têm dias e durações
de agenda diferentes: dois inquilinos idênticos não revelariam cota
vazando de um para o outro.

## Fora de escopo

Cobrança, checkout, gateway de pagamento e emissão fiscal continuam fora
da versão 1 (seção 2.2 do PRD). Nada aqui cobra de ninguém.

Entregas seguintes da especificação: convites que carregam o plano
contratado e o console de emissão (2), página de vendas e formulário de
contato (3), preparação final do domínio (4).

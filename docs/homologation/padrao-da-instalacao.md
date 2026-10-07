# O padrão da instalação: IA morta por 40 dias, SMS que nunca saiu

**Dois defeitos encontrados em 2026-10-06**, acompanhando o uso da
segunda clínica real (CALDAS, REGO E URBANO). Causas técnicas diferentes,
**mesma assinatura**: tudo que só é exercitado por quem depende do
*padrão da instalação* estava quebrado, e a primeira clínica — que tem
chave própria de IA e de SMS — nunca tocou nesses caminhos.

É o mesmo formato do defeito do logotipo (2026-10-05): a jornada que só
existe quando a instalação tem mais de uma clínica não é exercitada por
quem tem uma.

---

## 1. A IA da instalação estava morta desde 26/08

### O que o log disse

```
openai.APIStatusError: Error code: 410 - {'title': 'Gone', 'status': 410,
 'detail': "The model 'nvidia/llama-3.3-nemotron-super-49b-v1.5' has reached
 its end of life on 2026-08-26T09:00:00Z and is no longer available."}
```

Dois jobs dessa clínica, nos dois tipos que ela tentou
(`lab_extraction` e `patient_report`), com a mesma resposta.

### Por que ninguém notou

`AI_PROVIDER` e `AI_MODEL` moravam **só no `.env`**. Daí três
consequências que se somam:

- **não havia tela** mostrando qual era o padrão da instalação;
- **não havia verificação** conferindo o identificador contra o catálogo
  do provedor;
- **trocar exigia um ciclo de deploy** — editar arquivo, regerar o
  runtime, republicar.

E o erro chegava ao médico como `A tarefa não foi concluída. Tente
novamente.` — a frase genérica do `except Exception` de `run_ai_job`.
Conselho que não podia funcionar, sobre uma causa que ninguém na clínica
podia resolver.

O mais incômodo é que o sistema já sabia. `ai/providers/catalog.py`
abre com isto, escrito meses antes:

> Digitar identificador de modelo é a forma mais comum de a IA falhar em
> produção: o nome está certo hoje, o provedor o aposenta, e o erro só
> aparece quando alguém pede um resumo no meio de um atendimento.

A tela **da clínica** foi construída para evitar exatamente isso, com
lista vinda do provedor e teste de modelo. O padrão **da instalação**
ficou de fora, digitado à mão num arquivo que ninguém reconfere.

### O que mudou

**`InstallationSettings` ganhou `ai_provider`, `ai_model` e
`ai_base_url`**, com a regra que já valia para as outras chaves da tabela
(§7-D): *o `.env` semeia, o banco decide*. A tela é
`/instalacao/operacao/`, seção "Provedor de IA padrão da instalação".

**A chave continua em secret, e não no console.** Ela é credencial, e o
processo `app` — que serve o console — não recebe nenhuma, por desenho
(§2). Quem pode trocar o modelo não precisa poder ler a chave.

Isso tem uma consequência de arquitetura que decide o resto do desenho:
**a tela não pode perguntar nada ao provedor.** Daí a verificação ser uma
tarefa do worker (`ai.tasks.verificar_provedor_da_instalacao`), que faz
as duas perguntas que a tela da clínica já fazia e grava o resultado:

| Pergunta | Responde | Quem resolve se falhar |
| --- | --- | --- |
| `list_models` | o modelo escolhido ainda existe? | quem administra a instalação, escolhendo outro |
| `probe_model` | a chave funciona com esse modelo? | quem opera o servidor, trocando o secret |

A tela mostra a lista devolvida como sugestão, e **acusa em vermelho**
quando o modelo configurado não está nela — que é como um modelo
aposentado se parece.

### A mensagem de erro

`run_job` passou a distinguir pelo código de estado:

- **4xx (menos 408 e 429)** → configuração. *"O provedor de IA recusou a
  chamada por configuração (HTTP 410). Repetir não resolve: quem
  administra a instalação precisa conferir o provedor e o modelo em
  Operação."*
- **o resto** → instabilidade. *"Tente novamente em alguns minutos."*

408 e 429 são a exceção dentro do 4xx porque prazo e limite de taxa
passam sozinhos.

### O estado encontrado em produção

| Provedor | Chave | Resposta |
| --- | --- | --- |
| nvidia | válida | 80 modelos — mas **não** o configurado |
| openrouter | válida | 400 modelos |
| openai | inválida | recusou |
| anthropic | inválida | recusou |

---

## 2. O SMS da segunda clínica nunca saiu

### O que o registro disse

A entrega ficou gravada assim:

| Campo | Valor |
| --- | --- |
| `channel` | `sms` |
| `status` | `no_contact` → **"Sem contato cadastrado"** |
| `sanitized_error` da tentativa | `channel_disabled` |
| tempo entre criar e falhar | **3 ms** |

Três milissegundos é o detalhe que entrega a causa: não houve chamada de
rede. E o e-mail da mesma operação saiu 3 segundos depois, com sucesso.

### A causa

`SendConfirmationView` enviava **de dentro da requisição**. O processo
`app` não recebe o secret `NEURODOC_SMSDEV_API_KEY` — a chave de egresso
é do worker, por desenho (§2). Então:

- a clínica que informou a **própria** chave funciona, porque essa fica
  cifrada no banco e o `app` sabe decifrá-la;
- a clínica que depende da chave **da instalação** recebia
  `SmsChannelDisabled` e nada saía.

Com uma clínica só, e ela com chave própria, o defeito não tinha como
aparecer. O plano Completo da segunda clínica **inclui SMS** — e incluía
de fato: `has_sms('complete')` é verdadeiro, a trava de plano deixou
passar, a credencial da instalação existe no worker. O que faltava era o
envio acontecer onde a credencial está.

Isto é reincidência de uma correção já feita: `deliver_document_task`
existe exatamente por isto, e o docstring dela descreve o mesmo defeito
na entrega de documento. A confirmação de horário era a última entrega
que ainda saía da requisição.

### O que mudou

**`communications.tasks.send_confirmation_task`** — o envio vai para o
worker, como o documento. A view confere antes de enfileirar a única
coisa que a pessoa na tela pode resolver agora (contato cadastrado) e
responde *"a caminho de ...; o resultado aparece na lista de entregas"* —
o mesmo padrão do reenvio de documento.

**E uma varredura**, porque lista escrita à mão envelhece: nenhum
`*/views.py` pode chamar `send_sms`, `send_appointment_confirmation` ou
`deliver_document`. Foi a falta dessa varredura que deixou a confirmação
para trás quando o documento foi corrigido.

### O status que mentia

`no_contact` — "Sem contato cadastrado" — era gravado em **três** casos
diferentes: paciente sem contato, canal sem credencial, e organização
inativa. Os dois últimos mandam a clínica conferir o telefone do
paciente, que está certo.

Entrou `DeliveryStatus.CHANNEL_UNAVAILABLE` ("Canal indisponível"), em
vermelho e não em amarelo: diferente de contato faltando, aqui não há
nada que a clínica possa cadastrar.

**As linhas antigas não foram reclassificadas**, e é escolha. Uma entrega
gravada como `no_contact` em setembro pode ter sido qualquer um dos três
— os três caíam no mesmo valor, e não há no registro o que os separe.
Reclassificar em bloco inventaria uma certeza que não existe.

---

## O que estes dois defeitos têm em comum

**O padrão da instalação é um caminho de código sem dono.** Ele só é
exercitado por quem ainda não configurou nada — isto é, por toda clínica
nova, no pior momento possível para descobrir que algo não funciona. E
quem administra a instalação normalmente usa a própria clínica para
testar, que é justamente a que tem tudo configurado.

Vale como aviso de onde procurar o próximo: **o que a primeira clínica
nunca exercita.**

## Verificação

`checks/check_provedor_e_sms.py`, nove seções:

1. o que o console gravou vence o `.env`, e campo vazio cai no `.env`;
2. a verificação acusa modelo fora da lista — com o estado exato da
   produção —, não acusa o que está na lista, e **não acusa nada antes de
   verificar**;
3. a chave é lida pelo provedor em vigor, não por `settings.AI_PROVIDER`
   (senão trocar de provedor mandaria a chave do anterior);
4. 410 vira "repetir não resolve", 503 vira "tente novamente", 408 e 429
   são passageiros apesar de 4xx, e o diagnóstico não carrega credencial;
5. a tela existe, oferece o catálogo, avisa do modelo aposentado e **não**
   tem campo de chave;
6. o console **enfileira** a verificação e não fala com o provedor de
   dentro da requisição;
7. a varredura das views, mais a confirmação enfileirada;
8. `CHANNEL_UNAVAILABLE` nos dois gatilhos, com o tom vermelho;
9. o `app` continua **sem** secret de egresso — para a correção do SMS
   não ter sido "dar a chave ao processo web".

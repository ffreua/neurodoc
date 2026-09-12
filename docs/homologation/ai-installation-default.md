# Provedor de IA padrão da instalação

O padrão da instalação passa a alcançar os **dez** provedores do catálogo,
e não três. A instalação fica apontada para a **NVIDIA NIM** com um modelo
Nemotron, valendo para toda clínica que não configurou o provedor dela.

Evidências: `checks/check_ia_padrao.py`, contra a pilha Docker local.

## O defeito

Havia dois caminhos para montar o cliente de IA, e eles divergiram.

| Caminho | Quem usa | Provedores alcançados |
| --- | --- | --- |
| `AIProviderSettings` (por clínica) | A clínica que cadastrou provedor, chave e modelo na tela | **10**, pelo catálogo |
| `_GETTERS` (instalação) | Quem hospeda o sistema para si, e toda clínica sem configuração própria | **3** — `openrouter`, `openai`, `anthropic` |

O caminho por clínica passou a ser dirigido pelo catálogo quando os dez
provedores foram cadastrados (PRD 25.4). O da instalação ficou para trás,
num mapa de três, cada um num módulo próprio repetindo a mesma montagem
com outro nome de constante.

O efeito era um defeito silencioso de configuração: `AI_PROVIDER=nvidia`
no `.env` levantava `Unknown AI provider: nvidia`, ainda que a NVIDIA
estivesse no catálogo, tivesse `base_url` correto e funcionasse
perfeitamente quando uma clínica a escolhia pela tela. A tela oferecia o
que o servidor recusava — e quem opera o servidor não tinha como saber
disso sem ler o código, porque a mensagem dizia "desconhecido" sobre um
provedor que o produto lista.

## A correção

Uma montagem só (`ai/providers/_build`), dirigida pelo catálogo, usada
pelos dois caminhos. Os três módulos que a duplicavam
(`openrouter.py`, `openai_provider.py`, `anthropic_provider.py`) saíram:
manter código morto que repete a resolução é exatamente o que produziu a
divergência.

**A chave da instalação passou a ser uma, derivada do nome do provedor.**
Eram três constantes (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`), e era esse trio que amarrava o padrão a três
provedores: acrescentar um exigia editar `settings.py`, o mapa de getters
e o `docker-stack.yml`, e esquecer qualquer um dos três devolvia "Unknown
AI provider". Agora:

```python
AI_API_KEY = secret(f'{AI_PROVIDER.upper()}_API_KEY', required=False)
```

Habilitar um provedor novo como padrão é gravar o secret com o nome dele e
apontar `AI_PROVIDER`. A mensagem de chave ausente **nomeia o secret** que
falta (`Grave o secret NEURODOC_NVIDIA_API_KEY`), porque "chave não
configurada" sozinho manda quem opera o servidor procurar em três lugares.

## O que **não** mudou, e é o que importa

A precedência. A clínica que informou provedor, chave e modelo continua
tendo prioridade absoluta sobre o padrão da instalação — cair no provedor
da instalação seria mandar prontuário para um contrato que aquela clínica
não escolheu. `check_ia_padrao.py`, seção 6, monta uma clínica com Groq e
confere que, com a instalação em NVIDIA, o cliente sai com o modelo e o
endereço **da clínica**.

`AI_ENABLED=False` continua desligando tudo, mesmo com chave configurada,
e a verificação subiu para `get_chat_model`: antes ela estava dentro de
cada getter, e o caminho por clínica a checava por conta própria — duas
cópias da mesma regra, que é como uma delas some.

Trocar de provedor segue sendo ato explícito, nunca substituição
silenciosa quando um falha (RT-04).

## Configuração desta instalação

`.env`:

```
AI_PROVIDER=nvidia
AI_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5
AI_ENABLED=True
```

Secret: `NEURODOC_NVIDIA_API_KEY`, acrescentado a `docker-stack.yml` e
entregue ao **worker** — é lá que a IA roda (`ai/tasks.py`), e o processo
web não recebe chave de provedor nenhuma. `ops/secret_setup.py` passa a
pedi-la sozinho, porque lê a lista de secrets do próprio stack.

O modelo Nemotron é gratuito no `build.nvidia.com`, e é isso que torna
razoável deixá-lo como padrão de todas as clínicas: nenhuma delas precisa
de contrato para a IA funcionar, e a que quiser o próprio contrato
continua podendo cadastrá-lo.

## Pendência que continua aberta

**P-06** (base legal, contratos de operador, transferência internacional,
RIPD) não é afetada por esta mudança e continua bloqueando IA sobre dado
real. Trocar o provedor padrão troca para onde o texto desidentificado é
enviado — a política de privacidade *fail-closed* de `ai/privacy_policy.py`
continua valendo por igual, e é ela que recusa o envio quando o conteúdo
não satisfaz a política.

## O que foi verificado

`checks/check_ia_padrao.py`:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Os dez provedores do catálogo servem de padrão? | Dez, cada um com o `base_url` do catálogo; Anthropic pelo ramo próprio |
| 2 | A instalação está em NVIDIA? | `AI_PROVIDER=nvidia`, rótulo "NVIDIA NIM" |
| 3 | Sem chave, o erro diz qual secret gravar? | Nomeia `NEURODOC_NVIDIA_API_KEY` |
| 4 | Provedor fora do catálogo? | Recusado, listando os conhecidos |
| 5 | `AI_ENABLED=False` com chave? | Desliga |
| 6 | Clínica com provedor próprio cai no padrão? | Não — sai com modelo e endereço dela |

Nenhuma seção chama provedor de verdade: o que se verifica é a montagem do
cliente (provedor, modelo, endereço, chave), que é onde o defeito estava.

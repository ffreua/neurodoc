# A IA da instalação vigiada, e o provedor reserva (1.23)

## O problema

Em 2026-08-26 a NVIDIA aposentou o modelo padrão da instalação e passou a
responder `410 Gone`. A IA de quem dependia do padrão ficou **quarenta
dias** parada. A 1.7 trouxe o console e o botão "Verificar" — mas o botão
só rodava quando alguém clicava, e ninguém clica num botão sobre um
defeito que não sabe que existe. Em 2026-10-22 a última verificação do
principal tinha quinze dias.

Duas peças, e as duas eram necessárias: **saber** da falha, e **continuar
atendendo** enquanto ninguém age.

## A vigilância

`ai.tasks.vigiar_ia_da_instalacao`, no beat, de hora em hora (minuto 47).
Roda a mesma verificação do botão (`list_models` + `probe_model`), e a da
reserva se houver uma configurada. Na passagem de "ok" para "falhou",
manda e-mail a todo superadministrador ativo; repete uma vez por dia
enquanto durar (`ai_alerta_enviado_em`) e zera quando volta. O e-mail diz
o provedor, o modelo, o resultado e **se a reserva está cobrindo** — isso
muda a urgência. Não carrega dado clínico.

## A reserva

### Onde mora

`base.models.InstallationSettings`, campos `ai_reserva_*`. A **chave** fica
cifrada no banco (`base.crypto`, a mesma proteção da chave de IA de cada
clínica) — o pedido foi configurar sem editar arquivo no servidor. A tela
grava e mostra só os últimos caracteres; quem decifra é o worker, na hora
da chamada. A chave entra no `rotate_secrets_master_key`.

### Quando entra

Em `ai/services.py::run_job` e `ai/tasks.py::run_chat_turn`, que são os dois
únicos lugares que chamam o modelo:

| Situação | Troca? |
| --- | --- |
| Principal: exceção na chamada (fora do ar, 429, 410, 401, rede) | **sim** |
| Principal: tempo esgotado (marcado pelo grafo em `diagnostics.tempo_esgotado`) | **sim** |
| Principal sem chave ou sem modelo (`ProviderUnavailable`) | **sim** |
| Resposta chegou e foi recusada pela validação (JSON, esquema, tamanho) | **não** — trocar de provedor não conserta a forma de uma resposta |
| Clínica com IA própria utilizável | **nunca** — ela escolheu para onde o prontuário vai |
| Chat, depois da primeira palavra | **não** — emendaria dois textos |
| `AI_ENABLED=False` | **não** |

O job tem um orçamento de 270 s para as duas chamadas somadas (abaixo do
limite de 300 s do Celery); a reserva só é tentada com tempo útil.

### Visível, não silenciosa

- contador e data do último uso no console;
- `ai.reserva_usada` na trilha, com o motivo (classe e HTTP) — sem chave e
  sem conteúdo;
- o `AIArtifact` grava o provedor e o modelo **da reserva**.

### Ligar e desligar

Gravar provedor/modelo/chave **desliga** a reserva até a nova verificação
ficar verde. **Ligar exige a verificação em verde**; desligar é um clique.
Cada mudança entra na trilha (`ops.installation_ai_reserve_*`), nunca com
a chave.

## LGPD

Desligada, a reserva não trata dado e não é suboperador. Ligá-la a torna
suboperador de dados de saúde: a linha entra em
`docs/governance/suboperadores.md` e as clínicas são comunicadas (cláusula
8 do contrato de adesão).

## Verificação

`checks/check_ia_reserva.py` — doze grupos, com os provedores simulados
(nenhuma chamada sai para a internet). Bateria completa em 2026-10-22.

## Prazo do resumo e a segunda chamada (2026-11-05)

Um resumo de atendimento curto falhou em produção com "O provedor de IA
não respondeu em 30s", numa clínica com **IA própria** pela OpenRouter —
onde a reserva da instalação não entra, por desenho. Medido com texto
fictício, no worker de produção, o mesmo pedido levou **5,5 s, 2,8 s e
94 s** em três chamadas seguidas: o roteador manda cada pedido a um
servidor, e de vez em quando é um lento. A demora é sorteio, não peso do
pedido.

Duas mudanças em `ai/services.py`, valendo para toda clínica:

- o prazo do resumo e do apoio diagnóstico passou de **30 s para 75 s**
  (`DEFAULT_LIMITS`): o job roda no worker, ninguém fica olhando a tela,
  e o prazo curto só transformava a cauda do provedor em falha;
- o principal que esgota o prazo ganha **uma segunda chamada** ao mesmo
  provedor antes da reserva ou da falha (`_REPETIR_NO_PRAZO`), só em
  prazos de até 90 s — o relatório, com 240 s, ficaria acima do orçamento
  do job. A primeira chamada é abandonada, não cancelada: o custo é um
  pedido a mais ao provedor.

O que **não** mudou: o roteamento da OpenRouter da clínica com chave
própria continua sendo escolha dela. `check_ia_reserva` §4b cobre a
segunda chamada resolvendo sem a reserva.

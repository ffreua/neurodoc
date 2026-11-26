# MD-2026-11-26-01 — IA da instalação passa a ser só OpenRouter

**Data:** 2026-11-26. **Tipo:** operação (produção). **Feito nos dois na mesma rodada** (PD-M-2026-11-26-01).

## Por quê

A verificação horária da IA falhava com frequência. Medido de dentro do worker de produção:
o `nvidia/nemotron-3.5-super-vl-120b-a12b` pela API da NVIDIA levou 20 a 24 s em 5 de 8
chamadas e devolveu 503 ("content safety screening is temporarily unavailable") em outra; a
verificação espera 20 s. O mesmo modelo pela OpenRouter respondeu 8/8 em cerca de 1 s.

## Escolha dos modelos

Sete candidatos testados pela OpenRouter com o roteamento da instalação (`zdr`,
`data_collection: deny`, exclusão de provedores na China): 8 chamadas curtas e um caso
clínico **fictício**. Descartados: `openai/gpt-oss-120b` (português e critérios errados),
`deepseek/deepseek-v4-pro` (43 s e uma resposta vazia), `nvidia/nemotron-3.5-lightning`
pela OpenRouter (erros de português e um erro clínico: "hipercalemia" na sarcoidose).

| Papel | Modelo |
| --- | --- |
| Principal (chat, resumo) | `deepseek/deepseek-v4.1-flash` |
| Tarefas pesadas (apoio diagnóstico, relatório) | `z-ai/glm-5.3` |
| Reserva | `z-ai/glm-5.3-flash` (já era; família diferente do principal) |

## O que foi feito em produção

1. Secret `NEURODOC_OPENROUTER_API_KEY` (vazio, 8 bytes) recriado com a chave que a reserva
   já usava, copiada do banco para `/dev/shm` dentro da VPS e apagada com `shred`; worker
   parado e republicado com `deploy.sh --skip-build` (procedimento de `docs/operations/asaas.md`).
   O secret da NVIDIA não foi tocado. Armadilha: `docker exec -i` dentro de um script lido
   pela entrada padrão consome o resto do script.
2. Console: o mesmo que `InstallationAIView.post` grava, com o evento
   `ops.installation_ai_changed` na trilha (motivo registrado).
3. Conferido: verificação do principal, do pesado e da reserva aprovada; uma chamada real a
   cada um pelo cliente do sistema (`_installation_model`, `installation_reserve_model`),
   que manda o roteamento, respondeu.

## Documentos

`docs/governance/suboperadores.md`: OpenRouter principal e reserva; NVIDIA sem uso desde
2026-11-26, com a chave guardada. Nenhuma empresa nova entra na lista.

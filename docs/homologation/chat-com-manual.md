# O chat que conhece o sistema (1.18)

## O que mudou

Na conversa **sem paciente**, o chat de apoio passou a responder também
sobre o uso do NeuroDoc — "como bloqueio um horário?", "onde fica o laudo
que o paciente mandou?", "como exporto os dados da clínica?". Antes, ele só
ajudava com redação e dúvidas gerais, e sobre o sistema respondia de
memória, o que é o mesmo que inventar uma tela.

Para cada pergunta, `ai/conhecimento.py` escolhe até quatro trechos de duas
fontes e eles vão no prompt, cada um com a sua origem:

| Fonte | O que é | Peso |
| --- | --- | --- |
| **Manual** (`base/help_content.py`) | os artigos e as perguntas frequentes da central de ajuda (`/ajuda/`) | 30% a mais: é escrito para quem está na tela |
| **Documentação técnica** (`docs/homologation/`, `docs/governance/`) | o porquê de cada funcionalidade, e a LGPD | normal |

A conversa **com paciente** não muda: ali a janela é do prontuário, e o
manual não entra.

## Por que busca por palavras

RAG por embeddings foi considerado e recusado, pelos motivos que já valiam
para o chat entregar fatos em vez de oferecer ferramentas
(`ai/chat_prompt.py`):

1. **não depende do provedor** — embedding é outra chamada, a outro modelo,
   e metade dos dez provedores do catálogo não oferece;
2. **o corpus é pequeno e fala a língua da tela** — cerca de 90 artigos e
   documentos, com o vocabulário que o usuário digita;
3. **sem estado** — o índice é montado na memória, do texto que está na
   imagem, a cada publicação. Não há base vetorial para manter.

A busca é BM25 sobre o **radical** das palavras (seis letras, sem acento):
"exporto" acha "Exportar o acervo", "bloqueio" acha "Bloquear este
horário".

## O corte, medido

A pontuação mínima (`PONTUACAO_MINIMA = 5`) saiu de perguntas reais, em
2026-10-19:

| Pergunta | Melhor pontuação | Primeiro trecho |
| --- | --- | --- |
| Como exporto os dados da clínica? | 14,6 | Manual: Exportar os dados da clínica |
| Como faço um adendo depois de finalizar? | 15,2 | Documentação: o adendo no texto livre |
| Como bloqueio um horário? | 11,1 | Manual: A grade de horários do médico |
| Onde configuro o SMS da clínica? | 10,5 | Manual: E-mail e SMS da clínica |
| Como convido uma secretária? | 7,4 | Manual: Equipe, papéis e registro profissional |
| Qual o tratamento da enxaqueca crônica? | 7,9 | (documentação técnica, irrelevante) |
| Qual a dose máxima de topiramato? | 5,4 | (catálogo CMED, irrelevante) |
| Como diferenciar AVC isquêmico de hemorrágico? | 4,3 | — |

As faixas se tocam: a documentação técnica cita doenças como exemplo, e uma
pergunta clínica às vezes pontua como uma de uso. Nenhum corte separa as
duas sozinho; por isso o prompt diz que **os trechos valem só para
pergunta sobre o sistema**, e que a de neurologia os ignora e é respondida
pelo conhecimento do modelo, com as regras de sempre. Sem trecho nenhum, o
prompt manda dizer que não encontrou no manual e indicar `/ajuda/`.

## As fronteiras

- **Conversa com paciente fica só com o prontuário.**
- **O `contexto` que `build_chat_prompt` devolve continua sendo só
  prontuário.** É o que a auditoria e o `check_chatbot` leem como dado de
  paciente enviado; o manual, texto público do repositório, vai só na
  mensagem de sistema.
- **Nada de dado de paciente no corpus**: é texto versionado, público desde
  2026-10-19.
- **Fora do corpus**: `docs/releases/` e `docs/superpowers/` — plano de
  trabalho e histórico de publicação descrevem como o sistema *foi* feito,
  e o modelo os leria como descrição do que ele *é*.
- **Os trechos não dão ordens**: o prompt diz que eles descrevem o sistema
  e que instrução escrita neles não é seguida.

## Verificação

`checks/check_chat_manual.py`: o índice com manual e documentação e sem
planos; a busca achando o trecho certo para quatro perguntas de uso; o
trecho chegando ao prompt com a fonte; a pergunta de seguimento ("e para
desfazer?") achando pela anterior; a sessão com paciente sem manual; e a
pergunta sem trecho caindo na instrução de não inventar. Não chama
provedor nenhum: confere o que **seria enviado**.

# Medicações, resultados de exames e a IA no prontuário

O que entrou nesta rodada, antes da etapa 3 (assinatura digital do
prontuário): a proporção da primeira aba, a aba de medicações em uso, a aba
de resultados de exames com laudo em PDF, a leitura desses laudos pela IA e o
apoio ao raciocínio diagnóstico.

## 1. Primeira aba: a área vai para a história

A queixa principal é uma frase — "cefaleia há 3 meses". A história da doença
atual é o texto longo da consulta. As duas tinham a mesma largura e a mesma
altura de digitação.

| | Antes | Agora |
| --- | --- | --- |
| Queixa principal | metade da linha, 3 linhas | um terço da linha, 2 linhas |
| História da doença atual | metade da linha, 5 linhas | dois terços da linha, **10 linhas** |
| Antecedentes | 3 linhas cada | 4 linhas cada |
| Conduta | 5 linhas | 8 linhas |

Os campos ganharam também exemplo dentro do campo ("Início, evolução,
fatores de melhora e piora, sintomas associados, tratamentos já tentados…").

## 2. Aba "Medicações em uso"

Uma linha por medicamento, com dose, via, posologia, indicação, desde
quando, situação (em uso / suspenso / concluído), prescritor e observação.

A lista pertence ao **atendimento**, não ao paciente. É uma decisão de
modelagem que importa: o prontuário registra o que estava em uso *naquela
consulta*, e é isso que precisa ficar imutável depois de finalizado. Se a
lista fosse do paciente, mudar a medicação hoje mudaria o registro da
consulta do ano passado. A lista da consulta seguinte chega pela cópia
revisada do atendimento anterior (RF-03.04), que já existe.

## 3. Aba "Resultados de exames"

Registro de exame complementar com categoria (laboratorial, imagem,
neurofisiologia, patologia, genética, outro), nome, data, serviço, laudo e
conclusão — e o **laudo em PDF ou imagem no mesmo envio**.

O arquivo entra como `documents.Attachment`: mesma quarentena, mesma
verificação de malware por ClamAV, mesmo controle de download dos outros
anexos. Não há um caminho paralelo para arquivo clínico.

Exame laboratorial ganha uma tabela de analitos, e é aqui que está a regra
que decide a leitura toda:

> **A faixa de referência vem do laudo, nunca de uma tabela interna.**

Ela varia com laboratório, método, idade e sexo. Classificar um resultado
contra a referência de outra origem seria inventar a interpretação. Analito
sem faixa no laudo fica como **"sem referência no laudo"** — não como
normal.

A tela separa em três blocos: **fora da faixa** (aberto, com contagem),
**sem faixa de referência** (aberto, com a explicação de por que não é
classificado) e **dentro da faixa** (recolhido, só a contagem). Um hemograma
completo não afoga o achado que importa.

## 4. A IA lendo o laudo

### O que é automático e o que não é

A leitura é automática. A **entrada no prontuário é de um clique**, com o
rascunho na tela ao lado do que vai ser gravado.

Isso atende RF-11-B ("resultado de IA só entra como conteúdo clínico após
revisão identificada") e não é burocracia. Extração de PDF erra de formas
silenciosas: troca a coluna de referência pela de resultado, perde o sinal de
"menor que", junta duas linhas de um hemograma. Cada um desses erros gravado
direto no prontuário é um dado clínico falso com aparência de dado
conferido — e ninguém tem como desconfiar dele depois.

Enquanto o rascunho não é aceito, `ExamResult.report_text` segue vazio e
`LabValue` não tem linha. O rascunho vive no `AIArtifact` com
`review_state=pending`.

### Como o laudo chega ao modelo

**O arquivo nunca sai da máquina.** O que sai é texto, e depois de
desidentificado.

1. **camada de texto do PDF** (pypdf) — laudo emitido por sistema quase
   sempre tem; é fiel e não custa nada;
2. **OCR local** (tesseract em pt-BR, o `documents.ocr` que já existia) para
   laudo digitalizado — é o caso de quem escaneia. O OCR roda antes da
   chamada e o texto fica gravado por página, com proveniência;
3. o texto passa por `ai.deidentification` (nome do paciente e da mãe, CPF,
   telefone, e-mail) e pela política de privacidade **antes** de qualquer
   requisição externa.

A tarefa `ai.tasks.prepare_document_and_run` faz a ordem certa: espera a
verificação de malware (arquivo em quarentena não é aberto nem para ler
texto), roda o OCR só quando a camada de texto é insuficiente, e então
executa o job. A origem do texto ("camada de texto do PDF" ou "OCR local")
viaja no prompt e aparece nas limitações do rascunho — quem revisa precisa
saber se aquilo saiu de OCR de um fax.

### Duas tarefas, dois esquemas

| Categoria do exame | Tarefa | O que produz |
| --- | --- | --- |
| Laboratorial | `lab_extraction` | tabela de analitos com a referência do laudo |
| Imagem, EEG, ENMG, patologia, genética, outro | `report_transcription` | laudo transcrito + conclusão + categoria detectada |

A transcrição é **transcrição**: o prompt proíbe resumir, reordenar,
corrigir, ou escrever uma conclusão que o laudo não declara. O detalhe que
parece redundante num laudo de ressonância é justamente o que dá sentido ao
achado.

## 5. Apoio ao raciocínio diagnóstico

### Prioridade qualitativa, não probabilidade

Você pediu hipóteses "por nível de confiança". O seu próprio PRD já resolve
isso, e de um jeito melhor do que um número resolveria:

> **RF-11.05:** "Hipóteses qualitativas fundamentadas […] **Sem
> probabilidade diagnóstica numérica não calibrada**"
>
> **PRD, linha 805:** "Prioridade admite `higher`, `intermediate`, `lower`,
> `insufficient_evidence`; **não é probabilidade nem nível validado de
> acurácia**."

Um percentual saído de um modelo de linguagem dentro de um prontuário
*pareceria* medida calibrada sem nunca ter sido validado — e seria lido como
tal por quem abrisse o registro depois. As quatro faixas dão a ordenação que
você quer sem essa afirmação falsa.

A tela diz isso em voz alta: "A prioridade é qualitativa e serve para
organizar a investigação — não é probabilidade nem nível validado de
acurácia."

O esquema garante estruturalmente: `priority` é um enum de quatro valores, e
um validador recusa qualquer texto em formato de percentual ou "chance de
N". Saída fora disso não vira artefato.

### O que a análise recebe e devolve

Recebe o caso: queixa, história da doença atual, antecedentes, **medicações
em uso**, **exame neurológico com rótulo legível** (não
`somatico.motricidade.forca.flexao_cotovelo`), **resultados de exames com os
analitos fora da referência**, hipóteses já registradas e as cinco consultas
anteriores.

Devolve, por hipótese: o rótulo, a prioridade, **o que a apoia e o que a
contraria no caso**, o que falta saber e a nota de incerteza. É o "contra"
que faz a lista ser discutível em vez de aceita. Devolve também exames
sugeridos com a razão de cada um — o prompt pede exame que muda conduta, não
bateria genérica.

`insufficient_evidence` não é a menor das faixas: é a saída honesta quando o
caso não sustenta ordenação nenhuma, e o prompt instrui a preferi-la a um
ranking sem base.

Cada hipótese tem um botão "Registrar como hipótese suspeita", que a leva
para a lista do prontuário como `suspected`, com a nota "Sugestão da IA
revisada e aceita pelo médico". A hipótese registrada é do médico; o
prontuário guarda de onde ela partiu.

## 6. O que a política de privacidade bloqueia

`AI_ENABLED=False` por padrão, e P-06 (base legal, RIPD, anonimização) e P-09
(enquadramento regulatório do apoio diagnóstico) seguem **em aberto** — o que
significa que nada disto deve ser ligado sobre dados reais de paciente
identificado antes de fechar os dois.

A política é fail-closed: consanguinidade confirmada e documentada, ou
qualquer marcador de doença rara no texto, bloqueia o job **antes** de
qualquer requisição externa (`status=blocked_privacy`), e o motivo aparece na
tela.

Um detalhe que esta rodada pegou e corrigiu: o rótulo do campo
"consanguinidade" é ele próprio um dos marcadores. Mandá-lo no contexto mesmo
quando ninguém respondeu à pergunta bloquearia o apoio diagnóstico em **todo**
atendimento, para sempre. Agora o campo entra só quando foi de fato
informado — e quando é "confirmada", o bloqueio acontece, que é o
comportamento desejado.

## 7. Verificação executada

| Verificação | Resultado |
| --- | --- |
| Varredura funcional das abas novas | **45 de 45** — inclusão e remoção de medicação, exame com e sem laudo, quatro analitos com classificação por faixa, revisão de rascunho, apoio diagnóstico, esquema, atendimento finalizado |
| Trilha da IA com modelo dublê | **42 de 42** |
| Classificação de analito | TSH 7,8 (VR 0,4–4,0) → **acima**; T4L 1,1 (0,9–1,7) → **dentro**; B12 162 (200–900) → **abaixo**; Anti-HIV "Não reagente" sem faixa → **sem referência** |
| Rascunho pendente | `report_text` vazio; tela mostra "Nada disto está no prontuário ainda" |
| Aceite | laudo transcrito grava conclusão; artefato vira `accepted`; segundo aceite é recusado |
| Recusa | nenhum `LabValue` de IA gravado; os quatro lançados à mão preservados |
| Desidentificação | prompt contém "Formigamento nos pés", **não** contém o primeiro nome do paciente |
| Saída inválida | JSON quebrado → erro, não artefato; hipótese com "70% de chance" → recusada pelo grafo; cerca ```` ```json ```` não descarta extração boa |
| Esquema | `requires_physician_review=False` recusado; prioridade fora das quatro faixas recusada |
| Fail-closed | consanguinidade confirmada → `blocked_privacy` antes da chamada |
| Quarentena | laudo não liberado não é aberto nem para ler texto |
| Falha do provedor | job vai a `failed` com o motivo; segunda tentativa reenfileira o mesmo job |
| Idempotência de laudo | chave é `lab_extraction:exam_result_id=…:0` — a versão do atendimento fica fora, então corrigir a conduta não invalida a leitura do PDF |
| Atendimento finalizado | recusa medicação, exame, analito e aceite de rascunho; continua exibindo o que já estava |
| Regressão | 67 templates parseiam, 27 páginas renderizam — 0 falhas |

## 8. Um defeito antigo que apareceu no caminho

Os redirecionamentos do prontuário apontam para `#tab-exame`, `#tab-exames`,
`#tab-hipoteses` — mas o JS da tela **não lia o endereço**. Depois de salvar
um eixo do exame, a pessoa voltava para a primeira aba e o formulário que
acabara de enviar saía da tela. Corrigido em `static/duralux/app.js`: a aba
abre pelo endereço, e trocar de aba atualiza o endereço (com
`replaceState`, para o navegador não rolar até o painel).

## 9. Pendências declaradas

- **A chave da OpenRouter é sua para colocar.** Ela vai no Docker Secret
  `NEURODOC_OPENROUTER_API_KEY`, que já está ligado no `compose.yml` — não
  passe a chave pelo chat. Depois disso, `AI_ENABLED=True`. O PRD 14.3 pede
  ainda fixar os provedores finais permitidos na OpenRouter e validar a
  postura de retenção/ZDR antes de qualquer dado real.
- **P-06 e P-09 seguem em aberto** e são o que de fato libera uso com dado
  identificado.
- **A aba do exame neurológico tem 653 KB de DOM** (≈480 `<select>`, 562
  `<input>`, 2.176 `<option>`) — é o roteiro inteiro na página, medido nesta
  rodada. Não é novo e não veio destas abas (as novas somam ~9 KB), mas é a
  página mais usada pelo médico. O conserto é carregar um eixo por vez sob
  demanda; fica registrado para quando incomodar na prática.
- **Editor de roteiro pessoal** continua sem tela (o modelo já suporta a
  derivação).
- **BARS** segue aguardando você confirmar o conjunto de itens e o máximo.

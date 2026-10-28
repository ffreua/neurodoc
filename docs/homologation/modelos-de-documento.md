# Modelos de documento e emissão pela Conduta

Versão 1.28. Roteiro: `checks/check_modelos.py`. Pedido do Dr. Fernando em
2026-10-27.

## O que entrou

- **Menu → Modelos** (`/app/modelos/`), para quem tem o papel médico. Quatro
  tipos: **pedido de exames**, **relatório**, **solicitação de cirurgia** e
  **receita**. O pedido de exames tem uma aba por categoria — Laboratório
  (sangue e urina), Imagem, Neurofisiologia, Líquor, Cardiologia, Sono,
  Outros — e uma de **conjuntos**.
- **Modelos do sistema** (`modelos/padrao.py`), iguais em todas as clínicas:
  as listas enviadas pelo Dr. Fernando, reagrupadas (ver abaixo).
- **Modelos do médico** (`ModeloDocumento`): criar, editar, copiar um do
  sistema, duplicar e excluir.
- **Na Conduta dos dois tipos de atendimento** — a aba Conduta do
  estruturado e o cartão "Impressões e conduta" do texto livre —, o bloco
  **Documentos por modelo**: escolher, abrir, editar e emitir.
- Dois tipos novos de documento: **pedido de exames** (`exam_request`,
  número `PEX-`) e **solicitação de cirurgia** (`surgery_request`, `CIR-`).
  Relatório e receita por modelo usam os tipos que já existiam.

## O caminho da emissão

1. Na Conduta, o médico escolhe o modelo e clica em **Usar modelo**. Antes de
   sair da página, `clinical/atendimento.js` grava o texto ainda não salvo,
   de qualquer aba (atributo `data-nd-preservar-atendimento`).
2. A tela de emissão abre **uma seção por documento**, já preenchida. O
   conjunto "Queixa cognitiva" abre o pedido de **imagem** e o de
   **laboratório** separados, cada um com a caixa "Emitir este documento".
3. **Emitir em papel** (número, PDF sem tarja) ou **Preparar para
   assinatura digital** (pronto para assinar pela tela de cada documento).
4. Numa transação só:
   - cada seção vira um `MedicalDocument` por `documents.issuance.create_draft`,
     e daí `issue_on_paper` ou `mark_reviewed`;
   - o PDF fica nos **Anexos** do paciente;
   - no papel, o PDF do rascunho substituído sai da lista de Anexos (fica no
     banco, apagado logicamente): sem isso os Anexos mostrariam dois PDFs
     por pedido, um com a tarja de rascunho;
   - o texto de cada documento entra **na conduta** (`plan_text`), depois do
     que já estava;
   - a trilha registra `modelos.documentos_emitidos`, com ids e sem texto.

## Decisões

| Decisão | Alternativa recusada e por quê |
| --- | --- |
| **O modelo do médico é dele, não da clínica** (liga ao usuário, sem `tenant`) | Por vínculo (`Membership`), como o roteiro de exame. O médico em duas clínicas refaria cada modelo, e o cirurgião, cada lista de materiais. Modelo não carrega dado de paciente. Precedente: o bloco do SNCR |
| **Modelos do sistema em código** | Tabela semeada ou cópia por clínica. Mudar um pedido que sai com o nome de todas as clínicas é um commit com autor e data (como `plans.py` e `contract.py`), e não precisa provisionar clínica nova |
| **Categoria por grupo de itens, não por modelo** | Um modelo por categoria. "Queixa cognitiva" é um pedido só na cabeça do médico e dois no balcão; o modelo guarda os grupos, e a emissão separa |
| **Listas como uma linha por item**, com o código TUSS no começo | Tabela com linhas dinâmicas. Copiar, colar e apagar linha é o editor mais rápido, e não depende de JavaScript para incluir item. A busca TUSS insere a linha pronta |
| **Código TUSS como texto, nunca chave estrangeira** | A sincronização semanal apaga e recria a tabela TUSS; uma FK guardaria um id que deixa de existir |
| **O texto vai para `plan_text`** | Tabela nova "documentos da conduta". O campo de conduta já entra no `content_hash`, na exportação, no resumo e na consulta seguinte; uma segunda morada da conduta teria de ser ensinada a cada um |
| **Finalizado: adendo** | Bloquear a emissão, ou reescrever a conduta. Emitir depois de finalizar é legítimo; o adendo é o único registro que o finalizado aceita, e corpo e hash não mudam |
| **Tudo ou nada** | Emitir o que der. Metade dos pedidos emitida e a conduta sem o texto deles seria pior que nada |
| **A estrutura das seções vem do modelo, no servidor** | Ler do POST quantas seções e de que categoria. Um envio forjado emitiria categoria que o modelo não tem, ou pularia a indicação da imagem |
| **Os tipos novos ficam fora do formulário genérico** de documento e da retificação | O formulário só carrega texto; escolhê-los ali geraria documento vazio. Para corrigir, emite-se outro pelo modelo |
| **Imagem exige indicação clínica** | Exigir em toda categoria. Foi o pedido ("pedidos de imagem geralmente requerem"), e é regra de serviço de imagem e de convênio; nas demais, o campo existe e é opcional |
| **CID só se o médico escolher**, entre as hipóteses não refutadas | Preencher sozinho. Documento que sai com diagnóstico é decisão do médico; a declaração de comparecimento existe justamente sem CID |

## As listas do sistema

Reagrupadas, nunca reescritas (só postas em caixa alta):

- **Imagem não fica junto com sangue.** Os grupos de origem que misturavam
  categorias viraram **conjuntos**: Exames cardiológicos (cardiologia +
  laboratório), Queixa cognitiva (imagem + laboratório), Neuropatia
  (laboratório + neurofisiologia + outros), Rastreio paraneoplásico — homem
  e — mulher (imagem + laboratório + outros).
- **"Exames gerais" e "Reumatograma completo"**, citados dentro de Neuropatia
  e Miopatia, foram **expandidos**, sem repetir o exame que já constava.
- "COMPLEMENTO C4" aparecia duas vezes no Reumatograma e ficou uma.
- Nenhum código TUSS foi acrescentado: as listas não traziam, e código de
  memória num pedido de convênio é pior que nenhum.
- Mantido como veio, para o médico revisar: "TOTG 2G" (provavelmente 2 h).

## Defeito encontrado na homologação

A **data do documento** e a **hora da assinatura** no PDF eram formatadas no
fuso do processo (UTC). Entre 21h e meia-noite todo documento — não só os
novos — saía com a data do dia seguinte, e a hora da assinatura, três horas
adiantada. Corrigido em `documents/pdf/common.py` com `localtime`;
`check_modelos` confere a data do PDF contra o dia de Brasília.

## Homologação

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Os modelos do sistema estão na forma, sem exame repetido e sem imagem no laboratório? | 14 modelos, sim |
| 2 | A lista abre para o médico, não para a secretária, com o link só no menu de quem abre? | Sim |
| 3 | Criar (TUSS lido da linha), editar, copiar, excluir só por POST com confirmação? | Sim |
| 4 | O modelo de um médico abre para outro? E para o mesmo médico na outra clínica? | Não (404); sim |
| 5 | O conjunto abre um pedido por categoria, com o CID só das hipóteses não refutadas? | Sim |
| 6 | Imagem sem indicação é recusada sem gravar nada? | Sim |
| 7 | Em papel: um documento por categoria, número `PEX-`, PDF com paciente, exames, CID e data de Brasília, sem tarja? | Sim |
| 8 | Os Anexos mostram um PDF por documento, e a conduta recebe os pedidos depois do texto anterior? | Sim |
| 9 | Assinatura digital deixa o documento pronto para assinar? | Sim |
| 10 | Texto livre e finalizado (adendo, com corpo e hash intactos)? | Sim |
| 11 | Cirurgia com TUSS, quantidade, material, UTI e número `CIR-`; receita pelo modelo? | Sim |
| 12 | Conduta acima do limite, POST forjado, secretária, outra clínica, modelo alheio? | Recusados |
| 13 | O formulário genérico oferece ou aceita os tipos novos? | Não |
| 14 | No navegador: o texto digitado e não salvo é gravado antes de abrir a emissão, e a volta não oferece restaurar rascunho antigo? | Sim (conferido com agent-browser) |

# Homologação — Anexos privados e processamento local (S06)

Evidência coletada via scripts de verificação (`python manage.py shell`) contra
a pilha real (containers `app` e `celery_worker` separadamente, para respeitar
o isolamento de volumes descrito abaixo) e via `django.test.Client` contra as
views reais. Dados sintéticos apenas; nenhum arquivo clínico real foi usado.

## H-10 — Arquivos e processamento

- [x] Arquivo sintético válido (PDF) percorre quarentena até disponível
  (`receive_upload` → `scan_attachment` → `publish_from_quarantine`); tamanho
  acima de 25 MiB, extensão fora da lista permitida (`.exe`), conteúdo cujo
  MIME real (sniffado via `python-magic`) não bate com a extensão declarada, e
  PDF com cabeçalho inválido são todos recusados com mensagem útil **antes**
  de tocar disco ou o antivírus.
- [x] Nome de arquivo com *path traversal* (`../../etc/passwd.pdf`) é
  neutralizado por `sanitize_filename()` (`os.path.basename`, recusando `.`,
  `..` e qualquer caractere fora de uma lista segura) — o arquivo é aceito
  apenas com o nome já saneado (`passwd.pdf`), nunca com componentes de
  diretório.
- [x] **Detecção real de malware**: um arquivo contendo a assinatura EICAR de
  teste (amostra de verificação padrão da indústria, sem material clínico ou
  código malicioso real) foi rejeitado pelo `clamscan` de produção
  (`scan_attachment` → `reject_and_discard`, status final `rejected`) — testado
  com definições reais baixadas via `freshclam` para `/data/clamav`, não
  apenas simulado. Um PDF limpo, no mesmo teste, seguiu o caminho normal até
  `available`.
- [x] **Bug real encontrado e corrigido nesta sprint**: `integrations/antivirus.py`
  não apontava o `clamscan` para `/data/clamav` (o único diretório com volume
  persistente e gravável pelo worker, conforme `docker-stack.yml`/`compose.yml`);
  usava o caminho padrão do pacote (`/var/lib/clamav`), que não tem volume
  nenhum montado. Na prática isso faria todo scan real cair sempre em
  `ScanUnavailable` mesmo com definições atualizadas. Corrigido passando
  `--database=/data/clamav` explicitamente, e adicionada `update_definitions()`
  (via `freshclam`, executando como o próprio usuário do container, UID 10001,
  que já é dono do volume — sem *privilege drop*), registrada como tarefa
  periódica `documents.tasks.update_clamav_definitions` a cada 6h em
  `CELERY_BEAT_SCHEDULE`.
- [x] **Definição ausente/antiga mantém quarentena com erro visível**: testado
  em dois cenários reais — (1) volume `/data/clamav` vazio (recém-criado, sem
  `freshclam` executado) → `LibClamAV Error: cli_loaddbdir: No supported
  database files found`; (2) execução a partir do container `app` (que não
  monta `/data/clamav`, por design — apenas `celery_worker` o faz, já que o
  scan só ocorre na tarefa Celery) → mesmo erro. Em ambos, `scan_status`
  permanece `quarantined` e `scan_error` fica visível na tela de anexos;
  nenhum arquivo é liberado para download.
- [x] Preview (`render_preview_png`) roda via `pdftoppm` isolado (subprocess
  com timeout de 15s) e retorna PNG real (4763 bytes, assinatura PNG
  confirmada) para PDF; nunca executa o arquivo, apenas rasteriza a primeira
  página. DOCX levanta `PreviewUnavailable` (404) — nenhuma extração ativa de
  conteúdo Office é feita.
- [x] **Isolamento entre tenants**: o mesmo anexo, acessado por um usuário
  autenticado em outro tenant (`request.session['tenant_id']` diferente),
  responde 404 tanto para download quanto (por construção do mesmo
  `_attachment_or_404`) para preview e remoção — verificado via
  `django.test.Client` contra as rotas HTTP reais, não apenas a nível de
  queryset. Usuário não autenticado é redirecionado ao login (302), nunca vê
  o conteúdo.
- [x] Arquivo publicado é imutável por convenção de nome: `publish_from_quarantine`
  só sobrescreve se o caminho final (`<sha256>/<nome-original>`) ainda não
  existir; do contrário, apenas descarta o arquivo em quarentena (idempotência
  de reprocessamento). Arquivos com mesmo conteúdo mas nomes diferentes
  recebem cópias distintas dentro do mesmo diretório de hash — dedup real só
  ocorre quando conteúdo **e** nome coincidem.
- [x] `garbage_collect()` roda inteira dentro de `backup_exclusive()`, que
  segura o **mesmo** advisory lock do PostgreSQL usado por `ops/backup.py`
  (`ops/locks.py::BACKUP_LOCK`) e levanta `BackupInProgress` se o backup já
  o detiver; a compactação do arquivo morto (`documents/archive.py`) usa o
  mesmo bloco. Até 2026-09-19 as duas metades não se falavam: a aplicação
  consultava um arquivo em `/data/media/.backup_lock` que **nenhuma parte do
  sistema criava**, de modo que a recusa nunca acontecia e a compactação
  podia renomear um anexo no meio da cópia — produzindo um backup cujo banco
  aponta para arquivo inexistente, descoberto apenas na restauração.
  Com a trava ausente,
  remove fisicamente apenas anexos com `deleted_at` mais antigo que 30 dias
  **e** cujo `storage_key` não seja referenciado por nenhum outro anexo não
  deletado — testado com `dry_run=True` (relatório sem apagar) e
  `dry_run=False` (remoção real confirmada).
- [x] OCR (`run_ocr`) roda localmente via `pdftoppm` (rasterização) +
  `tesseract -l por` (pt-BR), nunca envia o arquivo a serviço externo. Testado
  com um PDF real gerado via `reportlab` contendo texto conhecido
  (“NEURODOC TESTE OCR 12345”) — o texto extraído bateu exatamente, com
  `AttachmentOcrPage` guardando `page_number` (proveniência) e `engine`.

## Decisões de escopo

- O teste de detecção de malware precisou inserir a assinatura EICAR
  diretamente na área de quarentena (contornando `validate_upload`), porque o
  parser de PDF do próprio ClamAV não faz varredura byte-a-byte de texto
  incorporado como comentário dentro da estrutura de um PDF válido — inserir a
  string dentro de um PDF bem formado resultava em `OK` (falso negativo do
  ClamAV para esse container específico, não do NeuroDoc). O caminho de
  validação de upload (extensão/MIME/estrutura) já está coberto
  separadamente pelos testes acima; o teste de antivírus isola apenas
  `scan_file`/`scan_attachment`/`reject_and_discard`, que é o que H-10 exige.
- Este ambiente de desenvolvimento não tem acesso a definições ClamAV
  pré-carregadas na imagem; `update_definitions()` foi executado manualmente
  uma vez para validar o fluxo real. Em produção, a tarefa periódica de 6h
  garante atualização contínua sem intervenção manual; se a rede para
  `database.clamav.net` cair, o mecanismo antimalware continua operando com a última base
  boa conhecida (falha grácil de `update_definitions`, sem afetar
  `scan_attachment`).
- `ComplementaryExam.attachment` (adiado de S05) e a integração de anexos com
  `MedicalDocument` (S07 — documentos assinados) permanecem para as próximas
  sprints; o modelo `Attachment` desta sprint já expõe `encounter` (nullable)
  suficiente para o vínculo básico usado no prontuário.
- O painel de administração (`documents/admin.py`) mantém `sha256` e
  `storage_key` somente leitura — nenhuma tela de administração permite
  substituir o arquivo de um anexo publicado.

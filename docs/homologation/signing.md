# Homologação — Documentos médicos e assinatura (S07)

Evidência coletada via scripts de verificação (`python manage.py shell`) contra
a pilha real e via `django.test.Client` contra as views reais. Certificado
**PFX autoassinado sintético** (chave RSA 2048 gerada em memória, CN com o
nome do médico de teste), já que P-05 (certificado ICP-Brasil real) permanece
não resolvido — ver "Decisões de escopo" abaixo. Nenhuma senha ou chave real
foi usada.

## H-08 — Assinatura e documentos

- [x] Cada tipo (receita, relatório, pedido, encaminhamento) gera PDF com
  identificação do médico (nome, CRM/UF, RQE quando existente), contato
  profissional, identificação do paciente e data — confirmado lendo os bytes
  do PDF gerado (`%PDF` válido) via `Attachment` `available` sem quarentena
  (conteúdo é sintetizado pelo próprio servidor, não upload de terceiro).
  PDF sem assinatura nunca chega a `issued`: `sign_and_issue` só altera o
  status para `issued` **após** `sign_pdf` retornar com sucesso; qualquer
  exceção mantém o documento em `ready_to_sign` (falha recuperável) ou
  `failed` (erro inesperado).
- [x] Sessão PFX testada nas 4 durações permitidas (2/4/6/12h) — duração fora
  da lista é recusada antes de qualquer I/O (`InvalidDuration`). Expiração é
  conferida no servidor a cada assinatura (`expires_at__gt=now`), nunca só no
  cliente. Revogação (`revoke_session`) remove a chave efêmera do tmpfs
  imediatamente e uma tentativa de assinatura subsequente falha com
  `SigningNotAuthorized`. Reboot/perda do tmpfs é simulado removendo o
  arquivo de chave sem revogar a linha no banco — `unlock_password` detecta a
  ausência (`SigningSessionKeyMissing`) e a assinatura é recusada mesmo com a
  sessão aparentando válida no banco, exatamente como especificado ("ausência
  da chave exige nova habilitação").
- [x] Sessão é **vinculada à sessão web** por hash (`session_binding_hash`):
  um `SigningSession` criado sob um `session_key` não é encontrado por
  `get_active_session` sob um `session_key` diferente — testado diretamente.
  Isso é o que impede secretaria/gestor/IA de reaproveitar uma sessão de
  assinatura do médico: eles nunca possuem o `session_key` do navegador do
  médico nem conseguem passar pela verificação de MFA recente dele.
- [x] **Papel não-médico bloqueado em cada camada**: `_own_doctor_membership_or_403`
  exige `access_context.has_role('doctor')`; testado via `django.test.Client`
  com uma conta de secretaria real — criação de documento (403), tentativa de
  assinatura (403) e acesso à tela de credenciais são todos recusados.
  Nenhuma dessas rotas aceita "assinar em nome de outro médico": a
  autorização é sempre a própria membership do usuário autenticado, nunca um
  parâmetro selecionável.
- [x] Senha do PFX incorreta é recusada em dois pontos independentes: no
  upload da credencial (`InvalidPfxFile`, o arquivo nem chega a ser
  envelopado) e na habilitação da sessão (`InvalidPfxPassword`, nenhuma
  chave efêmera é criada no tmpfs quando a senha falha — verificado
  comparando o conteúdo do diretório antes/depois da tentativa). Certificado
  cujo titular (CN) não bate com o nome do médico cadastrado é recusado no
  upload (`CredentialTitleMismatch`) — heurística substituindo a validação de
  cadeia ICP-Brasil real, indisponível nesta etapa (P-05). Credencial
  revogada não inicia nova sessão (`CredentialNotUsable`).
- [x] **Validação independente da assinatura**: o PDF assinado foi reaberto
  do zero (bytes lidos de volta do `Attachment` publicado, não do objeto em
  memória usado para assinar) e validado com `pyhanko.sign.validation.
  validate_pdf_signature` contra uma âncora de confiança própria — resultado
  `intact=True`, `valid=True`, `trusted=True`. O uso de `pyHanko` para
  assinar e para validar é a mesma biblioteca proposta no PRD; um verificador
  totalmente externo (VALIDAR/ITI) exige uma cadeia ICP-Brasil real e por
  isso não foi exercitado.
- [x] Assinatura é **incremental** (`IncrementalPdfFileWriter` + `sign_pdf`
  do pyHanko): o conteúdo original nunca é recomprimido ou reescrito, apenas
  uma atualização incremental é anexada — condição explícita do PRD
  ("não recriar páginas ou comprimir PDF depois de assinado").
  `signature_metadata` grava serial/fingerprint do certificado, hash SHA-256
  do conteúdo final assinado e timestamp — nenhuma senha ou chave em texto
  puro em nenhum desses campos, no Redis, no broker ou nos artefatos desta
  homologação.
- [x] **Numeração e versionamento**: `document_number` só é atribuído no
  instante da emissão bem-sucedida (lock advisory por tenant+ano evita
  colisão sob concorrência), nunca a rascunhos abandonados. Uma correção
  (`create_correction`) cria uma **nova linha** com `version` incrementada e
  `replaces_document` apontando para o original — o documento original
  permanece inalterado (`content_snapshot`/bytes assinados preservados),
  confirmado lendo o original após gerar a correção.
- [x] Evento `documents.document_issued` (`OutboxEvent`) só é criado depois
  que `status=issued` é persistido com sucesso, nunca antes — verificado
  diretamente no banco.

## Decisões de escopo

- **P-05 (certificado ICP-Brasil real) permanece aberto.** Toda a
  homologação acima usa um certificado A1 **autoassinado sintético**,
  gerado em memória com `cryptography` (RSA 2048, CN com nome de teste). A
  aplicação está pronta para um certificado real: `SigningCredential` grava
  `issuer`/`not_before`/`not_after`/serial/fingerprint reais do arquivo
  carregado, e a assinatura em si (`pyhanko.sign.signers`) não distingue um
  PFX de teste de um PFX ICP-Brasil real. O que falta é a validação de
  **cadeia** (AC raiz/intermediárias ICP-Brasil, OCSP/CRL) — hoje a única
  verificação é "a senha destrava o arquivo" e "o titular do certificado
  parece bater com o nome cadastrado" (heurística textual, não uma
  verificação criptográfica de identidade).
- O "titular" do certificado é validado por comparação textual normalizada
  (sem acentos, case-insensitive) entre o Common Name do certificado e o
  `professional_name` cadastrado — uma aproximação razoável sem uma cadeia
  ICP-Brasil real para extrair CPF/CRM do certificado de forma confiável.
- Nenhum carimbo visual de assinatura foi implementado (assinatura
  invisível/PAdES sem campo gráfico) — o pyHanko permite ambos; a validade
  jurídica não depende do carimbo visual, e a UI de carimbo fica para S14
  junto com a adequação ao design system (mesmo padrão de todas as sprints
  anteriores: corretude do backend primeiro).
- A limpeza de chaves órfãs do tmpfs (`documents.management.commands.
  cleanup_signing_keys`) é um comando Django comum, pensado para ser
  disparado por um timer do **host** a cada 5 minutos
  (`ops/neurodoc-signing-cleanup.timer/.service`, mesmo padrão de
  `ops/neurodoc-backup.timer`) — nunca pelo Celery beat, já que o worker não
  monta `/run/neurodoc-signing` (PRD seção 8). O timer em si não foi
  instalado em um host systemd real nesta etapa (ambiente de
  desenvolvimento local); o comando foi executado manualmente e verificado.
- `MedicalDocument.encounter` é obrigatório (não opcional) nesta
  implementação: todo documento médico nasce vinculado a um atendimento
  específico, consistente com o restante do prontuário (S05).
- O upload de PFX e o início de sessão de assinatura reaproveitam
  `accounts.mfa.mfa_verified_recently` (janela de 30 minutos) — um médico
  sem TOTP confirmado nunca consegue habilitar assinatura, o que é a
  política pretendida ("MFA obrigatório para... médicos que habilitem
  assinatura"), não uma lacuna.

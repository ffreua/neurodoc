# MFA, certificado e lista de pré-cadastros — plano de implementação

> **Para agentes executores:** SUB-SKILL OBRIGATÓRIA: use `executing-plans` para executar este plano tarefa por tarefa, com TDD em cada mudança de comportamento.

**Objetivo:** Exibir um QR escaneável no cadastro de MFA, orientar o médico antes do envio do certificado quando faltar MFA e impedir que pré-cadastros da agenda apareçam na lista de pacientes antes da confirmação da ficha.

**Arquitetura:** O QR será produzido no servidor a partir da mesma `config_url` do `TOTPDevice`, sem serviço externo e sem expor o segredo em uma requisição de imagem. A tela de certificados continuará protegida no POST, mas passará a refletir no GET se a conta está apta e a confirmação inicial da MFA passará a contar como verificação recente. A agenda continuará encontrando pré-cadastros para evitar duplicidade, enquanto somente a lista administrativa exigirá `registration_stage=complete`; salvar com sucesso a ficha completa fará a promoção de estágio.

**Stack:** Django 5, django-otp, ReportLab, Django Templates, roteiros de verificação em `checks/`.

**Especificação:** relato pós-deploy de 27/09/2026, consolidado na seção “Requisitos” deste arquivo.

## Requisitos

- A configuração de MFA deve mostrar QR e manter a URL textual como alternativa manual.
- A geração do QR não pode enviar o segredo TOTP a terceiros.
- Sem MFA configurada, a tela de certificado deve explicar o impedimento e oferecer o caminho para configurar MFA, em vez de apresentar um envio destinado a falhar com 403 cru.
- Confirmar o primeiro TOTP deve marcar a sessão como recentemente verificada.
- Credenciais, sessões e assinatura devem continuar limitadas ao vínculo do médico logado.
- Um paciente criado rapidamente pela agenda não aparece em `/app/patients/` enquanto estiver em `preliminary`.
- Ao a secretaria salvar validamente a ficha completa, o estágio muda para `complete` e o paciente passa a aparecer na lista.
- A busca usada pela própria agenda continua aceitando o pré-cadastro para não criar duplicatas.

## Restrições globais

- Não adicionar dependência: reutilizar ReportLab, já fixado em `requirements.txt`.
- Não rodar roteiros contra o banco de produção.
- Preservar e versionar separadamente a alteração pendente de sincronização do nome do contato.
- Comentários, mensagens do produto e commits em português.

---

### Tarefa 1: preservar a pendência herdada

**Arquivos:**
- Modificar já existente: `patients/contacts.py`
- Modificar já existente: `patients/forms.py`
- Modificar já existente: `patients/views.py`
- Modificar já existente: `scheduling/services.py`
- Criar já existente no worktree: `checks/check_nome_do_contato.py`

**Interfaces:**
- Produz: `SELF_RELATIONSHIP` e `sync_self_contact_name(patient) -> int`.

- [ ] Rodar `checks/check_nome_do_contato.py` no ambiente local e confirmar que a regressão passa.
- [ ] Rodar `git diff --check` e revisar o diff somente desses cinco arquivos.
- [ ] Criar um commit separado para não misturar a pendência anterior com os três defeitos atuais.

### Tarefa 2: QR do cadastro de MFA

**Arquivos:**
- Modificar: `accounts/mfa.py`
- Modificar: `accounts/views.py`
- Modificar: `templates/accounts/mfa_setup.html`
- Criar: `checks/check_mfa_certificado.py`

**Interfaces:**
- Produz: `qr_code_data_uri(payload: str) -> str`.
- Consome: `TOTPDevice.config_url`.

- [ ] Escrever no roteiro uma verificação de que duas URLs `otpauth://` diferentes produzem imagens SVG diferentes em `data:` URI e de que a tela contém uma imagem com texto alternativo.
- [ ] Rodar o roteiro e observar falha por ausência de `qr_code_data_uri`/imagem.
- [ ] Implementar o SVG compacto a partir da matriz do `QrCodeWidget`, com margem branca de quatro módulos e codificação base64.
- [ ] Passar a URI ao template tanto no GET quanto no POST inválido, preservando a URL textual.
- [ ] Rodar novamente o roteiro e confirmar o verde.

### Tarefa 3: percurso de MFA antes do certificado

**Arquivos:**
- Modificar: `accounts/views.py`
- Modificar: `templates/accounts/mfa_setup.html`
- Modificar: `templates/accounts/mfa_recovery_codes.html`
- Modificar: `documents/views.py`
- Modificar: `templates/documents/credentials.html`
- Testar: `checks/check_mfa_certificado.py`

**Interfaces:**
- Consome: `accounts.mfa.user_has_confirmed_totp(user)` e `accounts.mfa.mfa_verified_recently(request)`.
- Produz no contexto de certificado: `mfa_ativa: bool` e `mfa_recente: bool`.

- [ ] Acrescentar regressões: a página sem MFA oculta o formulário e mostra link de configuração; a confirmação de TOTP grava `mfa_verified_at`; uma credencial de outro médico não aparece nem pode ser selecionada/revogada.
- [ ] Rodar o roteiro e observar as falhas esperadas no aviso e na marca de MFA recente.
- [ ] Marcar a sessão como recente após `confirm_device`, preservar um `next` local seguro e oferecer retorno à tela de certificados após exibir os códigos de recuperação.
- [ ] Condicionar o formulário de envio a MFA ativa e recente; manter a validação do POST e trocar o caso “MFA inexistente” por redirecionamento explicativo.
- [ ] Rodar novamente o roteiro e confirmar todas as proteções, inclusive a de propriedade por médico.

### Tarefa 4: pré-cadastro fora da lista até a confirmação

**Arquivos:**
- Modificar: `patients/selectors.py`
- Modificar: `patients/views.py`
- Modificar: `checks/check_precadastro.py`

**Interfaces:**
- Consome: `RegistrationStage.PRELIMINARY` e `RegistrationStage.COMPLETE`.
- Produz: `list_patients(...)` contendo apenas cadastros completos; `PatientUpdateView` promovendo uma ficha preliminar após POST válido.

- [ ] Acrescentar ao roteiro um paciente preliminar ativo e confirmar que `list_patients` não o devolve, mas `autocomplete_patients` continua devolvendo-o.
- [ ] Acrescentar um POST válido de edição pela secretária e confirmar que o estágio vira `complete` e passa a constar em `list_patients`.
- [ ] Rodar o roteiro e observar falha primeiro na lista e depois na promoção do estágio.
- [ ] Filtrar a lista por `RegistrationStage.COMPLETE` sem alterar o autocomplete da agenda.
- [ ] Na edição válida, promover a instância preliminar antes de salvar e registrar a promoção nos metadados da auditoria.
- [ ] Rodar novamente o roteiro e confirmar o verde.

### Tarefa 5: documentação, verificação e publicação

**Arquivos:**
- Modificar: `checks/README.md`
- Criar ou modificar: `docs/homologation/mfa-certificado-e-precadastro.md`
- Criar na VPS: `docs/releases/<sha>.md` a partir do modelo, sem versionar segredos.

- [ ] Registrar no catálogo de roteiros o novo `check_mfa_certificado` e documentar as evidências das três correções.
- [ ] Rodar os roteiros focados e depois `manage.py rodar_roteiros`, classificando somente falhas já documentadas de catálogo/ambiente.
- [ ] Rodar `git diff --check`, verificações do Django e revisar o diff final.
- [ ] Commitar em unidades coerentes, publicar em `origin/main` e atualizar o checkout da VPS.
- [ ] Criar a homologação da release, rodar o preflight e executar o deploy por `ops.deploy`.
- [ ] Validar serviços `2/2`/`1/1`, healthcheck HTTPS, release ativa e logs recentes sem erro.

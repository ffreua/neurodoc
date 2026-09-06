# Homologação — Onboarding, pacientes e catálogos (S03)

Executada com dados sintéticos no ambiente local (`compose.yml`), sem qualquer
VPS, e-mail ou SMS real. Evidência coletada de duas formas: scripts de
verificação via `python manage.py shell` contra a pilha real (models, views,
middlewares) e interação real de navegador (`agent-browser`, Chrome via CDP)
para navegação por teclado e viewport móvel.

## H-01 — Convite e onboarding

- [x] Convite de plataforma (`purpose=platform`) validado na landing, redireciona
  para `/signup/<token>/`; criar usuário+organização+membership owner ocorre em
  uma única transação (`tenancy.services.accept_platform_invitation`).
- [x] Duas tentativas simultâneas não consomem o mesmo convite: `consume_invitation`
  usa `select_for_update()`; testado diretamente — a primeira chamada consome,
  a segunda retorna `None` sem erro.
- [x] Convite inválido/expirado/consumido não cria usuário nem organização parcial:
  reutilizar um token já consumido responde 400 sem tocar o banco; uma tentativa
  de signup com e-mail já cadastrado falha e **não queima o convite** (o convite
  permanece utilizável), pois a consumação e a criação da organização estão na
  mesma transação atômica.
- [x] Plano free é o único contratável: o formulário não expõe nenhum campo de
  plano; o serviço grava `plan='free'` incondicionalmente. Planos "Profissional"
  e "Clínica" aparecem na landing apenas como "Em breve", sem link/formulário.
- [x] CNPJ e razão social são obrigatórios e o CNPJ é validado pelo dígito
  verificador real (mod 11), não apenas por comprimento; CNPJ duplicado é
  rejeitado antes de tentar criar o tenant.
- [x] Navegação por teclado: Tab percorre landing → link "Usar convite" → link
  "Entrar" → campo de código → botão "Continuar", nesta ordem; testado com
  Chrome real (`agent-browser`), sem necessidade de mouse.
- [x] Viewport móvel (375×812): landing sem rolagem horizontal
  (`scrollWidth == 375`), conteúdo legível.

## Convites internos e gestão de colaboradores (RF-01.05, S03-T03)

- [x] Owner convida colaborador com papéis explícitos (`role_grants`); aceite
  cria Membership `active` para o e-mail vinculado (conta nova) ou adiciona um
  vínculo à conta já autenticada existente ("vinculação autorizada") — nunca
  cria uma segunda conta para o mesmo e-mail.
- [x] **Owner não atribui automaticamente habilitação médica**: conceder o papel
  `doctor` por convite cria a Membership com esse papel, mas
  `Membership.can_practice_clinically()` retorna `False` até existir um
  `PhysicianProfile` com `verification_status='verified'` — testado
  concretamente: papel concedido → `False`; perfil criado como `pending` →
  ainda `False`; perfil marcado `verified` → só então `True`.
- [x] Revogar a Membership do colaborador via `/app/org/collaborators/<id>/revoke/`
  muda o status para `revoked` imediatamente; como o `AccessContext` é
  reconstruído a cada requisição (S02), o acesso ao tenant cessa na próxima
  requisição sem necessidade de invalidar sessão.
- [x] Reutilizar o mesmo link de convite de colaborador após aceito responde 400.

## H-04 — Pacientes e demografia

- [x] Cadastro de adulto com campos completos, menor sem CPF
  (`Joao Menor Pereira`, 11 anos, `cpf=None`) e paciente com data de nascimento
  desconhecida (`birth_date=None` + motivo registrado) — os três aceitos pelo
  model; nenhum se torna obrigatório para os demais (validação condicional
  em `Patient.clean()`).
- [x] Erro de campo é exibido inline: submeter o formulário real sem data de
  nascimento nem motivo mostra "Provide a birth date or a reason it is unknown"
  imediatamente acima do campo `Birth date`, com os demais campos preenchidos
  preservados (sem perda de digitação).
- [x] CPF duplicado é tratado somente dentro do tenant: o mesmo CPF é rejeitado
  ao tentar cadastrar um segundo paciente na **mesma** clínica
  (`UniqueConstraint(tenant, cpf)` no banco), mas aceito normalmente em uma
  clínica **diferente** — confirmado inserindo o mesmo CPF nas duas clínicas
  de demonstração.
- [x] Medições com datas distintas preservam histórico: registrar um peso mais
  antigo e depois um mais recente mantém as duas linhas em `Observation`; o
  IMC calculado usa a medição de peso/altura mais recente de cada uma, com as
  datas de origem retornadas junto do valor (nunca um número isolado sem
  proveniência). Valor não positivo é rejeitado (`ValidationError`).
  Unidades são fixas por `kind` (kg/m), sem campo livre do cliente.
  Idade é calculada corretamente na data de referência (`age_at`).
- [x] Arquivamento mantém histórico: arquivar `Carlos Adulto da Silva` mantém o
  registro e suas 4 observações no banco, apenas remove o paciente da listagem
  ativa padrão (`status=active`); confirmado tanto via script quanto na
  listagem real do navegador (paciente ausente da lista após arquivar).
- [x] Contato autorizado é distinto de contato geral: `PatientContact` exige
  `relationship` quando `authorized_for_documents=True`; o contato de um menor
  exige `legal_authority` + `authority_evidence` registrados (representante
  legal), testado concretamente — contato sem relacionamento é rejeitado.
- [x] Busca por nome não revela pacientes de outra clínica: buscar "Carlos" no
  contexto da clínica B retorna lista vazia, mesmo havendo um paciente
  "Carlos Adulto da Silva" na clínica A.
- [x] Adicionar contato (`/app/patients/<id>/contacts/`) e cobertura
  (`/app/patients/<id>/coverage/`) pela tela real: contato sem `relationship`
  com `authorized_for_documents` marcado é rejeitado com erro no campo; plano
  de outra clínica nunca aparece no seletor (`ModelChoiceField` já filtrado
  por tenant) — submeter manualmente o ID de um plano de outro tenant também
  falha, pois o queryset do campo não o contém.
- [x] Endpoint de CEP (`/app/patients/cep-lookup/`) reaproveita a integração
  ViaCEP real e responde `{"found": true/false}` sem nunca incluir
  `complement`.
- [x] `responsible_membership` no formulário é restrito a médicos (`doctor`)
  ativos do próprio tenant — nunca lista vínculos de outra clínica; o rótulo
  exibido é o nome do profissional, não um identificador técnico (corrigido
  nesta sprint via `label_from_instance`).
- [x] Navegação por teclado no formulário: todos os campos (texto, seletor de
  data nativo, selects, textarea) são alcançáveis e operáveis via Tab, com
  rótulos associados automaticamente pelo `ModelForm`; confirmado com Chrome
  real. A automação do sub-campo dia/mês/ano do `<input type="date">` nativo
  via CDP se mostrou instável na ferramenta de automação (comportamento da
  ferramenta, não do formulário); o caminho de criação bem-sucedida com data
  válida foi validado no nível de código (view + model) via
  `django.test.Client`, não apenas por leitura.
- [x] Viewport móvel (375×812): lista de pacientes sem rolagem horizontal.

## CEP (RF-02.03, S03-T07)

- [x] CEP válido (01310-100, Av. Paulista) retorna endereço real via ViaCEP
  (chamada de rede real, timeout de 3 s); CEP malformado e CEP inexistente
  retornam `None` sem lançar exceção, permitindo cadastro manual.
- [x] `complement` nunca é retornado pela integração — só pode ser preenchido
  manualmente, nunca sobrescrito pela consulta.

## H-05 — Catálogos

- [x] Importador dry-run relata contagem sem persistir nada; `--commit` cria
  `CatalogRelease` + códigos numa transação; tentar reimportar a mesma
  combinação `(system, version)` falha com erro claro
  (`DuplicateReleaseVersion`), sem sobrescrever a release existente.
- [x] `activate_release` marca a nova release ativa e rebaixa a anterior do
  mesmo sistema para `superseded` — nunca apaga; snapshots de código já
  referenciados permanecem resolvíveis.
- [x] Amostra usada em `seed_demo`/testes é explicitamente rotulada como
  sintética (`version='SAMPLE-2026'`, `license_note` afirma não ser o catálogo
  oficial) — nunca se apresenta como CID-10/TUSS oficial.
- [x] Operadora/plano são por tenant (`Insurer`, `HealthPlan` com
  `UniqueConstraint(tenant, insurer, name)`); catálogos (`CatalogRelease`,
  `DiagnosisCode`, `ProcedureCode`) são GLOBAL e não carregam nenhum dado de
  paciente.

## `seed_demo` (RF-12.02)

- [x] Executado duas vezes seguidas: primeira execução cria 2 tenants, 2
  usuários, 3 memberships, 4 pacientes, 2 contatos, 2 observações, 1 cobertura,
  além da release de catálogo sintética; a segunda execução não cria nada
  (todos os contadores em zero) — idempotente confirmado.
- [x] Recusa executar quando `NEURODOC_DEMO_ALLOWED=False` (`CommandError`),
  consistente com o padrão de produção não habilitar o comando.
- [x] Nenhum e-mail/SMS real é enviado (canais desabilitados no ambiente);
  nenhum PFX é usado.

## Limites explícitos desta homologação

- Não cobre H-06 a H-23 (prontuário, assinatura, agenda, etc.), fora do
  escopo desta sprint.
- A automação de navegador cobriu landing, formulário de paciente e listagem;
  não cobriu o fluxo completo de convite de colaborador em um navegador real
  (validado via `django.test.Client`, que exercita a mesma pilha de views e
  middlewares, mas sem renderização visual).
- Nenhum dado real de paciente, CNPJ ou CPF de pessoa real foi usado; todos os
  CPFs/CNPJs de teste são sintéticos, porém matematicamente válidos.

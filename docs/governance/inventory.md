# Inventário LGPD, contratos e modalidades documentais

P-05 (titularidade/certificado real), P-06 (base legal, contratos de
operadores, retenção, transferência internacional, RIPD, anonimização) e
P-07 (situação/acesso técnico ao SNCR para modalidades controladas)
permanecem **pendentes** — nenhum responsável legal/regulatório real
assinou liberação alguma nesta execução. Este documento registra o que o
sistema **implementado** processa e retém, para que a assinatura de
liberação (quando houver responsáveis reais) tenha uma base concreta em vez
de uma promessa abstrata.

## Categorias de dado processadas (por app)

| Categoria | Onde vive | Retenção implementada | Observação |
| --- | --- | --- | --- |
| Identificação do paciente | `patients.Patient` | Sem expurgo automático (prontuário) | CPF, nome, nascimento, endereço |
| Contato de terceiro/responsável | `patients.PatientContact` | Sem expurgo automático | Autorização de entrega registrada por campo (`authorized_for_documents`, `legal_authority`) |
| Registro clínico (queixa, HPI, exame, diagnóstico) | `clinical.Encounter`, `ExaminationFinding`, `EncounterDiagnosis` | Imutável após finalização (hash), sem expurgo automático | Nunca aparece em log, alerta, financeiro ou CRM (verificado em S09/S10) |
| Anexos (exames, laudos externos) | `documents.Attachment` | Soft-delete + GC físico após 30 dias, nunca durante backup (lock) | Quarentena/antivírus antes de disponível (S06) |
| Documento médico assinado | `documents.MedicalDocument` | Sem expurgo automático; hash + versionamento | PAdES; certificado de teste nesta etapa (P-05) |
| Credencial de assinatura (PFX) | `documents.SigningCredential` | Até revogação/substituição | Cifrado por envelope; nunca em texto puro (S07) |
| Contato para entrega (e-mail/telefone) | `communications.Delivery`, `DocumentAccessToken` | Token expira em 7 dias; OTP de uso único | Nunca envia diagnóstico na mensagem (S08) |
| Financeiro (recebível/pagamento) | `finance.Receivable`, `Payment` | Sem expurgo automático | Isolado do prontuário; usuário financeiro não lê nota clínica (S09) |
| Auditoria | `audit.AuditEvent` | Sem expurgo automático (trilha) | `purpose`/`integrity_metadata` nunca recebem texto clínico por contrato do `record_audit_event` |

## Modalidades documentais e SNCR (P-07)

O sistema modela 4 tipos de documento médico (`prescription`, `report`,
`request`, `referral`, S07) com template e campos próprios por tipo. Nenhuma
integração com o SNCR (Sistema Nacional de Gerenciamento de Produtos
Controlados) foi implementada ou testada — receitas de substância
controlada, quando existirem como modalidade distinta, exigem acesso
técnico ao SNCR que depende de P-07 (situação regulatória ainda não
verificada). Até essa resolução, o tipo `prescription` deste sistema deve
ser tratado como receita comum, nunca como substituto de notificação a
órgão de controle.

## Retenção e anonimização

Não existe rotina de anonimização/expurgo definitiva do prontuário clínico
implementada — por decisão de produto ainda pendente (P-06: "política de
anonimização"). O que já está implementado e verificado:

- GC de anexos (S06): remove apenas o arquivo em disco de anexos
  logicamente removidos há mais de 30 dias e nunca referenciados por outra
  linha; nunca durante backup.
- `prepare_recovery` (S10): após uma restauração, invalida sessões/tokens e
  suspende entregas pendentes — não apaga nenhum registro clínico
  (verificado nesta sprint).
- `seed_demo`/dados sintéticos: nunca usam CPF/contato real; produção
  recusa a flag de demonstração por padrão (`NEURODOC_DEMO_ALLOWED`).

## Transferência internacional e IA

Nenhum dado é hoje enviado a um provedor de IA externo (`AI_ENABLED=False`
nesta etapa) nem a nenhum serviço fora do Brasil além do necessário para
TLS (Cloudflare, quando P-02 resolver). A revisão de transferência
internacional para IA é escopo de S11, condicionada a P-06/P-09.

## Decisões de escopo

- Este documento é um **inventário técnico**, não um registro de liberação
  assinado — a linha de aceite de S10-T09 ("Responsáveis assinam registro
  de liberação por finalidade/modalidade") exige um controlador/DPO real
  designado, que não existe nesta execução. Nenhuma assinatura foi
  fabricada; o campo de assinatura abaixo fica deliberadamente em branco.
- Quando P-05/P-06/P-07 resolverem, este inventário deve ser revisado
  linha a linha pelos responsáveis reais antes de qualquer liberação para
  clínica real (nunca apenas re-carimbado).

| Finalidade/modalidade | Responsável | Data | Assinatura |
| --- | --- | --- | --- |
| Prontuário clínico | _pendente (P-06)_ | — | — |
| Documento assinado/PAdES | _pendente (P-05)_ | — | — |
| Modalidade controlada (SNCR) | _pendente (P-07)_ | — | — |

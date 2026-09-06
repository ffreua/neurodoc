# NeuroDoc — Product Requirements Document

**Versão:** 1.0 • **Data:** 05/09/2026 • **Responsável pelo produto:** Dr Fernando Freua - CRM134.498 (também é o desenvolvedor) • **Estado:** especificação para implementação e homologação.

**Documento de origem:** NeuroDoc_prompt_mestre.md, versão 1.0. Este PRD é autossuficiente: contém as decisões, os requisitos, o planejamento e os anexos operacionais. A aplicação ainda deverá ser implementada; os comandos do guia são instruções para execução posterior. Nenhum servidor, conta de provedor ou ambiente de produção foi acessado ou alterado para elaborar este documento.

## Sumário

1. [Visão, objetivos e métricas](#1-visão-objetivos-e-métricas)
2. [Escopo e versões do produto](#2-escopo-e-versões-do-produto)
3. [Premissas, decisões e pendências](#3-premissas-decisões-e-pendências)
4. [Personas e permissões](#4-personas-e-permissões)
5. [Jornadas e estados de interface](#5-jornadas-e-estados-de-interface)
6. [Requisitos funcionais e critérios de aceite](#6-requisitos-funcionais-e-critérios-de-aceite)
7. [Requisitos técnicos e não funcionais](#7-requisitos-técnicos-e-não-funcionais)
8. [Arquitetura, apps e versões](#8-arquitetura-apps-e-versões)
9. [Modelagem de dados](#9-modelagem-de-dados)
10. [Autenticação, tenancy, auditoria e proteção de dados](#10-autenticação-tenancy-auditoria-e-proteção-de-dados)
11. [Prontuário e exame neurológico](#11-prontuário-e-exame-neurológico)
12. [Documentos, assinatura, entrega e scanner](#12-documentos-assinatura-entrega-e-scanner)
13. [Agenda, CRM, financeiro e indicadores](#13-agenda-crm-financeiro-e-indicadores)
14. [IA, tools, privacidade e streaming](#14-ia-tools-privacidade-e-streaming)
15. [Tarefas, eventos e notificações](#15-tarefas-eventos-e-notificações)
16. [Design system e acessibilidade](#16-design-system-e-acessibilidade)
17. [Infraestrutura, rede e releases](#17-infraestrutura-rede-e-releases)
18. [Guia sequencial de deploy Ubuntu](#18-guia-sequencial-de-deploy-ubuntu)
19. [Operação, recuperação e diagnóstico](#19-operação-recuperação-e-diagnóstico)
20. [Sprints e tarefas detalhadas](#20-sprints-e-tarefas-detalhadas)
21. [Homologação manual e critérios de liberação](#21-homologação-manual-e-critérios-de-liberação)
22. [Matriz de rastreabilidade](#22-matriz-de-rastreabilidade)
23. [Riscos, dependências e fontes](#23-riscos-dependências-e-fontes)
24. [Anexos operacionais completos](#24-anexos-operacionais-completos)

## 1. Visão, objetivos e métricas

O NeuroDoc será um sistema web para o atendimento longitudinal em neurologia e neurocirurgia, com agenda, cadastro de pacientes, prontuário estruturado, documentos assinados, comunicação, relatórios e gestão financeira básica. Cada clínica ou consultório constitui um tenant: uma organização cujos usuários e registros são separados logicamente das demais no mesmo banco.

O produto deve reduzir digitação repetitiva e uso de papel, sem transformar dados não avaliados em achados normais ou sugestões da IA em decisões médicas. A indisponibilidade de IA, SMS ou e-mail não deve impedir o médico de consultar o prontuário e salvar o atendimento.

| Objetivo | Indicador e forma de apuração | Meta proposta para o piloto |
| --- | --- | --- |
| Agilizar cadastro | Mediana do tempo entre abrir e salvar cadastro mínimo, excluindo pausas de mais de 5 minutos | Até 3 minutos após treinamento |
| Agilizar documentação | Tempo de documentação por atendimento comparado ao processo anterior, observado em pelo menos 30 consultas | Redução de 25%, sem elevar correções |
| Reduzir papel | Documentos elegíveis entregues digitalmente / documentos elegíveis emitidos | Pelo menos 80% |
| Evitar erros de agenda | Reservas sobrepostas não autorizadas confirmadas pelo sistema | Zero |
| Preservar autoria | Registros finalizados com médico, data, versão e trilha de alteração | 100% |
| Isolar clínicas | Acessos cruzados indevidos nos cenários de homologação e incidentes conhecidos | Zero; qualquer ocorrência bloqueia liberação |
| Tornar a IA utilizável | Sugestões aceitas, editadas, rejeitadas e não avaliadas, separadamente, sem usar aceitação como medida de acurácia | Medir no piloto; sem meta clínica artificial |

As metas são hipóteses de produto, não resultados medidos. Registrar baseline antes do piloto. Telemetria deve conter tempos, estados e identificadores internos, sem transcrever conteúdo clínico.

## 2. Escopo e versões do produto

### 2.1 Entregas progressivas

| Marco | Conteúdo obrigatório | Condição de uso |
| --- | --- | --- |
| M0 — fundação | Ambiente, autenticação, tenants, permissões, auditoria, banco, fila e primeiro deploy técnico | Apenas dados sintéticos |
| M1 — consultório funcional | Convites, pacientes, catálogos, agenda, secretaria, prontuário, anexos privados e rascunhos de documentos | Homologação interna; sem prometer emissão digital válida antes da assinatura |
| M2 — piloto assistencial | Assinatura validada, entrega protegida, lembretes, CRM, financeiro, backup restaurável e controles de acesso homologados | Clínicas convidadas, após critérios da seção 21 |
| M3 — apoio inteligente | IA com política de dados aprovada, análise por atendimento, resumo longitudinal, chat e streaming | Liberação por funcionalidade e tenant; funcionamento assistencial independente |
| M4 — gestão e acabamento | Relatórios completos, estatística elegível, integração de captura, UX final e documentação consolidada | Todos os requisitos do escopo rastreados |

Cada marco mantém as dependências do anterior. IA e scanner não podem adiar isolamento de arquivos, integridade clínica ou restauração. O plano free será o único disponível; nenhuma etapa inicial cobrará cartão de crédito.

### 2.2 Exclusões explícitas

Ficam fora da versão 1: cobrança da assinatura SaaS, gateway de pagamento, emissão fiscal, ERP/contabilidade, faturamento TISS, seguros/sinistros, internação e centro cirúrgico, PACS/DICOM completo, teleconsulta, marketplace de médicos e portal clínico completo do paciente. A página segura de recebimento de documentos faz parte do escopo.

Prescrições sujeitas a regras específicas de controle não serão habilitadas por simples existência de um PDF assinado. O conector e a modalidade documental somente serão liberados após validação da regra vigente e da integração exigida. A evolução do SNCR está descrita pela [Anvisa](https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa/2026/SNCR-o-que-muda-para-farmacias-e-drogarias-com-o-novo-sistema-de-controle-de-receitas); esta consulta não confirmou habilitação de integração para o NeuroDoc.

## 3. Premissas, decisões e pendências

**Legenda:** confirmado = demanda do produto; adotado = solução definida neste PRD; proposto = valor ou detalhamento a validar no piloto; pendente = depende de informação/validação externa.

| ID | Decisão adotada e objetivo preservado | Estado/impacto |
| --- | --- | --- |
| DEC-01 / CR-01 | Stack `neurodoc_v1`; redes `traefik_public`, `neurodoc_v1_internal`, `neurodoc_v1_egress`. Registry permanece `ghcr.io/pycodebr/scsi_v1` | Nomes fixos; propriedade do registry pendente |
| DEC-02 / CR-02 | Vocabulário clínico. “Sinistro” é resíduo de outro domínio; “negociação” limita-se a registros financeiros autorizados | Não criar corretora ou módulo de seguros |
| DEC-03 / CR-03 | `core` configura o projeto; `base` concentra primitivas pequenas compartilhadas; apps de domínio na raiz | Não criar um app monolítico |
| DEC-04 / CR-04 | Timestamps em models próprios e relações intermediárias explícitas; tabelas internas de bibliotecas permanecem sob gestão delas | Exceção documentada |
| DEC-05 / CR-05 | Papéis acumuláveis por vínculo; dono não recebe automaticamente permissões clínicas | Exige matriz de permissões |
| DEC-06 / CR-06 | OpenRouter/GLM padrão; OpenAI/Anthropic selecionáveis por administrador técnico; sem fallback externo implícito | Qualquer provedor deve cumprir política de dados |
| DEC-07 / CR-07 | Sessão de assinatura de 2/4/6/12 horas, sempre com ação médica por documento | A assinatura produzida não expira ao encerrar a sessão |
| DEC-08 / CR-08 | Desidentificação local; reidentificação reversível continua sendo pseudonimização; envio externo bloqueado quando não satisfaz a política | IA externa pode ficar indisponível para certos casos |
| DEC-09 / CR-09 | `collectstatic --clear` em staging por release; publicação atômica, retenção de releases e leitura dinâmica dos assets | Evitar limpeza de arquivos em uso |
| DEC-10 / CR-10 | App migra com advisory lock; worker/beat aguardam dependências e migrations locais aplicadas | Não depender de depends_on no Swarm |
| DEC-11 / CR-11 | Duas réplicas web, start-first, atualização sequencial, healthchecks e verificação posterior | Meta de continuidade; não é HA contra perda da VPS |
| DEC-12 / CR-12 | Parser literal de `.env`, env_files por serviço e configuração de stack gerada com valores controlados | Nenhum source/eval; secrets fora de env_file |
| DEC-13 / CR-13 | Três redes pré-criadas; interna com `docker network create --internal`; stack apenas referencia redes externas | A propriedade efetiva Internal deve ser inspecionada |
| DEC-14 / CR-14 | Captura com agente local de importação de pasta, pareado à sessão clínica; upload manual disponível desde M1 | Não prometer API universal de scanner no navegador |
| DEC-15 | Sessão seleciona tenant em `neurodoc.app.br/app/`; subdomínios opcionais são aliases registrados, sem inferência de permissão | Simplifica início; wildcard TLS permanece |
| DEC-16 | Um tenant por CNPJ cadastrado; filiais jurídicas distintas podem ter tenants distintos | Política proposta; revisão antes do onboarding se houver unidades com mesmo CNPJ |
| DEC-17 | SSR com Django Templates, JavaScript pequeno e SSE; ASGI/Uvicorn em produção | Evitar SPA sem necessidade |
| DEC-18 | Redis: resultados DB 0, cache DB 1, eventos transitórios DB 2; fonte clínica definitiva no PostgreSQL | Separação lógica não é fronteira de segurança |
| DEC-19 | PostgreSQL 17, roles separadas para migração e execução, nenhum superuser no Django | App recebe credencial de DDL por exigir migrations no entrypoint; risco residual documentado |
| DEC-20 | Nenhuma suíte de testes automatizados | Decisão confirmada; revisão, verificação sintática e homologação manual continuam obrigatórias |

### 3.1 Pendências que não impedem a especificação

| ID | Informação/validação pendente | Quem resolve | Momento limite |
| --- | --- | --- | --- |
| P-01 | `design_system/design-system.html` não foi fornecido nesta execução | Produto/design | Antes de homologar qualquer aderência visual |
| P-02 | URL Git, permissão GHCR, IP/arquitetura e acesso da VPS | Responsável técnico | S01 / primeiro deploy |
| P-03 | SMTP, SMSDEV, orçamento de IA e contatos reais de operação | Produto/operação | Antes de habilitar canais reais |
| P-04 | Resolução conjunta de dependências e digest das imagens | Desenvolvimento | S01; novas releases revisam lock |
| P-05 | Validação da assinatura com certificado A1 real autorizado, cadeia, revogação e modalidade documental | Médico responsável + segurança | Antes de emissão clínica |
| P-06 | Base legal, contratos de operadores, retenção, transferência internacional, RIPD e política de anonimização | Controlador + assessoria especializada | Antes de dados reais/IA externa |
| P-07 | Situação atual e acesso técnico ao SNCR/modalidades controladas | Produto + responsável regulatório | Antes da respectiva funcionalidade |
| P-08 | Windows/software do scanner e diretório de saída de cada consultório | Operação da clínica | S13 |
| P-09 | Validação de enquadramento regulatório do apoio diagnóstico, inclusive eventual SaMD | Produto + regulatório | Antes de divulgar finalidade clínica da IA |
| P-10 | Destino externo e titular da chave de recuperação de backup | Operação + controlador | Antes do piloto assistencial |

## 4. Personas e permissões

O usuário é global, mas seus papéis e concessões pertencem ao vínculo com a clínica. Papéis: `owner`, `doctor`, `secretary`, `manager`. `is_superuser` identifica a administração técnica da plataforma, não o dono da clínica. Ser `staff` não concede acesso ao admin global sem política adicional.

**Escopos:** A = administrativo do tenant; C = pacientes sob responsabilidade/concessão clínica; G = agregados autorizados; P = plataforma. `—` = negado. Um usuário com múltiplos papéis soma permissões, mantendo as restrições de habilitação e escopo.

| Ação | Dono | Médico | Secretaria | Gestor | Admin geral |
| --- | --- | --- | --- | --- | --- |
| Configurar organização/colaboradores | A | — | — | A se delegado | P |
| Conceder papel médico | A após validação profissional | — | — | — | P administrativo |
| Cadastrar/editar dados demográficos | A | C | A | A se delegado | Excepcional auditado |
| Agendar/remarcar/cancelar | A | Própria agenda | A | A | Excepcional |
| Configurar disponibilidade | A | Própria agenda | A se delegado | A | Excepcional |
| Ler notas/exames clínicos | Só se também médico e com C | C | — | — | Acesso excepcional justificado |
| Criar/finalizar atendimento | — sem papel médico | C, próprio registro | — | — | — sem habilitação |
| Retificar registro finalizado | — sem papel médico | Autor ou substituto formal autorizado; nunca apagar autoria | — | — | — |
| Anexar documento administrativo | A | C | A | A se delegado | Excepcional |
| Visualizar anexo clínico | Só com C | C | — | — | Excepcional |
| Preparar dados administrativos de documento | A | C | A | — | — |
| Emitir e assinar documento médico | — sem papel médico | Próprio certificado e C | — | — | — |
| Reenviar documento já emitido | A autorizado, sem ler conteúdo | C | A autorizado, sem ler conteúdo | — | Excepcional |
| Financeiro/CRM | A | Próprio escopo ou A delegado | A delegado | A | Excepcional |
| Dashboard clínico individual | Só com C | C | — | — | Excepcional |
| Dashboard agregado gerencial | G | G permitido | Agenda operacional | G | P sem prontuários |
| Chat/resumo clínico de IA | Só com C | C | — | — | — por padrão |
| Resumo administrativo por IA | A permitido | Próprio/A permitido | A permitido | A permitido | — por padrão |
| Admin Django técnico/dj-celery-panel | — | — | — | — | P |
| Gerar convite inicial da plataforma | — | — | — | — | P |

A concessão clínica adicional usa `PatientAccessGrant`, com concedente habilitado, finalidade, paciente, beneficiário, prazo e revogação. Mudança de papel ou vínculo revogado deve impedir novas consultas, downloads e entrega de eventos de streaming; requisições longas revalidam o acesso periodicamente. Administração excepcional registra motivo e duração; não se torna uma permissão invisível permanente.

## 5. Jornadas e estados de interface

### 5.1 Fluxos principais

| Jornada | Sequência e dados essenciais | Falhas relevantes |
| --- | --- | --- |
| Primeira conta | Landing → validar convite → e-mail/senha → CNPJ/razão social → free → confirmar e-mail → clínica criada | Convite usado/expirado, CNPJ já cadastrado, transação revertida |
| Secretaria cadastra e agenda | Buscar duplicidade no tenant → cadastro mínimo → contato autorizado → médico/horário → reservar → confirmar comunicação | Informação desconhecida, CEP indisponível, disputa simultânea do horário |
| Médico atende | Agenda → paciente → história/último atendimento → novo rascunho → revisar dados copiados → exame → conduta → finalizar | Edição concorrente, autosave sem rede, tentativa de finalizar campos sem revisão |
| Médico emite documento | Selecionar tipo → revisar conteúdo e destinatário → habilitar sessão de assinatura → ação “Assinar e emitir” → fila de entrega | PFX inválido, sessão expirada, indisponibilidade de validação da cadeia |
| Paciente recebe | Mensagem neutra → link de documento → verificação por código no contato registrado → download | Token expirado/revogado, tentativas excedidas, contato incorreto |
| Médico usa IA | Acionar análise → continuar atendimento → receber notificação → revisar fonte/resultado → aceitar/editar/rejeitar | Conteúdo não anonimizável, quota, provedor indisponível, saída inválida |
| Gestor acompanha | Selecionar período/médicos → indicadores com definições → exportar permitido | Dados insuficientes para estatística, exportação grande em fila |

### 5.2 Regras comuns de interface

Cada tela implementa: vazio útil, carregamento, dados preenchidos, erros por campo, permissão negada, conflito de versão e falha recuperável. Ações em fila mostram texto como “Análise em andamento. Você será avisado quando estiver pronta”, sem bloquear navegação. Falha de autosave deve ser visível; o aplicativo não pode mostrar “Salvo” antes da confirmação do servidor.

Por padrão, formulários clínicos não mantêm dados identificados em localStorage. Recuperação de rascunho usa gravação no servidor e estado em memória da aba; após perda de sessão, autenticar antes de recuperar. Upload e captura devem exibir sempre nome e data de nascimento do paciente selecionado antes da confirmação.

## 6. Requisitos funcionais e critérios de aceite

### 6.0 Contrato comum

Salvo rotas públicas expressamente indicadas, cada requisito exige usuário autenticado, vínculo ativo, tenant válido, permissão da ação e versão atual do objeto quando houver edição. Identificadores estrangeiros são resolvidos dentro do escopo autorizado. Falhas retornam mensagem pt-BR, não vazam dados de terceiros e não deixam alteração parcial. Concorrência retorna conflito recuperável (HTTP 409); formulário inválido não grava; acesso a objeto fora do escopo retorna 404. Os critérios abaixo são roteiros manuais a marcar somente na implementação.

### RF-01 — Acesso e onboarding

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-01.01 | Landing em `/`, login e criação de conta; apenas free clicável, sem cartão; demais planos “Em breve” | Plano free; outros apenas apresentação | H-01 |
| RF-01.02 | Convite inicial com 32 bytes aleatórios, hash, expiração padrão 7 dias e uso único; validar/consumir com bloqueio transacional | issued → consumed/expired/revoked | H-01 |
| RF-01.03 | Criar usuário, organização e membership owner numa transação; e-mail já existente exige login e vinculação autorizada | CNPJ validado e razão social obrigatórios | H-01 |
| RF-01.04 | Login por e-mail, recuperação nativa sem enumeração e confirmação de e-mail antes de acesso clínico | Tokens temporários e estado ativo | H-02 |
| RF-01.05 | Owner administra colaboradores; convite interno não cria nova organização; revogação de membership encerra acesso ao tenant | Papéis independentes por clínica | H-02/H-03 |

- [ ] RF-01-A: convite inválido/expirado/usado impede criação; duas submissões simultâneas não consomem o convite duas vezes.
- [ ] RF-01-B: plano free permite acesso sem pagamento; recuperação de senha não confirma se o e-mail existe.

### RF-02 — Pacientes e catálogos

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-02.01 | Cadastro com campos da seção 9.3, máscaras e obrigatoriedade condicional; paciente sem CPF pode ser cadastrado | active/archived; nunca exclusão de história por arquivamento | H-04 |
| RF-02.02 | Pesquisa paginada por nome/documento/contato, autocomplete scoped e alerta de possível duplicidade dentro do tenant | CPF único quando preenchido no tenant | H-03/H-04 |
| RF-02.03 | Consulta de CEP envia somente CEP; timeout 3 s e preenchimento manual; nunca sobrescrever complemento sem ação | Endereço com proveniência de consulta | H-04 |
| RF-02.04 | Medições com data, unidade e IMC calculado; idade calculada na data de referência | kg, m; Decimal; validade clínica sem diagnóstico automático | H-04 |
| RF-02.05 | Operadoras, planos e particular; importação versionada TUSS/CID-10 com origem e revisão de carga | Registro clínico guarda código/descrição históricos | H-05 |

- [ ] RF-02-A: cadastro de menor com CPF ausente e responsável funciona; falha do CEP não bloqueia salvamento.
- [ ] RF-02-B: busca, autocomplete e alerta de duplicidade não revelam pacientes de outra clínica; atualização de catálogo não reescreve registros históricos.

### RF-03 — Prontuário e atendimento

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-03.01 | Linha do tempo com atendimentos, documentos e anexos autorizados; atendimento é entidade própria | draft/in_progress/finalized; retificação em nova entidade | H-06 |
| RF-03.02 | Queixa, HMA, antecedentes pessoais/familiares e consanguinidade; texto estruturado e livre | Versão de formulário registrada | H-06 |
| RF-03.03 | Exame da seção 11 com lateridade e estados não avaliado/não informado/normal/alterado | Nenhum achado normal automaticamente | H-06 |
| RF-03.04 | Copiar conduta, hipóteses e informações de exames do último atendimento finalizado do mesmo médico e tenant, anterior ao atual; origem alternativa requer seleção explícita autorizada | Proveniência por campo; revisão obrigatória | H-06 |
| RF-03.05 | Autosave após 2 s sem digitação; controle de versão otimista; finalização explícita pelo médico | row_version; autor/data; hash do conteúdo final | H-06/H-07 |
| RF-03.06 | Registro finalizado é imutável; correção por adendo assinado/identificado, com justificativa e vínculo | Original sempre preservado | H-07 |

- [ ] RF-03-A: campo vazio não aparece como normal; copiar conduta não emite receita ou pedido automaticamente.
- [ ] RF-03-B: duas abas com versões antigas geram conflito visível; adendo não altera o documento original.

### RF-04 — Documentos e assinatura

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-04.01 | Receitas, relatórios, pedidos e encaminhamentos com templates e revisão médica | draft → ready_to_sign → signing → issued/failed | H-08 |
| RF-04.02 | PFX A1 do próprio médico, protegido conforme seção 12; validar titular/cadeia e modalidade | Credential active/expired/revoked | H-08 |
| RF-04.03 | Sessão de 2/4/6/12 horas, MFA, escopo usuário/tenant e revogação; assinatura exige clique médico por documento | AuthorizationSession com expiração no servidor | H-08 |
| RF-04.04 | Emissão somente após assinatura válida quando exigida; hash/versionamento e documento imutável | Nova correção referencia documento anterior | H-08 |
| RF-04.05 | Evento document.issued cria entregas por canais válidos habilitados, em transação/outbox | Não entregar documento cuja assinatura falhou | H-09 |

- [ ] RF-04-A: expirar a sessão impede novas assinaturas e não invalida artificialmente documentos já emitidos.
- [ ] RF-04-B: secretária/gestor/IA não conseguem assinar; falha do certificado mantém o documento não emitido.

### RF-05 — Anexos e captura

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-05.01 | Upload de PDF, JPEG, PNG, TIFF e DOCX, até 25 MiB por arquivo e 100 páginas em processamento; formatos adicionais exigem aprovação | quarantined → available/rejected; quotas por tenant | H-10 |
| RF-05.02 | Validar extensão/MIME/conteúdo, verificar malware e converter preview em isolamento; nenhum original disponível antes da aprovação | Hash, tamanho, tipo real, uploader e patient/encounter | H-10 |
| RF-05.03 | Download autenticado por objeto; sem rota pública de media; arquivos administrativos e clínicos possuem classes distintas | Auditoria inclusive negação | H-03/H-10 |
| RF-05.04 | Sessão de captura pareada com agente local; importação automática vinculada ao paciente selecionado; upload manual alternativo | open → receiving → completed/expired/cancelled | H-11 |

- [ ] RF-05-A: URL conhecida de outra clínica não fornece bytes; arquivo em quarentena não pode ser baixado pelo fluxo comum.
- [ ] RF-05-B: trocar de paciente encerra ou exige novo pareamento da captura; arquivo anterior não migra para paciente novo.

### RF-06 — Agenda e secretaria

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-06.01 | Calendário dia/semana/mês, médico, duração e disponibilidade; atalhos em teclado e lista móvel | Instantes armazenados com timezone | H-12 |
| RF-06.02 | Disponibilidade semanal, duração por tipo, intervalos, bloqueios, férias e exceções específicas por data | Exceção de data prevalece sobre regra semanal | H-12 |
| RF-06.03 | Reserva transacional, remarcação atômica e prevenção de sobreposição; encaixe exige permissão e justificativa | Estado e intervalo ocupado explícitos | H-12 |
| RF-06.04 | Confirmação, chegada, atendimento, término, cancelamento e falta; lembretes padrão 24 h e 2 h configuráveis | Outbox invalida lembrete de versão antiga | H-09/H-12 |
| RF-06.05 | Painel administrativo com próximos pacientes, pendências e contatos; sem notas clínicas | Visão por tenant e médico | H-03/H-12 |

- [ ] RF-06-A: duas reservas simultâneas para o mesmo horário produzem no máximo uma reserva comum confirmada.
- [ ] RF-06-B: remarcar invalida lembrete antigo; falta não é lançada antes de terminar o período de tolerância configurado.

### RF-07 — CRM

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-07.01 | Grid/kanban com filtros, responsável, prazo e histórico; etapas iniciais contato, agendamento pendente, agendado, acompanhamento e concluído | Colunas configuráveis sem semântica clínica | H-13 |
| RF-07.02 | Movimentação registra ator/estado anterior; integração com agenda por evento explícito | Card não finaliza atendimento nem emite documentos | H-13 |

- [ ] RF-07-A: arrastar card não altera prontuário; card administrativo não mostra diagnóstico ou exame sensível.

### RF-08 — Financeiro

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-08.01 | Valores por plano/médico/procedimento ou particular, com vigência e sem sobreposição de regras equivalentes | Histórico de tabela de preços | H-14 |
| RF-08.02 | Atendimento gera previsão idempotente; usuário autorizado confirma cobrança/recebimento | pending/partial/paid/cancelled | H-14 |
| RF-08.03 | Recebimentos parciais, ajustes e estornos são registros separados; Decimal BRL | Valor líquido = total de recebimentos menos estornos | H-14 |
| RF-08.04 | Visões por competência e caixa claramente separadas; exportação permitida | Sem gateway ou contabilidade fiscal | H-14/H-15 |

- [ ] RF-08-A: mudança no preço futuro não altera valor de consulta passada; reprocessar evento não duplica lançamento.
- [ ] RF-08-B: parcial e estorno conciliam com saldo em aberto; não há acesso a HMA pela tela financeira.

### RF-09 — Comunicação

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-09.01 | Backend nativo de e-mail Django e SMSDEV via POST/JSON; execução em worker | Estados separados para aceitação e entrega confirmada | H-09 |
| RF-09.02 | Mensagem neutra, link opaco e acesso por código; validade inicial de link 7 dias e revogação | Código 8 dígitos, 10 min, até 5 tentativas | H-09 |
| RF-09.03 | Se ambos os canais válidos estiverem habilitados, enviar ambos; canal ausente vira pendência | Responsável legal/contato autorizado registrado | H-09 |
| RF-09.04 | Retries e reconciliação sem alegar exactly-once no provedor; timeout ambíguo vira unknown até conciliar | Idempotency key local e refer no SMSDEV | H-09 |

- [ ] RF-09-A: mensagem não inclui diagnóstico, nome de medicamento ou CPF; token revogado/expirado não acessa documento.
- [ ] RF-09-B: sucesso HTTP no envio não aparece como “entregue” sem evidência do canal.

### RF-10 — Relatórios e análise

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-10.01 | Dashboard e relatórios com fórmulas da seção 13, filtros e origem dos dados | Janela temporal explícita | H-15 |
| RF-10.02 | Exportações CSV/PDF, síncronas até 1.000 linhas/5 s; acima disso, fila | Arquivo privado, expiração 24 h para exportações transitórias | H-15 |
| RF-10.03 | Sanitizar CSV contra fórmulas; agregar localização/diagnósticos conforme permissão | Supressão de células pequenas em visão gerencial | H-15 |
| RF-10.04 | Inferência apenas em relatório analítico previamente definido, com revisão metodológica | Sem p-valor automático por mudança de filtro | H-16 |

- [ ] RF-10-A: denominadores e ausentes aparecem; filtro clínico não amplia permissão do gestor.
- [ ] RF-10-B: conjunto inadequado recebe “análise inferencial indisponível” com motivo, sem resultado fabricado.

### RF-11 — IA e chat

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-11.01 | Análise assíncrona ao finalizar atendimento, quando política/tenant habilitados; rascunho separado do registro clínico | clinical_review: pending/accepted/edited/rejected | H-17 |
| RF-11.02 | Resumir paciente, exames e registros administrativos autorizados; consultar apenas dados pertinentes | Proveniência e versão da fonte | H-17 |
| RF-11.03 | Sessões de chat por usuário/tenant, paciente explicitamente selecionado e histórico persistente | Sem transferência de memória entre contextos | H-18 |
| RF-11.04 | Streaming real por SSE, Markdown sanitizado, cancelamento e reconexão | Eventos sequenciais com escopo e expiração | H-18 |
| RF-11.05 | Hipóteses qualitativas fundamentadas; faltantes, limites e aviso de avaliação médica | Sem probabilidade diagnóstica numérica não calibrada | H-17 |
| RF-11.06 | Desidentificação local e bloqueio quando risco residual não satisfaz política | disabled/blocked_privacy/queued/running/succeeded/failed/cancelled/stale | H-17 |

- [ ] RF-11-A: conteúdo não autorizado não chega ao modelo; instrução maliciosa em anexo não muda as tools permitidas.
- [ ] RF-11-B: resultado de IA só entra como conteúdo clínico após revisão identificada; revogar acesso encerra novas entregas de streaming.

### RF-12 — Admin, demonstração e documentação

| ID | Regra implementável | Dados/estado | Aceite |
| --- | --- | --- | --- |
| RF-12.01 | Admin para entidades e dj-celery-panel somente para administração técnica; mascarar argumentos/resultados/configuração | Sem delegar painel global à clínica | H-19 |
| RF-12.02 | `seed_demo` idempotente com múltiplos tenants, datas, perfis, consultas, documentos sintéticos e falhas controladas | Sem envio real, sem PFX real; demo bloqueada em produção por padrão | H-20 |
| RF-12.03 | MkDocs em docs/, Mermaid, operação e guias sempre atualizados | Conteúdo técnico online somente para staff técnico | H-19 |

- [ ] RF-12-A: repetir seed não duplica registros; seus jobs não disparam mensagens reais.
- [ ] RF-12-B: documentação protegida e painel técnico não expõem dados por URL direta.

## 7. Requisitos técnicos e não funcionais

Os IDs RT-01 a RT-10 preservam os grupos do prompt de origem. As metas abaixo ampliam RNF-01 em critérios operacionais.

| ID | Obrigação e métrica | Meta proposta/critério |
| --- | --- | --- |
| RT-01 | Python/Django, estrutura e simplicidade | Um settings.py; apps na raiz; código em inglês/PEP 8/aspas simples; nenhum teste automatizado |
| RT-02 | Tenancy em toda via de acesso | Escopo negado por padrão e nenhum relacionamento cruzado permitido |
| RT-03 | Privacidade e integridade | Mídia privada; dados finais imutáveis; auditoria; secrets protegidos |
| RT-04 | IA | LangChain/LangGraph, tools limitadas, validação de saída, revisão humana e bloqueio de dados inadequados |
| RT-05 | Infraestrutura | Sete serviços permanentes; três redes; volumes persistentes; placement de dados |
| RT-06 | Configuração | Parser literal; Docker Secrets; django-environ; hosts/origins corretos |
| RT-07 | TLS/proxy | Traefik Swarm, DNS-01 Cloudflare, domínio+wildcard, proxy confiável |
| RT-08 | Saúde e coordenação | Healthchecks de todos os serviços; dependências/schema; migrations com lock; beat único |
| RT-09 | Release | Imagem por digest, rollout coordenado, estáticos por release, rollback compatível |
| RT-10 | Operação | Deploy/skip-build e backup/restore documentados, falhas detectáveis |
| RNF-01.01 | Latência de navegação | p95 até 800 ms no servidor para páginas comuns, 20 usuários concorrentes, 50 mil pacientes/500 mil atendimentos sintéticos; medição pendente |
| RNF-01.02 | Busca/autocomplete | p95 até 500 ms; debounce 300 ms; mínimo 2 caracteres; até 20 sugestões |
| RNF-01.03 | Autosave | Confirmação até 1 s após request em condições normais; feedback explícito em falha |
| RNF-01.04 | Filas | Enfileiramento até 500 ms; atraso >60 s em fila interativa gera alerta; não garante duração da API |
| RNF-01.05 | Disponibilidade | Meta mensal de 99,5% no piloto, medição externa; sem garantia contratual/HA de host |
| RNF-01.06 | Recuperação | RPO proposto 24 h, RTO 4 h, sujeitos a restauração medida; antes disso são metas |
| RNF-01.07 | Segurança de transporte | TLS externo, backend não exposto; overlay interno único host; expansão multinó exige proteção da rede e revisão TLS interno |
| RNF-01.08 | Recursos | Sem swap como estratégia de capacidade; alertas disco 75%/85%, RAM sustentada 85%, fila e backups |
| RNF-01.09 | Acessibilidade | Navegação por teclado, foco, rótulos, erros associados; meta WCAG 2.2 AA, validação manual e design pendente |
| RNF-01.10 | Retenção transitória | Cache até 15 min; eventos SSE até 1 h; result backend até 24 h; exportação transitória até 24 h |

Medição de desempenho na homologação usa observação e ferramentas operacionais, sem criar uma suíte automatizada. Registrar hardware, tamanho de base, concorrência e percentis; qualquer afirmação de desempenho precisa dessa evidência.

## 8. Arquitetura, apps e versões

### 8.1 Organização

Monólito modular Django, PostgreSQL compartilhado, Celery separado para trabalho pesado e SSR com Django Templates. Services concentram transações de negócio; selectors/QuerySets recebem contexto autorizado; views não decidem regras clínicas de forma isolada. Signals, quando necessários, ficam no app correspondente e não substituem o fluxo explícito de emissão, assinatura ou pagamento.

| Caminho/app | Responsabilidade | Entidades principais |
| --- | --- | --- |
| `core/` | settings único, URLs, ASGI, Celery e leitura central de configuração | Sem models de negócio |
| `base/` | Timestamps, erros de domínio, validação comum, commands operacionais | Primitivas pequenas |
| `accounts/` | Usuário global, MFA, perfil profissional e recuperação | User, PhysicianProfile |
| `tenancy/` | Clínicas, vínculos, convites, domínio e concessões | Tenant, Membership, Invitation, PatientAccessGrant |
| `patients/` | Demografia, contatos autorizados e medições | Patient, PatientContact, Observation |
| `catalogs/` | CID-10/TUSS e versões globais de referência | CatalogRelease, DiagnosisCode, ProcedureCode |
| `clinical/` | Prontuário, atendimentos, achados e retificações | Encounter, ClinicalAmendment, ExaminationFinding |
| `scheduling/` | Agenda, disponibilidade e ocupação de slots | AvailabilityRule, ScheduleBlock, Appointment |
| `documents/` | Arquivos privados, geração, assinatura e entrega autorizada | Attachment, MedicalDocument, SigningCredential, SigningSession |
| `communications/` | E-mail, SMSDEV, links/códigos e status | Delivery, DeliveryAttempt, DocumentAccessToken |
| `crm/` | Kanban, etapas e histórico administrativo | CRMStage, CRMCard, CRMTransition |
| `finance/` | Tabela de valores, lançamentos e recebimentos | FeeSchedule, Receivable, Payment, FinancialAdjustment |
| `ai/` | Adaptadores, grafos, tools, política de dados e artefatos | AIJob, AIArtifact, ChatSession, ChatMessage |
| `notifications/` | Caixa interna e leitura de notificações | Notification |
| `audit/` | Auditoria de acesso e mudanças | AuditEvent |
| `reporting/` | Indicadores, exportações e relatórios elegíveis | ReportJob, ReportDefinition |
| `integrations/` | CEP e ponte de captura; conectores pequenos compartilhados | CaptureSession, CaptureDevice |
| `events/` | Outbox e estado de processamento idempotente | OutboxEvent, ProcessedEvent |
| `templates/`, `static/` | Componentes e assets do design system | Apenas arquivos públicos de interface |
| `docs/`, `mkdocs.yml` | Documentação publicada com controle de acesso | Markdown e Mermaid |
| `ops/`, `scripts/` | Entrada dos serviços, geração do stack, deploy e backup | Anexos operacionais deste PRD |

Não criar tabelas para “cliente”, “corretora” ou “sinistro”. Em inglês de código, usar `patient`, `tenant`, `encounter`, `document` e `appointment`. Django Admin técnico usa filtros explícitos, mas a aplicação clínica/administrativa possui telas próprias e permissões por tenant.

```mermaid
flowchart TB
  B["Navegador"] --> T["Traefik e TLS"]
  T --> A["Django ASGI"]
  A --> P["PostgreSQL"]
  A --> Q["RabbitMQ"]
  Q --> W["Celery worker"]
  W --> P
  W --> R["Redis: estado transitório"]
  R --> A
  W --> E["IA, SMTP e SMSDEV"]
```

### 8.2 Matriz de versões

Os números abaixo foram encontrados nas fontes indicadas. Isso confirma disponibilidade/documentação, não equivale à execução da stack conjunta. As tags Docker devem ser resolvidas para digests pelo procedimento de release; se uma tag não existir para a arquitetura selecionada, o deploy para antes de modificar serviços.

| Componente | Baseline selecionada | Evidência e observação |
| --- | --- | --- |
| Ubuntu VPS | 24.04 LTS amd64 | [Docker no Ubuntu](https://docs.docker.com/engine/install/ubuntu/) lista suporte; escolha conservadora para o guia |
| Python | 3.14.7 | [Python Downloads](https://www.python.org/downloads/); atende `>3.13` sem ambiguidade de patch |
| Django | 6.1.1 | [Download oficial](https://www.djangoproject.com/download/); [matriz Python](https://docs.djangoproject.com/en/6.1/faq/install/) inclui 3.14 |
| LangChain | 1.4.0 | [PyPI do projeto](https://pypi.org/project/langchain/); atende `>1.0` |
| LangGraph | 1.2.11 | [PyPI do projeto](https://pypi.org/project/langgraph/) |
| Celery | 5.6.3 | [PyPI](https://pypi.org/project/celery/); suporte inicial a Python 3.14 documentado na [linha 5.6](https://docs.celeryq.dev/en/v5.6.3/history/changelog-5.6.html) |
| dj-celery-panel | 0.6.0 | [Metadados do projeto](https://pypi.org/project/dj-celery-panel/) incluem Django 6.1/Python 3.14; validar painel e mascaramento |
| PostgreSQL | 17.11 | [Política de versões](https://www.postgresql.org/support/versioning/); imagem candidata `postgres:17.11-bookworm` |
| RabbitMQ | 4.3.5 | [Releases](https://www.rabbitmq.com/release-information); usar imagem sem management público; revisão de suporte antes de novembro/2026 |
| Redis | 8.10.1 | [Releases oficiais](https://github.com/redis/redis/releases); avaliar licenciamento aplicável à distribuição escolhida |
| Traefik | 3.7.12 | [Release oficial](https://github.com/traefik/traefik/releases/tag/v3.7.12); provider `swarm`, não exemplos legados de Docker swarmMode |
| Docker Engine | 29.8.0 como candidato do guia | [Instrução oficial Ubuntu](https://docs.docker.com/engine/install/ubuntu/); verificar versão disponível no repositório e fixá-la |
| Compose plugin | Versão estável do repositório Docker, registrada no primeiro provisionamento | Não foi resolvida uma versão exata nesta execução; S01 registra e fixa pacote |
| WhiteNoise | 6.12.0 | [Documentação](https://whitenoise.readthedocs.io/en/stable/django.html) |
| ReportLab / pypdf | Resolver faixas estáveis do anexo de dependências | Geração/manipulação; não são a solução de assinatura |
| pyHanko | Resolver versão estável e homologar PAdES | [Documentação do projeto](https://docs.pyhanko.eu/en/latest/); cabeçalho de documentação não foi tomado como número de release |
| django-environ, psycopg, Uvicorn, redis-py, HTTPX, Pydantic, MFA, sanitização e MkDocs | Resolver conjuntamente em S01 e congelar no requirements.txt | Compatibilidade conjunta pendente; não existe lock fictício neste documento |
| Modelo padrão | `z-ai/glm-5.3-flash` via OpenRouter | [Página do modelo](https://openrouter.ai/z-ai/glm-5.3-flash); validar recursos e provedor final por configuração |

Interpretação dos limites originais: adota-se uma série posterior a 3.13 para Python e posterior a 6.0 para Django; não se utiliza `>=` para relaxar a exigência. `requirements.in` fixa os seis pacotes centrais verificados e define faixas para os demais. O comando de resolução do guia produz `requirements.txt` com versões exatas e hashes; esse arquivo deve ser revisado, commitado e atualizado a cada alteração. O build recusa ausência de lock.

## 9. Modelagem de dados

### 9.1 Convenções e invariantes

Models próprios têm `id: UUID` como chave primária, `created_at` e `updated_at: timestamptz` automáticos e `row_version: bigint` para objetos editáveis. Nos registros imutáveis, `updated_at` permanece igual ao último evento permitido; imutabilidade é regra de autorização e integridade, não ausência do campo. Relações explícitas também possuem timestamps. Tabelas internas Django/Celery/LangGraph não serão modificadas para satisfazer essa convenção.

`TenantModel` acrescenta `tenant_id: FK(Tenant, PROTECT), NOT NULL`. Cada model de domínio na tabela 9.4 é tenant-scoped, salvo marcado GLOBAL. `created_by`/`updated_by` apontam para usuário quando houver ação humana; processos registram service actor e initiating_user quando disponível. Nenhum `CASCADE` deve apagar prontuário, assinatura, auditoria ou financeiro por exclusão de usuário/paciente.

Relações para pacientes, encontros, documentos e memberships são validadas no service transacional. Além disso, FKs sensíveis terão garantia no banco por chave composta `(tenant_id, referenced_id)` referenciando unicidade `(tenant_id, id)` da entidade destino, criada por migration explícita compatível com Django. A FK simples permanece útil ao ORM; o SQL de garantia composta é mantido por migration reversível. Assim, operações bulk não abrem uma exceção de isolamento. Alternativa sem essa garantia não atende ao aceite de RT-02.

Índices comuns: `(tenant_id, created_at)`, `(tenant_id, status)` e índices das buscas indicadas por entidade. Páginas usam ordenação estável com ID como desempate. Datas clínicas têm contexto explícito: data do fato, data de registro e timezone de apresentação.

### 9.2 Identidade e acesso

| Model | Campos específicos e obrigatoriedade | Constraints/índices/regras |
| --- | --- | --- |
| User — GLOBAL | email EmailField obrigatório; password hash nativo; first_name/last_name; is_active; is_staff; is_superuser; email_verified_at opcional | AbstractUser customizado com username removido; email normalizado em minúsculas por decisão do produto e unicidade com Lower(email); nunca senha em texto |
| PhysicianProfile — GLOBAL | user OneToOne; professional_name; crm_number; crm_state(2); rqe opcional; professional_phone/email/address; verification_status | CRM/UF únicos; validação administrativa não substitui consulta a situação profissional quando exigida |
| Tenant — GLOBAL | legal_name(255); trade_name opcional; cnpj(14); slug(63); status; plan='free'; timezone; settings JSON validado | CNPJ único; slug único, sem palavras reservadas; settings sem credenciais |
| TenantDomain — GLOBAL | tenant FK; hostname; verified_at; is_primary | Hostname único, normalizado; apenas domínio autorizado |
| Membership | user FK; roles ArrayField de choices; status; invited_by; activated_at/revoked_at | Unique(tenant,user); roles permitidos fixos; médico exige perfil profissional válido |
| Invitation — GLOBAL | token_hash; purpose(platform/collaborator); target_tenant opcional; email_binding opcional; role_grants; expires_at; consumed_at; consumed_by; revoked_at; issued_by | Propósito define quem pode emitir; consumo com select_for_update; nenhum token bruto persistido |
| PatientAccessGrant | patient FK; beneficiary_membership; permission_set; reason; granted_by; expires_at opcional; revoked_at | Todas as FKs no mesmo tenant; não conceder assinatura de outro profissional |
| MFADevice — biblioteca + registro próprio de vínculo | dispositivo TOTP, usuário e estado; WebAuthn não integra esta baseline | Segredos de MFA protegidos; nenhuma chave compartilhada por clínica |

| RecoveryCode — GLOBAL | user FK; code_hash Char(255); used_at DateTime nullable; expires_at DateTime nullable | Código apresentado uma vez, hash com salt, consumo transacional; não usar otp_static com token bruto |

### 9.3 Dicionário do cadastro de paciente

Campos “condicionais” têm justificativa visível e não impedem o atendimento quando legitimamente desconhecidos. Pessoa sem documento recebe ID interno; nunca usar CPF fictício para passar validação.

| Interface | Código/tipo | Obrigatoriedade e validação | Edição/visibilidade |
| --- | --- | --- | --- |
| Nome completo | full_name Char(255) | Obrigatório, sem espaços vazios; aceitar nomes reais diversos | Cadastro A/C |
| Nascimento | birth_date Date nullable | Obrigatório se conhecido; caso desconhecido, reason + estimated_birth_year opcionais; não aceitar futuro | A/C; idade calculada |
| Sexo informado | sex_at_registration choice nullable | Feminino/masculino/intersexo/não informado; registrar finalidade clínica; não inferir identidade de gênero | A/C |
| CPF | cpf Char(11) nullable | Dígitos verificadores, único no tenant quando presente | Mascarado fora da edição autorizada |
| RG | identity_number Char(30) nullable | Formato livre controlado, órgão/UF opcionais | A/C |
| Nome da mãe | mother_name Char(255) nullable | Opcional | A/C |
| CEP | postal_code Char(8) nullable | Somente dígitos, consulta ViaCEP com limite e timeout | A/C |
| Endereço | street(255), number(30), complement(100), district(100), city(100), state(2), country(2='BR') | Opcional; município/UF consistentes quando conhecidos | A/C; gerencial somente agregado |
| Telefone | PatientContact.phone E.164 nullable | Validar formato; não fabricar telefone de demo | A/C; somente contato autorizado recebe |
| E-mail | PatientContact.email nullable | Validar sintaxe e confirmação do canal | A/C |
| Quem indicou | referral_source choice + referral_details(255) | Opções paciente/médico/internet/plano/outro/não informado | A/C |
| Peso | Observation(weight_kg) Decimal(6,2) | Positivo, data de medição; limites geram alerta de conferência, não diagnóstico | Cadastro da medida e acesso clínico |
| Altura | Observation(height_m) Decimal(4,2) | Positiva, unidade em metros e data | Igual ao peso |
| IMC | Valor calculado | peso_kg / altura_m², apresentar uma casa decimal; não misturar medidas históricas sem informar datas | Somente leitura derivada |
| Estado civil | marital_status choice nullable | Solteiro/casado/união estável/divorciado/viúvo/outro/não informado | A/C |
| Profissão | occupation Char(150) nullable | Opcional | A/C |
| Pagamento | payment_category choice | Particular/plano; plano obrigatório somente quando categoria plano | A/C administrativo |
| Plano | active_coverage FK nullable | Elegível no tenant; matrícula e validade opcionais em PatientCoverage | A/C administrativo |
| Médico responsável | responsible_membership FK | Obrigatório para abrir atendimento; pode permanecer pendente no pré-cadastro | Membership com papel doctor no tenant |
| Observações administrativas | administrative_notes Text | Opcional; instrução explícita para não registrar história clínica aqui | A autorizado |
| Contato responsável | PatientContact relationship, legal_authority, authority_evidence | Condicional para menor/incapaz/representante autorizado | Registro de finalidade, vigência e canal |

O cadastro demográfico não concentra medidas repetidas ou notas clínicas. Os componentes mostram as medidas mais recentes com data, sem substituir a série histórica.

### 9.4 Entidades clínicas e operacionais

Todas as linhas abaixo herdam campos comuns e tenant, salvo GLOBAL. O conteúdo JSON tem schema versionado e validação no service; não é um depósito livre para contornar modelagem.

| Model | Campos específicos essenciais | Garantias e índices |
| --- | --- | --- |
| Patient | Campos demográficos de 9.3; responsible_membership; status; archived_at/reason | Unique condicional(tenant,cpf); índice nome normalizado por tenant; PROTECT história |
| PatientContact | patient; name; relationship; phone/email; verified_phone_at/email_at; authorized_for_documents; sms_enabled/email_enabled; valid_until | Mesmo tenant; confirmação de canal e representante; histórico de alteração |
| Observation | patient; encounter opcional; kind; numeric_value Decimal; unit; observed_at; source | Índice(tenant,patient,kind,observed_at); valor positivo para peso/altura |
| Insurer | name; ans_registration opcional; active | Mesmo tenant; duplicidade normalizada |
| HealthPlan | insurer; name; active; administrative_notes | Unique(tenant,insurer,name) |
| PatientCoverage | patient; plan; member_number; starts_on/ends_on | Não alterar retroativamente cobertura usada no atendimento |
| CatalogRelease — GLOBAL | system(CID10/TUSS); version; source_url; imported_at; content_sha256; license_note; status | Importação auditada; não presumir que TUSS e Rol ANS são equivalentes |
| DiagnosisCode / ProcedureCode — GLOBAL | release FK; code; description; parent_code opcional; active | Unique(release,code); codes referenciados não apagados |
| Encounter | patient; physician_membership; appointment opcional; occurred_at; chief_complaint; hpi; personal_history; family_history; consanguinity_state; consanguinity_details; plan_text; status; finalized_at/by; content_hash | Índice(tenant,patient,occurred_at); texto de fechamento imutável |
| EncounterDiagnosis | encounter; diagnosis_code opcional; code_snapshot; description_snapshot; certainty(suspected/confirmed/refuted); rank; physician_note | Não confundir certainty clínica com output do LLM; tenant igual |
| ComplementaryExam | patient; encounter opcional; procedure_code opcional; title; requested_at/performed_at; result_text; status; attachment FK opcional | Exame prévio não vira novo pedido por cópia |
| ExaminationFinding | encounter; domain; item_code; side; body_site; state; numeric_value opcional; qualifier; note; schema_version | Unique(tenant,encounter,item_code,side,body_site) com normalização de ausentes; evidências por item |
| CarryForwardItem | target_encounter; source_encounter; field_path; source_version/hash; copied_value; reviewed_at/by; review_action | Unicidade de campo/origem; bloqueia finalização se revisão pendente |
| ClinicalAmendment | encounter; author; reason; text; signed_document opcional; authored_at | Append-only; nunca substituir original |
| AvailabilityRule | physician_membership; weekday; local_start/local_end; starts_on/ends_on; slot_minutes; buffer_minutes; appointment_type | Intervalo positivo, sem vigências contraditórias |
| ScheduleBlock | physician_membership; start_at/end_at; kind; reason; override_rule | Exceção de data prevalece; impedir reserva comum em bloqueio |
| Appointment | patient; physician_membership; starts_at/ends_at; occupied_range; status; type; is_overbook; override_reason/by; version; cancellation_reason | ExclusionConstraint para reserva normal; índices(tenant,physician,starts_at), (tenant,status,starts_at) |
| Attachment | patient; encounter opcional; storage_key; original_name; mime; bytes; sha256; classification; scan_status; uploaded_by; document_date; encryption_metadata | Chave opaca não é permissão; sem caminho controlado pelo cliente; original imutável |
| MedicalDocument | patient; encounter; physician; document_number Char(64); version PositiveInteger; kind; template_version; content_snapshot; pdf_attachment; signed_pdf_attachment; status; issued_at; signature_metadata; replaces_document opcional | Unique(tenant,document_number); preservar bytes assinados; issuer explícito |
| SigningCredential | physician; ciphertext_path; wrapped_key_metadata; certificate_serial/fingerprint; issuer; not_before/not_after; status | Não persistir senha PFX; separado de media; acesso apenas próprio autorizado |
| SigningSession | physician; membership; expires_at; revoked_at; mfa_at; session_binding_hash; encrypted_unlock_material; ephemeral_key_id | TTL no servidor, artefato de desbloqueio transitório cifrado; nunca senha/chave em plaintext |
| DocumentAccessToken | document; contact; token_hash; expires_at; revoked_at; last_access_at; otp_hash/expiry/attempts | Código e token com hash; erro genérico e limite por token/IP |
| Delivery | document ou appointment; contact; channel; event_version; status; provider_id; idempotency_key; next_attempt_at | Unique(tenant,idempotency_key); conteúdo mínimo e destino protegido |
| DeliveryAttempt | delivery; attempt_number; started_at/ended_at; outcome; provider_code; sanitized_error | Append-only; não guardar API key/body clínico |
| CRMStage | name; order; active; color_token | Token do design system; mesmo tenant |
| CRMCard | patient; appointment opcional; stage; assigned_membership; due_at; administrative_summary | Histórico separado; sem diagnóstico em texto administrativo |
| CRMTransition | card; from_stage; to_stage; actor; reason | Append-only |
| FeeSchedule | physician; plan nullable; procedure nullable; payment_category; gross_amount; doctor_share_amount; effective_from/to | BRL Decimal(12,2); vigências equivalentes não sobrepostas |
| Receivable | patient; encounter; charge_kind; fee_snapshot; expected_amount; charged_amount; due_date; competence_date; status | Unique origem(tenant,encounter,charge_kind); cancelamento com motivo |
| Payment | receivable; paid_at; amount Decimal(12,2); method; external_reference nullable | Valor positivo; saldo e estado derivados transacionalmente |
| FinancialAdjustment | receivable/payment; type(discount/surcharge/refund/writeoff); amount; reason; approved_by | Não editar pagamento consumado; ajuste auditado |
| AIJob | user; membership; patient/encounter opcionais; kind; source_version/hash; purpose; policy_version; status; limits; task_id; cancel_requested_at | Idempotência de objetivo/versão; nenhum payload clínico no broker |
| AIArtifact | job; schema_version; provider/model; prompt_version; source_refs; result JSON; review_state; reviewer; reviewed_at; supersedes | Conteúdo cifrado quando necessário; aprovação humana rastreada |
| ChatSession | owner_user; tenant; patient opcional; title; status; last_message_at | Unique contexto de owner; troca de paciente cria nova sessão |
| ChatMessage | session; role; content; source_refs; ai_job opcional; state; sequence | Unique(session,sequence); Markdown sanitizado; mensagens preservadas conforme política |
| Notification | user; tenant; kind; target_type/id; sanitized_title; read_at | Não mostrar diagnóstico em toast de tela compartilhada |
| OutboxEvent | topic; aggregate_type/id; event_version; payload_minimal; status; available_at; locked_until; attempts | Chave única de evento; payload apenas IDs e metadados mínimos |
| ProcessedEvent | event; consumer; processed_at | Unique(event,consumer); impede efeito local duplicado |
| AuditEvent | actor; tenant nullable; action; object_type/id; purpose; outcome; request_id; origin_ip_protected; integrity_metadata | Append-only; índice por tenant/data/objeto; retenção própria |
| ReportDefinition | key; version; role_requirements; filters_schema; metric_definition | Fórmulas versionadas; inferência só em definição aprovada |
| ReportJob | user; report_definition; filters; source_cutoff; status; private_attachment; expires_at | Revalidar permissão no download |
| CaptureDevice | tenant; display_name; public_key; status; last_seen_at | Credencial limitada à captura, sem consulta ao prontuário |
| CaptureSession | patient; encounter; device; created_by; token_hash; expires_at; status; next_sequence | Sessão de 15 min renovável por ação; arquivos fora de sessão rejeitados |

```mermaid
erDiagram
  TENANT ||--o{ MEMBERSHIP : possui
  USER ||--o{ MEMBERSHIP : participa
  TENANT ||--o{ PATIENT : registra
  PATIENT ||--o{ ENCOUNTER : recebe
  MEMBERSHIP ||--o{ ENCOUNTER : realiza
  ENCOUNTER ||--o{ MEDICAL_DOCUMENT : gera
  PATIENT ||--o{ ATTACHMENT : possui
```

### 9.5 Tipos e nulabilidade comuns

A notação compacta da tabela 9.4 usa os contratos abaixo; aplicar antes de criar migrations. Relações intermediárias recebem UUID/timestamps próprios. Campos de ação posterior são nullable até o evento, sem preencher data fictícia. Campo clínico vazio não representa exame normal.

| Família de campos | Tipo/limite e obrigatoriedade |
| --- | --- |
| patient, encounter, document, contact, membership, physician_membership, source/target_encounter e referências nomeadas a models | ForeignKey UUID com PROTECT; relações marcadas opcionais são nullable. physician aponta para PhysicianProfile; actor/user/author/reviewer para User; plan para HealthPlan |
| status, kind, type, state, role, certainty, side, domain, payment_category, method, outcome, review_action | CharField até 40 com TextChoices fechado; obrigatório; escolhas e transições das seções funcionais. kind/type não aceita valor arbitrário do cliente |
| *_at, *_until, not_before/not_after e source_cutoff | DateTimeField com timezone; nullable quando evento ainda não ocorreu. expires_at de tokens/sessões é obrigatório; created_at/updated_at sempre preenchidos |
| *_date, document_date, starts_on/ends_on, effective_from/to | DateField; fim de vigência nullable para aberto, início obrigatório; document_date pode ser desconhecida |
| local_start/local_end; weekday; slot_minutes/buffer_minutes | TimeField; PositiveSmallInteger 0–6; PositiveSmallInteger, duração >0/buffer >=0 |
| occupied_range | DateTimeRangeField, [início,fim), não vazio, derivado de intervalo + buffers |
| hpi, chief_complaint, histories, plan_text, result_text, note, reason, administrative_summary | TextField com limites no form/service: 20.000 caracteres por bloco clínico e 2.000 por nota administrativa/motivo; blank permitido em rascunho, regras de finalização aplicadas no service |
| name/title/professional_name; description/snapshot de catálogo; email; telefone | CharField 255; TextField até 4.000; EmailField 254; CharField 16 E.164; nulabilidade de cadastro em 9.3 |
| hash/sha256/token_hash/session_binding_hash/content_hash | CharField 64 para SHA-256 hexadecimal; obrigatório quando o objeto existe, salvo content_hash antes de finalizar; otp_hash usa formato de hash com salt até 255 |
| storage_key/ciphertext_path; original_name; MIME; source_url | CharField 512; CharField 255; CharField 100; URLField 2.048. Caminho nunca vem pronto do cliente |
| idempotency_key, task_id, provider_id, aggregate_type, object_type, consumer | CharField até 255; ID de provedor nullable antes da aceitação; unicidades incluem tenant quando pertinente |
| version/schema_version/prompt_version/policy_version | Versão de schema/política CharField 40; versão de registro/sequence/event_version e contadores PositiveBigInteger; inicial explícito |
| metadata, snapshots estruturados, filters, limits, source_refs, schemas, payload_minimal, result | JSONField com schema versionado, defaults callable dict/list; limites de tamanho; não receber credenciais. Valor copiado pode ser JSON escalar tipado |
| encrypted_unlock_material | BinaryField nullable, ciphertext autenticado; limpar ao revogar. ephemeral_key_id é UUID opaco. Chaves mestras nunca são campo do model |
| monetary *_amount e amount; numeric_value | Decimal(12,2) BRL; Decimal(12,4) para achado genérico, com unidade/validação por kind; medições específicas seguem 9.3 |
| active/is_*/authorized_for_*/sms_enabled/email_enabled | BooleanField, default False salvo estado ativo explicitamente definido na criação |
| object_id/aggregate_id/target_id/request_id | UUIDField; ponte polimórfica validada por whitelist/service; não cria FK genérica que ignore tenant |

Estados adicionais de recuperação: Delivery pode ficar `needs_reconciliation`, OutboxEvent pode ficar `held_restored`; dispatcher só consome estados elegíveis explicitamente, e nunca esses dois. SigningSession.revoked_at é nullable; OTP pode ficar sem hash após revogação. DocumentAccessToken pertence ao app communications, apesar do vínculo ao documento. AuditEvent permite tenant nulo para evento técnico global e origin_ip_protected vazio para command local.

CatalogRelease/DiagnosisCode/ProcedureCode são globais; Insurer/HealthPlan são por tenant. Catálogos usam a [entrada TISS/TUSS da ANS](https://www.gov.br/ans/pt-br/assuntos/prestadores/padrao-para-troca-de-informacao-de-saude-suplementar-2013-tiss) e a [transferência de arquivos DATASUS](https://datasus.saude.gov.br/transferencia-de-arquivos/), com arquivo/versão/licença de cada carga ainda a obter e validar em S03. A consulta de endereço usa [ViaCEP](https://viacep.com.br/), somente CEP de oito dígitos, tratamento de 400/erro e timeout, sem consulta em massa do cadastro.

### 9.6 Regras de consistência e exclusão

A imutabilidade de snapshots finalizados e registros append-only terá triggers no PostgreSQL para os caminhos de DML, além das regras nos services/admin; manutenção extraordinária com privilégios de banco exige procedimento auditado. Arquivar paciente suspende novas rotinas administrativas por padrão, mas não elimina registros. Corrigir duplicidade requer procedimento de merge auditado, dentro do mesmo tenant, com mapa dos IDs de origem e preservação documental; a primeira versão pode restringir merge à operação técnica assistida. Exclusão física depende de política de retenção e bloqueios legais, nunca de um botão genérico no admin.

Valores financeiros são Decimal(12,2), BRL, com quantize de 0,01 e ROUND_HALF_UP por lançamento; somar valores já arredondados e nunca converter para float. Datas de consulta e nascimento não são convertidas indiscriminadamente para strings. Foreign keys para catálogos globais são permitidas, mas nenhuma tabela global contém prontuários ou dados identificadores de pacientes.

## 10. Autenticação, tenancy, auditoria e proteção de dados

### 10.1 Fluxo de autorização

1. Django autentica a sessão; middleware leve exclui somente as rotas públicas enumeradas, e `/health/` é tratado antes de qualquer consulta.
2. Para `/app/`, selecionar tenant da sessão e confirmar Membership ativa; se houver alias de subdomínio, o alias precisa corresponder à organização selecionada.
3. Criar `AccessContext(user_id, tenant_id, membership_id, permissions, request_id)` imutável por requisição; tarefas reconstroem contexto no servidor a partir de IDs persistidos.
4. Selector recebe contexto e aplica filtro tenant antes de procurar o ID do objeto; política por paciente/perfil complementa esse filtro.
5. Service aplica validações, autorização, row_version e transação; banco reforça unicidade, referências e conflitos temporais.
6. Registrar evento de auditoria mínimo. Resposta e qualquer arquivo privado usam `Cache-Control: private, no-store` quando contiverem dados clínicos.

Managers sem contexto não devem retornar todos os registros. Admin, migrations, seed e rotinas globais possuem caminhos explícitos separados e auditados; não obter contexto por variável global mutável ou thread local que possa vazar entre requisições ASGI.

### 10.2 Sessões e proteção do frontend

Cookie de sessão host-only, HttpOnly, Secure em produção e SameSite=Lax; não compartilhar cookie por todos os subdomínios. CSRF em toda mutação; SSE usa GET somente para leitura e POST protegido para iniciar/cancelar jobs. CORS não será aberto para `*`. Links externos em Markdown usam atributos seguros; raw HTML é removido e esquemas como javascript são rejeitados. Não utilizar `mark_safe` sobre saída do LLM.

Política proposta: sessão administrativa de 8 h, bloqueio por inatividade de 30 min, reautenticação para ações críticas. MFA obrigatório para admin da plataforma, owner e médicos que habilitem assinatura. A sessão clínica é independente da autorização temporária de PFX. Login tem limitação por conta+IP e atraso progressivo; recuperação mostra resposta uniforme.

### 10.3 LGPD, sigilo e retenção

Dados de saúde e genéticos recebem tratamento de informação sensível. Remoção de nomes não garante anonimização: considerar associação por outros meios e reversibilidade. Essas distinções decorrem das definições e regras da [LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm). A política específica do NeuroDoc deve ser validada pelo controlador e documentada antes de dados reais; consentimento de comunicação não será usado como justificativa universal para todas as operações.

A clínica normalmente decide finalidades assistenciais; o papel contratual da plataforma e dos provedores depende da operação real, devendo constar no registro de tratamento. Dados enviados por roteadores de IA podem alcançar outros provedores; revisar contratos, localização, retenção e mecanismo aplicável de transferência, à luz da [regulamentação da ANPD](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024).

A [Lei 13.787/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13787.htm) disciplina digitalização/guarda e permite eliminação de prontuários após prazo mínimo de 20 anos a partir do último registro, nas condições previstas. Isso não vira uma rotina automática de apagar todo conteúdo ao atingir 20 anos: outras obrigações, litígios, tipo de documento e política aprovada podem exigir conservação maior.

| Classe | Política inicial proposta | Descarte/acesso |
| --- | --- | --- |
| Prontuário/documentos finais | Preservação conforme regra assistencial e legal validada; sem exclusão automática v1 | Apenas processo formal com retenção/bloqueios avaliados |
| PFX | Até revogação/substituição e política de recuperação | Destruição segura de material autorizado quando aplicável, preservando certificados públicos/evidências |
| Chat clínico usado em decisão | Preservar vínculo ao artefato incorporado e sua proveniência | Não descartar origem necessária à rastreabilidade |
| Chat não incorporado e rascunhos IA | 90 dias propostos, configuráveis após aprovação | Remover respeitando bloqueios e política de auditoria |
| Eventos SSE/cache/resultado Celery | 1 h / 15 min / 24 h | TTL; não fonte definitiva |
| Exportações temporárias | 24 h | Revogação imediata possível; original permanece |
| Logs operacionais sem PHI | 30 dias propostos | Rotação e acesso técnico restrito |
| Auditoria clínica/assinatura | Alinhada à política de evidência correspondente | Append-only e integridade; não apagar com usuário |

Na VPS, adotar disco/backup criptografado e permissões do sistema; TLS externo não substitui criptografia de repouso. PFX requer cifragem adicional por chave independente. Dados clínicos não devem aparecer em logs, traces externos, URLs de busca, sistemas de erro ou argumentos de tarefas.

## 11. Prontuário e exame neurológico

### 11.1 Estrutura de consulta

Cabeçalho: paciente, médico, clínica, data/hora, origem do agendamento, modalidade, status e versão. Seções recolhíveis: queixa; HMA; antecedentes pessoais; antecedentes familiares/consanguinidade; exame; hipóteses; exames complementares; conduta; anexos/documentos. Texto livre sempre disponível junto aos controles relevantes.

Campos mínimos de finalização: médico habilitado, paciente, data, queixa/HMA ou justificativa de impossibilidade, avaliação documentada e conduta ou justificativa; itens não avaliados podem permanecer assim de forma explícita. “Normal em todos os itens” somente por ação deliberada sobre uma seção, com indicação visual e possibilidade de desfazer antes da finalização, nunca pré-selecionado.

| Domínio | Controles e granularidade mínima | Texto/alertas |
| --- | --- | --- |
| Cognitivo | Estado de consciência, orientação, linguagem, atenção, memória, funções executivas, praxia/gnosia; avaliado/não avaliado | Instrumentos/escores somente quando realmente aplicados; não calcular escore de avaliação ausente |
| Força | Segmento/grupo muscular e lado; graduação 0–5 e qualificadores definidos, sem impor números fracionários arbitrários | Limitação por dor, esforço ou compreensão |
| Tônus | Normal/hipotonia/hipertonia; tipo e distribuição | Proposta complementar ao núcleo original |
| Sensibilidade superficial | Tátil/dolorosa/térmica conforme realizada; território e lado | Área para distribuição e dissociação |
| Sensibilidade profunda | Vibratória/proprioceptiva; local, lado, método/medida quando aplicada | “Não avaliada” distinta de “preservada” |
| Reflexos miotáticos | Bicipital, tricipital, braquiorradial, patelar, aquileu; lado; ausente/reduzido/normal/vivo/exaltado; clônus | Escala utilizada identificada; não converter entre escalas sem regra |
| Reflexos cutâneos | Plantar por lado: flexor/extensor/indiferente/não avaliado; abdominais e outros quando examinados | Não confundir resposta plantar indiferente com Babinski |
| Coordenação axial | Equilíbrio sentado/em pé, controle de tronco e alterações | Registrar limitações e suporte necessário |
| Coordenação apendicular | Índex-nariz, calcanhar-joelho, diadococinesia por lado | Dismetria/tremor/decomposição, sem preencher achados presumidos |
| Marcha/equilíbrio | Base, padrão, tandem, Romberg se realizado, auxílio | Proposta complementar; preservar contexto de segurança da avaliação |
| I | Olfação quando avaliada | Método/lado e limitações |
| II | Acuidade, campo visual e fundoscopia quando realizados | Resultados e método |
| III/IV/VI | Motilidade ocular, diplopia/nistagmo; pupilas no contexto apropriado | Itens identificados por nervo, relações clínicas não duplicadas |
| V | Sensibilidade facial por território, motricidade mastigatória, reflexos quando examinados | Lateralidade e modalidade |
| VII | Motricidade facial e distribuição | Repouso/ativação quando relevante |
| VIII | Audição e avaliação vestibular quando realizadas | Método e limitação |
| IX/X | Voz, palato, deglutição/reflexos conforme avaliação | Registrar teste realizado, não inferir segurança de deglutição |
| XI | Esternocleidomastoideo e trapézio por lado | Força e limitação |
| XII | Língua: trofismo, fasciculações e mobilidade | Desvio e lado |

Nervos cranianos podem compartilhar um componente visual, mas os achados mantêm identificação individual por nervo/item. Controles incompatíveis são mutuamente exclusivos; normalidade global não convive com alteração no mesmo item sem resolução explícita.

### 11.2 Reutilização segura

Ao abrir retorno, mostrar banner “Dados trazidos da consulta de DD/MM/AAAA — revisão pendente”. Copiar somente os campos definidos em RF-03.04. A origem padrão é o mesmo médico; outra origem exige seleção explícita dentro das concessões clínicas. Exames prévios mantêm datas e não são tratados como resultados novos. Copiar hipótese suspeita não a converte em confirmada.

Finalizar bloqueia edição do snapshot e registra hash. Adendo inclui motivo, autor, data e conteúdo novo; leitura deve mostrar documento original e adendo em sequência. Alteração cadastral posterior não muda nome/documento que constavam no PDF histórico já assinado.

## 12. Documentos, assinatura, entrega e scanner

### 12.1 Documento médico

Templates incluem identificação do médico/CRM/UF, RQE quando existente, identificação do paciente, data, contato e endereço profissional, campos próprios do tipo e assinatura adequada. A Resolução CFM 2.381/2024 define requisitos mínimos para documentos médicos e assinatura qualificada em documentos eletrônicos; a adequação final de cada modalidade deverá ser revisada. [Texto oficial do CFM](https://sistemas.cfm.org.br/normas/arquivos/resolucoes/BR/2024/2381_2024.pdf).

ReportLab monta o PDF; pypdf manipula documentos quando necessário antes da assinatura; pyHanko é a escolha técnica proposta para assinar/validar PAdES. A [documentação do pyHanko](https://docs.pyhanko.eu/en/latest/) distingue assinatura, validação e simples carimbo visual. A aplicação deverá homologar cadeia ICP-Brasil, revogação, formato e evidências temporais pertinentes; isso não está certificado por este PRD.

### 12.2 Custódia de PFX e autorização temporária

PFX cifrado em volume `neurodoc_v1_signing`, fora de media, com chave de dados por credencial envelopada por `NEURODOC_PFX_MASTER_KEY`. O segredo mestre de produção é Docker Secret e somente o app que realiza assinatura o recebe. Worker de IA não monta esse volume e não recebe essa chave.

O médico informa a senha ao habilitar a sessão após MFA. A senha/material de desbloqueio é cifrado com uma chave aleatória exclusiva da sessão; o ciphertext pode permanecer no registro SigningSession, mas a chave da sessão fica somente no tmpfs privado `/run/neurodoc-signing` da VPS, arquivo 0600 pertencente ao UID 10001. Ambas as réplicas app montam esse diretório; worker, beat, banco e proxy não o montam. O script de provisionamento verifica que o diretório está em tmpfs e recria-o vazio após reboot. Não fazer backup desse diretório.

Cada assinatura revalida expiração, revogação, usuário, membership e sessão web no banco antes de ler a chave temporária. Expiração/revogação remove a chave; limpeza no app e command periódico no app removem órfãos; o worker apenas marca revogação no banco e não recebe acesso ao tmpfs; ausência da chave exige nova habilitação. Reinício de processo não amplia a autorização e reboot da VPS invalida o desbloqueio. Esta é a solução inicial concreta para compartilhar autorização entre réplicas na mesma VPS sem colocar senha em texto puro em Redis, banco ou disco persistente. A chave efêmera é material sensível em memória do host, acessível ao administrador do host; não equivale a HSM. A expansão multinó exige outra solução de custódia e não pode copiar essas chaves para storage comum duradouro.

A senha nunca vai para cookie, localStorage, logs, broker ou result backend. O volume PFX mantém o arquivo cifrado com chave mestre própria; o tmpfs contém somente chaves temporárias de autorização. A implementação do envelope, remoção de chaves, proteção contra symlinks e concorrência é critério de S07 e P-05, e não foi executada com certificado real nesta etapa.

Em cada documento: autenticar/autorização → conferir sessão e certificado → gerar bytes finais → assinar → validar → gravar arquivo de forma atômica → persistir estado/hash/evento. Não recriar páginas ou comprimir PDF depois de assinado. Timeout/erro mantém estado não emitido. O sistema não armazena a senha PFX permanentemente.

### 12.3 Entrega protegida

O evento de emissão produz uma entrega por canal habilitado/contato válido. O SMS usa POST JSON para `https://api.smsdev.com.br/v1/send`, com `key`, `type=9`, `number`, `msg` e `refer` conforme [documentação SMSDEV](https://www.smsdev.com.br/en/envio-sms/). `refer` identifica a tentativa local; não é assumido como garantia de idempotência do provedor. A chave fica apenas no worker, e logs de HTTP têm corpo e credenciais omitidos.

Mensagem proposta: “Seu documento está disponível no NeuroDoc. Acesse o link para visualizá-lo com segurança.” O link contém token aleatório sem nome/CPF. A página exige código enviado ao contato previamente confirmado, com limite de tentativas. Se não houver canal verificado, a emissão permanece válida, mas a entrega vira pendência para conferência cadastral; a secretaria não recebe o conteúdo clínico por isso.

A consulta de entrega usa POST/JSON em `https://api.smsdev.com.br/v1/dlr`, com `key` e lista de `id` das mensagens; a documentação também menciona consulta por referência. Homologar o schema/códigos de status da conta antes de mapear delivered. O baseline usa polling limitado (1, 5, 15 e 60 minutos; depois revisão administrativa), sem callback público não autenticado. Sem ID após timeout, conciliar pela referência quando suportado ou pelo atendimento do provedor. [Consulta DLR SMSDEV](https://www.smsdev.com.br/en/consulta-situacao-da-mensagem/).

O provedor descreve cobrança por blocos de 160 caracteres na página de envio; a versão inicial limita o template completo, incluindo link, a 160 caracteres e homologa acentos/segmentação na conta. Rate limit contratado e semântica de cada código DLR permanecem P-03; proposta local: até uma requisição de envio por segundo, fila e backoff em 429, sem alegar limite universal do provedor. `refer` tem até 100 caracteres. Manter verificação TLS ativa e chave fora da URL mesmo quando exemplos do fornecedor usam GET. [Envio SMSDEV](https://www.smsdev.com.br/en/envio-sms/).

### 12.4 Captura de scanner

Primeiro fluxo: software do scanner salva PDF/TIFF em pasta local; agente pequeno de captura monitora essa pasta. O agente é pareado por código temporário, usa HTTPS, chave do dispositivo e token de sessão limitado a upload. Ele não busca pacientes por conta própria. Antes de cada lote, a interface confirma paciente e atendimento; após captura, lista páginas/arquivos e resultado de processamento.

Upload atômico com hash, tamanho e sequência; repetição do mesmo hash na mesma sessão gera alerta e evita duplicidade automática. Não consumir um arquivo ainda em gravação: exigir estabilidade de tamanho e renomeação/fechamento quando disponível. Deletar arquivo local após upload é opcional e nunca automático por padrão. Armazenamento e antivírus locais da clínica integram a validação operacional P-08. Durante falha de rede, preservar fila local cifrada e informar que ainda não foi anexado ao prontuário.

## 13. Agenda, CRM, financeiro e indicadores

### 13.1 Agenda e concorrência

Intervalos ocupados são semiabertos `[início,fim)`, com buffers incluídos; consultas que apenas encostam nas bordas não conflitam. PostgreSQL usa extensão `btree_gist` e ExclusionConstraint sobre tenant, médico e intervalo, condicionada a estados que ocupam agenda e a reservas comuns. O Django documenta esse mecanismo para impedir sobreposição em [constraints PostgreSQL](https://docs.djangoproject.com/en/6.1/ref/contrib/postgres/constraints/).

O service obtém lock por agenda/médico/dia antes de validar disponibilidades e inserir, incluindo encaixes autorizados. Se a consulta cruza dia, bloquear os dias em ordem estável. A constraint complementa o service, e não cobre sozinha regras de férias/bloqueio. Encaixe sobreposto requer permissão `scheduling.overbook`, justificativa e confirmação visual; jamais decorre apenas de parâmetro enviado pelo cliente.

```mermaid
stateDiagram-v2
  [*] --> scheduled
  scheduled --> confirmed
  scheduled --> cancelled
  confirmed --> cancelled
  scheduled --> checked_in
  confirmed --> checked_in
  checked_in --> in_progress
  in_progress --> completed
  scheduled --> no_show
  confirmed --> no_show
```

Remarcação cria histórico de intervalo/versão dentro da mesma transação; o horário anterior é liberado somente com sucesso da nova reserva. Cancelamento de consulta não apaga atendimento/documentos já existentes. `no_show` depende de ação autorizada ou regra explicitamente configurada depois do horário/tolerância; não usar a ausência de check-in como prova clínica de falta.

### 13.2 Financeiro

No atendimento, armazenar snapshot da regra de preço aplicável à data: valor cobrado, repasse previsto e pagador. Repasse não é sinônimo de recebimento. Recebimento efetivo pode diferir do previsto e precisa de registro; ajustes/estornos têm motivo e autoria. Relatórios financeiros não puxam texto do prontuário.

### 13.3 Dicionário de indicadores

| Indicador | Fórmula/unidade de análise | Inclusões, ausentes e filtros |
| --- | --- | --- |
| Carteira ativa | Pacientes distintos com status active na data de corte | Não confundir cadastro com paciente atendido |
| Pacientes atendidos | COUNT DISTINCT(patient_id) em encounters finalizados no período | Tenant, médico e período do atendimento |
| Consultas realizadas | COUNT appointments completed ou encounters finalizados vinculados, com regra única de reconciliação | Fonte oficial do indicador: encounters finalizados; exibir discrepância administrativa |
| Novos pacientes | Primeira consulta finalizada no tenant ocorrida no período | Primeira data no tenant, não por médico, salvo opção claramente nomeada |
| Retornos | Atendimentos cujo paciente já tinha consulta finalizada anterior no escopo escolhido | Não inferir retorno apenas pelo tipo selecionado na agenda |
| Taxa de falta | no_show / (completed + no_show) de consultas com desfecho no período | Excluir canceladas/futuras/em andamento; mostrar n |
| Ocupação de agenda | Minutos ocupados por reservas válidas / minutos ofertados após bloqueios | Separar encaixes para não mascarar taxa >100% |
| Particular/plano | Pacientes ou consultas por categoria de pagamento, conforme seletor explícito | Sem duplicar paciente silenciosamente quando tem ambas; relatório de consultas preferencial |
| Idade | Idade na data do atendimento ou corte, método identificado | Desconhecidos separados; mediana/IQR e faixas |
| Localização | Pacientes distintos por município/UF | Sem endereço exato; desconhecidos visíveis; células pequenas agregadas |
| Diagnóstico | Pacientes distintos por código e certeza clínica | Hipóteses e confirmados em séries diferentes; sem confirmação pelo LLM |
| Seguimento observado | Última menos primeira consulta finalizada, em dias/365,25 | Paciente com uma consulta tem duração observada zero, não perda de seguimento confirmada |
| Receita por competência | Soma charged_amount + ajustes elegíveis pela competence_date | Recebimento em caixa reportado separadamente |
| Recebido em caixa | Soma Payment.amount – refunds por paid_at | Sem duplicar cancelamento e estorno |
| Saldo em aberto | Cobrado líquido – recebido líquido, por vencimento/corte | Saldo negativo indica crédito/exige conciliação |
| Repasse previsto | Soma doctor_share_snapshot nos atendimentos elegíveis | Não rotular como repasse pago |
| Tempo de documentação | Duração ativa de edição baseada em eventos de interação | Pausas longas excluídas; telemetria não registra texto |

Para gestores, células com menos de 5 pacientes são agregadas/suprimidas por proposta de privacidade, com cuidado para evitar reidentificação por subtração de totais. Isso é controle gerencial, não declaração de anonimização completa. O médico autorizado pode acessar detalhes de seus pacientes conforme finalidade assistencial.

### 13.4 Estatística inferencial

Não haverá um botão genérico “calcular significância”. Um `ReportDefinition` analítico aprovado especifica pergunta, população, desfecho, unidade de análise, tratamento de medidas repetidas, dados faltantes e método. Exemplo de proposta: comparar taxa de falta entre modalidades usando pacientes/consultas com dependência tratada adequadamente e intervalos de confiança; a escolha do estimador depende do desenho real. Baixa amostra, viés de seleção ou ausência de variáveis necessárias impedem liberação automática. Não interpretar associação como efeito causal. Exportação para pesquisa exige governança própria, não se confunde com relatório assistencial.

## 14. IA, tools, privacidade e streaming

### 14.1 Fluxo de execução

Grafo LangGraph com nós determinísticos de autorização, seleção, desidentificação e validação, além dos nós de geração. O servidor injeta tenant/usuário; o modelo não pode escolhê-los. A [documentação de streaming do LangGraph](https://docs.langchain.com/oss/python/langgraph/streaming) fornece modalidades de emissão incremental, mas persistência e autorização do NeuroDoc são responsabilidades da aplicação.

```mermaid
flowchart TB
  J["Job autorizado"] --> M["Dados mínimos locais"]
  M --> D["Desidentificação local"]
  D --> G{"Política satisfeita?"}
  G -->|Não| B["Bloquear envio e informar"]
  G -->|Sim| L["Provedor autorizado"]
  L --> V["Validar schema e referências"]
  V --> R["Rascunho para revisão médica"]
  R --> H["Aceitar, editar ou rejeitar"]
```

### 14.2 Contratos de tools

| Tool | Entrada do modelo | Escopo imposto pelo servidor | Limite inicial |
| --- | --- | --- | --- |
| `get_patient_timeline` | Intervalo de datas e tipo de evento | Paciente selecionado e C; tenant não é argumento público | 50 eventos por página, até 200 por job |
| `get_encounter_summary` | Encounter ID dentro dos candidatos autorizados | Médico/paciente concedido | 1 atendimento por chamada |
| `get_exam_findings` | Categoria e período | Resultados autorizados já desidentificados | 30 resultados |
| `get_document_excerpt` | ID autorizado, página/trecho | Somente texto local previamente processado e permitido | 8.000 caracteres por trecho |
| `get_administrative_status` | Tipo agenda/contato/pendência | Perfil administrativo, sem notas clínicas | 50 itens |
| `get_financial_summary` | Período e categoria | Permissão financeira e agregação | 100 linhas agregadas |

Tools leem views/seletores de dados autorizados e desidentificados; não fornecem conexão de banco ao LLM. Cada chamada é reautorizada. Limites: máximo 8 chamadas de tools, 3 ciclos de raciocínio instrumental, contexto de entrada até 32 mil tokens e saída até 4 mil tokens por geração inicial, todos configuráveis sob orçamento. São limites de produto propostos, inferiores à capacidade máxima anunciada do modelo.

### 14.3 Política de dados da IA

Pipeline local detecta identificadores diretos, metadados, nomes em texto/OCR e padrões de documentos. Datas podem ser convertidas em intervalos relativos, localidades generalizadas e idade em faixa quando não comprometer o propósito, com registro dessas transformações. Doenças raras, variantes e genealogia exigem avaliação do risco residual; não há detector universal que garanta anonimização.

Por padrão `AI_ENABLED=False` até homologação. Em produção, somente casos que satisfaçam a política aprovada podem sair da VPS. Caso falhe, status `blocked_privacy`, sem request externo, com opção de continuar o atendimento sem IA. Dados pseudonimizados reversíveis permanecem pessoais; sua utilização externa exigiria mudança expressa da política, contrato/base legal e revisão — não é autorizada por um toggle informal.

No OpenRouter, pin dos provedores finais permitidos e política de retenção adequada. Configuração de retenção zero, quando suportada, não elimina a análise legal nem torna o dado anônimo; o [guia de ZDR do OpenRouter](https://openrouter.ai/docs/guides/features/zdr) é referência a validar contra o roteamento efetivo. Não usar treinamento/telemetria clínica externa por padrão. LangSmith não é habilitado para payloads clínicos.

### 14.4 Schema de saída clínica

```json
{
  "schema_version": "1.0",
  "summary": "Texto sintético sem identificadores",
  "documented_findings": [],
  "hypotheses": [
    {
      "label": "Hipótese a avaliar",
      "priority": "higher",
      "supporting_evidence_refs": [],
      "contradictory_evidence_refs": [],
      "missing_information": [],
      "uncertainty_note": "Fundamento e limitação da priorização"
    }
  ],
  "suggested_next_steps": [],
  "limitations": [],
  "requires_physician_review": true,
  "disclaimer": "Apoio à decisão. Não substitui a avaliação médica."
}
```

Prioridade admite `higher`, `intermediate`, `lower`, `insufficient_evidence`; não é probabilidade nem nível validado de acurácia. Pydantic valida campos, tamanho, enumerações e referências existentes. Rejeitar ID de fonte inexistente e conteúdos incompatíveis com schema. Uma tentativa de correção de formato pode ocorrer sem ampliar dados enviados; persistir falha após isso. O modelo pode declarar insuficiência de evidência.

### 14.5 Chat e streaming

POST `/app/ai/chat/sessions/{id}/messages/` salva mensagem e job; devolve job_id. O worker transmite tokens/eventos por Redis Streams DB 2, chave contendo tenant/user/session/job e TTL 1 h. Endpoint SSE autenticado lê eventos em ordem, envia heartbeat a cada 15 s e revalida vínculo a cada lote/até 15 s; mensagem final fica no PostgreSQL. Não tratar UUID da stream como segredo suficiente.

Reconexão usa Last-Event-ID somente dentro da sessão autorizada; se o buffer expirou, carregar estado final/histórico do banco. Cancelamento muda estado persistente, interrompe trabalho assim que possível e informa que custos já incorridos não são recuperados. Limite inicial: uma geração clínica ativa por usuário, duas por tenant e duas simultâneas na VPS; requests excedentes aguardam fila.

O servidor é ASGI com Uvicorn. Middleware de tenant/streaming deve ser compatível com async, usando acesso ao ORM de modo apropriado e sem fixar conexão de banco durante todo o stream. Traefik/SSE não usa middleware de buffering; timeouts permitem heartbeat. O navegador sanitiza Markdown incremental e final; a representação salva não é tratada como HTML confiável.

## 15. Tarefas, eventos e notificações

### 15.1 Eventos e idempotência

A transação que finaliza/assina/cria agendamento grava `OutboxEvent`; um dispatcher no Celery beat/worker recupera eventos vencidos com `select_for_update(skip_locked=True)`. Publicação e marcação usam estados/lease, permitindo redelivery. A unicidade em `ProcessedEvent` e no efeito de negócio protege contra execução repetida. Não se promete exactly-once entre banco e provedor externo.

| Fila | Tarefas | Limites e retorno |
| --- | --- | --- |
| `communications` | Lembretes, documentos, códigos e reconciliação | Timeout HTTP 10 s; 3 retentativas com 30/120/600 s, salvo timeout ambíguo que exige conciliação |
| `ai` | Resumo, hipóteses, chat e sanitização computacional | Soft limit 240 s, hard 300 s, até 2 retries para falha transitória; nunca retry de privacy block |
| `documents` | Processamento de upload, preview/OCR e relatórios | Soft 300 s, hard 360 s; quotas de página/tamanho; assinatura permanece controlada no app |
| `maintenance` | Outbox, limpeza transitória e métricas | Jobs pequenos, idempotentes; não excluir registros clínicos finais |

A tabela de agendamentos periódicos deve ser registrada em S06/S08/S10: dispatcher outbox a cada 5 s, limpeza de transitórios a cada 5 min, atualização ClamAV a cada 6 h e reconciliação de jobs parados a cada minuto. Cada consumidor revalida tenant/contexto e usa lock/idempotência. Limpeza física de chaves de assinatura roda no app por command técnico acionado por timer de host a cada 5 min, além de remoção imediata nas ações de revogação; Celery não monta esse tmpfs.

Uma instância worker inicial consome as quatro filas, concorrência 2 e prefetch 1. Se IA atrasar mensagens, a primeira expansão será separar workers por fila mantendo as mesmas redes; não aumentar concorrência indiscriminadamente na mesma VPS. Beat é singleton com schedule persistido em volume próprio e atualização stop-first.

Preview DOCX usa extração local de texto com validação do ZIP e XML seguro, sem executar Office/macros/OLE ou resolver links externos. OCR usa Tesseract local e rasterização limitada com Poppler; ClamAV usa base em /data/clamav. S06 deve homologar limites e isolamento do processo de conversão e a atualização de assinaturas por freshclam como UID 10001; falha de scanner, isolamento ou definição antimalware mantém quarentena. Instalar binários no Dockerfile não implementa essa política sozinho.

No modo `NEURODOC_RECOVERY_MODE=True`, worker consome somente fila `recovery`, sem jobs de domínio. O ping operacional usa essa fila; agendamentos que o beat publicar não são processados até a conciliação e liberação do modo. A interface de domínio deve ficar restrita aos operadores de recuperação e impedir novas emissões/agendamentos/envios. O command anexo invalida sessões/tokens e marca trabalho restaurado para revisão, atravessando tenants somente por ser operação técnica global identificada e auditada.

### 15.2 Estado e falha

Jobs: queued → running → succeeded/failed/cancelled/blocked_privacy; stalled após ausência de heartbeat e reconciliação. Resultados definitivos e autoria ficam no banco; Celery result backend contém apenas referência/status mínimo. `acks_late` só em tarefas idempotentes; proteção contra worker perdido não autoriza duplicar envio SMS.

Mudança do paciente após iniciar resumo compara source_hash no retorno: artefato vira stale, não sobrescreve resultado aprovado. Se usuário perde acesso antes da execução, job é cancelado/negado sem obter os dados. Notificações mostram mensagem mínima, tenant e link autorizado; estado read_at persiste entre navegações.

## 16. Design system e acessibilidade

P-01 permanece aberta: o arquivo visual não foi disponibilizado. A implementação não pode afirmar aderência a cores, fontes e componentes ainda não inspecionados. S01 deve catalogar tokens e S03 converter componentes necessários para templates reutilizáveis; não escolher uma identidade visual substituta.

| Área | Especificação de interação | Critério manual |
| --- | --- | --- |
| Menu | Itens por permissão; clínica ativa sempre visível | Usuário não confunde tenants e não descobre conteúdo proibido via contadores |
| Formulários | Label persistente, máscara não destrutiva, erro no campo e resumo no topo | Cadastro completo por teclado |
| Exame | Seções progressivas, lado explícito, alternativas mutuamente exclusivas | Não há normalidade automática ou valores invisíveis |
| Agenda | Semana/dia no desktop; lista e dia no celular; não depender só de drag-and-drop | Agendar/remarcar por botão e teclado |
| Jobs | Loading local no botão, status acessível e notificação persistente | Navegação permanece disponível |
| Documentos | Revisão de paciente/emissor/conteúdo/destinatário antes de assinar | Nenhuma emissão por clique acidental em ação administrativa |
| Gráficos | Título, unidade, período, legenda e tabela alternativa | Informação compreensível sem depender apenas de cor |
| Chat | Streaming sem roubar foco, anúncio de conclusão e cancelamento | Markdown malicioso não executa script |

Usar datas DD/MM/AAAA, valores monetários em R$ e fuso America/Sao_Paulo. Código e schemas continuam em inglês. Recursos adicionais propostos devem reutilizar o design system, sem introduzir componentes de aparência incompatível.


## 17. Infraestrutura, rede e releases

### 17.1 Capacidade e topologia escolhidas

Baseline de produção proposta: **8 vCPU, 16 GiB RAM, 200 GiB SSD/NVMe, amd64, Ubuntu 24.04 LTS**, armazenamento do provedor criptografado e cópia externa de backups. A escolha comporta os limites abaixo, a terceira réplica web temporária e alguma margem para build. É dimensionamento inicial, sujeito a H-23; não é resultado de carga executada. Para demonstração local com dados sintéticos: 4 vCPU/8 GiB/60 GiB, uma réplica e tarefas serializadas; não usar esse mínimo para prometer a capacidade do piloto.

| Serviço permanente | Réplicas | CPU limite / reserva por réplica | Memória limite / reserva | Rede | Estado |
| --- | --- | --- | --- | --- | --- |
| app | 2 | 1 / 0,25 | 1 GiB / 384 MiB | traefik_public + neurodoc_v1_internal | media, staticfiles, signing; chaves temporárias em tmpfs |
| celery_worker | 1, concorrência 2 | 1,5 / 0,75 | 3 GiB / 1 GiB | interna + neurodoc_v1_egress | media, definições ClamAV |
| celery_beat | 1 | 0,25 / 0,1 | 256 MiB / 64 MiB | interna + egress | agenda/heartbeat em volume beat |
| db | 1 | 1 / 0,25 | 2 GiB / 512 MiB | interna | PostgreSQL |
| rabbitmq | 1 | 0,75 / 0,25 | 1 GiB / 256 MiB | interna | filas persistentes |
| redis | 1 | 0,5 / 0,1 | 512 MiB / 128 MiB | interna | AOF; maxmemory 384 MiB/noeviction |
| traefik | 1 | 0,5 / 0,1 | 256 MiB / 64 MiB | traefik_public | ACME persistente |

Os limites somam aproximadamente 9 GiB em situação normal; rollout web acrescenta até 1 GiB. Build não possui reserva automática: observar RAM/disco antes e interromper a publicação se a margem não existir. Converter documentos grandes não pode ignorar o limite global do worker. Limites por job da seção 15 continuam necessários.

| Rede | Criação | Propriedade efetiva | Alcance |
| --- | --- | --- | --- |
| traefik_public | Overlay fora do stack | Internal=false, external=true na referência YAML | Traefik e app; apenas Traefik publica portas |
| neurodoc_v1_internal | Overlay com `--internal` fora do stack | Internal=true, external=true na referência YAML | DB/brokers sem saída direta ou portas no host |
| neurodoc_v1_egress | Overlay fora do stack | Internal=false, external=true na referência YAML | Saída dos workers/beat; nenhuma porta publicada |

Uma rede com saída não é allowlist de destinos. A primeira versão restringe URLs nos adaptadores e impede ferramentas de acessar URLs arbitrárias; controle de saída no firewall/proxy pode reforçar isso. App também tem saída pela rede pública, necessária à consulta de CEP e verificações de certificado. A separação impede conceder rede pública aos workers, mas não equivale a isolamento contra comprometimento do host.

Todos os serviços de dados ficam no nó `neurodoc_data=true`. O script recusa múltiplos nós: volumes locais não acompanham automaticamente uma task transferida para outro servidor. Expandir exige outro projeto de persistência/backup, rede e assinatura. Esta é uma limitação documentada dos [volumes locais Docker](https://docs.docker.com/engine/storage/volumes/).

### 17.2 Volumes e chaves

| Volume externo | Montagem | Dono operacional e recuperação |
| --- | --- | --- |
| neurodoc_v1_postgres | /var/lib/postgresql/data | Imagem PostgreSQL; recuperar por dump lógico, não por cópia de diretório ativo |
| neurodoc_v1_media | /data/media | UID 10001; arquivos privados imutáveis após publicação; backup diário |
| neurodoc_v1_staticfiles | /data/staticfiles | UID 10001; reconstruível pela imagem da release |
| neurodoc_v1_signing | /data/signing | UID 10001; PFX criptografado; backup separado da chave mestra |
| neurodoc_v1_rabbitmq | /var/lib/rabbitmq | Usuário da imagem; outbox permite reconstruir trabalho perdido |
| neurodoc_v1_redis | /data | Usuário da imagem; transitório, não restaurar como fonte clínica |
| neurodoc_v1_beat | /data/beat | UID 10001; reconstruível; sem dois schedulers |
| neurodoc_v1_clamav | /data/clamav | UID 10001; assinaturas antimalware atualizadas por tarefa controlada |
| neurodoc_v1_letsencrypt | /letsencrypt | ACME, modo 0600 dos arquivos; backup criptografado |

`/run/neurodoc-signing` pertence a UID/GID 10001, modo 0700, em tmpfs do host; é montado somente nas réplicas app. Não é Docker Secret porque seu conteúdo varia a cada autorização médica. Não entra no backup. Swap deve estar desabilitado ou criptografado com política aprovada para que tmpfs não implique persistência inadvertida de chaves. Suspensão/hibernação com imagem de memória não faz parte da operação autorizada.

Credenciais de banco são distintas: postgres apenas bootstrap/recuperação, neurodoc_owner para DDL, neurodoc_app para DML. Por exigência de migrations no app, o container web ainda possui a credencial de DDL; isso aumenta seu impacto se comprometido e deve constar na revisão de segurança. Não chamar isso de isolamento absoluto de privilégios.

Docker Secrets guarda os valores; o projeto implementa `secret()` e os entrypoints dos brokers implementam a leitura. Não se pressupõe suporte universal a `_FILE`. PostgreSQL usa a interface da imagem oficial; Traefik/Lego recebe `CF_DNS_API_TOKEN_FILE`. O token `CLOUDFLARE_DNS_API_TOKEN` existe somente no Traefik. Os valores de canais e IA ficam somente no worker. E-mail de recuperação usa os forms/tokens nativos com entrega enfileirada; o app não deve chamar SMTP diretamente.

### 17.3 Readiness, bootstrap e tráfego

`/health/` retorna 200 sem autenticação, banco, broker ou redirecionamento. Serve como liveness: o processo HTTP está respondendo. Middleware específico valida Host e responde antes do middleware de tenant. O app só inicia Uvicorn depois de esperar banco, aplicar migrations sob advisory lock e publicar estáticos. `ops/probe_ready.py` verifica banco, schema da release e marcador de estáticos após convergência.

Essa separação preserva o healthcheck independente do banco pedido no prompt, mas uma falha de banco posterior ao startup pode deixar `/health/` verde. A aplicação retorna erro controlado nas operações afetadas e a observação de readiness registra incidente. O script verifica readiness ao liberar a release; o timer externo de monitoramento deve verificá-la continuamente. Não usar `/health/` sozinho como prova de saúde assistencial.

Worker e beat aguardam banco, schema, RabbitMQ e Redis, com backoff/timeout, e depois usam reconexão de cliente. Falha definitiva é visível no job, no serviço e no alerta; dez tentativas de restart podem se esgotar. O app permite consulta/prontuário sem IA e sem envio imediato quando o broker está indisponível, graças à outbox no banco. O beat apenas agenda; a exclusão mútua dos jobs periódicos e os IDs de eventos evitam que redelivery multiplique efeitos.

### 17.4 Publicação e estáticos

Cada imagem usa a tag do SHA Git completo em `ghcr.io/pycodebr/scsi_v1` e o stack recebe o digest confirmado pelo registry. Uma tag já publicada é reutilizada, sem rebuild silencioso. App, worker e beat recebem o mesmo digest. `--skip-build` reutiliza o registro `last-successful.json`, inclusive RELEASE_ID, e nunca atribui o commit recém-baixado à imagem anterior.

O deploy aplica um `ROLLOUT_ID` novo em app/worker/beat para uma única atualização coordenada, inclusive em mudança somente de configuração. Não executa outro `service update --force` ao final. App usa start-first/parallelism=1; worker e beat usam stop-first. Broker/DB/Redis e Traefik têm um exemplar: sua atualização pode interromper serviço, e mudanças de imagens de infraestrutura são recusadas pelo fluxo normal depois da primeira instalação. Exigem manutenção planejada e backup.

Swarm start-first não garante, sozinho, prontidão funcional antes de retirar a réplica anterior. Bootstrap anterior ao servidor, healthcheck do Traefik, duas réplicas, intervalo entre atualizações, margem de capacidade e migrations expand compatíveis reduzem a janela de falha. H-21 deve observar requisições e conexões SSE durante a atualização; não se declara zero downtime nesta especificação.

Arquivos públicos usam `/static/<RELEASE_ID>/<arquivo-com-hash>`. `collectstatic --clear --noinput` roda em diretório `.staging-<uuid>` dentro do volume. Lock de arquivo serializa coletores; `.ready` identifica publicação concluída; rename atômico publica a pasta inteira. Nenhuma limpeza ocorre na pasta servida. Reter no mínimo as duas últimas releases e por 30 dias, além de qualquer release ainda referenciada por execução/rollback. Limpeza só após inspeção dessas condições e nunca no entrypoint.

O WhiteNoise é usado para **storage de manifesto e compressão**. O atendimento HTTP dos assets usa `ops/staticfiles.py`, que resolve releases publicadas no volume compartilhado e suporta ASGI. Assim, uma réplica antiga também atende assets de uma release publicada após seu startup. `WHITENOISE_AUTOREFRESH=False`: a documentação o destina a desenvolvimento e desaconselha seu uso em produção. O middleware anexo envia os arquivos sem compressão de transporte; gzip/brotli pode ser servido pelo proxy/CDN para estáticos públicos, sem afetar manifesto/hash. Essa composição é uma decisão arquitetural, sujeita a H-21/H-23, derivada da [documentação WhiteNoise](https://whitenoise.readthedocs.io/en/stable/django.html) e do [comportamento do collectstatic](https://docs.djangoproject.com/en/6.0/ref/contrib/staticfiles/).

Mídia, documentos, prontuário, downloads por token e documentação técnica nunca entram nessa rota estática nem em cache público. Cloudflare deve ignorar cache dessas rotas. `/technical-docs/` utiliza o artefato MkDocs da imagem e `ops/docs.py`, somente para superuser técnico com MFA. Em S02, registrar a rota raiz e a rota `<path:path>` no URLconf e permitir a passagem pelo middleware de tenant somente depois da validação técnica. Em S01/S02, instalar também `dj-control-room` e registrar `dj_control_room_base`, `dj_celery_panel` e `dj_control_room`, conforme a [instalação do pacote](https://pypi.org/project/dj-celery-panel/); proteger todas as suas URLs com a mesma política técnica e revisar exposição de payloads.

## 18. Guia sequencial de deploy Ubuntu

### 18.0 Como usar e pré-condições

**Este guia especifica ações futuras. Nenhuma VPS foi acessada, nenhuma imagem foi publicada e nenhum deploy foi executado nesta elaboração.** O anexo contém arquivos operacionais completos; os apps de negócio, suas migrations, URLconf, templates e documentação inicial ainda precisam ser implementados nas sprints. O build não é executável apenas com este PRD. A resolução conjunta de dependências e a homologação dos anexos são P-04 e H-21/H-22.

Nos comandos, substituir os placeholders antes da execução; não copiar sinais `<` e `>` para o shell. Cada bloco informa o ambiente de execução. Caminho de instalação fixado em `/srv/neurodoc`. Usar sessões interativas protegidas, nunca colar credenciais em tickets ou logs.

| Placeholder | Como preencher |
| --- | --- |
| VPS_IP | IPv4 público confirmado da VPS |
| ADMIN_IP | IP público autorizado para SSH; atualizar firewall se mudar |
| GIT_URL | URL SSH real, com acesso de leitura; não inferir a partir do GHCR |
| RELEASE_SHA | SHA Git de 40 caracteres da release homologada |
| GHCR_USER | Conta com acesso ao pacote solicitado |
| OPS_EMAIL | E-mail de operação real; no command de recuperação, usar o e-mail do administrador técnico cadastrado |
| DOCKER_VERSION, COMPOSE_VERSION, CONTAINERD_VERSION, BUILDX_VERSION | Valores completos exibidos pelo apt para Ubuntu noble/amd64, registrados na homologação |
| BACKUP_RECIPIENT | Chave pública age `age1...` gerada fora da VPS |
| BACKUP_HOST, BACKUP_USER, BACKUP_PATH | Destino externo SSH contratado/autorizado, com retenção e acesso definidos |
| BACKUP_SET | Diretório concluído de backup, contendo COMPLETE e manifest.json |
| RECOVERY_IDENTITY | Caminho protegido da chave privada age no host de recuperação, preferencialmente em `/run` |

Tokens do produto, PFX, passphrases e senhas reais não são placeholders em arquivos versionados. Quando um domínio, imagem ou serviço externo não estiver disponível, parar na etapa correspondente e registrar o erro; não escolher substituto silencioso.

### 18.1 Preparar acesso, usuário e relógio

No computador do operador, usar a chave SSH fornecida/instalada pelo provedor:

```bash
ssh root@VPS_IP
```

Na sessão inicial da VPS, instalar atualizações e ferramentas, criar o usuário de operação e instalar **a chave pública do operador** em `/home/neurodocops/.ssh/authorized_keys`, usando editor. Não copiar chaves privadas para o servidor.

```bash
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg git ufw chrony python3 python3-yaml age rsync openssl
adduser neurodocops
usermod -aG sudo neurodocops
install -d -m 700 -o neurodocops -g neurodocops /home/neurodocops/.ssh
nano /home/neurodocops/.ssh/authorized_keys
chown neurodocops:neurodocops /home/neurodocops/.ssh/authorized_keys
chmod 600 /home/neurodocops/.ssh/authorized_keys
systemctl enable --now chrony
timedatectl set-timezone America/Sao_Paulo
timedatectl status
```

Abrir uma segunda sessão `ssh neurodocops@VPS_IP`, verificar sudo e manter a inicial aberta até confirmar acesso. Só então desabilitar senha SSH/root login por arquivo em `/etc/ssh/sshd_config.d/`, validar com `sudo sshd -t` e recarregar SSH. Registrar sincronização NTP; horários incorretos prejudicam assinatura, tokens e TLS.

### 18.2 Firewall e Docker

No firewall do provedor: entrada TCP 22 somente de ADMIN_IP; 80/443 públicas durante a homologação da origem; demais portas negadas. Repetir para IPv6 ou não publicar AAAA. Na VPS, como neurodocops:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from ADMIN_IP to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Docker pode encaminhar portas publicadas fora das regras comuns do UFW; o firewall do provedor e a ausência de portas nos serviços internos são controles obrigatórios. Não expor 2375/2376, 2377, 7946, 4789, 5432, 5672, 6379, 15672 ou 8082 à internet. A topologia de um nó não exige portas Swarm públicas; futura expansão restringiria TCP 2377, TCP/UDP 7946 e UDP 4789 aos IPs privados autorizados dos nós. [Docker/Ubuntu e firewall](https://docs.docker.com/engine/install/ubuntu/).

Instalar o repositório oficial para **Ubuntu 24.04 noble/amd64**. Este bloco não deve ser usado sem ajuste em outra distribuição/arquitetura:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
apt-cache madison docker-ce docker-compose-plugin containerd.io docker-buildx-plugin
```

Selecionar versões compatíveis exibidas pelo apt; candidato Engine 29.8.0 deve ser confirmado. Substituir as quatro variáveis de pacote nos argumentos abaixo pelos valores completos do apt, incluindo epoch/sufixo, quando presentes. Não usar um número inexistente só por constar na matriz.

```bash
sudo apt-get install -y docker-ce=DOCKER_VERSION docker-ce-cli=DOCKER_VERSION containerd.io=CONTAINERD_VERSION docker-buildx-plugin=BUILDX_VERSION docker-compose-plugin=COMPOSE_VERSION
sudo systemctl enable --now docker
sudo usermod -aG docker neurodocops
```

Fazer logout/login para carregar o grupo. O grupo docker equivale operacionalmente a acesso privilegiado ao host; limitá-lo à equipe técnica. Verificar:

```bash
docker version
docker compose version
docker info
```

Registrar versões e arquitetura em `docs/operations/environment.md`. Atualizações futuras são planejadas, com release notes/backup; fixar versão não autoriza ignorar correções de segurança.

### 18.3 Repositório e dependências reproduzíveis

Na VPS, como neurodocops, após disponibilizar credencial Git restrita e os apps implementados:

```bash
sudo install -d -m 0750 -o neurodocops -g neurodocops /srv/neurodoc
git clone GIT_URL /srv/neurodoc
cd /srv/neurodoc
git status --short
chmod +x scripts/deploy.sh scripts/backup.sh ops/entrypoint.sh
```

`requirements.in` é entrada de resolução, não lock. Em máquina de desenvolvimento amd64 com Docker, na raiz do repositório, gerar o lock com o Python alvo. A ferramenta de resolução também deve ter sua versão registrada em S01:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e PIP_CACHE_DIR=/tmp/pip-cache -v "$PWD:/src" -w /src python:3.14.7-slim-bookworm sh -c 'python -m venv /tmp/resolver && /tmp/resolver/bin/pip install pip-tools && /tmp/resolver/bin/pip-compile --generate-hashes --resolver=backtracking --output-file=requirements.txt requirements.in && /tmp/resolver/bin/pip --version && /tmp/resolver/bin/pip show pip-tools'
```

Esse comando resolve dependências; se falhar, ajustar faixas com evidência, mantendo Python >3.13/Django >6.0/LangChain >1.0, e registrar a decisão. Não há `requirements.txt` artificial no anexo. Commitar o lock e o registro do resolvedor; reproduzir a instalação com `pip install --require-hashes`/`pip check` no build. Usar imagem Python resolvida por digest para congelar também o resolvedor quando o primeiro baseline for aprovado. `.venv` local fica na raiz quando houver Python 3.14 instalado; o container cria sua própria `/app/.venv`, sem copiar a do host.

Desenvolvimento local usa os sete serviços do Compose anexo, bridge local, HTTP apenas em loopback e integrações desligadas:

```bash
cp .env.example .env
python3 -m ops.secret_setup --local
python3 -m ops.local_compose
docker compose build app
docker compose run --rm --no-deps --user 0 --entrypoint python app -c 'import os; from pathlib import Path; [(os.chown(p,10001,10001),os.chmod(p,0o750)) for p in Path("/data").iterdir() if p.is_dir()]'
docker compose run --rm --no-deps --user 0 --entrypoint python celery_worker -c 'import os; os.chown("/data/clamav",10001,10001)'
docker compose run --rm --no-deps --user 0 --entrypoint python celery_beat -c 'import os; os.chown("/data/beat",10001,10001)'
docker compose up -d
docker compose ps
```

A imagem `neurodoc:dev` criada pelo build é compartilhada com worker/beat. Acessar localhost:8000 ou localhost:8080 (Traefik local). Em rebuild de assets com RELEASE_ID=dev, parar o app e remover **apenas** `/data/staticfiles/public/static/dev` no volume de desenvolvimento antes de subir novamente; esse procedimento não existe em produção. Compose não oferece o rollout Swarm; essa diferença é deliberada.

### 18.4 Swarm, redes e dados persistentes

Na VPS, verificar `docker info`. Somente se Swarm ainda estiver inativo:

```bash
docker swarm init --advertise-addr VPS_IP
```

Saída esperada: manager ativo. Não divulgar tokens de ingresso. Habilitar autolock e custodiar a chave de desbloqueio fora da VPS; após reboot, o operador precisará desbloquear o manager antes da recuperação dos serviços:

```bash
docker swarm update --autolock=true
docker node ls
docker node update --label-add neurodoc_data=true self
```

O comando de autolock pode mostrar chave sensível: executar em terminal protegido, sem captura compartilhada. Criar cada rede somente se não existir; se já existir, inspecionar suas propriedades antes de prosseguir:

```bash
docker network create --driver overlay traefik_public
docker network create --driver overlay --internal neurodoc_v1_internal
docker network create --driver overlay neurodoc_v1_egress
docker network inspect traefik_public neurodoc_v1_internal neurodoc_v1_egress --format '{{.Name}} driver={{.Driver}} scope={{.Scope}} internal={{.Internal}}'
```

Esperar internal=true somente na rede interna. O helper de deploy cria os nove volumes externos e ajusta as raízes dos volumes da aplicação para UID 10001; dados PostgreSQL/Rabbit/Redis são inicializados pelas próprias imagens. Nunca executar `docker volume prune` neste host.

Preparar diretório de chaves temporárias e backup:

```bash
sudo tee /etc/tmpfiles.d/neurodoc-signing.conf >/dev/null <<'EOF'
d /run/neurodoc-signing 0700 10001 10001 -
EOF
sudo systemd-tmpfiles --create /etc/tmpfiles.d/neurodoc-signing.conf
findmnt -n -o FSTYPE -T /run/neurodoc-signing
sudo install -d -m 0700 -o neurodocops -g neurodocops /srv/neurodoc-backups
swapon --show
```

Esperar tmpfs e ausência de swap sem proteção aprovada. Diretórios de chaves reaparecem vazios a cada boot: todas as sessões de assinatura precisarão ser habilitadas novamente.

### 18.5 DNS, TLS e secrets

No painel Cloudflare da zona autorizada `neurodoc.app.br`, criar A do apex para VPS_IP. Criar wildcard A/CNAME para subdomínios se os aliases forem usados. Não criar AAAA sem IPv6 funcional. Wildcard do certificado cobre um nível de subdomínio; apex é SAN separado; não confundir certificado com existência de registros DNS ou cadastro de domínio no tenant.

Criar API token restrito à zona com **Zone:DNS:Edit e Zone:Zone:Read**, conforme [Lego/Cloudflare](https://go-acme.github.io/lego/dns/cloudflare/). Não utilizar a Global API Key. DNS-01 usa a API e não depende de desligar o proxy Cloudflare. Começar com proxy desativado ou verificar origem por `curl --resolve`; depois ativar Full (strict). Nunca usar Flexible, que pode criar loop de HTTPS.

Em estação de custódia, fora da VPS, criar o par age e guardar a chave privada em cofre com procedimento de recuperação:

```bash
age-keygen -o neurodoc-recovery.agekey
age-keygen -y neurodoc-recovery.agekey
```

Copiar **somente a chave pública** para BACKUP_AGE_RECIPIENT. Na VPS, criar `.env` a partir do exemplo, modo 0600, usando editor:

```bash
cd /srv/neurodoc
cp .env.example .env
chmod 600 .env
nano .env
```

Configuração necessária: ACME_EMAIL real, BACKUP_AGE_RECIPIENT real, hosts/origins/default URL intactos, DEBUG=False; canais inicialmente False; NEURODOC_RELEASE_APPROVED permanece False até homologação. O parser aceita `KEY=VALUE` literal, sem comentários ao fim da linha, expansão `$` ou `source`. Valores sensíveis entram pelos prompts a seguir; valores não sensíveis contendo `$` são rejeitados ao gerar env_file, em vez de reinterpretados silenciosamente.

```bash
python3 -m ops.secret_setup
docker secret ls --format '{{.Name}}'
```

O helper gera senhas aleatórias fortes, chave Django e chave mestra PFX, solicita token Cloudflare sem eco e permite informar credenciais opcionais de SMTP/SMS/IA. Enter deixa o canal com marcador DISABLED; não habilitar a respectiva flag até substituir esse secret por valor válido. Gera um pacote age de recuperação **antes** de criar secrets; copiá-lo para destino externo e conferir disponibilidade da chave de custódia. Em falha parcial, usar esse mesmo pacote com `--recover`, não gerar credenciais diferentes. Esse modo não compara o conteúdo dos secrets já existentes; recuperação integral deve ocorrer em host vazio.

Credenciais externas são do operador/controlador, conforme contratos; a elaboração do PRD não criou contas nem tokens. Rodar `secret ls` exibe nomes, nunca valores. Não executar comandos de inspeção que imprimam ambiente completo da aplicação.

### 18.6 Registry e primeira publicação

Na VPS, usar token GHCR com permissões concedidas à conta/organização para push/pull do pacote solicitado. O login bem-sucedido não prova, sozinho, autorização de push naquele namespace; o primeiro push deve confirmá-la. Usar leitura protegida:

```bash
read -r -s -p 'Token GHCR: ' ND_GHCR_TOKEN
printf '%s' "$ND_GHCR_TOKEN" | docker login ghcr.io -u GHCR_USER --password-stdin
unset ND_GHCR_TOKEN
```

Guardar `/home/neurodocops/.docker` com permissões restritas; usar credential helper quando disponível/homologado. Não versionar credenciais. Se a organização não conceder acesso a `ghcr.io/pycodebr/scsi_v1`, registrar P-02 e interromper a publicação; não renomear o registry unilateralmente.

Após implementação do marco e homologação correspondente, registrar SHA, evidências e responsável em `docs/releases/RELEASE_SHA.md`. O operador altera NEURODOC_RELEASE_APPROVED=True e NEURODOC_SCHEMA_CHANGE=expand. A flag é uma trava declarativa, não executa nem comprova homologação.

```bash
cd /srv/neurodoc
scripts/deploy.sh
```

Resultado esperado: preflight → pull fast-forward → leitura do helper atualizado → resolução de imagens → build/push ou reutilização de tag existente → volumes/configs/env_files → stack → convergência dos sete serviços → readiness app. Timeout/falha retorna código diferente de zero. O primeiro deploy com ACME staging não exige certificado público confiável no check externo automático; a verificação manual é obrigatória.

Se a imagem não compilar, o script para antes de aplicar o stack. Se migrations falharem, o novo app não inicia o HTTP; observar rollback/serviços e diagnosticar com dados sensíveis omitidos. `NEURODOC_SCHEMA_CHANGE=expand` exige revisão humana das migrations; não impede que código incorreto faça DDL destrutivo.

### 18.7 Certificado definitivo e administrador inicial

Com ACME staging, verificar DNS-01, roteamento e logs restritos do Traefik. Depois trocar apenas ACME_DIRECTORY para `https://acme-v02.api.letsencrypt.org/directory` e aplicar:

```bash
scripts/deploy.sh --skip-build
docker stack services neurodoc_v1
docker stack ps neurodoc_v1 --no-trunc
curl --fail --silent --show-error https://neurodoc.app.br/health/
curl --resolve neurodoc.app.br:443:VPS_IP --fail --silent --show-error https://neurodoc.app.br/health/
openssl s_client -connect VPS_IP:443 -servername neurodoc.app.br </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Esperar 200/ok, certificado válido, apex e wildcard SAN, sem loop. Não usar `-k` como evidência de TLS válido. Staging usa arquivo ACME separado para não contaminar o certificado definitivo. Se o firewall da origem só permitir Cloudflare, autorizar temporariamente ADMIN_IP para essa verificação e removê-lo depois. Atualizar lista de IPs confiáveis Cloudflare a cada configuração gerada; não habilitar forwardedHeaders insecure.

Criar administrador com comando nativo, selecionando uma única réplica em execução. O comando deve solicitar e-mail e senha interativamente; não receber senha por argumento:

```bash
ND_APP_CONTAINER=$(docker ps -q --filter label=com.docker.swarm.service.name=neurodoc_v1_app | head -n 1)
docker exec -it "$ND_APP_CONTAINER" python manage.py createsuperuser
unset ND_APP_CONTAINER
```

Completar o fluxo de cadastro MFA criado em S02, antes de abrir admin/dj-control-room/documentação. Admin global não recebe acesso clínico ordinário. Gerar convite pelo formulário técnico implementado em S03: destinatário, expiração, plano free e uso único. O link é exibido uma única vez; entrega controlada conforme a política de convite, sem registrar token em logs. Não existe command de convite presumido neste anexo.

### 18.8 Homologação operacional da primeira release

Na VPS, inspecionar somente status/metadados:

```bash
docker service ps neurodoc_v1_app --no-trunc
docker service ps neurodoc_v1_celery_worker --no-trunc
docker service ps neurodoc_v1_celery_beat --no-trunc
docker stats --no-stream
sudo ss -lntup
ND_APP_CONTAINER=$(docker ps -q --filter label=com.docker.swarm.service.name=neurodoc_v1_app | head -n 1)
docker exec "$ND_APP_CONTAINER" python /app/ops/probe_ready.py
docker exec "$ND_APP_CONTAINER" python -m ops.queue_probe
unset ND_APP_CONTAINER
```

Esperar dois apps, um worker, um beat; brokers e banco saudáveis, sem portas públicas internas; probe de fila devolve resultado sem dados clínicos. A tarefa de ping anexa não envia mensagens a pessoas e não altera prontuário.

Em terminal protegido no container worker, efetuar apenas uma requisição sem credencial nem dados clínicos a um destino público aprovado, para verificar DNS/egress; não usar um endpoint de envio SMS ou chamada LLM como probe. Conferir login, CSRF, logout, isolamento entre duas clínicas fictícias e negação de anexo cruzado no navegador. `seed_demo` é desenvolvido em S03/S14 e bloqueado por padrão em produção; usar ambiente de homologação com flags de canal False.

Habilitar HSTS somente após validar todos os hosts usados. A primeira configuração tem `SECURE_HSTS_SECONDS=0`; a alteração para 31536000 e eventual includeSubDomains requer revisão dos aliases e release homologada. Essa dependência não fica escondida em uma promessa de segurança pronta.

### 18.9 Deploy regular, configuração e reversão

Deploy regular: repositório limpo, backup recente copiado externamente, mudanças de schema expand revisadas, release aprovada e `scripts/deploy.sh`. Configuração sem imagem: `scripts/deploy.sh --skip-build`; ele puxa o Git por exigência do fluxo, mas usa o digest/RELEASE_ID do registro anterior. Alterar estrutura YAML/helpers incompatível com a imagem antiga exige nova release; não usar skip-build nesse caso.

O arquivo `.runtime/candidate.json` representa a tentativa; `.runtime/last-successful.json` representa a última convergência; `.runtime/previous-successful.json` permite identificar a anterior. Guardar esses metadados com a documentação da release, sem credenciais. Código, infra images, migrations e contexto de aprovação precisam corresponder. Um código de saída zero do script cobre checks operacionais descritos, não todos os aceites clínicos.

## 19. Operação, recuperação e diagnóstico

### 19.1 Backup, consistência e retenção

Backup diário às 03:00 America/Sao_Paulo, com até 10 minutos de atraso aleatório, retenção operacional de 30 dias. RPO de 24 h e RTO de 4 h são metas a medir. A retenção do backup não substitui a política de retenção do prontuário.

`scripts/backup.sh` usa o mesmo lock de operação que o deploy. O helper adquire advisory lock 72654002, que **todos os processos de remoção física de mídia/PFX devem respeitar**. Faz pg_dump com snapshot consistente, depois copia arquivos imutáveis de media/signing e ACME. Publicar arquivos exige escrever em área temporária, fsync/rename e só então confirmar referência no banco; arquivos referenciados não podem ser sobrescritos. Arquivos adicionados depois do snapshot podem aparecer a mais no backup, sem serem usados pela restauração; exclusões ficam suspensas pelo lock. Sem esses contratos implementados em S06/S07, o backup não atende à consistência declarada.

Cada stream é criptografado com age diretamente, sem dump desprotegido em disco. O manifest inclui SHA-256 e tamanho de cada arquivo; COMPLETE só é escrito após sucesso de todos. Qualquer falha invalida o conjunto e retorna erro. Rotação só remove diretórios concluídos, com padrão de nome validado, dentro do BACKUP_DIR autorizado e depois de novo backup bem-sucedido. Backups incompletos são investigados manualmente. O conjunto precisa vir de custódia confiável: hashes no mesmo diretório detectam corrupção, não autenticam um remetente malicioso capaz de substituir também o manifest.

Na VPS:

```bash
cd /srv/neurodoc
scripts/backup.sh
sudo cp ops/neurodoc-backup.service /etc/systemd/system/neurodoc-backup.service
sudo cp ops/neurodoc-backup.timer /etc/systemd/system/neurodoc-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now neurodoc-backup.timer
systemctl list-timers neurodoc-backup.timer
systemctl status neurodoc-backup.service
```

O timer foi especificado, não instalado nesta elaboração. A conta neurodocops deve poder acessar Docker e BACKUP_DIR. Monitorar falha do serviço pelo mecanismo de alertas contratado; systemd sozinho não avisa uma pessoa. Não criar envio real de alertas até os destinatários serem definidos.

Copiar o conjunto concluído para destino externo por SSH com host key previamente conferida:

```bash
rsync -a --checksum /srv/neurodoc-backups/BACKUP_SET/ BACKUP_USER@BACKUP_HOST:BACKUP_PATH/BACKUP_SET/
```

Não usar `--delete`. O destino deve limitar a credencial da VPS a criação de conjuntos, com retenção protegida contra exclusão pelo mesmo usuário quando disponível. Verificar hashes no destino e manter registro de última cópia bem-sucedida. Agendar essa cópia após COMPLETE usando o mecanismo do destino escolhido em P-10; credenciais e API do provedor não foram inventadas aqui. Sem cópia externa concluída e restauração confirmada, não liberar o piloto assistencial.

| Estado adicional | Tratamento |
| --- | --- |
| PFX criptografado | Incluído em signing; chave mestra no pacote de secrets age, separado |
| Secrets Django/banco/brokers/provedores | Pacote age de bootstrap, atualizado após rotação e guardado externamente |
| Chave privada age / chave de autolock | Custódia fora da VPS; acesso independente dos backups |
| Imagem por digest + Git da release | Retenção no GHCR/Git e registro do manifest; impedir remoção de versões recuperáveis |
| Outbox/jobs oficiais | No PostgreSQL; reconciliar após restauração antes de reabrir canais |
| Redis/cache/SSE/beat | Reconstruir; invalidar sessões transitórias; eventos não são prontuário |
| RabbitMQ | Recriar e reconciliar outbox; não restaurar dump de filas como prova de entrega |
| Estáticos/ClamAV | Reconstruir da imagem/assinaturas verificadas |
| Desbloqueios PFX em tmpfs | Nunca restaurar; médico autoriza nova sessão |

### 19.2 Restauração completa em host separado

Executar H-22 antes de dados reais e periodicamente, em VPS **separada e vazia**, com firewall restrito aos operadores. Nunca apontar o helper para a VPS produtiva. Os scripts recusam volumes NeuroDoc já existentes e serviço produtivo durante preparação de dados; se uma tentativa falhar, usar outro host vazio ou examinar/remover somente os recursos da tentativa com autorização operacional documentada.

1. Preparar Ubuntu, Docker, usuário, Git, Swarm, label, redes, tmpfs e GHCR conforme 18.1–18.5. Não iniciar o stack. Copiar o conjunto de backup concluído e o pacote de secrets cifrado de fonte confiável. Disponibilizar a identidade age em caminho protegido na memória do host para a janela de recuperação.
2. Ler `manifest.json` e fazer checkout do **RELEASE_ID exato** do backup. O código dessa release deve conter o helper de recuperação homologado. Não aplicar migrations novas durante a restauração. Copiar `.env.example` para `.env`, preencher e-mail/backup público e manter AI/EMAIL/SMS False e NEURODOC_RECOVERY_MODE=True. Validar o manifesto com o helper; ele verifica nomes, tamanhos e hashes antes de criar dados.

```bash
cd /srv/neurodoc
git switch --detach RELEASE_SHA
python3 -m ops.secret_setup --recover /srv/recovery/bootstrap-secrets.age --identity RECOVERY_IDENTITY
python3 -m ops.restore --prepare-data --backup-dir /srv/recovery/BACKUP_SET --identity RECOVERY_IDENTITY
```

3. O helper cria volumes canônicos novos; sobe PostgreSQL de recuperação sem portas publicadas, com a imagem do manifest e roles iniciais; restaura o dump como neurodoc_owner e mídia/PFX/ACME nos volumes corretos. A lista de restauração exclui a criação já realizada do schema public e da extensão btree_gist. Este baseline aprova somente essa extensão: outra extensão exige revisão do procedimento. Exige histórico django_migrations não vazio e encerra o PostgreSQL temporário antes da ativação.
4. Conferir o marcador `.runtime/restore-data.json`; registrar release e horário. Revisar o código/lock e alterar NEURODOC_RELEASE_APPROVED=True, mantendo canais False. A ativação valida o checkout exato, usa os digests do backup, recria configs/serviços e coleta estáticos. Não faz git pull/build nem migra para uma versão diferente.

```bash
python3 -m ops.restore --activate --backup-dir /srv/recovery/BACKUP_SET
curl --resolve neurodoc.app.br:443:VPS_IP --fail --silent --show-error https://neurodoc.app.br/health/
```

5. Em estação de homologação, resolver temporariamente o domínio para a VPS de recuperação por arquivo hosts ou DNS interno controlado. Proteger a origem por firewall, manter integrações desabilitadas e validar H-22: contagens agregadas por tenant, amostra sintética de prontuários/adendos, hashes de anexos, negação entre tenants, PDFs e integridade de assinaturas existentes. Arquivos privados precisam ser conferidos por endpoint autorizado e hash, não por publicação temporária de `/media/`.
6. Invalidar sessões web/tokens de acesso recuperados conforme command anexo integrado e homologado em S10; expirar SigningSessions, limpar autorizadores transitórios e suspender entregas/AIJobs recuperados até conciliação. Este command usa transações e auditoria; não apagar registros clínicos. A recuperação não deve repetir SMS/e-mails já aceitos após o instante do backup: classificar os pendentes como `needs_reconciliation` operacional e compará-los ao provedor.
Executar na réplica app de recuperação, usando o e-mail do administrador técnico restaurado:

```bash
ND_APP_CONTAINER=$(docker ps -q --filter label=com.docker.swarm.service.name=neurodoc_v1_app | head -n 1)
docker exec -it "$ND_APP_CONTAINER" python manage.py prepare_recovery --operator-email OPS_EMAIL --reason 'Restauracao isolada e conciliacao do conjunto aprovado'
unset ND_APP_CONTAINER
```

A conta indicada precisa existir como superuser técnico ativo. Refazer login após o command, que encerra sessões restauradas. Depois da conciliação, retirar NEURODOC_RECOVERY_MODE e reconfigurar serviços por `ops.restore --activate` não é permitido porque esse comando exige o modo protetivo; retornar ao fluxo normal de release/skip-build somente após ajustar Git/upstream e registrar a imagem restaurada como referência. Manter canais desligados até liberação específica.

7. Medir tempo total, idade do snapshot e perdas possíveis. Se não houver incidente real, manter o host isolado e registrar evidência; não alterar DNS público. Ao recuperar produção de um incidente, anunciar janela, bloquear escrita na origem antiga, garantir que só um ambiente receba tráfego e então mudar A/AAAA/roteamento para a VPS recuperada. Verificar TLS externo, login e documento sintético; habilitar canais gradualmente após conciliação. Preservar a origem anterior isolada para investigação, sem dois beats produtivos.
8. Retirar a identidade age da memória do host e encerrar acessos temporários; manter custódia externa. Não alegar apagamento físico garantido de memória. Voltar a branch de operação com upstream somente após registrar como o SHA restaurado se relaciona ao Git atual; o deploy normal exige pull fast-forward. Fazer novo backup externo do ambiente recuperado.

Dados reais usados em ensaio exigem os mesmos controles do ambiente assistencial. Preferir conjuntos sintéticos completos para a homologação inicial. Comprovar a recuperação da chave mestra e de um PFX autorizado sem expor sua senha é parte do aceite, mesmo quando os dados clínicos são sintéticos.

### 19.3 Rollback e mudanças de infraestrutura

Falha de rollout web pode acionar rollback automático, mas o comando termina com falha e exige inspeção. Não presumir que ele reverteu também worker/beat. Em incidente de aplicação após liberação, identificar `previous-successful.json`, confirmar compatibilidade do schema atual com imagem anterior e, em janela coordenada, usar o recurso `docker service rollback` dos três serviços de aplicação, esperando convergência de cada operação. Verificar qual especificação Docker considera anterior antes de executar; uma tentativa intermediária pode ter mudado esse histórico.

```bash
docker service inspect neurodoc_v1_app --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
docker service inspect neurodoc_v1_celery_worker --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
docker service inspect neurodoc_v1_celery_beat --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
```

Somente após confirmar o histórico apropriado, executar rollback do app, observar estado/saúde; depois worker e beat, um por vez.

```bash
docker service rollback --detach=false neurodoc_v1_app
docker service ps neurodoc_v1_app
docker service rollback --detach=false neurodoc_v1_celery_worker
docker service ps neurodoc_v1_celery_worker
docker service rollback --detach=false neurodoc_v1_celery_beat
docker service ps neurodoc_v1_celery_beat
```

Cada rollback somente prossegue depois de conferir convergência do anterior; qualquer falha interrompe a sequência e exige diagnóstico.
 Beat permanece stop-first. Concluir com probe de prontidão, fila e revisão dos jobs. Se o histórico anterior não corresponder ao digest aprovado, preparar arquivo de configuração com o digest aprovado a partir do registro, revisar com `docker stack config` e aplicar como uma release de recuperação; não tentar adivinhar uma tag. Registrar o novo estado bem-sucedido para que skip-build não volte à release defeituosa.

Migrations destrutivas não são desfeitas automaticamente. Usar expand → backfill em lotes → leitura dupla/compatível → troca → contract somente depois de terminar a janela de rollback, com manutenção e backup. DDL de longa duração exige medição, lock timeout e plano de interrupção. Elevar major PostgreSQL, alterar RabbitMQ, Redis ou Traefik exige consultar upgrade suportado e executar ensaio de restauração; o script normal bloqueia troca de imagem de infraestrutura para não tratá-la como simples atualização web.

### 19.4 Rotação e observação

Secrets são imutáveis no Swarm. Preferir nova versão com alias/target estável quando o requisito admitir: atualizar mapeamento externo e referências, guardar novo pacote de recuperação cifrado, aplicar rollout e retirar versão antiga somente após não haver serviços referenciando-a. O nome canônico Cloudflare solicitado deve ser mantido; para substituí-lo, planejar interrupção do Traefik, retirar a referência do serviço, substituir o secret e reaplicar o stack. Não tentar remover secret ainda utilizado. Senhas de PostgreSQL/RabbitMQ existentes no volume também precisam ser alteradas no serviço, em transação/janela compatível; trocar só o arquivo de secret quebra autenticação.

Para canais inicialmente DISABLED, preencher credencial antes de habilitar a flag, homologar o destinatário sintético autorizado e verificar limites/entrega. Rotação da chave PFX exige recriptografia controlada com versão de chave por credencial e recuperação das versões antigas; não substituir a chave mestra e perder acesso ao acervo. Guardar token GHCR em mecanismo apropriado e renovar a autorização de pull nos serviços com `--with-registry-auth`.

| Sinal | Limite/ação proposta | Responsável |
| --- | --- | --- |
| HTTP externo/CSRF/login sintético | Disponibilidade mensal; 3 falhas consecutivas em 1 min abrem incidente | Operação |
| Readiness de cada app | A cada minuto por canal técnico protegido, sem resposta clínica | Operação |
| Worker/beat | Réplicas desejadas, heartbeat e ping; beat duplicado é incidente | Operação |
| Fila/outbox | Idade >60 s em interativa, retries esgotados e unknown de comunicação | Operação + administrativo |
| Disco/RAM | Disco 75% aviso/85% crítico; RAM >85% sustentada | Operação |
| Backup externo | Ausência de conjunto externo verificado por 26 h | Operação + custodiante |
| Certificado/credenciais | Alertar antes da expiração; nunca publicar PFX/chave em monitoramento | Operação + médico |
| Auditoria e isolamento | Acesso cruzado ou quebra de integridade bloqueia release | Segurança/produto |
| IA | Custo por tenant, bloqueios de privacidade, timeout e rejeição médica | Produto + responsável clínico |

Os coletores e destinatários de alerta são entregas de S10, sem introduzir oitavo serviço permanente obrigatório. Usar o monitoramento do provedor ou agente de host contratado. Logs incluem timestamp, event_code, request/job ID, tenant opaco e resultado; nunca corpo clínico, tokens, documentos, prompts integrais, senhas ou parâmetros sensíveis. Revisar filtros do Django/Celery e do painel antes de exposição; configuração WARNING do anexo, isoladamente, não faz essa sanitização.

### 19.5 Diagnóstico sem exposição de segredos

| Sintoma | Conferir | Correção e condição de retomada |
| --- | --- | --- |
| Pull/push negado | Login GHCR, permissão no pacote, digest/tag e rede | Corrigir autorização; preservar registry; não publicar tag diferente por tentativa |
| Variável ausente/parser | Chave em .env.example, formato literal, linha indicada; não imprimir valores | Corrigir arquivo, rodar geração/configuração novamente |
| Secret indisponível | Nome e montagem, role do serviço, modo de arquivo | Corrigir referência/permissão; não copiar secret para env_file |
| ACME/DNS | Zona do token, permissões, TXT propagado, horário, API e limites | Validar staging; migrar para produção após emissão real |
| Loop HTTPS/CSRF | Cloudflare Full strict, X-Forwarded-Proto confiável, hosts/origins | Corrigir proxy; não remover CSRF para fazer login funcionar |
| Worker sem internet | Redes anexadas, DNS/NAT, firewall e timeout do destino | Requisição neutra de diagnóstico; nunca enviar prontuário como probe |
| Broker não pronto | Health, credencial/vhost persistido, espaço e fila | Restaurar dependência e retomar com idempotência; restart finito pode exigir intervenção |
| Migration lock | Sessão detentora e migration ativa; versão/schema | Esperar ou interromper transação comprovadamente travada; não matar backend sem avaliar rollback |
| Asset 404/hash ausente | RELEASE_ID da página, .ready, manifesto, caminho e volume | Reproduzir collectstatic na área isolada; não limpar arquivos da release servida |
| Health redireciona | Ordem HealthMiddleware, Host localhost, URL exata | Restaurar exceção específica; não desligar HTTPS globalmente |
| Serviço pending/OOM | Recursos reservados, disco, label placement, memória do build | Liberar margem com ação controlada ou ampliar VPS; não remover todos os limites |
| Backup falha/trava | Lock de operação/GC, age, disco, banco e COMPLETE | Não rotacionar incompleto; corrigir e fazer novo conjunto/cópia externa |
| Assinatura indisponível após reboot | tmpfs recriado, PFX e chave mestra disponíveis | Médico reautoriza sessão; assinaturas já emitidas continuam preservadas |
| Restore com extensão/schema incompatível | Manifest/release exata e lista de extensões homologadas | Interromper e ajustar procedimento em ambiente separado; não ignorar erro de pg_restore |

Usar `docker service ps` e status agregado primeiro. Logs detalhados são lidos apenas em terminal autorizado, com janela curta e revisão de redaction; não colar saída integral em atendimento ou ferramentas externas.


## 20. Sprints e tarefas detalhadas

Premissa proposta: duas pessoas desenvolvedoras em tempo integral, responsável clínico/produto disponível semanalmente e apoio pontual de operação, design e governança. Sprints de duas semanas; 14 sprints representam cerca de 28 semanas de calendário **se as dependências externas forem resolvidas a tempo**. Não é promessa de prazo. Reservar capacidade para integração, correções e revisão médica; reestimar após S02/S05. As tarefas abaixo devem caber, preferencialmente, em até um dia de desenvolvimento; ao exceder isso, desdobrar mantendo o ID pai e o aceite.

Todos os itens estão abertos por se tratar de planejamento. Dependência indicada por uma sprint inteira significa seus critérios de saída; referências Txx apontam para tarefas específicas. A ausência de testes automatizados é mantida; verificação sintática, inspeção e homologação manual não constituem uma suíte automatizada do produto.

O caminho crítico é S02 (autorização/tenant) → S04/S05 (agenda e autoria) → S06/S07 (arquivo privado e assinatura) → S08 (entrega consistente) → S10 (recuperação e piloto). Para IA, P-06/P-09 e S11 antecedem qualquer transmissão externa; S12 depende desses controles. Operação começa em S01/S02 e ganha validação assistencial em S10, evitando deixá-la toda para o encerramento. M0 encerra em S02; M1 funcional após S07-T03; M2 em S10; M3 em S12; M4 em S14.

### S01 — Fundação técnica e dependências

**Objetivo/entregável:** Repositório organizado, resolução de versões e ambiente local reprodutível.

**Dependências:** Nenhuma; acesso ao material de produto e P-01/P-02.

- [x] **S01-T01 — Registrar decisões, limites e responsáveis pendentes.** Dependências: —. Componente: `docs/decisions.md`. Requisitos: RT-01, RT-04, RT-10. **Aceite:** P-01 a P-10 têm dono e condição de liberação.

- [x] **S01-T02 — Conferir o design system e inventariar tokens/componentes.** Dependências: P-01. Componente: `docs/design-system.md`. Requisitos: RNF-01.09. **Aceite:** Tokens extraídos do arquivo real, sem identidade visual inventada.

- [x] **S01-T03 — Resolver requirements.in no Python 3.14 e congelar hashes.** Dependências: P-04. Componente: `requirements.in, requirements.txt`. Requisitos: RT-01. **Aceite:** Build instala o lock e pip check não indica conflito.

- [x] **S01-T04 — Criar pacote core, base e esqueleto dos apps de domínio.** Dependências: S01-T01. Componente: `core/, base/, apps na raiz`. Requisitos: RT-01. **Aceite:** Django carrega apps com um único settings.py.

- [x] **S01-T05 — Integrar parser literal e leitura de secrets por arquivo.** Dependências: S01-T04. Componente: `ops/env.py, core/settings.py`. Requisitos: RT-06. **Aceite:** Valor especial é lido como dado e erro nunca mostra o secret.

- [x] **S01-T06 — Integrar Dockerfile, entrypoints e commands de espera.** Dependências: S01-T03, S01-T04. Componente: `Dockerfile, ops/, base/management/commands/`. Requisitos: RT-05, RT-08. **Aceite:** Container não inicia HTTP antes de preparar banco/schema/assets.

- [x] **S01-T07 — Preparar os sete serviços locais e volumes.** Dependências: S01-T06. Componente: `compose.yml, ops/local_compose.py`. Requisitos: RT-05. **Aceite:** Compose local converge com canais externos desabilitados.

- [x] **S01-T08 — Criar MkDocs com Mermaid e páginas iniciais de operação.** Dependências: S01-T04. Componente: `docs/, mkdocs.yml`. Requisitos: RF-12.03, RT-01. **Aceite:** mkdocs build --strict gera páginas e diagrama legíveis.

- [x] **S01-T09 — Inspecionar baseline de VPS, imagens e versões de pacotes.** Dependências: P-02, S01-T03. Componente: `docs/operations/environment.md`. Requisitos: RT-05, RT-09. **Aceite:** Arquitetura e digests disponíveis registrados, sem latest.

- [x] **S01-T10 — Registrar inventário de permissões e superfícies de acesso.** Dependências: S01-T01. Componente: `docs/security/access-surfaces.md`. Requisitos: RT-02, RT-03. **Aceite:** Listagem inclui admin, jobs, anexos, exports, cache e SSE.

- [x] **Saída de S01:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S02 — Identidade, tenants e auditoria

**Objetivo/entregável:** Acesso negado por padrão, relações coerentes e baseline M0 técnico.

**Dependências:** S01; usuário customizado definido antes da primeira migration.

- [x] **S02-T01 — Criar User por e-mail e migração inicial de identidade.** Dependências: S01-T04. Componente: `accounts/models.py`. Requisitos: RF-01.04, RT-02. **Aceite:** Login não depende de username e unicidade normalizada é preservada.

- [x] **S02-T02 — Criar Tenant, Membership e papéis acumuláveis.** Dependências: S02-T01. Componente: `tenancy/models.py`. Requisitos: RF-01.05, RT-02. **Aceite:** Mesmo usuário tem papéis distintos em duas clínicas fictícias.

- [x] **S02-T03 — Implementar AccessContext e seleção de tenant.** Dependências: S02-T02. Componente: `tenancy/context.py, selectors.py`. Requisitos: RT-02. **Aceite:** Ausência de vínculo ativo nega resolução de objetos.

- [x] **S02-T04 — Implementar middleware com exceções públicas explícitas.** Dependências: S02-T03. Componente: `tenancy/middleware.py`. Requisitos: RT-02, RT-07. **Aceite:** Host arbitrário e tenant do cliente não concedem acesso.

- [x] **S02-T05 — Criar garantias compostas de tenant em migrations comuns.** Dependências: S02-T02. Componente: `tenancy/migrations/, base/models.py`. Requisitos: RT-02. **Aceite:** Inserção manual de FK cruzada no banco falha.

- [x] **S02-T06 — Integrar sessões, recuperação nativa e revogação de acesso.** Dependências: S02-T01, S02-T03. Componente: `accounts/views.py, forms.py, services.py`. Requisitos: RF-01.04, RF-01.05. **Aceite:** H-02 encerra acesso revogado e não enumera contas.

- [x] **S02-T07 — Implementar MFA TOTP, recuperação e habilitação privilegiada.** Dependências: S02-T06. Componente: `accounts/mfa.py, templates/accounts/`. Requisitos: RT-03, RF-04.03. **Aceite:** Operação privilegiada exige verificação recente e recovery code é de uso único.

- [x] **S02-T08 — Criar AuditEvent e API explícita de auditoria.** Dependências: S02-T03. Componente: `audit/models.py, services.py`. Requisitos: RT-03. **Aceite:** Registra acesso/negação sem texto clínico nem token.

- [x] **S02-T09 — Adicionar redaction de logs e limites de autenticação.** Dependências: S02-T08. Componente: `base/logging.py, accounts/throttling.py`. Requisitos: RT-03. **Aceite:** Logs inspecionados não contêm senha, corpo clínico ou token.

- [x] **S02-T10 — Proteger Admin, painéis técnicos e rotas MkDocs.** Dependências: S02-T04, S02-T07, S01-T08. Componente: `core/urls.py, admin.py, ops/docs.py`. Requisitos: RF-12.01, RF-12.03. **Aceite:** Usuário comum não abre nenhuma URL dos três pacotes do painel.

- [x] **S02-T11 — Homologar isolamento inicial e deploy técnico M0.** Dependências: S02-T05, S02-T10, S01-T09. Componente: `docs/homologation/M0.md`. Requisitos: RT-02, RT-08, RT-09. **Aceite:** H-02/H-03/H-19 básicos e H-21 técnico registrados com dados sintéticos.

- [x] **Saída de S02:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S03 — Onboarding, pacientes e catálogos

**Objetivo/entregável:** Clínicas convidadas cadastram pacientes e selecionam referências válidas.

**Dependências:** S02; material visual P-01 e versão das fontes de catálogo.

- [x] **S03-T01 — Criar convite inicial com hash, expiração e consumo transacional.** Dependências: S02. Componente: `tenancy/invitations.py`. Requisitos: RF-01.02, RF-01.03. **Aceite:** Duas tentativas simultâneas não consomem o mesmo convite.

- [x] **S03-T02 — Montar landing e formulário de organização/plano free.** Dependências: S03-T01, S01-T02. Componente: `base/views.py, templates/onboarding/`. Requisitos: RF-01.01, RF-01.03. **Aceite:** CNPJ/razão social obrigatórios e planos futuros não são contratáveis.

- [x] **S03-T03 — Implementar convites internos e gestão de colaboradores.** Dependências: S03-T01. Componente: `tenancy/views.py, forms.py`. Requisitos: RF-01.05. **Aceite:** Owner não atribui automaticamente habilitação médica.

- [x] **S03-T04 — Criar Patient com validações e unicidades condicionais.** Dependências: S02-T05. Componente: `patients/models.py, forms.py`. Requisitos: RF-02.01, RF-02.02. **Aceite:** Menor sem CPF é aceito e duplicidade não revela outro tenant.

- [x] **S03-T05 — Criar contatos autorizados e responsável legal.** Dependências: S03-T04. Componente: `patients/contacts.py, templates/patients/`. Requisitos: RF-02.01, RF-09.03. **Aceite:** Contato de entrega exige finalidade e vínculo registrado.

- [x] **S03-T06 — Implementar lista, detalhe, busca e arquivamento.** Dependências: S03-T04. Componente: `patients/views.py, selectors.py`. Requisitos: RF-02.01, RF-02.02. **Aceite:** H-04 mantém histórico após arquivamento e paginação estável.

- [x] **S03-T07 — Integrar consulta ViaCEP com timeout e edição manual.** Dependências: S03-T04. Componente: `integrations/cep.py`. Requisitos: RF-02.03. **Aceite:** Falha/erro do serviço deixa cadastro utilizável e não altera complemento.

- [x] **S03-T08 — Criar medições históricas, idade contextual e cálculo IMC.** Dependências: S03-T04. Componente: `patients/observations.py`. Requisitos: RF-02.04. **Aceite:** Medições anteriores permanecem e unidades inválidas são recusadas.

- [x] **S03-T09 — Cadastrar operadoras/planos e modalidade particular.** Dependências: S03-T04. Componente: `patients/coverage.py, forms.py`. Requisitos: RF-02.05. **Aceite:** Plano pertence à operadora e vigência é explícita.

- [x] **S03-T10 — Criar importador versionado de CID-10/TUSS com dry-run.** Dependências: P-04, S03-T09. Componente: `catalogs/importers.py, management/commands/`. Requisitos: RF-02.05. **Aceite:** Carga usa fonte/versionamento reais e não altera descrição histórica.

- [x] **S03-T11 — Implementar fixtures sintéticas idempotentes de dois tenants.** Dependências: S03-T06, S03-T09. Componente: `base/management/commands/seed_demo.py`. Requisitos: RF-12.02. **Aceite:** Rodar duas vezes não duplica cadastro nem dispara comunicação.

- [x] **S03-T12 — Homologar onboarding/cadastro e componentes de formulário.** Dependências: S03-T02, S03-T10, S03-T11. Componente: `docs/homologation/patients.md`. Requisitos: RF-01, RF-02, RNF-01.09. **Aceite:** H-01/H-04/H-05 por teclado e em celular registrados.

- [x] **Saída de S03:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S04 — Agenda e trabalho da secretaria

**Objetivo/entregável:** Reserva consistente, calendário e pendências administrativas.

**Dependências:** S03; isolamento e contatos estabelecidos.

- [x] **S04-T01 — Modelar disponibilidade semanal e duração por tipo.** Dependências: S03. Componente: `scheduling/models.py, forms.py`. Requisitos: RF-06.01, RF-06.02. **Aceite:** Regra semanal não aceita intervalo inválido.

- [x] **S04-T02 — Implementar bloqueios, férias e exceções por data.** Dependências: S04-T01. Componente: `scheduling/availability.py`. Requisitos: RF-06.02. **Aceite:** Exceção datada prevalece sem alterar histórico semanal.

- [x] **S04-T03 — Criar Appointment, estados e histórico de remarcação.** Dependências: S04-T01. Componente: `scheduling/models.py`. Requisitos: RF-06.03, RF-06.04. **Aceite:** Transições ilegais são recusadas no service.

- [x] **S04-T04 — Adicionar exclusion constraint e reserva transacional.** Dependências: S04-T03, S02-T05. Componente: `scheduling/services.py, migrations/`. Requisitos: RF-06.03. **Aceite:** H-12 com duas abas confirma apenas uma reserva comum sobreposta.

- [x] **S04-T05 — Implementar encaixe com permissão, motivo e lock estável.** Dependências: S04-T04. Componente: `scheduling/services.py`. Requisitos: RF-06.03. **Aceite:** Encaixe exige justificativa e não ignora bloqueio sem autorização.

- [x] **S04-T06 — Montar calendário dia/semana/mês e lista móvel.** Dependências: S04-T04, S01-T02. Componente: `templates/scheduling/, static/scheduling/`. Requisitos: RF-06.01, RNF-01.09. **Aceite:** Remarcar por botão/teclado e não apenas arrastar.

- [x] **S04-T07 — Implementar check-in, confirmação, falta e cancelamento.** Dependências: S04-T03. Componente: `scheduling/views.py`. Requisitos: RF-06.04. **Aceite:** Cancelar libera horário e mantém trilha de estados.

- [x] **S04-T08 — Montar painel da secretaria com contatos e pendências.** Dependências: S04-T06, S03-T05. Componente: `templates/scheduling/desk.html`. Requisitos: RF-06.05. **Aceite:** Sem notas clínicas ou diagnóstico em cards/contadores.

- [x] **S04-T09 — Gravar eventos de lembrete com versão do agendamento.** Dependências: S04-T07. Componente: `scheduling/events.py, events/models.py`. Requisitos: RF-06.04, RF-09. **Aceite:** Remarcação invalida lembretes da versão anterior.

- [x] **S04-T10 — Homologar limites, timezone e concorrência da agenda.** Dependências: S04-T05, S04-T08, S04-T09. Componente: `docs/homologation/scheduling.md`. Requisitos: RF-06, RT-02. **Aceite:** H-12 inclui duas abas, cancelamento e consultas adjacentes.

- [x] **Saída de S04:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S05 — Prontuário e exame neurológico

**Objetivo/entregável:** Atendimento longitudinal revisado e imutável após finalização.

**Dependências:** S04 e acesso clínico por paciente.

- [x] **S05-T01 — Modelar Encounter, autoria, estados e row_version.** Dependências: S03-T04, S02-T05. Componente: `clinical/models.py`. Requisitos: RF-03.01, RF-03.05. **Aceite:** Tenant/médico/paciente obrigatórios e estados controlados.

- [x] **S05-T02 — Montar história clínica, antecedentes e consanguinidade.** Dependências: S05-T01. Componente: `clinical/forms.py, templates/clinical/`. Requisitos: RF-03.02. **Aceite:** Todos os blocos clínicos solicitados têm campo e origem claros.

- [x] **S05-T03 — Criar achados cognitivos e força por segmento/lado.** Dependências: S05-T01. Componente: `clinical/examination.py`. Requisitos: RF-03.03. **Aceite:** Normal/alterado/não avaliado/não informado são distintos.

- [x] **S05-T04 — Criar sensibilidade superficial/profunda e reflexos.** Dependências: S05-T03. Componente: `clinical/examination.py`. Requisitos: RF-03.03. **Aceite:** Qualificadores e lateralidade não se contradizem.

- [x] **S05-T05 — Criar coordenação, marcha, equilíbrio e tônus.** Dependências: S05-T03. Componente: `clinical/examination.py`. Requisitos: RF-03.03. **Aceite:** Controles propostos são identificados e não vêm normais por padrão.

- [x] **S05-T06 — Criar nervos cranianos I a VI individualmente.** Dependências: S05-T03. Componente: `clinical/cranial_nerves.py`. Requisitos: RF-03.03. **Aceite:** Cada nervo mantém achado, lado e limitação quando aplicável.

- [x] **S05-T07 — Criar nervos cranianos VII a XII individualmente.** Dependências: S05-T06. Componente: `clinical/cranial_nerves.py`. Requisitos: RF-03.03. **Aceite:** Não existe um único campo indiferenciado para todos os nervos.

- [x] **S05-T08 — Implementar cópia segura do atendimento anterior.** Dependências: S05-T02, S03-T10. Componente: `clinical/carry_forward.py`. Requisitos: RF-03.04. **Aceite:** Origem correta, revisão pendente e nenhum novo exame físico/pedido automático.

- [x] **S05-T09 — Implementar autosave com conflito e recuperação de rascunho.** Dependências: S05-T01, S05-T02. Componente: `clinical/views.py, static/clinical/`. Requisitos: RF-03.05, RNF-01.03. **Aceite:** Duas abas não sobrescrevem revisão silenciosamente.

- [x] **S05-T10 — Implementar finalização transacional e adendo imutável.** Dependências: S05-T07, S05-T08, S05-T09. Componente: `clinical/finalization.py`. Requisitos: RF-03.06, RT-03. **Aceite:** Original preservado, autoria/hash e adendo visíveis.

- [x] **S05-T11 — Montar linha do tempo e navegação longitudinal.** Dependências: S05-T10. Componente: `clinical/selectors.py, templates/clinical/timeline.html`. Requisitos: RF-03.01. **Aceite:** Eventos são cronológicos e obedecem concessão clínica.

- [x] **S05-T12 — Homologar prontuário com médico responsável.** Dependências: S05-T11. Componente: `docs/homologation/clinical.md`. Requisitos: RF-03, RT-02, RT-03. **Aceite:** H-06/H-07 aprovados sem achado normal implícito.

- [x] **Saída de S05:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S06 — Anexos privados e processamento local

**Objetivo/entregável:** Upload em quarentena, download autorizado e base de consistência do backup.

**Dependências:** S05; contrato de arquivo imutável e autorização.

- [x] **S06-T01 — Criar Attachment, classes, metadados e quotas.** Dependências: S05. Componente: `documents/models.py`. Requisitos: RF-05.01. **Aceite:** Limites de tamanho/página e classe do arquivo são persistidos.

- [x] **S06-T02 — Implementar gravação temporária e publicação atômica.** Dependências: S06-T01. Componente: `documents/storage.py`. Requisitos: RF-05.01, RT-10. **Aceite:** Banco só referencia arquivo publicado e nenhum original é sobrescrito.

- [x] **S06-T03 — Validar extensão, MIME e estrutura de PDF/imagem/DOCX.** Dependências: S06-T02. Componente: `documents/validators.py`. Requisitos: RF-05.02. **Aceite:** Arquivo disfarçado e traversal são recusados antes do processamento.

- [x] **S06-T04 — Integrar ClamAV local e atualização de definições.** Dependências: S06-T03. Componente: `documents/tasks.py, integrations/antivirus.py`. Requisitos: RF-05.02. **Aceite:** Definição ausente/antiga mantém quarentena com erro visível.

- [x] **S06-T05 — Criar preview local com limites de CPU/memória/páginas.** Dependências: S06-T04. Componente: `documents/preview.py`. Requisitos: RF-05.02. **Aceite:** Arquivo grande não monopoliza worker e preview não executa conteúdo ativo.

- [x] **S06-T06 — Implementar download e preview por objeto autorizado.** Dependências: S06-T04. Componente: `documents/views.py`. Requisitos: RF-05.03, RT-02. **Aceite:** H-10/H-03 negam URL conhecida de outro tenant.

- [x] **S06-T07 — Implementar classificação, vínculo e data do exame.** Dependências: S06-T06. Componente: `documents/forms.py`. Requisitos: RF-05.01, RF-03.01. **Aceite:** Mudança de paciente/atendimento valida contexto e é auditada.

- [x] **S06-T08 — Criar remoção lógica e GC com lock de backup.** Dependências: S06-T02. Componente: `documents/retention.py`. Requisitos: RT-03, RT-10. **Aceite:** GC não remove arquivo referenciado nem atua durante backup.

- [x] **S06-T09 — Implementar OCR local e origem do texto extraído.** Dependências: S06-T05. Componente: `documents/ocr.py`. Requisitos: RF-05.02, RT-04. **Aceite:** OCR identificado permanece local e mantém proveniência de página.

- [x] **S06-T10 — Homologar arquivos e fechamento da etapa de anexos.** Dependências: S06-T07, S06-T08, S06-T09. Componente: `docs/homologation/attachments.md`. Requisitos: RF-05, RT-03. **Aceite:** H-10 inclui malware sintético permitido, formatos ruins e acesso cruzado.

- [x] **Saída de S06:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S07 — Documentos médicos e assinatura

**Objetivo/entregável:** Documento revisado, assinado e preservado, pronto para fluxo de entrega.

**Dependências:** S05/S06; P-05/P-07 e titularidade do certificado.

- [ ] **S07-T01 — Modelar MedicalDocument, versões e estados de emissão.** Dependências: S06. Componente: `documents/models.py`. Requisitos: RF-04.01, RF-04.04. **Aceite:** PDF gerado não é tratado como documento emitido.

- [ ] **S07-T02 — Criar template de receita comum e campos por modalidade.** Dependências: S07-T01, P-05. Componente: `documents/pdf/prescription.py`. Requisitos: RF-04.01. **Aceite:** Médico revisa conteúdo/identificação antes da assinatura.

- [ ] **S07-T03 — Criar templates de relatório, pedido e encaminhamento.** Dependências: S07-T02. Componente: `documents/pdf/`. Requisitos: RF-04.01. **Aceite:** Cada tipo tem campos obrigatórios definidos e layout do design system.

- [ ] **S07-T04 — Implementar upload PFX, envelope e metadados públicos.** Dependências: S07-T01, S02-T07. Componente: `documents/credentials.py`. Requisitos: RF-04.02, RT-03. **Aceite:** Certificado privado não entra em media, logs ou worker.

- [ ] **S07-T05 — Implementar sessão 2/4/6/12 h com chave em tmpfs.** Dependências: S07-T04. Componente: `documents/signing_sessions.py`. Requisitos: RF-04.03. **Aceite:** Expiração no servidor, vínculo à sessão web e chave não persistente.

- [ ] **S07-T06 — Implementar revogação, limpeza e invalidação no reboot.** Dependências: S07-T05. Componente: `documents/signing_sessions.py, maintenance`. Requisitos: RF-04.03, RT-03. **Aceite:** Revogação impede novo uso em ambas as réplicas.

- [ ] **S07-T07 — Integrar assinatura PAdES com pyHanko e validação.** Dependências: S07-T03, S07-T05, P-05. Componente: `documents/signing.py`. Requisitos: RF-04.04. **Aceite:** Senha inválida, revogação, expiração e falha não produzem estado issued.

- [ ] **S07-T08 — Implementar confirmação médica por documento e auditoria.** Dependências: S07-T07. Componente: `documents/views.py, audit/`. Requisitos: RF-04.03, RF-04.04. **Aceite:** Secretaria/IA não conseguem assinar com sessão do médico.

- [ ] **S07-T09 — Persistir arquivo final, hash e evento de emissão.** Dependências: S07-T08, S06-T02. Componente: `documents/issuance.py, events/`. Requisitos: RF-04.05. **Aceite:** Evento só existe após assinatura válida e arquivo final disponível.

- [ ] **S07-T10 — Homologar certificado autorizado com documento sintético.** Dependências: S07-T09, P-05. Componente: `docs/homologation/signing.md`. Requisitos: RF-04, RT-03. **Aceite:** H-08 registra evidência de validação, sem PFX/senha nos anexos.

- [ ] **Saída de S07:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S08 — Comunicações, outbox e notificações

**Objetivo/entregável:** Entrega protegida, lembretes e falhas conciliáveis.

**Dependências:** S04/S07; contratos e credenciais P-03.

- [ ] **S08-T01 — Criar dispatcher outbox com lease e ProcessedEvent.** Dependências: S04-T09, S07-T09. Componente: `events/dispatcher.py, tasks.py`. Requisitos: RT-08, RF-09.04. **Aceite:** Redelivery não duplica efeito de negócio.

- [ ] **S08-T02 — Modelar Delivery e DeliveryAttempt por canal.** Dependências: S08-T01. Componente: `communications/models.py`. Requisitos: RF-09.01, RF-09.04. **Aceite:** Aceito pelo provedor difere de entrega confirmada.

- [ ] **S08-T03 — Integrar backend nativo de e-mail no worker.** Dependências: S08-T02, P-03. Componente: `communications/email.py`. Requisitos: RF-09.01, RF-01.04. **Aceite:** Recuperação/convite/documento usam fila e remetente autorizado.

- [ ] **S08-T04 — Implementar adaptador SMSDEV POST JSON e timeout.** Dependências: S08-T02, P-03. Componente: `communications/smsdev.py`. Requisitos: RF-09.01. **Aceite:** Endpoint e campos reais homologados com destinatário autorizado.

- [ ] **S08-T05 — Criar links opacos, OTP, tentativas e revogação.** Dependências: S07-T09, S08-T03. Componente: `communications/access.py`. Requisitos: RF-09.02. **Aceite:** Link isolado não abre documento e token não revela identificadores.

- [ ] **S08-T06 — Conectar emissão à entrega em ambos os canais elegíveis.** Dependências: S08-T04, S08-T05. Componente: `communications/services.py`. Requisitos: RF-04.05, RF-09.03. **Aceite:** Ausência de contato gera pendência sem invalidar emissão.

- [ ] **S08-T07 — Conectar lembretes às versões atuais de agenda.** Dependências: S08-T01, S04-T09. Componente: `scheduling/tasks.py`. Requisitos: RF-06.04, RF-09. **Aceite:** Remarcação/cancelamento impede lembrete obsoleto.

- [ ] **S08-T08 — Implementar unknown, reconciliação e reenvio autorizado.** Dependências: S08-T04, S08-T06. Componente: `communications/reconciliation.py`. Requisitos: RF-09.04. **Aceite:** Timeout ambíguo não gera retry cego.

- [ ] **S08-T09 — Criar Notification e caixa interna com read_at.** Dependências: S08-T01. Componente: `notifications/models.py, views.py`. Requisitos: RF-11, RT-02. **Aceite:** Notificação persiste e não aparece em outro tenant.

- [ ] **S08-T10 — Homologar comunicação e falhas de dependência.** Dependências: S08-T07, S08-T08, S08-T09. Componente: `docs/homologation/communications.md`. Requisitos: RF-09, RT-08. **Aceite:** H-09 diferencia accepted/delivered/unknown sem envio clínico no texto.

- [ ] **Saída de S08:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S09 — CRM e financeiro

**Objetivo/entregável:** Gestão administrativa rastreável e separada do prontuário.

**Dependências:** S04/S08; regras de valores aprovadas pelo produto.

- [ ] **S09-T01 — Modelar etapas, cards e transições do CRM.** Dependências: S04. Componente: `crm/models.py`. Requisitos: RF-07.01. **Aceite:** Etapa administrativa é distinta do estado clínico.

- [ ] **S09-T02 — Criar kanban/grid com filtros e ação por teclado.** Dependências: S09-T01. Componente: `crm/views.py, templates/crm/`. Requisitos: RF-07.01. **Aceite:** Cards não exibem diagnósticos e movem por botão.

- [ ] **S09-T03 — Integrar agenda por evento explícito e histórico.** Dependências: S09-T02, S08-T01. Componente: `crm/events.py`. Requisitos: RF-07.02. **Aceite:** Mover card não finaliza consulta ou emite documento.

- [ ] **S09-T04 — Modelar tabelas de preço/repasse com vigência.** Dependências: S03-T09. Componente: `finance/models.py`. Requisitos: RF-08.01. **Aceite:** Regra equivalente não tem períodos sobrepostos.

- [ ] **S09-T05 — Implementar escolha da regra e snapshot do atendimento.** Dependências: S09-T04, S05-T10. Componente: `finance/pricing.py`. Requisitos: RF-08.01, RF-08.02. **Aceite:** Mudança de tabela não altera consulta histórica.

- [ ] **S09-T06 — Criar recebível por evento idempotente.** Dependências: S09-T05, S08-T01. Componente: `finance/receivables.py`. Requisitos: RF-08.02. **Aceite:** Reprocessar finalização não duplica lançamento.

- [ ] **S09-T07 — Implementar pagamentos parciais e estado do saldo.** Dependências: S09-T06. Componente: `finance/payments.py`. Requisitos: RF-08.03. **Aceite:** Decimal e arredondamento centavo conciliam soma e saldo.

- [ ] **S09-T08 — Implementar ajustes/estornos com motivo e auditoria.** Dependências: S09-T07. Componente: `finance/adjustments.py`. Requisitos: RF-08.03. **Aceite:** Estorno não apaga recebimento original.

- [ ] **S09-T09 — Criar visões distintas de competência e caixa.** Dependências: S09-T08. Componente: `finance/selectors.py, templates/finance/`. Requisitos: RF-08.04. **Aceite:** Valores de datas diferentes aparecem no período correto.

- [ ] **S09-T10 — Homologar CRM/financeiro e privacidade administrativa.** Dependências: S09-T03, S09-T09. Componente: `docs/homologation/management.md`. Requisitos: RF-07, RF-08, RT-02. **Aceite:** H-13/H-14 fecham valores sem leitura de notas clínicas.

- [ ] **Saída de S09:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S10 — Operação e piloto assistencial

**Objetivo/entregável:** M2 recuperável, com acesso/assinatura/entrega e operação homologados.

**Dependências:** S02–S09; P-02/P-05/P-06/P-10 resolvidas para uso real.

- [ ] **S10-T01 — Integrar anexos de deploy ao repositório implementado.** Dependências: S01, S09. Componente: `ops/, scripts/, docker-stack.yml`. Requisitos: RT-05, RT-06, RT-07. **Aceite:** Nomes/redes/secrets/arquivos usados correspondem ao guia.

- [ ] **S10-T02 — Homologar primeira publicação e certificado na origem.** Dependências: S10-T01, P-02. Componente: `docs/operations/deploy.md`. Requisitos: RT-07, RT-08. **Aceite:** H-21 staging/prod e wildcard sem loop nem portas internas públicas.

- [ ] **S10-T03 — Homologar rollout simultâneo de páginas e assets.** Dependências: S10-T02. Componente: `ops/runtime.py, ops/staticfiles.py`. Requisitos: RT-09. **Aceite:** Duas releases coexistem sem limpeza do diretório servido.

- [ ] **S10-T04 — Validar migrations expand e rollback de aplicação.** Dependências: S10-T03. Componente: `docs/operations/rollback.md`. Requisitos: RT-09. **Aceite:** Rollback não depende de downgrade destrutivo e worker/beat são coerentes.

- [ ] **S10-T05 — Instalar timer de backup e cópia externa autorizada.** Dependências: S06-T08, S10-T02, P-10. Componente: `ops/backup.py, timer, integração do destino`. Requisitos: RT-10. **Aceite:** Conjunto COMPLETE íntegro chega fora da VPS e falha gera alerta.

- [ ] **S10-T06 — Executar restauração isolada de banco/mídia/PFX.** Dependências: S10-T05. Componente: `ops/restore.py, docs/operations/restore.md`. Requisitos: RT-10, RNF-01.06. **Aceite:** H-22 registra RPO/RTO e comprova acesso à chave de recuperação.

- [ ] **S10-T07 — Criar command de pós-restauração e reconciliação.** Dependências: S10-T06, S08-T08. Componente: `base/management/commands/prepare_recovery.py`. Requisitos: RT-03, RT-10. **Aceite:** Expira sessões/tokens e suspende entregas pendentes sem apagar prontuário.

- [ ] **S10-T08 — Configurar métricas operacionais e redaction final.** Dependências: S02-T09, S10-T02. Componente: `base/logging.py, docs/operations/monitoring.md`. Requisitos: RNF-01.04, RNF-01.05, RNF-01.08. **Aceite:** Alertas chegam ao destinatário definido e logs não mostram dados clínicos.

- [ ] **S10-T09 — Revisar inventário LGPD, contratos e modalidades documentais.** Dependências: P-05, P-06, P-07, S07. Componente: `docs/governance/`. Requisitos: RT-03, RF-04. **Aceite:** Responsáveis assinam registro de liberação por finalidade/modalidade.

- [ ] **S10-T10 — Executar homologação M2 com duas clínicas fictícias.** Dependências: S10-T04, S10-T07, S10-T08, S10-T09. Componente: `docs/homologation/M2.md`. Requisitos: RF-01 a RF-09, RT-02, RT-03. **Aceite:** Critérios bloqueantes da seção 21 satisfeitos antes de convidar clínica real.

- [ ] **Saída de S10:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S11 — IA com autorização e revisão médica

**Objetivo/entregável:** Análise e resumo versionados, bloqueados quando a política não permite envio.

**Dependências:** S05/S06/S08; P-06/P-09 e provedor final aprovados.

- [ ] **S11-T01 — Modelar AIJob, AIArtifact e revisão clínica versionada.** Dependências: S05-T10. Componente: `ai/models.py`. Requisitos: RF-11.01, RF-11.02. **Aceite:** Nova geração não sobrescreve artefato revisado anterior.

- [ ] **S11-T02 — Criar adaptador OpenRouter com modelo padrão explícito.** Dependências: S01-T03, P-03. Componente: `ai/providers/openrouter.py`. Requisitos: RT-04. **Aceite:** Identificador, streaming/tools e limitações de schema documentados.

- [ ] **S11-T03 — Criar adaptadores OpenAI/Anthropic e seleção autorizada.** Dependências: S11-T02. Componente: `ai/providers/`. Requisitos: RT-04. **Aceite:** Troca de provedor é explícita e não amplia política de dados.

- [ ] **S11-T04 — Implementar autorização e seleção mínima local.** Dependências: S11-T01, S02-T03. Componente: `ai/context.py`. Requisitos: RT-02, RT-04. **Aceite:** Usuario revogado e patient_id arbitrário não entram no job.

- [ ] **S11-T05 — Implementar desidentificação local de texto/metadados/OCR.** Dependências: S11-T04, S06-T09. Componente: `ai/deidentification.py`. Requisitos: RF-11.06, RT-04. **Aceite:** Originais identificados nunca são enviados para anonimização externa.

- [ ] **S11-T06 — Implementar decisão de risco residual e fail closed.** Dependências: S11-T05, P-06. Componente: `ai/privacy_policy.py`. Requisitos: RF-11.06. **Aceite:** Caso raro/genealogia não seguro vira blocked_privacy sem request.

- [ ] **S11-T07 — Criar tools de linha do tempo e achados de exame.** Dependências: S11-T04, S11-T06. Componente: `ai/tools/clinical.py`. Requisitos: RT-04. **Aceite:** Tool revalida escopo e limita páginas/linhas/chamadas.

- [ ] **S11-T08 — Criar tools administrativas/financeiras separadas.** Dependências: S11-T07, S09. Componente: `ai/tools/administrative.py`. Requisitos: RT-02, RT-04. **Aceite:** Chat administrativo não obtém nota clínica nem certificado.

- [ ] **S11-T09 — Montar grafo, schema Pydantic e limites de custo/tempo.** Dependências: S11-T02, S11-T06, S11-T07. Componente: `ai/graphs.py, schemas.py`. Requisitos: RT-04, RF-11.05. **Aceite:** Saída inválida/referência inventada não é apresentada como válida.

- [ ] **S11-T10 — Conectar finalização/resumo manual à fila e notificação.** Dependências: S11-T09, S08-T09. Componente: `ai/tasks.py, views.py`. Requisitos: RF-11.01, RF-11.02. **Aceite:** Falha de IA preserva atendimento e informa resultado ao solicitante.

- [ ] **S11-T11 — Montar revisão médica aceitar/editar/rejeitar e stale.** Dependências: S11-T10. Componente: `ai/review.py, templates/ai/`. Requisitos: RF-11.05, RT-03. **Aceite:** Aceitar não assina/prescreve e fonte alterada torna rascunho stale.

- [ ] **S11-T12 — Homologar casos de privacidade, injeção e insuficiência.** Dependências: S11-T08, S11-T11, P-09. Componente: `docs/homologation/ai.md`. Requisitos: RF-11, RT-04. **Aceite:** H-17 registra bloqueio, limites e decisão médica sem alegar acurácia.

- [ ] **Saída de S11:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S12 — Chat persistente e streaming

**Objetivo/entregável:** Sessões isoladas, SSE real e experiência de trabalho sem bloqueio da página.

**Dependências:** S11 e middleware async homologado.

- [ ] **S12-T01 — Modelar sessões/mensagens e contexto explícito de paciente.** Dependências: S11-T01. Componente: `ai/chat_models.py`. Requisitos: RF-11.03. **Aceite:** Trocar tenant não reaproveita histórico/contexto automaticamente.

- [ ] **S12-T02 — Criar lista de sessões, título e navegação lateral.** Dependências: S12-T01. Componente: `ai/chat_views.py, templates/ai/chat/`. Requisitos: RF-11.03. **Aceite:** Sessões pertencem ao usuário/tenant correto.

- [ ] **S12-T03 — Implementar publicação Redis Streams por job e sequência.** Dependências: S12-T01, S11-T09. Componente: `ai/streaming.py`. Requisitos: RF-11.04. **Aceite:** Chave inclui tenant/user/session/job e TTL de 1 h.

- [ ] **S12-T04 — Criar endpoint SSE com autorização e heartbeat.** Dependências: S12-T03, S02-T04. Componente: `ai/sse.py`. Requisitos: RF-11.04, RT-02. **Aceite:** Revogação interrompe leitura e não mantém conexão ORM aberta.

- [ ] **S12-T05 — Implementar reconexão por Last-Event-ID e buffer expirado.** Dependências: S12-T04. Componente: `ai/sse.py, static/ai/chat.js`. Requisitos: RF-11.04. **Aceite:** Reconectar não duplica mensagem nem acessa stream alheia.

- [ ] **S12-T06 — Implementar cancelamento e limite de concorrência.** Dependências: S12-T03, S11-T09. Componente: `ai/cancellation.py`. Requisitos: RF-11.04, RT-04. **Aceite:** Cancelamento fica persistido e não promete estorno de custo.

- [ ] **S12-T07 — Integrar Markdown incremental e final sanitizado.** Dependências: S12-T04. Componente: `ai/rendering.py, static/ai/chat.js`. Requisitos: RF-11.04, RT-03. **Aceite:** Scripts/links perigosos não executam durante streaming.

- [ ] **S12-T08 — Persistir conclusão/notificação e referências de origem.** Dependências: S12-T05, S08-T09. Componente: `ai/chat_services.py`. Requisitos: RF-11.03, RF-11.04. **Aceite:** Resultado final sobrevive à perda do Redis.

- [ ] **S12-T09 — Homologar SSE através do Traefik durante rollout.** Dependências: S12-T07, S12-T08, S10-T03. Componente: `docs/homologation/chat.md`. Requisitos: RF-11, RT-09. **Aceite:** H-18 preserva escopo e comunica reconexão/interrupção.

- [ ] **Saída de S12:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S13 — Relatórios e captura local

**Objetivo/entregável:** M4 funcional: indicadores definidos e captura vinculada ao atendimento.

**Dependências:** S09/S12; método analítico, P-08 e política de exportação.

- [ ] **S13-T01 — Criar seletores dos indicadores de pacientes/seguimento.** Dependências: S05, S09. Componente: `reporting/patients.py`. Requisitos: RF-10.01. **Aceite:** Numeradores e faltantes reproduzem a tabela da seção 13.

- [ ] **S13-T02 — Criar indicadores de agenda, modalidade e financeiro.** Dependências: S13-T01. Componente: `reporting/operations.py`. Requisitos: RF-10.01. **Aceite:** Caixa/competência e unidade paciente/consulta não se confundem.

- [ ] **S13-T03 — Montar dashboard, filtros e tabelas alternativas.** Dependências: S13-T02, S01-T02. Componente: `templates/reporting/, static/reporting/`. Requisitos: RF-10.01, RNF-01.09. **Aceite:** Gráfico mostra período, unidade, n e dados ausentes.

- [ ] **S13-T04 — Implementar CSV seguro e supressão gerencial.** Dependências: S13-T02. Componente: `reporting/exporters.py`. Requisitos: RF-10.02, RF-10.03. **Aceite:** Células com fórmula não executam e filtro não expõe clínica alheia.

- [ ] **S13-T05 — Implementar PDF e exportação grande assíncrona privada.** Dependências: S13-T04, S08-T09. Componente: `reporting/tasks.py`. Requisitos: RF-10.02. **Aceite:** Arquivo expira em 24 h e conclusão gera notificação autorizada.

- [ ] **S13-T06 — Formalizar primeiro ReportDefinition inferencial elegível.** Dependências: S13-T01, responsável metodológico. Componente: `reporting/models.py, docs/analytics/`. Requisitos: RF-10.04. **Aceite:** Pergunta/unidade/amostra/pressupostos registrados ou relatório fica indisponível.

- [ ] **S13-T07 — Criar CaptureDevice/CaptureSession e pareamento.** Dependências: S06, P-08. Componente: `integrations/capture.py`. Requisitos: RF-05.04. **Aceite:** Token só autoriza upload na sessão vinculada.

- [ ] **S13-T08 — Implementar receptor de lote com hash/ordem e quarentena.** Dependências: S13-T07, S06-T02. Componente: `integrations/capture_views.py`. Requisitos: RF-05.04. **Aceite:** Repetição e troca de paciente não anexam silenciosamente no lugar errado.

- [ ] **S13-T09 — Criar agente local de pasta e transporte HTTPS limitado.** Dependências: S13-T08, P-08. Componente: `capture_agent/`. Requisitos: RF-05.04. **Aceite:** Arquivo ainda sendo gravado não é enviado e fila local é protegida.

- [ ] **S13-T10 — Criar confirmação visual de páginas e recuperação de falha.** Dependências: S13-T09. Componente: `templates/integrations/capture/`. Requisitos: RF-05.04. **Aceite:** Usuário vê paciente/lote correto e mantém upload manual disponível.

- [ ] **S13-T11 — Homologar indicadores, exportações e scanner real autorizado.** Dependências: S13-T05, S13-T06, S13-T10. Componente: `docs/homologation/reports-capture.md`. Requisitos: RF-05, RF-10. **Aceite:** H-11/H-15/H-16 registrados sem dados clínicos externos indevidos.

- [ ] **Saída de S13:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.

### S14 — Homologação final e documentação

**Objetivo/entregável:** Versão 1 integralmente rastreada e operacionalmente revisada.

**Dependências:** S01–S13; nenhuma pendência bloqueante para a funcionalidade liberada.

- [ ] **S14-T01 — Completar cenários sintéticos de demo em múltiplas datas.** Dependências: S03-T11, S13. Componente: `base/management/commands/seed_demo.py`. Requisitos: RF-12.02. **Aceite:** H-20 cobre faltas, retornos, planos, documentos e falhas sem entregas reais.

- [ ] **S14-T02 — Revisar aderência visual e estados das jornadas.** Dependências: S01-T02, S13. Componente: `templates/, static/, docs/design-system.md`. Requisitos: RNF-01.09. **Aceite:** Arquivo real do design system fundamenta cada divergência corrigida.

- [ ] **S14-T03 — Homologar teclado, foco, rótulos e telas móveis.** Dependências: S14-T02. Componente: `templates/, docs/homologation/accessibility.md`. Requisitos: RNF-01.09. **Aceite:** Cadastro, consulta, agenda e chat concluídos sem depender de mouse.

- [ ] **S14-T04 — Medir latência de páginas, buscas, autosave e fila.** Dependências: S14-T01, S10-T08. Componente: `docs/homologation/performance.md`. Requisitos: RNF-01.01 a RNF-01.04. **Aceite:** H-23 registra percentis, base, máquina e concorrência usados.

- [ ] **S14-T05 — Revisar consultas/índices e resolver gargalo medido prioritário.** Dependências: S14-T04. Componente: `selectors.py, migrations dos apps`. Requisitos: RNF-01.01, RNF-01.02. **Aceite:** Nova medição compara a mesma consulta e contexto.

- [ ] **S14-T06 — Repetir revisão manual das superfícies de autorização alteradas.** Dependências: S14-T01, S02-T10, S12. Componente: `docs/homologation/isolation.md`. Requisitos: RT-02, RT-03. **Aceite:** H-03 cobre admin/export/chat/tasks/download/cache novamente.

- [ ] **S14-T07 — Conferir políticas de retenção, chaves e resposta a incidentes.** Dependências: S10-T09, S13. Componente: `docs/governance/, docs/operations/`. Requisitos: RT-03, RT-10. **Aceite:** Responsáveis e fluxo de incidente estão acessíveis e atualizados.

- [ ] **S14-T08 — Atualizar guias MkDocs por perfil e por operação.** Dependências: S14-T03, S14-T07. Componente: `docs/, mkdocs.yml`. Requisitos: RF-12.03. **Aceite:** Build estrito e navegação técnica protegida aprovados em H-19.

- [ ] **S14-T09 — Conferir rastreabilidade, pendências e release notes.** Dependências: S14-T05, S14-T06, S14-T08. Componente: `docs/releases/, matriz da seção 22`. Requisitos: RF-01 a RF-12, RT-01 a RT-10. **Aceite:** Nenhum requisito some por adiamento e toda restrição tem gate explícito.

- [ ] **S14-T10 — Registrar aceite do produto e liberar funcionalidades elegíveis.** Dependências: S14-T09, médico/produto/operação. Componente: `docs/homologation/v1.md`. Requisitos: RF-01 a RF-12, RNF-01. **Aceite:** Critérios da seção 21 aprovados; módulos bloqueados continuam identificados.

- [ ] **Saída de S14:** entregável demonstrado, evidências manuais registradas, documentação correspondente atualizada e nenhuma falha de isolamento/integridade aberta no escopo entregue.


## 21. Homologação manual e critérios de liberação

### 21.1 Registro de evidências

Executar os roteiros com dados fictícios em ambiente separado. Registrar responsável, data, SHA/digest, versões, navegador/dispositivo, pré-condições, passos, resultado esperado/observado e evidência sem dados pessoais. Cada caso é manual; não criar pytest, unittest ou suíte automatizada de navegador. Comandos de sintaxe, estado de serviços e integridade do backup são verificações operacionais.

Essa estratégia aumenta o risco de regressões não detectadas e depende de disciplina de revisão. Não descrever a ausência de incidentes nos roteiros como prova universal de isolamento, segurança, conformidade ou acurácia clínica. Repetir somente os casos afetados por mudanças e os bloqueantes de acesso/integridade/release, conforme análise da alteração.

### H-01 — Convite e onboarding

Pré-condição: convites fictícios válido, expirado, revogado e consumido; usuário existente e novo; canal real desabilitado.

- [ ] Criar tenant free por convite válido com CNPJ/razão social; repetir simultaneamente em outra aba e confirmar um único consumo/tenant.
- [ ] Convite inválido/expirado não cria usuário nem organização parcial; e-mail existente exige login antes de vínculo.
- [ ] Landing permite login/cadastro por convite; planos futuros exibem “Em breve”, sem cartão ou contratação ativa.

### H-02 — Autenticação, sessão e vínculos

- [ ] Login por e-mail normalizado, logout, recuperação com resposta uniforme, MFA e recovery code de uso único funcionam; senha/token não aparecem em log.
- [ ] Usuário participa de duas clínicas com papéis distintos e troca o contexto explicitamente; vínculo suspenso deixa de autorizar novas requisições.
- [ ] Inatividade e expiração exigem novo login; reautenticação privilegiada e sessão PFX possuem escopos/durações independentes.

### H-03 — Isolamento em todas as superfícies

Pré-condição: clínicas fictícias A/B, pacientes e anexos diferentes; usuário médico A, secretaria A, gestor A, usuário B e técnico global. Obter IDs/URLs **sintéticos** por conta autorizada para o ensaio.

- [ ] Listagem, detalhe, busca, autocomplete, criação/edição, relações de formulário e arquivamento não revelam objetos B à conta A; ausência de contexto nega acesso.
- [ ] Manipular tenant_id, patient_id, hostname, campos ocultos e IDs de sessão não concede acesso; FK cruzada inserida por caminho bulk/SQL autorizado de homologação é rejeitada pelo banco.
- [ ] Downloads, previews, CSV/PDF, dashboard e links recebidos obedecem escopo e verificação adicional; media não possui diretório público.
- [ ] Admin/ações em lote/painel Celery/documentação não ficam disponíveis a usuários da clínica; acesso técnico excepcional a dado clínico exige concessão e auditoria.
- [ ] Job enfileirado antes da revogação não lê dados depois dela; cache, notificações, chat, SSE e tools não reutilizam chave/contexto de outro tenant.
- [ ] Secretaria/gestor/owner sem papel clínico não leem exame, hipóteses, anexos clínicos ou resumo assistencial; somar owner+physician concede somente a política clínica definida.

### H-04 — Pacientes e demografia

- [ ] Cadastrar adulto com campos completos, menor sem CPF e paciente com informações desconhecidas; máscaras não alteram o dado válido nem tornam tudo obrigatório.
- [ ] Medições com datas/unidades distintas preservam história; IMC e idade usam referência correta; CPF duplicado é tratado somente dentro do tenant.
- [ ] CEP inválido, inexistente ou serviço indisponível permite cadastro manual; arquivamento mantém histórico e contato autorizado é distinguido de contato geral.

### H-05 — Catálogos

- [ ] Importar versão oficialmente obtida, registrar fonte/data/hash/condições de uso e revisar contagem/erros antes de ativar; demo nunca se apresenta como catálogo oficial.
- [ ] Atualizar descrição/código de referência sem alterar snapshots clínicos anteriores; TUSS não habilita faturamento TISS fora do escopo.
- [ ] Operadora, plano e particular têm vínculos/visibilidade corretos; catálogos globais não transportam dados de pacientes.

### H-06 — Atendimento e exame

- [ ] Preencher todos os blocos clínicos, consanguinidade, cognição, força, sensibilidade, reflexos, coordenação e nervos I–XII; verificar lateridade e qualificadores pertinentes.
- [ ] Não informado e não avaliado não são convertidos em normal; alternativas contraditórias no mesmo item são impedidas sem perder texto de limitação.
- [ ] Retorno copia somente conduta, hipóteses e informações de exames da origem prevista, com data/revisão; não copia exame físico realizado nem cria receita/pedido novo.
- [ ] Duas abas com autosave produzem conflito visível, sem sobrescrita silenciosa; perda de rede preserva estado de rascunho com indicação de falha.

### H-07 — Finalização e retificação

- [ ] Apenas médico autorizado finaliza após revisar campos copiados; autoria, momento, versão e hash ficam registrados.
- [ ] Edição direta/ação admin/caminho bulk não altera snapshot final; adendo mantém original, motivo, autor e data.
- [ ] Alteração cadastral posterior não modifica documento histórico; falha de IA/broker não impede persistir atendimento finalizado e evento na outbox.

### H-08 — Assinatura e documentos

- [ ] Gerar cada tipo com paciente/emissor/campos obrigatórios corretos; confirmar que PDF sem assinatura não recebe sucesso de emissão quando a assinatura é exigida.
- [ ] Habilitar sessão PFX em cada duração 2/4/6/12 h e verificar expiração no servidor, revogação, duas réplicas e reboot; não confundir o encerramento da sessão com validade de assinatura anterior.
- [ ] Senha inválida, certificado de titular incorreto, expirado/revogado e erro de cadeia/validação bloqueiam emissão; secretaria/gestor/IA não executam assinatura.
- [ ] Validar integridade e autoria de PDF sintético assinado com certificado autorizado, inclusive em verificador independente. O [VALIDAR do ITI](https://www.gov.br/pt-br/servicos/realizar-validacao-de-assinaturas-eletronicas-validar) é uma referência de verificação; enviar somente documento cuja submissão tenha sido autorizada.
- [ ] Hash/versionamento preservam documento emitido; correção gera nova versão; nenhuma senha/chave aparece no banco em texto puro, Redis, broker, logs ou artefatos de homologação.

### H-09 — Entrega e lembretes

- [ ] Documento emitido gera e-mail e SMS quando ambos são elegíveis; ausência de canal gera pendência; mensagem não contém diagnóstico nem PDF em URL permanente.
- [ ] Link sem OTP, expirado, revogado ou com tentativas excedidas não libera documento; contato legal autorizado recebe a comunicação prevista.
- [ ] API aceita mensagem → accepted; delivered somente com evidência real. Timeout após possível aceitação → unknown, sem reenvio automático cego.
- [ ] Remarcar/cancelar invalida lembrete antigo; reprocessar outbox não duplica efeito; indisponibilidade SMTP/SMS não invalida prontuário.

### H-10 — Arquivos e processamento

- [x] Arquivo sintético válido de cada formato percorre quarentena até disponível; tamanho/páginas/MIME inválidos são recusados com mensagem útil.
- [x] Preview não executa macros/scripts/referências externas; detector antimalware indisponível/definição inválida mantém quarentena. Usar amostra de verificação autorizada, sem material clínico real.
- [x] Download e preview de A falham para B e perfil administrativo sem permissão; path traversal, nome malicioso e parâmetros de preview não expõem volume.
- [x] Arquivo referenciado é imutável; GC respeita o lock de backup e retenção; OCR mantém proveniência e não envia identificado a serviço externo.

### H-11 — Scanner

- [ ] Parear dispositivo autorizado, selecionar paciente/atendimento, capturar lote e visualizar vínculo/páginas antes de concluir; navegador não precisa de driver universal.
- [ ] Trocar paciente, repetir hash, receber arquivo ainda em gravação ou expirar sessão não anexa automaticamente no contexto errado.
- [ ] Queda de rede mantém fila local protegida; upload manual continua funcional; arquivo local não é apagado por padrão.

### H-12 — Agenda

- [ ] Criar disponibilidade, bloqueio, férias e exceção datada; verificar duração/buffers, dia/semana/mês e lista móvel.
- [ ] Duas contas reservam intervalo sobreposto simultaneamente: apenas uma reserva comum confirma; intervalos adjacentes são permitidos; encaixe exige permissão/motivo.
- [ ] Remarcação é atômica, cancelamento libera horário e histórico permanece; verificar confirmação/check-in/atendimento/conclusão/falta e timezone.

### H-13 — CRM

- [ ] Grid/kanban filtram responsável/prazo/etapa; transição registra ator, anterior e seguinte e funciona por teclado.
- [ ] Card não mostra diagnóstico nem altera estado clínico/assinatura; integração com agenda ocorre pelo evento definido.

### H-14 — Financeiro

- [ ] Aplicar preço/repasse vigente, alterar tabela depois e conferir snapshot histórico; valores usam Decimal BRL com arredondamento de centavos explícito.
- [ ] Recebimentos parciais, ajuste e estorno preservam registros e conciliam saldo; evento duplicado não gera segunda cobrança.
- [ ] Visões de competência/caixa usam datas e fórmulas corretas; usuário financeiro não lê nota clínica.

### H-15 — Relatórios

- [ ] Para conjunto sintético de totais conhecidos, conferir cada numerador/denominador da seção 13 e os filtros de tenant/médico/período; desconhecidos não desaparecem da interpretação.
- [ ] Células pequenas/endereços gerenciais são agregados; exportações obedecem permissão e proteção contra fórmula CSV.
- [ ] Exportação grande vai para fila, notifica, gera arquivo privado e expira em 24 h; gráfico tem tabela alternativa acessível.

### H-16 — Inferência elegível

- [ ] Pergunta, desenho, unidade, amostra, faltantes, medidas repetidas, multiplicidade e pressupostos estão registrados no ReportDefinition.
- [ ] Ausência desses requisitos impede resultado inferencial; baixo n/viés e intervalos são apresentados com limite interpretativo, sem causalidade automática ou p-valor por filtro.

### H-17 — IA

- [ ] Job reautoriza usuário/tenant/paciente, seleciona dados mínimos e bloqueia envio quando desidentificação/risco residual falha; incluir genealogia/doença rara/metadados/OCR na revisão.
- [ ] Tools não aceitam tenant controlado pelo modelo, SQL/URL arbitrários ou instruções presentes no documento; leitura administrativa não acessa material clínico.
- [ ] Resposta fora de schema, fonte inexistente, timeout e orçamento excedido geram estados controlados; prioridade qualitativa não vira probabilidade diagnóstica numérica.
- [ ] Rascunho tem fontes, modelo, versão, limites e revisão médica; aceitar/editar/rejeitar é auditável; fonte alterada torna artefato stale.
- [ ] Provedor alternativo é escolhido explicitamente; política de retenção/roteamento final é verificada; IA indisponível não bloqueia prontuário.

### H-18 — Chat e SSE

- [ ] Duas sessões/tenants/pacientes permanecem separadas; médico e secretaria recebem apenas ferramentas de seus escopos.
- [ ] Tokens chegam incrementalmente pelo Traefik; heartbeat, reconexão, Last-Event-ID, cancelamento e buffer expirado têm estados visíveis.
- [ ] Revogação interrompe leitura; Markdown malicioso não executa script durante ou após stream; resultado final permanece após perda do Redis.
- [ ] Rollout comunica reconexão quando necessária; não apresentar animação de texto pronto como streaming real.

### H-19 — Admin e documentação

- [ ] Admin, dj-celery-panel e dependências têm todas as rotas protegidas por perfil técnico/MFA; argumentos/resultados/configuração sensíveis são mascarados ou suprimidos.
- [ ] MkDocs/diagramas renderizam em URL autenticada, incluindo assets da documentação; usuário da clínica não os acessa.
- [ ] Guias contêm instalação, permissões, integração, backup/restauração/diagnóstico e release vigente, sem credencial ou dados reais.

### H-20 — Demonstração

- [ ] seed_demo é idempotente e cria clínicas, perfis, múltiplas datas, faltas/retornos, planos/particular, arquivos e falhas sintéticas.
- [ ] Não há envio real, PFX real, prontuário real ou contatos roteáveis de pacientes; produção recusa execução com flag padrão.

### H-21 — Deploy e rollback

- [ ] Preflight recusa DEBUG True, imagem ausente, rede interna não isolada, secret faltante, repositório com mudanças rastreadas e release não aprovada.
- [ ] Primeiro deploy converge; health é 200 sem banco/auth/redirect, prontidão adicional verifica banco/schema/assets; logs/status não expõem secrets.
- [ ] HTTPS origem/apex/wildcard, proxy/origins/CSRF e portas obedecem ao guia; worker tem egress; banco/brokers não têm porta pública.
- [ ] Rollout usa mesma imagem para app/worker/beat, duas versões de assets coexistem e há um único beat; encerramento de task é conciliável.
- [ ] skip-build reutiliza digest/RELEASE_ID anterior; falha controlada em homologação retorna erro e rollback deixa estado coerente, sem downgrade destrutivo de schema.

### H-22 — Backup e recuperação

- [ ] Conjunto concluído tem hashes/tamanhos válidos, cópia externa e chave recuperável; falha de nova cópia não remove o último backup válido.
- [ ] Restaurar em host vazio/separado a release exata, banco, mídia, PFX e ACME; conferir contagens/vínculos/hashes e isolamento A/B.
- [ ] Sessões transitórias são invalidadas, canais ficam suspensos até reconciliação e não há dois ambientes produtivos escrevendo.
- [ ] Medir RPO/RTO, recuperar material criptografado autorizado e registrar operador/custodiante; nenhuma afirmação de recuperação depende apenas de pg_dump terminar.

### H-23 — Desempenho e acessibilidade

- [ ] Medir RNF-01.01–.04 na máquina/base/concorrência propostas; registrar p95 e gargalos, incluindo busca, autosave, enfileiramento e coexistência no rollout.
- [ ] Conferir RAM/disco/fila e monitoramento de backup/TLS; se metas falharem, ajustar escopo/capacidade com aprovação do produto antes de afirmar atendimento.
- [ ] Completar jornadas principais por teclado em desktop e em celular/tablet, verificando foco, contraste, rótulos, erros, loading local e conteúdo equivalente dos gráficos.

### 21.2 Gates por marco

| Marco | Evidência mínima | Bloqueantes |
| --- | --- | --- |
| M0 | H-02/H-03/H-19 básicos e H-21 técnico | Auth/tenant/secret/rede inválidos; somente dados sintéticos |
| M1 | H-01/H-04/H-05/H-06/H-07/H-10/H-12 e geração de rascunhos de H-08 | Perda de autoria, acesso cruzado, agenda inconsistente, upload privado inseguro |
| M2 | H-08/H-09/H-13/H-14/H-21/H-22 e revisão de H-03 | Assinatura não homologada, backup sem recuperação, contratos/finalidade indefinidos, comunicação insegura |
| M3 | H-17/H-18 com P-06/P-09 resolvidas para a funcionalidade | Envio identificado indevido, ferramenta fora de escopo, emissão autônoma, probabilidade inventada |
| M4 | H-11/H-15/H-16/H-19/H-20/H-23 e revisão das superfícies alteradas | Relatório enganoso, exportação indevida, captura incorreta, ausência de evidência visual/operacional |

- [ ] Médico/produto, desenvolvimento e operação registraram aceite do marco, com SHA/digest e funcionalidades habilitadas.
- [ ] Nenhum defeito de acesso cruzado, perda de registro, assinatura indevida, divulgação de mídia ou recuperação desconhecida permanece aberto no escopo liberado.
- [ ] Pendências externas continuam explícitas e funcionalidades dependentes permanecem bloqueadas; isso não remove requisitos do roadmap.


## 22. Matriz de rastreabilidade

### 22.1 Requisitos funcionais

Os IDs RF-01 a RF-12 são os grupos originais; seus subitens tornam o aceite rastreável. Todos também obedecem a RT-02/RT-03, ao contrato comum de 6.0 e aos estados de tela das seções 5/16. Uma faixa de seções indica onde estão a regra funcional e seu detalhamento; não substitui o aceite da seção 21.

| Requisito | Seções além de 6 | Componente | Tarefas | Aceite |
| --- | --- | --- | --- | --- |
| RF-01.01 | 3–5, 9–10 | accounts, tenancy, onboarding | S03-T02 | H-01 |
| RF-01.02 | 3–5, 9–10 | accounts, tenancy, onboarding | S03-T01 | H-01 |
| RF-01.03 | 3–5, 9–10 | accounts, tenancy, onboarding | S03-T01, S03-T02 | H-01 |
| RF-01.04 | 3–5, 9–10 | accounts, tenancy, onboarding | S02-T01, S02-T06, S08-T03 | H-02 |
| RF-01.05 | 3–5, 9–10 | accounts, tenancy, onboarding | S02-T02, S03-T03 | H-02/H-03 |
| RF-02.01 | 9–10 | patients, catalogs, integrations/cep | S03-T04, S03-T05, S03-T06 | H-04 |
| RF-02.02 | 9–10 | patients, catalogs, integrations/cep | S03-T04, S03-T06 | H-03/H-04 |
| RF-02.03 | 9–10 | patients, catalogs, integrations/cep | S03-T07 | H-04 |
| RF-02.04 | 9–10 | patients, catalogs, integrations/cep | S03-T08 | H-04 |
| RF-02.05 | 9–10 | patients, catalogs, integrations/cep | S03-T09, S03-T10 | H-05 |
| RF-03.01 | 9, 11 | clinical | S05-T01, S05-T11 | H-06 |
| RF-03.02 | 9, 11 | clinical | S05-T02 | H-06 |
| RF-03.03 | 9, 11 | clinical | S05-T03, S05-T04, S05-T05, S05-T06, S05-T07 | H-06 |
| RF-03.04 | 9, 11 | clinical | S05-T08 | H-06 |
| RF-03.05 | 9, 11 | clinical | S05-T09, S05-T10 | H-06/H-07 |
| RF-03.06 | 9, 11 | clinical | S05-T10 | H-07 |
| RF-04.01 | 9, 12 | documents, signing | S07-T01, S07-T02, S07-T03 | H-08 |
| RF-04.02 | 9, 12 | documents, signing | S07-T04, S07-T07 | H-08 |
| RF-04.03 | 9, 12 | documents, signing | S07-T05, S07-T06, S07-T08 | H-08 |
| RF-04.04 | 9, 12 | documents, signing | S07-T07, S07-T09 | H-08 |
| RF-04.05 | 9, 12 | documents, signing | S07-T09, S08-T06 | H-09 |
| RF-05.01 | 9–10, 12, 15 | documents, integrations/capture | S06-T01, S06-T02, S06-T07 | H-10 |
| RF-05.02 | 9–10, 12, 15 | documents, integrations/capture | S06-T03, S06-T04, S06-T05, S06-T09 | H-10 |
| RF-05.03 | 9–10, 12, 15 | documents, integrations/capture | S06-T06 | H-03/H-10 |
| RF-05.04 | 9–10, 12, 15 | documents, integrations/capture | S13-T07, S13-T08, S13-T09, S13-T10 | H-11 |
| RF-06.01 | 9, 13, 15 | scheduling | S04-T01, S04-T06 | H-12 |
| RF-06.02 | 9, 13, 15 | scheduling | S04-T01, S04-T02 | H-12 |
| RF-06.03 | 9, 13, 15 | scheduling | S04-T03, S04-T04, S04-T05 | H-12 |
| RF-06.04 | 9, 13, 15 | scheduling | S04-T07, S04-T09, S08-T07 | H-09/H-12 |
| RF-06.05 | 9, 13, 15 | scheduling | S04-T08 | H-03/H-12 |
| RF-07.01 | 9, 13 | crm | S09-T01, S09-T02 | H-13 |
| RF-07.02 | 9, 13 | crm | S09-T03 | H-13 |
| RF-08.01 | 9, 13 | finance | S09-T04, S09-T05 | H-14 |
| RF-08.02 | 9, 13 | finance | S09-T06 | H-14 |
| RF-08.03 | 9, 13 | finance | S09-T07, S09-T08 | H-14 |
| RF-08.04 | 9, 13 | finance | S09-T09 | H-14/H-15 |
| RF-09.01 | 12, 15 | communications, events | S08-T02, S08-T03, S08-T04 | H-09 |
| RF-09.02 | 12, 15 | communications, events | S08-T05 | H-09 |
| RF-09.03 | 12, 15 | communications, events | S08-T06 | H-09 |
| RF-09.04 | 12, 15 | communications, events | S08-T01, S08-T08 | H-09 |
| RF-10.01 | 13, 15–16 | reporting | S13-T01, S13-T02, S13-T03 | H-15 |
| RF-10.02 | 13, 15–16 | reporting | S13-T04, S13-T05 | H-15 |
| RF-10.03 | 13, 15–16 | reporting | S13-T04 | H-15 |
| RF-10.04 | 13, 15–16 | reporting | S13-T06 | H-16 |
| RF-11.01 | 10, 14–15 | ai, notifications | S11-T01, S11-T10, S11-T11 | H-17 |
| RF-11.02 | 10, 14–15 | ai, notifications | S11-T04, S11-T07, S11-T08, S11-T10 | H-17 |
| RF-11.03 | 10, 14–15 | ai, notifications | S12-T01, S12-T02, S12-T08 | H-18 |
| RF-11.04 | 10, 14–15 | ai, notifications | S12-T03, S12-T04, S12-T05, S12-T06, S12-T07 | H-18 |
| RF-11.05 | 10, 14–15 | ai, notifications | S11-T09, S11-T11 | H-17 |
| RF-11.06 | 10, 14–15 | ai, notifications | S11-T05, S11-T06, S11-T12 | H-17 |
| RF-12.01 | 8, 10, 16–19 | admin, docs, seed_demo | S02-T10 | H-19 |
| RF-12.02 | 8, 10, 16–19 | admin, docs, seed_demo | S03-T11, S14-T01 | H-20 |
| RF-12.03 | 8, 10, 16–19 | admin, docs, seed_demo | S01-T08, S02-T10, S14-T08 | H-19 |

### 22.2 Engenharia e metas

| Requisito | Seções | Componente | Tarefas principais | Aceite |
| --- | --- | --- | --- | --- |
| RT-01 | 8–9, 18, 24 | core/base, lock, docs | S01-T03 a S01-T08; S14-T08 | H-19/H-21 e inspeção de estrutura |
| RT-02 | 4–10, 14–15 | tenancy, selectors, constraints, admin/tools | S02-T01 a S02-T05; S02-T10; S14-T06 | H-02/H-03 |
| RT-03 | 9–12, 19 | audit, private storage, auth, signing | S02-T07 a S02-T09; S06-T02 a S06-T08; S07; S10-T09 | H-03/H-07/H-08/H-10/H-22 |
| RT-04 | 14–15 | providers, graph, tools, privacy | S11-T02 a S11-T12; S12-T03 a S12-T08 | H-17/H-18 |
| RT-05 | 17–18, 24 | Compose/stack, volumes, placement | S01-T07; S01-T09; S10-T01 | H-21 |
| RT-06 | 17–18, 24 | settings, env reader, secret setup | S01-T05; S10-T01 | H-21 preflight/inspeção sem valores |
| RT-07 | 17–18, 24 | Traefik, ACME, proxy/origins | S10-T01; S10-T02 | H-21 TLS/proxy |
| RT-08 | 15, 17–18, 24 | waits, locks, health, outbox, beat | S01-T06; S08-T01; S10-T02 | H-09/H-21 |
| RT-09 | 17–19, 24 | deploy, static release, schema | S10-T03; S10-T04; S12-T09 | H-21 rollout/rollback |
| RT-10 | 18–19, 24 | deploy/backup/restore, timers | S10-T01; S10-T05 a S10-T08 | H-21/H-22 |
| RNF-01.01 | 7, 8, 17 | consultas/índices e capacidade | S14-T04; S14-T05 | H-23 latência de páginas |
| RNF-01.02 | 6, 7, 9 | busca e autocomplete scoped | S03-T06; S14-T04; S14-T05 | H-04/H-23 |
| RNF-01.03 | 5–7, 11 | autosave e row_version | S05-T09; S14-T04 | H-06/H-23 |
| RNF-01.04 | 7, 15, 19 | outbox/filas/alertas | S08-T01; S10-T08; S14-T04 | H-09/H-23 |
| RNF-01.05 | 7, 17, 19 | observação externa e rollout | S10-T03; S10-T08 | H-21 e medição mensal do piloto |
| RNF-01.06 | 7, 19 | backup externo/recuperação | S10-T05 a S10-T07 | H-22 RPO/RTO |
| RNF-01.07 | 7, 17–18 | TLS, rede, firewall | S10-T01; S10-T02 | H-21 portas/certificado |
| RNF-01.08 | 7, 17, 19 | limites, disco/RAM/fila | S10-T08; S14-T04 | H-23 |
| RNF-01.09 | 5, 16, 20 | design system e componentes | S01-T02; S03-T12; S14-T02; S14-T03 | H-23 e revisão visual com arquivo real |
| RNF-01.10 | 7, 10, 14–15 | TTL/cache/SSE/exports | S12-T03; S12-T05; S13-T05 | H-15/H-18 e inspeção de expiração |

### 22.3 Conflitos resolvidos

| ID original | Decisão | Implementação e evidência |
| --- | --- | --- |
| CR-01 | DEC-01 | Nomes canônicos em stack/scripts; registry preservado; H-21 |
| CR-02 | DEC-02 | Models de paciente/atendimento; CRM administrativo; exclusão de sinistro em 2.2 |
| CR-03 | DEC-03 | core configura, base compartilha, apps na raiz; S01-T04 |
| CR-04 | DEC-04 | Timestamps em models próprios; exceções de bibliotecas em 9.1; S02-T05 |
| CR-05 | DEC-05 | Papéis por membership sem privilégio clínico por hierarquia; H-03 |
| CR-06 | DEC-06 | OpenRouter padrão/adaptadores explícitos; S11-T02/S11-T03; H-17 |
| CR-07 | DEC-07 | Sessão PFX temporária separada de validade da assinatura; S07-T05/S07-T06; H-08 |
| CR-08 | DEC-08 | Desidentificação local e distinção de pseudonimização; S11-T05/S11-T06; H-17 |
| CR-09 | DEC-09 | Staging, lock, publicação atômica e retenção de assets; S10-T03; H-21 |
| CR-10 | DEC-10 | Esperas, schema, reconexão e jobs idempotentes; S01-T06/S08-T01; H-21 |
| CR-11 | DEC-11 | Duas réplicas/margem/readiness e limite de VPS única; S10-T03/S10-T04; H-21 |
| CR-12 | DEC-12 | Parser literal e env_file distinto de interpolação; S01-T05; H-21 |
| CR-13 | DEC-13 | Redes pré-criadas, internal efetivo inspecionado; S10-T01; H-21 |
| CR-14 | DEC-14 | Agente de pasta pareado + upload; S13-T07 a S13-T10; H-11 |

P-01 a P-10 permanecem na seção 3.1 com responsável/prazo de gate. Prescrições reguladas, métodos inferenciais e IA externa podem continuar indisponíveis até a resolução das respectivas pendências; os requisitos são mantidos nas sprints e neste mapa.


## 23. Riscos, dependências e fontes

### 23.1 Riscos concretos

| Risco | Consequência | Controle/decisão | Dono e critério |
| --- | --- | --- | --- |
| Consulta ou FK sem tenant | Divulgação/cruzamento de prontuários | AccessContext, FK composta, selectors, revisão de todos os acessos | Desenvolvimento; H-03 bloqueante |
| Registros finais alteráveis por caminho secundário | Perda de integridade/autoria | Services explícitos, triggers de imutabilidade e adendos | Desenvolvimento + médico; H-07 |
| PFX/chave ou sessão indevidamente reutilizados | Assinatura sem autorização do titular | Volume cifrado, chave separada, MFA, tmpfs, confirmação por documento | Segurança + médico; P-05/H-08 |
| Documento identificado enviado à IA | Tratamento externo incompatível com a política | Desidentificação local, avaliação residual, fail closed, provedor final autorizado | Controlador + produto; P-06/P-09/H-17 |
| Prompt injection em texto/OCR/tool | Leitura indevida ou saída enganosa | Conteúdo é dado; tools restritas; fonte/saída validadas; revisão médica | Desenvolvimento; H-17 |
| API aceita envio, mas ocorre timeout local | Duplicidade ou falsa alegação de entrega | unknown, DLR/conciliar, sem retry cego e sem exactly-once fictício | Operação + secretaria; H-09 |
| Mudança normativa/modalidade/SNCR | Emissão inadequada ou promessa incorreta | Bloqueio por modalidade, revisão de fontes e documentação vigente | Produto/regulatório; P-05/P-07 |
| Perda da única VPS | Indisponibilidade e perda do disco/estado | Backup cifrado externo, imagem/chaves recuperáveis, restauração medida | Operação/custodiante; H-22 |
| Migrations incompatíveis ou lock longo | Interrupção no rollout, rollback inviável | Expand/contract, revisão de DDL, duas versões compatíveis e manutenção quando necessária | Desenvolvimento/operação; H-21 |
| Remoção global de estáticos | Páginas sem CSS/JS durante atualização | Collectstatic isolado, publicação atômica, retenção e leitura por release | Operação; H-21 |
| Conversor/antivírus indisponível ou arquivo hostil | Execução indevida, consumo excessivo ou vazamento | Quarentena, formatos limitados, processamento local e isolamento homologado | Desenvolvimento/operação; S06/H-10 |
| Volume local transferido para outro nó | Banco/mídia aparentemente vazios | Um nó/placement obrigatório; script recusa multinó | Operação; H-21 |
| Socket Docker no Traefik | Comprometimento do proxy pode alcançar controle do host | Socket necessário ao provider Swarm, restrito ao Traefik/manager; patching e acesso administrativo mínimo | Operação; revisão de segurança. Montagem :ro não transforma API em somente leitura |
| App com credencial de migração | Comprometimento web permite DDL | Segredo só app, role própria, sem superuser; risco residual explícito pela exigência de bootstrap no app | Segurança; revisão pré-piloto |
| Fila única de worker saturada por IA/OCR | Atraso de SMS/relatórios | Limites por job, prefetch 1, custo/concurrency e possibilidade de workers por fila após medição | Operação; RNF-01.04/H-23 |
| Sem suíte automatizada | Regressão pode escapar ao aceite manual | Roteiros rastreados e revisão disciplinada, sem alegar cobertura automática | Produto/desenvolvimento; cada release |
| Arquivo do design system ausente | Aparência divergente da exigida | P-01 bloqueia aceite visual; nenhuma paleta é inventada neste PRD | Produto/design; H-23 |
| Imagens/pacotes ainda não resolvidos em conjunto | Build ou integração incompatível | P-04, lock com hashes, digests e homologação da composição | Desenvolvimento; S01/H-21 |
| Backup sem chave ou cópia externa verificável | Dump existe, mas não permite recuperação | Custódia independente, ensaio completo e alerta de cópia | Operação + controlador; P-10/H-22 |
| Interpretação estatística inadequada | Indicadores enganosos ou inferência clínica indevida | Unidade/fórmula explícitas, dados ausentes, desenho e revisão metodológica | Produto/metodologia; H-15/H-16 |

### 23.2 Evidência e limites desta elaboração

Foram consultadas fontes primárias técnicas e brasileiras, e o documento distingue informação publicada, decisão arquitetural e dependência de homologação. Disponibilidade de release ou metadados de pacote não comprova instalação conjunta, protocolo de assinatura ou comportamento operacional na VPS.

Os anexos foram revisados quanto a sintaxe e coerência textual/estrutural conforme registro final abaixo. **Não foram executados Docker/Swarm, build de imagem, resolução integral do requirements.txt, chamadas autenticadas a SMS/IA, emissão de certificado TLS, assinatura com PFX real, ensaio de carga ou restauração de um banco clínico.** Esses aceites permanecem abertos nas sprints. O arquivo `design_system/design-system.html` não foi disponibilizado.

O modelo OpenRouter solicitado foi localizado, com recursos anunciados na página. Suporte anunciado a tools/saída JSON não equivale a garantia de conformidade estrita a JSON Schema; a aplicação valida Pydantic e referências, e S11 deve comprovar streaming/tool calling/saída estruturada com o provedor final escolhido. Não se promete acurácia, disponibilidade ou política uniforme de dados entre provedores.

### 23.3 Fontes consultadas

Consulta em **05/09/2026**, salvo informação datada indicada pela própria fonte. Links próximos às decisões dão o contexto de uso; esta lista facilita sua revisão em novas releases. Não se copiaram exemplos inseguros de credencial por URL ou de TLS desativado.

| Tema | Fonte primária |
| --- | --- |
| Python | [Downloads e releases](https://www.python.org/downloads/) |
| Django | [Download](https://www.djangoproject.com/download/), [compatibilidade Python](https://docs.djangoproject.com/en/6.1/faq/install/) |
| Staticfiles Django | [collectstatic e opções](https://docs.djangoproject.com/en/6.0/ref/contrib/staticfiles/) |
| Constraints de agenda | [ExclusionConstraint PostgreSQL/Django](https://docs.djangoproject.com/en/6.1/ref/contrib/postgres/constraints/) |
| LangChain/LangGraph | [LangChain no PyPI](https://pypi.org/project/langchain/), [LangGraph no PyPI](https://pypi.org/project/langgraph/), [streaming](https://docs.langchain.com/oss/python/langgraph/streaming) |
| Celery | [Pacote](https://pypi.org/project/celery/), [histórico 5.6](https://docs.celeryq.dev/en/v5.6.3/history/changelog-5.6.html) |
| Painel Celery | [Instalação, dependências e compatibilidade](https://pypi.org/project/dj-celery-panel/) |
| PostgreSQL | [Política de versionamento](https://www.postgresql.org/support/versioning/) |
| RabbitMQ | [Informações de release/suporte](https://www.rabbitmq.com/release-information) |
| Redis | [Releases oficiais](https://github.com/redis/redis/releases) |
| Docker | [Instalação Ubuntu](https://docs.docker.com/engine/install/ubuntu/), [interpolação de ambiente](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/), [volumes](https://docs.docker.com/engine/storage/volumes/) |
| Traefik | [Release 3.7.12](https://github.com/traefik/traefik/releases/tag/v3.7.12), [provider Swarm](https://doc.traefik.io/traefik/reference/install-configuration/providers/swarm/) |
| Cloudflare/ACME | [Lego Cloudflare](https://go-acme.github.io/lego/dns/cloudflare/), [IPv4](https://www.cloudflare.com/ips-v4), [IPv6](https://www.cloudflare.com/ips-v6) |
| WhiteNoise | [Storage, configuração e limitações de autorefresh](https://whitenoise.readthedocs.io/en/stable/django.html) |
| OpenRouter | [GLM 5.3 Flash](https://openrouter.ai/z-ai/glm-5.3-flash), [política ZDR](https://openrouter.ai/docs/guides/features/zdr) |
| SMSDEV | [Envio](https://www.smsdev.com.br/en/envio-sms/), [consulta DLR](https://www.smsdev.com.br/en/consulta-situacao-da-mensagem/) |
| CEP | [ViaCEP e respostas de erro](https://viacep.com.br/) |
| Catálogos | [ANS/TISS/TUSS](https://www.gov.br/ans/pt-br/assuntos/prestadores/padrao-para-troca-de-informacao-de-saude-suplementar-2013-tiss), [DATASUS](https://datasus.saude.gov.br/transferencia-de-arquivos/) |
| LGPD | [Lei 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm) |
| Prontuários e retenção | [Lei 13.787/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13787.htm) |
| Transferência internacional | [Resolução ANPD 19/2024](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024) |
| Documentos médicos | [Resolução CFM 2.381/2024](https://sistemas.cfm.org.br/normas/arquivos/resolucoes/BR/2024/2381_2024.pdf) |
| Controle de prescrições | [Comunicado Anvisa sobre SNCR](https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa/2026/SNCR-o-que-muda-para-farmacias-e-drogarias-com-o-novo-sistema-de-controle-de-receitas) |
| Assinatura/validação | [pyHanko](https://docs.pyhanko.eu/en/latest/), [serviço VALIDAR/ITI](https://www.gov.br/pt-br/servicos/realizar-validacao-de-assinaturas-eletronicas-validar) |

A aplicação concreta e seus responsáveis devem revisar as fontes antes de cada liberação regulada. O PRD não substitui parecer jurídico, validação clínica, certificação de assinatura ou classificação regulatória do produto.

## 24. Anexos operacionais completos

### 24.0 Contrato de integração

Cada bloco abaixo corresponde ao arquivo indicado, relativo à raiz do repositório. São artefatos operacionais de referência completos, sem funções omitidas por reticências. Devem ser integrados aos apps de negócio e homologados nas sprints; não constituem o sistema clínico completo. As exceções deliberadas são `requirements.txt`, que só pode ser entregue após resolução real com hashes, e os componentes funcionais cujo desenvolvimento é o objetivo das sprints. Nenhum resultado de instalação conjunta foi inventado.

`compose.yml` foi gerado pelo helper local; antes de usá-lo, gerar os env_files e secrets locais indicados em 18.3. O Swarm utiliza `.runtime/*.env` gerados pelo deploy, sem segredos em texto no YAML. `ops/traefik.example.yml` demonstra a configuração completa com CIDRs oficiais consultados; `ACME_EMAIL=CHANGE_ME` deve ser preenchido no .env. Produção utiliza a configuração efetivamente gerada em `.runtime/traefik.yml`, não uma edição paralela do exemplo.

`core/settings.py` lista apps e middleware que serão implementados em S01/S02; `core/urls.py`, models, migrations, forms, templates e docs funcionais não são omitidos de uma aplicação supostamente pronta: são desenvolvimento futuro expressamente fora desta execução. Os commands de recuperação pressupõem os models/campos/estados das seções 9/15 e devem ser integrados antes da liberação clínica.

**Conferência deste documento:**

- Sintaxe: Python analisado por AST, shell por sh -n e YAML carregado; nenhuma execução de aplicação/infraestrutura.
- Estrutura: sete serviços no Compose e no Swarm; referências de redes/secrets e políticas operacionais conferidas.
- Rastreabilidade: 53 subrequisitos funcionais, RT-01–RT-10, RNF-01.01–.10 e CR-01–CR-14 mapeados; 147 tarefas abertas e 23 roteiros H.

| Arquivo | Uso |
| --- | --- |
| `.dockerignore` | Artefato anexo integral |
| `.env.example` | Artefato anexo integral |
| `.gitignore` | Artefato anexo integral |
| `Dockerfile` | Artefato anexo integral |
| `base/management/commands/bootstrap_release.py` | Artefato anexo integral |
| `base/management/commands/prepare_recovery.py` | Artefato anexo integral |
| `base/management/commands/wait_for_db.py` | Artefato anexo integral |
| `base/management/commands/wait_for_dependencies.py` | Artefato anexo integral |
| `base/tasks.py` | Artefato anexo integral |
| `compose.yml` | Artefato anexo integral |
| `core/__init__.py` | Artefato anexo integral |
| `core/asgi.py` | Artefato anexo integral |
| `core/celery.py` | Artefato anexo integral |
| `core/settings.py` | Artefato anexo integral |
| `docker-stack.yml` | Artefato anexo integral |
| `manage.py` | Artefato anexo integral |
| `mkdocs.yml` | Artefato anexo integral |
| `ops/__init__.py` | Artefato anexo integral |
| `ops/backup.py` | Artefato anexo integral |
| `ops/celery_health.py` | Artefato anexo integral |
| `ops/deploy.py` | Artefato anexo integral |
| `ops/docs.py` | Artefato anexo integral |
| `ops/entrypoint.sh` | Artefato anexo integral |
| `ops/env.py` | Artefato anexo integral |
| `ops/http_health.py` | Artefato anexo integral |
| `ops/infra_entrypoint.sh` | Artefato anexo integral |
| `ops/local_compose.py` | Artefato anexo integral |
| `ops/make_runtime.py` | Artefato anexo integral |
| `ops/neurodoc-backup.service` | Artefato anexo integral |
| `ops/neurodoc-backup.timer` | Artefato anexo integral |
| `ops/postgres_init.sh` | Artefato anexo integral |
| `ops/probe_ready.py` | Artefato anexo integral |
| `ops/queue_probe.py` | Artefato anexo integral |
| `ops/restore.py` | Artefato anexo integral |
| `ops/runtime.py` | Artefato anexo integral |
| `ops/scheduler.py` | Artefato anexo integral |
| `ops/secret_setup.py` | Artefato anexo integral |
| `ops/staticfiles.py` | Artefato anexo integral |
| `ops/traefik-local.yml` | Artefato anexo integral |
| `ops/traefik.example.yml` | Artefato anexo integral |
| `requirements.in` | Artefato anexo integral |
| `scripts/backup.sh` | Artefato anexo integral |
| `scripts/deploy.sh` | Artefato anexo integral |

### 24.1 — `.dockerignore`

```text
.git
.venv
.env
.env.*
.secrets
.runtime
**/__pycache__
*.pyc
*.pfx
*.p12
*.pem
*.key
*.age
media
staticfiles
site
node_modules
```

### 24.2 — `.env.example`

```text
# Literal KEY=VALUE. No inline comments or variable interpolation.
DEBUG=False
ALLOWED_HOSTS=neurodoc.app.br,.neurodoc.app.br,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://neurodoc.app.br,https://*.neurodoc.app.br
TIME_ZONE=America/Sao_Paulo
PUBLIC_BASE_URL=https://neurodoc.app.br
APP_REPLICAS=2
AI_ENABLED=False
AI_PROVIDER=openrouter
AI_MODEL=z-ai/glm-5.3-flash
EMAIL_ENABLED=False
EMAIL_HOST=smtp.example.invalid
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=no-reply@neurodoc.app.br
SMS_ENABLED=False
PYTHON_IMAGE=python:3.14.7-slim-bookworm
POSTGRES_IMAGE=postgres:17.11-bookworm
RABBITMQ_IMAGE=rabbitmq:4.3.5
REDIS_IMAGE=redis:8.10.1
TRAEFIK_IMAGE=traefik:v3.7.12
ACME_EMAIL=CHANGE_ME
ACME_DIRECTORY=https://acme-staging-v02.api.letsencrypt.org/directory
BACKUP_DIR=/srv/neurodoc-backups
BACKUP_RETENTION_DAYS=30
BACKUP_AGE_RECIPIENT=CHANGE_ME
DEPLOY_TIMEOUT_SECONDS=1200
NEURODOC_DEMO_ALLOWED=False
NEURODOC_RECOVERY_MODE=False
NEURODOC_SCHEMA_CHANGE=expand
NEURODOC_RELEASE_APPROVED=False
NEURODOC_NODES=1
NEURODOC_DOCS_ENABLED=True
```

### 24.3 — `.gitignore`

```text
.venv/
.env
.env.*
!.env.example
.secrets/
.runtime/
__pycache__/
*.pyc
*.pfx
*.p12
*.pem
*.key
*.age
media/
staticfiles/
site/
```

### 24.4 — `Dockerfile`

```dockerfile
ARG PYTHON_IMAGE=python:3.14.7-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 libpq5 clamav clamav-freshclam tesseract-ocr tesseract-ocr-por \
    poppler-utils fonts-dejavu-core ca-certificates tar \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && python -m venv /app/.venv
COPY requirements.txt /app/requirements.txt
RUN pip install --require-hashes -r requirements.txt && pip check
COPY . /app
RUN mkdocs build --strict \
    && chmod +x /app/ops/entrypoint.sh \
    && chown -R 10001:10001 /app
ARG RELEASE_ID
ENV RELEASE_ID=${RELEASE_ID}
LABEL org.opencontainers.image.revision=${RELEASE_ID}
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD python /app/ops/http_health.py
ENTRYPOINT ["/app/ops/entrypoint.sh"]
CMD ["app"]
```

### 24.5 — `base/management/commands/bootstrap_release.py`

```python
from django.core.management.base import BaseCommand
from ops.runtime import prepare_release


class Command(BaseCommand):
    help = 'Migrate under an advisory lock and publish release static files.'

    def handle(self, *args, **options):
        prepare_release()
```

### 24.6 — `base/management/commands/prepare_recovery.py`

```python
import uuid

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Invalidate restored sessions and hold external work for reconciliation.'

    def add_arguments(self, parser):
        parser.add_argument('--operator-email', required=True)
        parser.add_argument('--reason', required=True)

    def handle(self, *args, **options):
        if not settings.NEURODOC_RECOVERY_MODE or any([
            settings.EMAIL_ENABLED, settings.SMS_ENABLED, settings.AI_ENABLED,
        ]):
            raise CommandError('Recovery mode and disabled external channels are required')
        operator = get_user_model().objects.filter(
            email__iexact=options['operator_email'], is_active=True,
            is_staff=True, is_superuser=True,
        ).first()
        if operator is None:
            raise CommandError('An active technical administrator must be identified')
        reason = options['reason'].strip()
        if not 10 <= len(reason) <= 500:
            raise CommandError('Provide a recovery reason of 10 to 500 characters')
        now = timezone.now()
        counts = {}
        with transaction.atomic():
            counts['sessions'] = Session.objects.all().delete()[0]
            counts['signing'] = apps.get_model('documents', 'SigningSession')._base_manager.update(
                revoked_at=now, encrypted_unlock_material=b'', updated_at=now,
            )
            counts['tokens'] = apps.get_model('communications', 'DocumentAccessToken')._base_manager.update(
                revoked_at=now, otp_hash='', updated_at=now,
            )
            counts['ai_jobs'] = apps.get_model('ai', 'AIJob')._base_manager.filter(
                status__in=['queued', 'running', 'stalled'],
            ).update(status='cancelled', cancel_requested_at=now, updated_at=now)
            counts['deliveries'] = apps.get_model('communications', 'Delivery')._base_manager.filter(
                status__in=['pending', 'queued', 'processing', 'accepted', 'unknown', 'failed'],
            ).update(status='needs_reconciliation', next_attempt_at=None, updated_at=now)
            counts['events'] = apps.get_model('events', 'OutboxEvent')._base_manager.exclude(
                status='completed',
            ).update(status='held_restored', locked_until=None, updated_at=now)
            apps.get_model('audit', 'AuditEvent')._base_manager.create(
                actor=operator, tenant_id=None, action='platform.recovery_prepared',
                object_type='platform', object_id=uuid.uuid4(), purpose=reason,
                outcome='success', request_id=uuid.uuid4(), integrity_metadata=counts,
            )
        self.stdout.write('Recovery state prepared; reconcile held work before normal operation.')
```

### 24.7 — `base/management/commands/wait_for_db.py`

```python
from django.core.management.base import BaseCommand
from ops.runtime import database_ready, wait_until


class Command(BaseCommand):
    help = 'Wait for the application database without exposing credentials.'

    def handle(self, *args, **options):
        wait_until(database_ready, 'database')
```

### 24.8 — `base/management/commands/wait_for_dependencies.py`

```python
from django.core.management.base import BaseCommand
from ops.runtime import wait_dependencies


class Command(BaseCommand):
    help = 'Wait for database schema, broker and result backend.'

    def handle(self, *args, **options):
        wait_dependencies()
```

### 24.9 — `base/tasks.py`

```python
from celery import shared_task
from django.conf import settings


@shared_task(name='base.tasks.operational_ping', expires=60, ignore_result=False)
def operational_ping():
    return {'ok': True, 'release': settings.RELEASE_ID}
```

### 24.10 — `compose.yml`

```yaml
services:
  app:
    image: neurodoc:dev
    command:
    - app
    env_file:
    - .runtime/app.env
    environment:
      RELEASE_ID: dev
      ROLLOUT_ID: dev
    read_only: true
    tmpfs:
    - /tmp:size=128m,mode=1777
    - /run/neurodoc-signing:size=16m,uid=10001,gid=10001,mode=0700
    volumes:
    - media:/data/media
    - staticfiles:/data/staticfiles
    - signing:/data/signing
    secrets:
    - NEURODOC_DJANGO_SECRET_KEY
    - NEURODOC_DB_APP_PASSWORD
    - NEURODOC_DB_OWNER_PASSWORD
    - NEURODOC_RABBITMQ_PASSWORD
    - NEURODOC_REDIS_PASSWORD
    - NEURODOC_PFX_MASTER_KEY
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - python
      - /app/ops/http_health.py
      interval: 15s
      timeout: 5s
      start_period: 120s
      retries: 5
    stop_grace_period: 60s
    restart: on-failure:10
    build:
      context: .
      args:
        PYTHON_IMAGE: python:3.14.7-slim-bookworm
        RELEASE_ID: dev
    ports:
    - 127.0.0.1:8000:8000
  celery_worker:
    image: neurodoc:dev
    command:
    - worker
    env_file:
    - .runtime/worker.env
    environment:
      RELEASE_ID: dev
      ROLLOUT_ID: dev
    read_only: true
    tmpfs:
    - /tmp:size=256m,mode=1777
    volumes:
    - media:/data/media
    - clamav:/data/clamav
    secrets:
    - NEURODOC_DJANGO_SECRET_KEY
    - NEURODOC_DB_APP_PASSWORD
    - NEURODOC_RABBITMQ_PASSWORD
    - NEURODOC_REDIS_PASSWORD
    - NEURODOC_SMTP_PASSWORD
    - NEURODOC_SMSDEV_API_KEY
    - NEURODOC_OPENROUTER_API_KEY
    - NEURODOC_OPENAI_API_KEY
    - NEURODOC_ANTHROPIC_API_KEY
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - python
      - /app/ops/celery_health.py
      - worker
      interval: 30s
      timeout: 10s
      start_period: 180s
      retries: 5
    stop_grace_period: 390s
    restart: on-failure:10
  celery_beat:
    image: neurodoc:dev
    command:
    - beat
    env_file:
    - .runtime/beat.env
    environment:
      RELEASE_ID: dev
      ROLLOUT_ID: dev
    read_only: true
    tmpfs:
    - /tmp:size=64m,mode=1777
    volumes:
    - beat:/data/beat
    secrets:
    - NEURODOC_DJANGO_SECRET_KEY
    - NEURODOC_DB_APP_PASSWORD
    - NEURODOC_RABBITMQ_PASSWORD
    - NEURODOC_REDIS_PASSWORD
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - python
      - /app/ops/celery_health.py
      - beat
      interval: 30s
      timeout: 5s
      start_period: 180s
      retries: 5
    stop_grace_period: 30s
    restart: on-failure:10
  db:
    image: postgres:17.11-bookworm
    environment:
      POSTGRES_DB: neurodoc
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD_FILE: /run/secrets/NEURODOC_DB_ADMIN_PASSWORD
      POSTGRES_INITDB_ARGS: --auth-host=scram-sha-256 --auth-local=trust
    volumes:
    - postgres:/var/lib/postgresql/data
    configs:
    - source: postgres_init
      target: /docker-entrypoint-initdb.d/10-neurodoc.sh
      mode: 365
    secrets:
    - NEURODOC_DB_ADMIN_PASSWORD
    - NEURODOC_DB_OWNER_PASSWORD
    - NEURODOC_DB_APP_PASSWORD
    networks:
    - local
    healthcheck:
      test:
      - CMD-SHELL
      - pg_isready -U postgres -d neurodoc
      interval: 15s
      timeout: 5s
      start_period: 90s
      retries: 5
    stop_grace_period: 60s
    restart: on-failure:10
  rabbitmq:
    image: rabbitmq:4.3.5
    hostname: rabbitmq
    entrypoint:
    - sh
    - /etc/neurodoc/infra_entrypoint.sh
    - rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: neurodoc
      RABBITMQ_DEFAULT_VHOST: neurodoc
      RABBITMQ_NODENAME: rabbit@rabbitmq
    volumes:
    - rabbitmq:/var/lib/rabbitmq
    configs:
    - source: infra_entrypoint
      target: /etc/neurodoc/infra_entrypoint.sh
    secrets:
    - NEURODOC_RABBITMQ_PASSWORD
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - rabbitmq-diagnostics
      - -q
      - check_port_connectivity
      interval: 30s
      timeout: 15s
      start_period: 120s
      retries: 5
    stop_grace_period: 60s
    restart: on-failure:10
  redis:
    image: redis:8.10.1
    entrypoint:
    - sh
    - /etc/neurodoc/infra_entrypoint.sh
    - redis
    volumes:
    - redis:/data
    configs:
    - source: infra_entrypoint
      target: /etc/neurodoc/infra_entrypoint.sh
    secrets:
    - NEURODOC_REDIS_PASSWORD
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - sh
      - /etc/neurodoc/infra_entrypoint.sh
      - redis-health
      interval: 15s
      timeout: 5s
      start_period: 30s
      retries: 5
    stop_grace_period: 30s
    restart: on-failure:10
  traefik:
    image: traefik:v3.7.12
    command:
    - --entrypoints.web.address=:80
    - --entrypoints.ping.address=:8082
    - --ping=true
    - --ping.entrypoint=ping
    - --providers.file.filename=/etc/traefik/local.yml
    environment: {}
    read_only: true
    tmpfs:
    - /tmp:size=32m,mode=1777
    ports:
    - 127.0.0.1:8080:80
    volumes: []
    configs:
    - source: traefik_local
      target: /etc/traefik/local.yml
    secrets: []
    networks:
    - local
    healthcheck:
      test:
      - CMD
      - traefik
      - healthcheck
      - --ping
      - --entrypoints.ping.address=:8082
      - --ping.entrypoint=ping
      interval: 15s
      timeout: 5s
      start_period: 30s
      retries: 5
    restart: on-failure:10
networks:
  local:
    driver: bridge
volumes:
  postgres: {}
  redis: {}
  rabbitmq: {}
  media: {}
  staticfiles: {}
  signing: {}
  beat: {}
  clamav: {}
configs:
  postgres_init:
    file: ./ops/postgres_init.sh
  infra_entrypoint:
    file: ./ops/infra_entrypoint.sh
  traefik_local:
    file: ./ops/traefik-local.yml
secrets:
  NEURODOC_DJANGO_SECRET_KEY:
    file: ./.secrets/NEURODOC_DJANGO_SECRET_KEY
  NEURODOC_DB_ADMIN_PASSWORD:
    file: ./.secrets/NEURODOC_DB_ADMIN_PASSWORD
  NEURODOC_DB_OWNER_PASSWORD:
    file: ./.secrets/NEURODOC_DB_OWNER_PASSWORD
  NEURODOC_DB_APP_PASSWORD:
    file: ./.secrets/NEURODOC_DB_APP_PASSWORD
  NEURODOC_RABBITMQ_PASSWORD:
    file: ./.secrets/NEURODOC_RABBITMQ_PASSWORD
  NEURODOC_REDIS_PASSWORD:
    file: ./.secrets/NEURODOC_REDIS_PASSWORD
  NEURODOC_SMTP_PASSWORD:
    file: ./.secrets/NEURODOC_SMTP_PASSWORD
  NEURODOC_SMSDEV_API_KEY:
    file: ./.secrets/NEURODOC_SMSDEV_API_KEY
  NEURODOC_OPENROUTER_API_KEY:
    file: ./.secrets/NEURODOC_OPENROUTER_API_KEY
  NEURODOC_OPENAI_API_KEY:
    file: ./.secrets/NEURODOC_OPENAI_API_KEY
  NEURODOC_ANTHROPIC_API_KEY:
    file: ./.secrets/NEURODOC_ANTHROPIC_API_KEY
  NEURODOC_PFX_MASTER_KEY:
    file: ./.secrets/NEURODOC_PFX_MASTER_KEY
```

### 24.11 — `core/__init__.py`

```python
from .celery import app as celery_app

__all__ = ('celery_app',)
```

### 24.12 — `core/asgi.py`

```python
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
application = get_asgi_application()
```

### 24.13 — `core/celery.py`

```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
app = Celery('neurodoc')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### 24.14 — `core/settings.py`

```python
import os
import re
from pathlib import Path
from urllib.parse import quote

import environ

from ops.env import read_env, secret


BASE_DIR = Path(__file__).resolve().parent.parent
if (BASE_DIR / '.env').exists():
    for key, value in read_env(BASE_DIR / '.env').items():
        os.environ.setdefault(key, value)
env = environ.Env()
DEBUG = env.bool('DEBUG', default=False)
SECRET_KEY = secret('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = env('TIME_ZONE', default='America/Sao_Paulo')
USE_I18N = True
USE_TZ = True
ROOT_URLCONF = 'core.urls'
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL = 'accounts.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth',
    'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles',
    'django.contrib.postgres', 'django_otp',
    'django_otp.plugins.otp_totp',
    'dj_control_room_base', 'dj_celery_panel', 'dj_control_room',
    'base', 'accounts', 'tenancy', 'patients',
    'catalogs', 'clinical', 'scheduling', 'documents', 'communications',
    'crm', 'finance', 'ai', 'notifications', 'audit', 'reporting',
    'integrations', 'events',
]
MIDDLEWARE = [
    'ops.http_health.HealthMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'ops.staticfiles.ReleaseStaticMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'tenancy.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
database = {
    'ENGINE': 'django.db.backends.postgresql',
    'HOST': env('DB_HOST', default='db'), 'PORT': '5432',
    'NAME': 'neurodoc', 'CONN_MAX_AGE': 0, 'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': 5},
}
DATABASES = {'default': dict(
    database, USER='neurodoc_app', PASSWORD=secret('DB_APP_PASSWORD'),
)}
if env.bool('RUN_MIGRATIONS', default=False):
    DATABASES['migrations'] = dict(
        database, USER='neurodoc_owner', PASSWORD=secret('DB_OWNER_PASSWORD'),
    )
redis_password = quote(secret('REDIS_PASSWORD'), safe='')
rabbit_password = quote(secret('RABBITMQ_PASSWORD'), safe='')
REDIS_BASE = f'redis://:{redis_password}@redis:6379'
CELERY_BROKER_URL = f'amqp://neurodoc:{rabbit_password}@rabbitmq:5672/neurodoc'
CELERY_RESULT_BACKEND = f'{REDIS_BASE}/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_RESULT_EXPIRES = 86400
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 100
CELERY_BROKER_TRANSPORT_OPTIONS = {'confirm_publish': True}
CELERY_TASK_DEFAULT_QUEUE = 'maintenance'
CELERY_TASK_DEFAULT_DELIVERY_MODE = 'persistent'
CELERY_TASK_SEND_SENT_EVENT = False
CELERY_WORKER_SEND_TASK_EVENTS = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 360
# Domain tasks register routes and periodic entries during their sprints.
CELERY_TASK_ROUTES = {
    'communications.tasks.*': {'queue': 'communications'},
    'ai.tasks.*': {'queue': 'ai'},
    'documents.tasks.*': {'queue': 'documents'},
    'reporting.tasks.*': {'queue': 'documents'},
}
CELERY_BEAT_SCHEDULE = {}
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
    'LOCATION': f'{REDIS_BASE}/1', 'TIMEOUT': 900,
    'KEY_PREFIX': 'neurodoc',
}}
AI_EVENTS_REDIS_URL = f'{REDIS_BASE}/2'
RELEASE_ID = env('RELEASE_ID', default='dev')
if not re.fullmatch(r'(dev|[a-f0-9]{40})', RELEASE_ID):
    raise ValueError('Invalid RELEASE_ID')
STATIC_URL = f'/static/{RELEASE_ID}/'
STATIC_ROOT = Path(os.environ.get('STATIC_PREPARATION_ROOT', '/data/staticfiles/public/static/' + RELEASE_ID))
WHITENOISE_AUTOREFRESH = False
WHITENOISE_USE_FINDERS = False
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
MEDIA_ROOT = Path('/data/media')
MEDIA_URL = '/private-media-unrouted/'
PFX_ROOT = Path('/data/signing')
SIGNING_SESSION_KEY_ROOT = Path('/run/neurodoc-signing')
PFX_MASTER_KEY = secret('PFX_MASTER_KEY', required=False)
DATA_UPLOAD_MAX_MEMORY_SIZE = 26214400
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SECURE_HSTS_SECONDS = 0
# Enable after staging validation: 31536000, then includeSubDomains if all aliases use TLS.
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
EMAIL_ENABLED = env.bool('EMAIL_ENABLED', default=False)
EMAIL_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_ENABLED
    else 'django.core.mail.backends.locmem.EmailBackend'
)
EMAIL_HOST = env('EMAIL_HOST', default='smtp.example.invalid')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = secret('SMTP_PASSWORD', required=(EMAIL_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
SMS_ENABLED = env.bool('SMS_ENABLED', default=False)
SMSDEV_API_KEY = secret('SMSDEV_API_KEY', required=(SMS_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
AI_ENABLED = env.bool('AI_ENABLED', default=False)
AI_PROVIDER = env('AI_PROVIDER', default='openrouter')
AI_MODEL = env('AI_MODEL', default='z-ai/glm-5.3-flash')
OPENROUTER_API_KEY = secret('OPENROUTER_API_KEY', required=False)
OPENAI_API_KEY = secret('OPENAI_API_KEY', required=False)
ANTHROPIC_API_KEY = secret('ANTHROPIC_API_KEY', required=False)
NEURODOC_DEMO_ALLOWED = env.bool('NEURODOC_DEMO_ALLOWED', default=False)
NEURODOC_RECOVERY_MODE = env.bool('NEURODOC_RECOVERY_MODE', default=False)
NEURODOC_DOCS_ENABLED = env.bool('NEURODOC_DOCS_ENABLED', default=True)
# Production logging filters must be integrated in S02/S10; never log request bodies.
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django.security.DisallowedHost': {
        'handlers': ['console'], 'level': 'ERROR', 'propagate': False,
    }},
}
```

### 24.15 — `docker-stack.yml`

```yaml
version: '3.9'
x-restart: &restart
  condition: on-failure
  delay: 10s
  max_attempts: 10
  window: 120s
x-placement: &placement
  constraints: ['node.labels.neurodoc_data == true']
services:
  app:
    image: ${APP_IMAGE}
    command: [app]
    env_file: [.runtime/app.env]
    environment:
      RELEASE_ID: ${RELEASE_ID}
      ROLLOUT_ID: ${ROLLOUT_ID}
    read_only: true
    tmpfs: ['/tmp:size=128m,mode=1777']
    volumes:
      - media:/data/media
      - staticfiles:/data/staticfiles
      - signing:/data/signing
      - type: bind
        source: /run/neurodoc-signing
        target: /run/neurodoc-signing
    secrets:
      - NEURODOC_DJANGO_SECRET_KEY
      - NEURODOC_DB_APP_PASSWORD
      - NEURODOC_DB_OWNER_PASSWORD
      - NEURODOC_RABBITMQ_PASSWORD
      - NEURODOC_REDIS_PASSWORD
      - NEURODOC_PFX_MASTER_KEY
    networks: [traefik_public, neurodoc_v1_internal]
    healthcheck:
      test: [CMD, python, /app/ops/http_health.py]
      interval: 15s
      timeout: 5s
      start_period: 120s
      retries: 5
    stop_grace_period: 60s
    deploy:
      replicas: ${APP_REPLICAS}
      restart_policy: *restart
      placement: *placement
      resources:
        limits: {cpus: '1.0', memory: 1G}
        reservations: {cpus: '0.25', memory: 384M}
      update_config:
        parallelism: 1
        delay: 120s
        monitor: 180s
        order: start-first
        failure_action: rollback
        max_failure_ratio: 0
      rollback_config:
        parallelism: 1
        delay: 30s
        order: start-first
        monitor: 180s
        failure_action: pause
      labels:
        com.neurodoc.platform: neurodoc_v1
        traefik.enable: 'true'
        traefik.swarm.network: traefik_public
        traefik.http.routers.neurodoc.rule: 'Host(`neurodoc.app.br`) || HostRegexp(`^[a-z0-9-]+\.neurodoc\.app\.br$$`)'
        traefik.http.routers.neurodoc.entrypoints: websecure
        traefik.http.routers.neurodoc.tls: 'true'
        traefik.http.routers.neurodoc.tls.certresolver: cloudflare
        traefik.http.routers.neurodoc.tls.domains[0].main: neurodoc.app.br
        traefik.http.routers.neurodoc.tls.domains[0].sans: '*.neurodoc.app.br'
        traefik.http.services.neurodoc.loadbalancer.server.port: '8000'
        traefik.http.services.neurodoc.loadbalancer.healthcheck.path: /health/
        traefik.http.services.neurodoc.loadbalancer.healthcheck.hostname: localhost
        traefik.http.services.neurodoc.loadbalancer.healthcheck.interval: 15s
        traefik.http.services.neurodoc.loadbalancer.healthcheck.timeout: 5s
  celery_worker:
    image: ${APP_IMAGE}
    command: [worker]
    env_file: [.runtime/worker.env]
    environment: {RELEASE_ID: '${RELEASE_ID}', ROLLOUT_ID: '${ROLLOUT_ID}'}
    read_only: true
    tmpfs: ['/tmp:size=256m,mode=1777']
    volumes: [media:/data/media, clamav:/data/clamav]
    secrets:
      - NEURODOC_DJANGO_SECRET_KEY
      - NEURODOC_DB_APP_PASSWORD
      - NEURODOC_RABBITMQ_PASSWORD
      - NEURODOC_REDIS_PASSWORD
      - NEURODOC_SMTP_PASSWORD
      - NEURODOC_SMSDEV_API_KEY
      - NEURODOC_OPENROUTER_API_KEY
      - NEURODOC_OPENAI_API_KEY
      - NEURODOC_ANTHROPIC_API_KEY
    networks: [neurodoc_v1_internal, neurodoc_v1_egress]
    healthcheck:
      test: [CMD, python, /app/ops/celery_health.py, worker]
      interval: 30s
      timeout: 10s
      start_period: 180s
      retries: 5
    stop_grace_period: 390s
    deploy:
      replicas: 1
      placement: *placement
      restart_policy: *restart
      resources:
        limits: {cpus: '1.5', memory: 3G}
        reservations: {cpus: '0.75', memory: 1G}
      update_config: {parallelism: 1, order: stop-first, failure_action: rollback, monitor: 180s}
  celery_beat:
    image: ${APP_IMAGE}
    command: [beat]
    env_file: [.runtime/beat.env]
    environment: {RELEASE_ID: '${RELEASE_ID}', ROLLOUT_ID: '${ROLLOUT_ID}'}
    read_only: true
    tmpfs: ['/tmp:size=64m,mode=1777']
    volumes: [beat:/data/beat]
    secrets:
      - NEURODOC_DJANGO_SECRET_KEY
      - NEURODOC_DB_APP_PASSWORD
      - NEURODOC_RABBITMQ_PASSWORD
      - NEURODOC_REDIS_PASSWORD
    networks: [neurodoc_v1_internal, neurodoc_v1_egress]
    healthcheck:
      test: [CMD, python, /app/ops/celery_health.py, beat]
      interval: 30s
      timeout: 5s
      start_period: 180s
      retries: 5
    stop_grace_period: 30s
    deploy:
      replicas: 1
      placement: *placement
      restart_policy: *restart
      resources:
        limits: {cpus: '0.25', memory: 256M}
        reservations: {cpus: '0.1', memory: 64M}
      update_config: {parallelism: 1, order: stop-first, failure_action: rollback, monitor: 180s}
      rollback_config: {parallelism: 1, order: stop-first}
  db:
    image: ${POSTGRES_IMAGE}
    environment:
      POSTGRES_DB: neurodoc
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD_FILE: /run/secrets/NEURODOC_DB_ADMIN_PASSWORD
      POSTGRES_INITDB_ARGS: '--auth-host=scram-sha-256 --auth-local=trust'
    volumes: [postgres:/var/lib/postgresql/data]
    configs:
      - source: postgres_init
        target: /docker-entrypoint-initdb.d/10-neurodoc.sh
        mode: 0555
    secrets: [NEURODOC_DB_ADMIN_PASSWORD, NEURODOC_DB_OWNER_PASSWORD, NEURODOC_DB_APP_PASSWORD]
    networks: [neurodoc_v1_internal]
    healthcheck:
      test: [CMD-SHELL, 'pg_isready -U postgres -d neurodoc']
      interval: 15s
      timeout: 5s
      start_period: 90s
      retries: 5
    stop_grace_period: 60s
    deploy:
      replicas: 1
      placement: *placement
      restart_policy: *restart
      resources:
        limits: {cpus: '1.0', memory: 2G}
        reservations: {cpus: '0.25', memory: 512M}
      update_config: {parallelism: 1, order: stop-first, failure_action: pause}
  rabbitmq:
    image: ${RABBITMQ_IMAGE}
    hostname: rabbitmq
    entrypoint: [sh, /etc/neurodoc/infra_entrypoint.sh, rabbitmq]
    environment:
      RABBITMQ_DEFAULT_USER: neurodoc
      RABBITMQ_DEFAULT_VHOST: neurodoc
      RABBITMQ_NODENAME: rabbit@rabbitmq
    volumes: [rabbitmq:/var/lib/rabbitmq]
    configs:
      - source: infra_entrypoint
        target: /etc/neurodoc/infra_entrypoint.sh
    secrets: [NEURODOC_RABBITMQ_PASSWORD]
    networks: [neurodoc_v1_internal]
    healthcheck:
      test: [CMD, rabbitmq-diagnostics, -q, check_port_connectivity]
      interval: 30s
      timeout: 15s
      start_period: 120s
      retries: 5
    stop_grace_period: 60s
    deploy:
      replicas: 1
      placement: *placement
      restart_policy: *restart
      resources:
        limits: {cpus: '0.75', memory: 1G}
        reservations: {cpus: '0.25', memory: 256M}
      update_config: {parallelism: 1, order: stop-first, failure_action: pause}
  redis:
    image: ${REDIS_IMAGE}
    entrypoint: [sh, /etc/neurodoc/infra_entrypoint.sh, redis]
    volumes: [redis:/data]
    configs:
      - source: infra_entrypoint
        target: /etc/neurodoc/infra_entrypoint.sh
    secrets: [NEURODOC_REDIS_PASSWORD]
    networks: [neurodoc_v1_internal]
    healthcheck:
      test: [CMD, sh, /etc/neurodoc/infra_entrypoint.sh, redis-health]
      interval: 15s
      timeout: 5s
      start_period: 30s
      retries: 5
    stop_grace_period: 30s
    deploy:
      replicas: 1
      placement: *placement
      restart_policy: *restart
      resources:
        limits: {cpus: '0.5', memory: 512M}
        reservations: {cpus: '0.1', memory: 128M}
      update_config: {parallelism: 1, order: stop-first, failure_action: pause}
  traefik:
    image: ${TRAEFIK_IMAGE}
    command: ['--configFile=/etc/traefik/traefik.yml']
    environment:
      CF_DNS_API_TOKEN_FILE: /run/secrets/CLOUDFLARE_DNS_API_TOKEN
    read_only: true
    tmpfs: ['/tmp:size=32m,mode=1777']
    ports:
      - {target: 80, published: 80, protocol: tcp, mode: host}
      - {target: 443, published: 443, protocol: tcp, mode: host}
    volumes:
      - letsencrypt:/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro
    configs:
      - source: traefik_settings
        target: /etc/traefik/traefik.yml
    secrets: [CLOUDFLARE_DNS_API_TOKEN]
    networks: [traefik_public]
    healthcheck:
      test: [CMD, traefik, healthcheck, '--ping']
      interval: 15s
      timeout: 5s
      start_period: 30s
      retries: 5
    deploy:
      replicas: 1
      placement:
        constraints: ['node.role == manager', 'node.labels.neurodoc_data == true']
      restart_policy: *restart
      resources:
        limits: {cpus: '0.5', memory: 256M}
        reservations: {cpus: '0.1', memory: 64M}
      update_config: {parallelism: 1, order: stop-first, failure_action: rollback}
networks:
  traefik_public: {external: true, name: traefik_public}
  neurodoc_v1_internal: {external: true, name: neurodoc_v1_internal}
  neurodoc_v1_egress: {external: true, name: neurodoc_v1_egress}
volumes:
  postgres: {external: true, name: neurodoc_v1_postgres}
  redis: {external: true, name: neurodoc_v1_redis}
  rabbitmq: {external: true, name: neurodoc_v1_rabbitmq}
  media: {external: true, name: neurodoc_v1_media}
  staticfiles: {external: true, name: neurodoc_v1_staticfiles}
  letsencrypt: {external: true, name: neurodoc_v1_letsencrypt}
  signing: {external: true, name: neurodoc_v1_signing}
  beat: {external: true, name: neurodoc_v1_beat}
  clamav: {external: true, name: neurodoc_v1_clamav}
configs:
  postgres_init: {external: true, name: '${POSTGRES_INIT_CONFIG}'}
  infra_entrypoint: {external: true, name: '${INFRA_ENTRYPOINT_CONFIG}'}
  traefik_settings: {external: true, name: '${TRAEFIK_CONFIG}'}
secrets:
  NEURODOC_DJANGO_SECRET_KEY: {external: true}
  NEURODOC_DB_ADMIN_PASSWORD: {external: true}
  NEURODOC_DB_OWNER_PASSWORD: {external: true}
  NEURODOC_DB_APP_PASSWORD: {external: true}
  NEURODOC_RABBITMQ_PASSWORD: {external: true}
  NEURODOC_REDIS_PASSWORD: {external: true}
  NEURODOC_SMTP_PASSWORD: {external: true}
  NEURODOC_SMSDEV_API_KEY: {external: true}
  NEURODOC_OPENROUTER_API_KEY: {external: true}
  NEURODOC_OPENAI_API_KEY: {external: true}
  NEURODOC_ANTHROPIC_API_KEY: {external: true}
  NEURODOC_PFX_MASTER_KEY: {external: true}
  CLOUDFLARE_DNS_API_TOKEN: {external: true}
```

### 24.16 — `manage.py`

```python
#!/usr/bin/env python
import os
import sys

from django.core.management import execute_from_command_line

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    execute_from_command_line(sys.argv)
```

### 24.17 — `mkdocs.yml`

```yaml
site_name: NeuroDoc
site_url: https://neurodoc.app.br/technical-docs/
docs_dir: docs
site_dir: site
use_directory_urls: true
theme:
  name: material
  language: pt-BR
markdown_extensions:
  - tables
  - admonition
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
```

### 24.18 — `ops/__init__.py`

```python
# Operational helpers for the NeuroDoc application.
```

### 24.19 — `ops/backup.py`

```python
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ops.deploy import configuration, run
from ops.env import ROOT


BACKUP_LOCK = 72654002


def container_for(service):
    ids = run(['docker', 'ps', '-q', '--filter',
               f'label=com.docker.swarm.service.name=neurodoc_v1_{service}']).splitlines()
    if len(ids) != 1:
        raise RuntimeError(f'Expected one container for {service}')
    return ids[0]


def encrypt_stream(command, output, recipient):
    with output.open('xb') as destination:
        producer = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        try:
            encryptor = subprocess.run(['age', '-r', recipient], stdin=producer.stdout,
                                       stdout=destination, stderr=subprocess.DEVNULL)
            producer.stdout.close()
            code = producer.wait(timeout=3600)
            if code or encryptor.returncode:
                raise RuntimeError('Backup stream or encryption failed')
        finally:
            if producer.poll() is None:
                producer.kill()
                producer.wait()


def main():
    os.umask(0o077)
    config = configuration()
    root = Path(config['BACKUP_DIR'])
    if not root.is_absolute() or root.name != 'neurodoc-backups' or root.is_symlink():
        raise RuntimeError('Use an absolute, non-symlink directory named neurodoc-backups')
    recipient = config['BACKUP_AGE_RECIPIENT']
    if not recipient.startswith('age1'):
        raise RuntimeError('A valid offline age recipient is required')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    record_path = ROOT / '.runtime/last-successful.json'
    record = json.loads(record_path.read_text())
    database = container_for('db')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = root / f'{stamp}-{uuid.uuid4().hex[:8]}'
    target.mkdir(mode=0o700)
    keeper = subprocess.Popen(
        ['docker', 'exec', '-i', '-e', 'PGCONNECT_TIMEOUT=5', database,
         'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'neurodoc'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    locked = False
    try:
        keeper.stdin.write("SET statement_timeout = '10s';\n")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            keeper.stdin.write(f'SELECT pg_try_advisory_lock({BACKUP_LOCK});\n')
            keeper.stdin.flush()
            response = keeper.stdout.readline().strip()
            if response == 't':
                locked = True
                break
            if response != 'f':
                raise RuntimeError('Backup lock session failed')
            time.sleep(2)
        if not locked:
            raise RuntimeError('Backup lock timeout')
        encrypt_stream(
            ['docker', 'exec', database, 'pg_dump', '-U', 'postgres',
             '-d', 'neurodoc', '--format=custom', '--no-owner', '--no-acl', '--no-comments'],
            target / 'database.dump.age', recipient,
        )
        for volume in ['media', 'signing', 'letsencrypt']:
            encrypt_stream(
                ['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                 '--entrypoint', 'tar', '--mount',
                 f'type=volume,src=neurodoc_v1_{volume},dst=/source,readonly',
                 record['APP_IMAGE'], '-C', '/source', '-cf', '-', '.'],
                target / f'{volume}.tar.age', recipient,
            )
        files = {}
        for path in target.iterdir():
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1048576), b''):
                    digest.update(chunk)
            files[path.name] = {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
        manifest = {'completed_at': datetime.now(timezone.utc).isoformat(),
                    'release': record, 'files': files,
                    'consistency': 'database snapshot then immutable files; deletion lock held'}
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        (target / 'COMPLETE').write_text('ok\n')
    finally:
        if keeper.poll() is None:
            try:
                keeper.stdin.write('\\q\n')
                keeper.stdin.flush()
            except BrokenPipeError:
                pass
            try:
                keeper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                keeper.kill()
                keeper.wait()
    if not (target / 'COMPLETE').exists():
        raise RuntimeError('Backup did not complete')
    retention = int(config['BACKUP_RETENTION_DAYS'])
    if retention < 7:
        raise RuntimeError('Retention must be at least seven days')
    cutoff = time.time() - retention * 86400
    for folder in root.iterdir():
        if folder == target or folder.is_symlink() or not folder.is_dir():
            continue
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', folder.name):
            continue
        if (folder / 'COMPLETE').is_file() and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder)
    print(f'Encrypted backup complete: {target.name}; copy off-host and verify restore.')


if __name__ == '__main__':
    main()
```

### 24.20 — `ops/celery_health.py`

```python
import os
import socket
import sys
import time
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
if sys.argv[1] == 'beat':
    try:
        age = time.time() - float(Path('/tmp/beat-heartbeat').read_text())
        raise SystemExit(0 if 0 <= age < 60 else 1)
    except (ValueError, FileNotFoundError):
        raise SystemExit(1)
else:
    from core.celery import app
    name = f'worker@{socket.gethostname()}'
    replies = app.control.inspect(destination=[name], timeout=5).ping() or {}
    raise SystemExit(0 if replies.get(name, {}).get('ok') == 'pong' else 1)
```

### 24.21 — `ops/deploy.py`

```python
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from ops.env import ROOT, read_env
from ops.make_runtime import make_traefik, prepare_runtime


STACK = 'neurodoc_v1'
REGISTRY = 'ghcr.io/pycodebr/scsi_v1'
SERVICES = ['app', 'celery_worker', 'celery_beat', 'db', 'rabbitmq', 'redis', 'traefik']
IMAGE_KEYS = ['PYTHON_IMAGE', 'POSTGRES_IMAGE', 'RABBITMQ_IMAGE', 'REDIS_IMAGE', 'TRAEFIK_IMAGE']


def run(args, env=None, input_text=None):
    result = subprocess.run(args, cwd=ROOT, env=env, input=input_text,
                            text=True, capture_output=True)
    if result.returncode:
        # Detailed output may contain application data; do not print it here.
        raise RuntimeError(f'Command failed: {args[0]} {args[1]} (exit {result.returncode})')
    return result.stdout.strip()


def configuration():
    defaults = read_env(ROOT / '.env.example')
    custom = read_env(ROOT / '.env')
    unknown = set(custom) - set(defaults)
    if unknown:
        raise ValueError(f'Unknown configuration keys: {sorted(unknown)}')
    defaults.update(custom)
    return defaults


def inspect_network(name, internal):
    data = json.loads(run(['docker', 'network', 'inspect', name]))[0]
    if data['Driver'] != 'overlay' or data['Scope'] != 'swarm':
        raise RuntimeError(f'Invalid network driver/scope: {name}')
    if bool(data['Internal']) != internal:
        raise RuntimeError(f'Invalid network isolation: {name}')


def preflight(config):
    if config['DEBUG'] != 'False':
        raise RuntimeError('Production requires DEBUG=False')
    if config['NEURODOC_RELEASE_APPROVED'] != 'True':
        raise RuntimeError('Release homologation has not been recorded')
    if config['NEURODOC_SCHEMA_CHANGE'] != 'expand':
        raise RuntimeError('Destructive schema changes require a maintenance procedure')
    hosts = set(config['ALLOWED_HOSTS'].split(','))
    if not {'neurodoc.app.br', '.neurodoc.app.br', 'localhost', '127.0.0.1'} <= hosts:
        raise RuntimeError('Required ALLOWED_HOSTS entries missing')
    origins = set(config['CSRF_TRUSTED_ORIGINS'].split(','))
    if not {'https://neurodoc.app.br', 'https://*.neurodoc.app.br'} <= origins:
        raise RuntimeError('Required CSRF trusted origins missing')
    if config['PUBLIC_BASE_URL'] != 'https://neurodoc.app.br':
        raise RuntimeError('Unexpected production base URL')
    if int(config['APP_REPLICAS']) < 2:
        raise RuntimeError('Production rollout baseline requires two web replicas')
    if config['ACME_EMAIL'] == 'CHANGE_ME' or '@' not in config['ACME_EMAIL']:
        raise RuntimeError('Configure the ACME account email')
    info = json.loads(run(['docker', 'info', '--format', '{{json .Swarm}}']))
    if info.get('LocalNodeState') != 'active' or not info.get('ControlAvailable'):
        raise RuntimeError('Run on an active Swarm manager')
    nodes = run(['docker', 'node', 'ls', '-q']).splitlines()
    if len(nodes) != 1 or config['NEURODOC_NODES'] != '1':
        raise RuntimeError('This deployment requires the documented single-node topology')
    node = json.loads(run(['docker', 'node', 'inspect', 'self']))[0]
    if node['Spec'].get('Labels', {}).get('neurodoc_data') != 'true':
        raise RuntimeError('The persistent-data node label is missing')
    for name, internal in [('traefik_public', False),
                           ('neurodoc_v1_internal', True),
                           ('neurodoc_v1_egress', False)]:
        inspect_network(name, internal)
    import yaml
    stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
    for name in stack['secrets']:
        run(['docker', 'secret', 'inspect', name, '--format', '{{.ID}}'])
    if run(['findmnt', '-n', '-o', 'FSTYPE', '-T', '/run/neurodoc-signing']) != 'tmpfs':
        raise RuntimeError('Signing session keys must reside on tmpfs')
    for path in ['requirements.txt', 'manage.py', 'core/asgi.py',
                 'accounts/models.py', 'tenancy/middleware.py', 'docs/index.md']:
        if not (ROOT / path).is_file():
            raise RuntimeError(f'Implementation prerequisite missing: {path}')
    lock = (ROOT / 'requirements.txt').read_text()
    if '--hash=' not in lock:
        raise RuntimeError('Resolve and commit requirements.txt with hashes')
    if run(['git', 'status', '--porcelain', '--untracked-files=no']):
        raise RuntimeError('Commit or resolve tracked changes before deployment')


def resolve_image(reference):
    if ':latest' in reference or (':' not in reference and '@sha256:' not in reference):
        raise RuntimeError('Unpinned image reference')
    run(['docker', 'pull', reference])
    data = json.loads(run(['docker', 'image', 'inspect', reference]))[0]
    digests = data.get('RepoDigests') or []
    if not digests:
        raise RuntimeError('Registry digest unavailable')
    return next((item for item in digests if item.split('@')[0] == reference.split('@')[0]), digests[0])


def create_config(path, prefix):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    name = f'neurodoc_{prefix}_{digest}'
    exists = subprocess.run(['docker', 'config', 'inspect', name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if exists.returncode:
        run(['docker', 'config', 'create', name, str(path)])
    return name


def initialize_volumes(image):
    import yaml
    stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
    for value in stack['volumes'].values():
        run(['docker', 'volume', 'create', value['name']])
    mounts = []
    for item in ['media', 'staticfiles', 'signing', 'beat', 'clamav']:
        mounts += ['--mount', f'type=volume,src=neurodoc_v1_{item},dst=/data/{item}']
    program = (
        'import os; from pathlib import Path; '
        '[(os.chown(p,10001,10001),os.chmod(p,0o750)) '
        'for p in Path("/data").iterdir() if p.is_dir()]'
    )
    run(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
         '--entrypoint', 'python', *mounts, image, '-c', program])


def wait_for_stack(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = True
        for service in SERVICES:
            name = f'{STACK}_{service}'
            data = json.loads(run(['docker', 'service', 'inspect', name]))[0]
            state = data.get('UpdateStatus', {}).get('State')
            if state in {'paused', 'rollback_started', 'rollback_paused', 'rollback_completed'}:
                raise RuntimeError(f'Deployment failed or rolled back: {service}')
            if state and state != 'completed':
                ready = False
            desired = data['Spec']['Mode']['Replicated']['Replicas']
            containers = run(['docker', 'ps', '-q', '--filter',
                              f'label=com.docker.swarm.service.name={name}']).splitlines()
            if len(containers) != desired:
                ready = False
                continue
            for container in containers:
                info = json.loads(run(['docker', 'inspect', container]))[0]
                if info['State'].get('Health', {}).get('Status') != 'healthy':
                    ready = False
        if ready:
            apps = run(['docker', 'ps', '-q', '--filter',
                        f'label=com.docker.swarm.service.name={STACK}_app']).splitlines()
            for container in apps:
                run(['docker', 'exec', container, 'python', '/app/ops/probe_ready.py'])
            return
        print('Waiting for service health and convergence...', flush=True)
        time.sleep(10)
    raise RuntimeError('Stack convergence timeout; inspect services before retrying')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--synced', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = configuration()
    preflight(config)
    if not args.synced:
        run(['git', 'pull', '--ff-only'])
        options = ['--skip-build'] if args.skip_build else []
        os.execv(sys.executable, [sys.executable, '-m', 'ops.deploy',
                                 *options, '--synced'])
    runtime = prepare_runtime(config)
    record_path = runtime / 'last-successful.json'
    previous = json.loads(record_path.read_text()) if record_path.exists() else None
    images = {key: resolve_image(config[key]) for key in IMAGE_KEYS}
    if previous:
        for key in IMAGE_KEYS[1:]:
            if previous[key] != images[key]:
                raise RuntimeError('Infrastructure image changed: use a planned maintenance upgrade')
    if args.skip_build:
        if not previous:
            raise RuntimeError('--skip-build requires a previous successful release record')
        app_image = resolve_image(previous['APP_IMAGE'])
        release = previous['RELEASE_ID']
    else:
        release = run(['git', 'rev-parse', 'HEAD'])
        if not re.fullmatch(r'[a-f0-9]{40}', release):
            raise RuntimeError('Invalid Git commit identifier')
        tag = f'{REGISTRY}:{release}'
        published = subprocess.run(['docker', 'manifest', 'inspect', tag],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if published.returncode != 0:
            run(['docker', 'build', '--pull', '--build-arg',
                 f'PYTHON_IMAGE={images["PYTHON_IMAGE"]}', '--build-arg',
                 f'RELEASE_ID={release}', '-t', tag, '.'])
            run(['docker', 'push', tag])
        app_image = resolve_image(tag)
    label = json.loads(run(['docker', 'image', 'inspect', app_image]))[0]
    if label['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != release:
        raise RuntimeError('Image revision does not match release record')
    initialize_volumes(app_image)
    cidrs = []
    for suffix in ['ips-v4', 'ips-v6']:
        with urllib.request.urlopen(f'https://www.cloudflare.com/{suffix}', timeout=10) as response:
            cidrs.extend(response.read().decode().splitlines())
    traefik_file = make_traefik(config, cidrs)
    params = dict(images, APP_IMAGE=app_image, RELEASE_ID=release,
                  ROLLOUT_ID=uuid.uuid4().hex, APP_REPLICAS=config['APP_REPLICAS'])
    params['POSTGRES_INIT_CONFIG'] = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    params['INFRA_ENTRYPOINT_CONFIG'] = create_config(ROOT / 'ops/infra_entrypoint.sh', 'infra')
    params['TRAEFIK_CONFIG'] = create_config(traefik_file, 'traefik')
    command_env = dict(os.environ, **params)
    rendered = run(['docker', 'stack', 'config', '--compose-file', 'docker-stack.yml'], env=command_env)
    if '${' in rendered:
        raise RuntimeError('Unresolved stack variables')
    candidate = runtime / 'candidate.json'
    candidate.write_text(json.dumps(params, indent=2))
    candidate.chmod(0o600)
    run(['docker', 'stack', 'deploy', '--with-registry-auth',
         '--resolve-image', 'always', '--compose-file', 'docker-stack.yml', STACK], env=command_env)
    wait_for_stack(int(config['DEPLOY_TIMEOUT_SECONDS']))
    if 'staging' not in config['ACME_DIRECTORY']:
        with urllib.request.urlopen(config['PUBLIC_BASE_URL'] + '/health/', timeout=15) as response:
            if response.status != 200:
                raise RuntimeError('External HTTPS health check failed')
    if record_path.exists():
        (runtime / 'previous-successful.json').write_bytes(record_path.read_bytes())
    record_path.write_text(json.dumps(params, indent=2))
    record_path.chmod(0o600)
    print(f'Release {release} deployed; all services are healthy.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
```

### 24.22 — `ops/docs.py`

```python
import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe


@require_safe
def technical_docs(request, path=''):
    user = request.user
    if not (settings.NEURODOC_DOCS_ENABLED and user.is_authenticated
            and user.is_active and user.is_staff and user.is_superuser
            and user.is_verified()):
        raise Http404
    root = (settings.BASE_DIR / 'site').resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or any(p.startswith('.') for p in path.split('/')):
        raise Http404
    if target.is_dir():
        target = target / 'index.html'
    if not target.is_file():
        raise Http404
    response = FileResponse(target.open('rb'), content_type=
                            mimetypes.guess_type(target.name)[0] or
                            'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    return response
```

### 24.23 — `ops/entrypoint.sh`

```sh
#!/bin/sh
set -eu
umask 027
case "${1:-app}" in
  app)
    python manage.py wait_for_db
    python manage.py bootstrap_release
    exec uvicorn core.asgi:application --host 0.0.0.0 --port 8000 \
      --workers 2 --no-access-log --timeout-keep-alive 30 \
      --no-proxy-headers
    ;;
  worker)
    python manage.py wait_for_dependencies
    ND_WORKER_QUEUES=communications,ai,documents,maintenance
    if [ "${NEURODOC_RECOVERY_MODE:-False}" = 'True' ]; then
      ND_WORKER_QUEUES=recovery
    fi
    exec celery -A core worker --hostname='worker@%h' \
      --loglevel=WARNING --concurrency=2 --prefetch-multiplier=1 \
      --queues="$ND_WORKER_QUEUES"
    ;;
  beat)
    python manage.py wait_for_dependencies
    exec celery -A core beat --loglevel=WARNING \
      --scheduler=ops.scheduler.HeartbeatScheduler \
      --schedule=/data/beat/celerybeat-schedule --max-interval=10
    ;;
  *)
    exec "$@"
    ;;
esac
```

### 24.24 — `ops/env.py`

```python
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_env(path):
    result = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError(f'Invalid environment key at line {number}')
        if key in result:
            raise ValueError(f'Duplicate environment key: {key}')
        if value.startswith('"'):
            value = json.loads(value)
        if not isinstance(value, str) or any(c in value for c in '\x00\r\n'):
            raise ValueError(f'Invalid environment value for {key}')
        result[key] = value
    return result


def secret(name, required=True):
    file_name = os.environ.get(f'{name}_FILE')
    direct = os.environ.get(name)
    if file_name and direct is not None:
        raise ValueError(f'Ambiguous secret configuration: {name}')
    value = Path(file_name).read_text().rstrip('\r\n') if file_name else direct
    if required and (not value or value == 'DISABLED'):
        raise ValueError(f'Missing secret: {name}')
    return value or ''


def write_env(path, values):
    lines = []
    for key, value in values.items():
        value = str(value)
        # Generated env_files contain non-sensitive configuration only.
        if any(c in value for c in '\r\n\x00$'):
            raise ValueError(f'Unsafe Docker env_file interpolation: {key}')
        lines.append(f'{key}={value}')
    Path(path).write_text('\n'.join(lines) + '\n')
    Path(path).chmod(0o600)
```

### 24.25 — `ops/http_health.py`

```python
import urllib.request

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpResponse


class HealthMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    @staticmethod
    def health_response(request):
        request.get_host()
        response = HttpResponse('ok', content_type='text/plain')
        response['Cache-Control'] = 'no-store'
        return response

    def __call__(self, request):
        if self.is_async:
            return self.acall(request)
        if request.path_info == '/health/':
            return self.health_response(request)
        return self.get_response(request)

    async def acall(self, request):
        if request.path_info == '/health/':
            return self.health_response(request)
        return await self.get_response(request)


if __name__ == '__main__':
    with urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=4) as result:
        raise SystemExit(0 if result.status == 200 else 1)
```

### 24.26 — `ops/infra_entrypoint.sh`

```sh
#!/bin/sh
set -eu
umask 077
case "$1" in
  rabbitmq)
    export RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/NEURODOC_RABBITMQ_PASSWORD)"
    exec docker-entrypoint.sh rabbitmq-server
    ;;
  redis)
    password_hash="$(sha256sum /run/secrets/NEURODOC_REDIS_PASSWORD | cut -d ' ' -f 1)"
    cat > /tmp/neurodoc-redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync everysec
maxmemory 384mb
maxmemory-policy noeviction
user default on #${password_hash} ~* &* +@all
EOF
    chown redis:redis /tmp/neurodoc-redis.conf
    exec docker-entrypoint.sh redis-server /tmp/neurodoc-redis.conf
    ;;
  redis-health)
    export REDISCLI_AUTH="$(cat /run/secrets/NEURODOC_REDIS_PASSWORD)"
    exec redis-cli --no-auth-warning ping
    ;;
  *) exit 2 ;;
esac
```

### 24.27 — `ops/local_compose.py`

```python
import yaml
from ops.env import ROOT, read_env
from ops.make_runtime import prepare_runtime


config = read_env(ROOT / '.env.example')
config.update(read_env(ROOT / '.env'))
config.update(DEBUG='True', ALLOWED_HOSTS='localhost,127.0.0.1',
              CSRF_TRUSTED_ORIGINS='http://localhost:8000,http://127.0.0.1:8000,http://localhost:8080,http://127.0.0.1:8080',
              PUBLIC_BASE_URL='http://localhost:8000', EMAIL_ENABLED='False',
              SMS_ENABLED='False', AI_ENABLED='False', NEURODOC_DEMO_ALLOWED='True')
prepare_runtime(config)
stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
stack.pop('version', None)
for key in list(stack):
    if key.startswith('x-'):
        stack.pop(key)
images = {'db': config['POSTGRES_IMAGE'], 'rabbitmq': config['RABBITMQ_IMAGE'],
          'redis': config['REDIS_IMAGE'], 'traefik': config['TRAEFIK_IMAGE']}
for name, service in stack['services'].items():
    service.pop('deploy', None)
    service['restart'] = 'on-failure:10'
    service['image'] = images.get(name, 'neurodoc:dev')
    service['networks'] = ['local']
    if name in ['app', 'celery_worker', 'celery_beat']:
        service['environment'] = {'RELEASE_ID': 'dev', 'ROLLOUT_ID': 'dev'}
    if name == 'app':
        service['build'] = {'context': '.', 'args': {
            'PYTHON_IMAGE': config['PYTHON_IMAGE'], 'RELEASE_ID': 'dev',
        }}
        service['ports'] = ['127.0.0.1:8000:8000']
        service['volumes'] = [item for item in service['volumes'] if isinstance(item, str)]
        service['tmpfs'].append('/run/neurodoc-signing:size=16m,uid=10001,gid=10001,mode=0700')
    if name == 'traefik':
        service['command'] = [
            '--entrypoints.web.address=:80', '--entrypoints.ping.address=:8082',
            '--ping=true', '--ping.entrypoint=ping',
            '--providers.file.filename=/etc/traefik/local.yml',
        ]
        service['environment'] = {}
        service['secrets'] = []
        service['volumes'] = []
        service['configs'] = [{'source': 'traefik_local', 'target': '/etc/traefik/local.yml'}]
        service['ports'] = ['127.0.0.1:8080:80']
        service['healthcheck']['test'] = ['CMD', 'traefik', 'healthcheck', '--ping',
                                         '--entrypoints.ping.address=:8082',
                                         '--ping.entrypoint=ping']
stack['networks'] = {'local': {'driver': 'bridge'}}
stack['volumes'] = {name: {} for name in stack['volumes'] if name != 'letsencrypt'}
stack['configs'] = {
    'postgres_init': {'file': './ops/postgres_init.sh'},
    'infra_entrypoint': {'file': './ops/infra_entrypoint.sh'},
    'traefik_local': {'file': './ops/traefik-local.yml'},
}
stack['secrets'] = {name: {'file': f'./.secrets/{name}'}
                    for name in stack['secrets'] if name != 'CLOUDFLARE_DNS_API_TOKEN'}
(ROOT / 'compose.yml').write_text(yaml.safe_dump(stack, sort_keys=False))
print('compose.yml and development env_files generated; only local HTTP is published.')
```

### 24.28 — `ops/make_runtime.py`

```python
import ipaddress
from pathlib import Path

import yaml

from ops.env import ROOT, write_env


SECRET_MAP = {
    'DJANGO_SECRET_KEY': 'NEURODOC_DJANGO_SECRET_KEY',
    'DB_APP_PASSWORD': 'NEURODOC_DB_APP_PASSWORD',
    'DB_OWNER_PASSWORD': 'NEURODOC_DB_OWNER_PASSWORD',
    'RABBITMQ_PASSWORD': 'NEURODOC_RABBITMQ_PASSWORD',
    'REDIS_PASSWORD': 'NEURODOC_REDIS_PASSWORD',
    'SMTP_PASSWORD': 'NEURODOC_SMTP_PASSWORD',
    'SMSDEV_API_KEY': 'NEURODOC_SMSDEV_API_KEY',
    'OPENROUTER_API_KEY': 'NEURODOC_OPENROUTER_API_KEY',
    'OPENAI_API_KEY': 'NEURODOC_OPENAI_API_KEY',
    'ANTHROPIC_API_KEY': 'NEURODOC_ANTHROPIC_API_KEY',
    'PFX_MASTER_KEY': 'NEURODOC_PFX_MASTER_KEY',
}
COMMON_KEYS = [
    'DEBUG', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'TIME_ZONE',
    'PUBLIC_BASE_URL', 'DEFAULT_FROM_EMAIL', 'AI_ENABLED', 'AI_PROVIDER',
    'AI_MODEL', 'EMAIL_ENABLED', 'EMAIL_HOST', 'EMAIL_PORT',
    'EMAIL_HOST_USER', 'EMAIL_USE_TLS', 'SMS_ENABLED', 'NEURODOC_DEMO_ALLOWED',
    'NEURODOC_DOCS_ENABLED',
    'NEURODOC_RECOVERY_MODE',
]
BASE_SECRETS = ['DJANGO_SECRET_KEY', 'DB_APP_PASSWORD',
                'RABBITMQ_PASSWORD', 'REDIS_PASSWORD']


def prepare_runtime(config):
    runtime = ROOT / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    for role in ['app', 'worker', 'beat']:
        values = {key: config[key] for key in COMMON_KEYS}
        values['SERVICE_ROLE'] = role
        values['RUN_MIGRATIONS'] = 'True' if role == 'app' else 'False'
        names = list(BASE_SECRETS)
        if role == 'app':
            names += ['DB_OWNER_PASSWORD', 'PFX_MASTER_KEY']
        elif role == 'worker':
            names += ['SMTP_PASSWORD', 'SMSDEV_API_KEY',
                      'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY']
        for name in names:
            values[f'{name}_FILE'] = f'/run/secrets/{SECRET_MAP[name]}'
        write_env(runtime / f'{role}.env', values)
    return runtime


def make_traefik(config, cidrs):
    networks = [str(ipaddress.ip_network(line.strip(), strict=True))
                for line in cidrs if line.strip()]
    if len(networks) < 10:
        raise ValueError('Cloudflare trusted IP list is incomplete')
    data = {
        'api': {'dashboard': False},
        'log': {'level': 'WARN'},
        'ping': {'entryPoint': 'ping'},
        'entryPoints': {
            'web': {
                'address': ':80',
                'forwardedHeaders': {'trustedIPs': networks},
                'http': {'redirections': {'entryPoint': {
                    'to': 'websecure', 'scheme': 'https', 'permanent': True,
                }}},
            },
            'websecure': {
                'address': ':443',
                'forwardedHeaders': {'trustedIPs': networks},
                'transport': {'respondingTimeouts': {
                    'readTimeout': '60s', 'writeTimeout': '0s', 'idleTimeout': '180s',
                }},
            },
            'ping': {'address': ':8082'},
        },
        'providers': {'swarm': {
            'endpoint': 'unix:///var/run/docker.sock',
            'exposedByDefault': False,
            'network': 'traefik_public',
            'constraints': 'Label(`com.neurodoc.platform`, `neurodoc_v1`)',
        }},
        'certificatesResolvers': {'cloudflare': {'acme': {
            'email': config['ACME_EMAIL'],
            'caServer': config['ACME_DIRECTORY'],
            'storage': '/letsencrypt/acme-staging.json' if 'staging' in
                       config['ACME_DIRECTORY'] else '/letsencrypt/acme.json',
            'dnsChallenge': {'provider': 'cloudflare',
                             'resolvers': ['1.1.1.1:53', '8.8.8.8:53']},
        }}},
    }
    path = ROOT / '.runtime/traefik.yml'
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path
```

### 24.29 — `ops/neurodoc-backup.service`

```ini
[Unit]
Description=Backup criptografado do NeuroDoc
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
User=neurodocops
Group=neurodocops
WorkingDirectory=/srv/neurodoc
ExecStart=/srv/neurodoc/scripts/backup.sh
UMask=0077
TimeoutStartSec=4h
NoNewPrivileges=true
```

### 24.30 — `ops/neurodoc-backup.timer`

```ini
[Unit]
Description=Backup diario do NeuroDoc

[Timer]
OnCalendar=*-*-* 03:00:00 America/Sao_Paulo
Persistent=true
RandomizedDelaySec=600
Unit=neurodoc-backup.service

[Install]
WantedBy=timers.target
```

### 24.31 — `ops/postgres_init.sh`

```sh
#!/bin/sh
set -eu
export ND_OWNER_PASSWORD="$(cat /run/secrets/NEURODOC_DB_OWNER_PASSWORD)"
export ND_APP_PASSWORD="$(cat /run/secrets/NEURODOC_DB_APP_PASSWORD)"
psql -v ON_ERROR_STOP=1 --username postgres --dbname neurodoc -q <<'SQL'
SET log_min_error_statement = 'panic';
\getenv owner_password ND_OWNER_PASSWORD
\getenv app_password ND_APP_PASSWORD
CREATE ROLE neurodoc_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE neurodoc_app LOGIN PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO neurodoc_owner;
GRANT USAGE ON SCHEMA public TO neurodoc_app;
GRANT CONNECT ON DATABASE neurodoc TO neurodoc_owner, neurodoc_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neurodoc_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO neurodoc_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neurodoc_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO neurodoc_app;
CREATE EXTENSION IF NOT EXISTS btree_gist;
SQL
unset ND_OWNER_PASSWORD ND_APP_PASSWORD
```

### 24.32 — `ops/probe_ready.py`

```python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()
from ops.runtime import app_ready
raise SystemExit(0 if app_ready() else 1)
```

### 24.33 — `ops/queue_probe.py`

```python
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from core.celery import app
from django.conf import settings

queue = 'recovery' if settings.NEURODOC_RECOVERY_MODE else 'maintenance'
result = app.send_task('base.tasks.operational_ping', queue=queue, expires=60)
value = result.get(timeout=30)
if value.get('ok') is not True:
    raise SystemExit(1)
result.forget()
print('Queue and result backend responded to an operational probe.')
```

### 24.34 — `ops/restore.py`

```python
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from ops.deploy import (
    REGISTRY, configuration, create_config, initialize_volumes,
    preflight, resolve_image, run, wait_for_stack,
)
from ops.env import ROOT
from ops.make_runtime import make_traefik, prepare_runtime


def decrypt_to(command, archive, identity, capture=False):
    source = subprocess.Popen(['age', '-d', '-i', identity, str(archive)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        target = subprocess.run(command, stdin=source.stdout,
                                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        source.stdout.close()
        code = source.wait(timeout=3600)
        if code or target.returncode:
            raise RuntimeError('Restore decryption or consumer failed')
        return target.stdout if capture else None
    finally:
        if source.poll() is None:
            source.kill()
            source.wait()


def read_manifest(folder):
    if not (folder / 'COMPLETE').is_file():
        raise RuntimeError('Incomplete backup')
    manifest = json.loads((folder / 'manifest.json').read_text())
    expected = {'database.dump.age', 'media.tar.age', 'signing.tar.age', 'letsencrypt.tar.age'}
    if set(manifest['files']) != expected:
        raise RuntimeError('Unexpected archive list')
    for name, info in manifest['files'].items():
        path = folder / name
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1048576), b''):
                digest.update(chunk)
        if digest.hexdigest() != info['sha256'] or path.stat().st_size != info['bytes']:
            raise RuntimeError(f'Archive integrity mismatch: {name}')
    record = manifest['release']
    if not record['APP_IMAGE'].startswith(REGISTRY + '@sha256:'):
        raise RuntimeError('Unexpected application registry')
    return record


def prepare_data(folder, identity, record):
    if not identity:
        raise RuntimeError('--identity is required for data restoration')
    services = run(['docker', 'service', 'ls', '--format', '{{.Name}}']).splitlines()
    if any(name.startswith('neurodoc_v1_') or name == 'neurodoc_restore_db' for name in services):
        raise RuntimeError('Use a separate empty recovery host')
    volumes = run(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
    if any(name.startswith('neurodoc_v1_') for name in volumes):
        raise RuntimeError('Recovery refuses existing NeuroDoc volumes')
    for key in ['APP_IMAGE', 'POSTGRES_IMAGE']:
        resolve_image(record[key])
    for name in ['postgres', 'media', 'signing', 'letsencrypt']:
        run(['docker', 'volume', 'create', f'neurodoc_v1_{name}'])
    pgconfig = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    command = [
        'docker', 'service', 'create', '--name', 'neurodoc_restore_db',
        '--network', 'neurodoc_v1_internal', '--constraint', 'node.labels.neurodoc_data==true',
        '--mount', 'type=volume,source=neurodoc_v1_postgres,target=/var/lib/postgresql/data',
        '--config', f'source={pgconfig},target=/docker-entrypoint-initdb.d/10-neurodoc.sh,mode=0555',
        '--env', 'POSTGRES_DB=neurodoc', '--env', 'POSTGRES_USER=postgres',
        '--env', 'POSTGRES_PASSWORD_FILE=/run/secrets/NEURODOC_DB_ADMIN_PASSWORD',
        '--env', 'POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=trust',
        '--health-cmd', 'pg_isready -U postgres -d neurodoc', '--health-interval', '5s',
        '--health-retries', '20', '--limit-memory', '2G', '--replicas', '1',
    ]
    for name in ['ADMIN', 'OWNER', 'APP']:
        command += ['--secret', f'NEURODOC_DB_{name}_PASSWORD']
    run(command + [record['POSTGRES_IMAGE']])
    database = None
    for attempt in range(120):
        ids = run(['docker', 'ps', '-q', '--filter',
                   'label=com.docker.swarm.service.name=neurodoc_restore_db']).splitlines()
        if len(ids) == 1:
            state = json.loads(run(['docker', 'inspect', ids[0]]))[0]['State']
            if state.get('Health', {}).get('Status') == 'healthy':
                database = ids[0]
                break
        time.sleep(2)
    if not database:
        raise RuntimeError('Recovery database did not become ready')
    listing = decrypt_to(
        ['docker', 'run', '--rm', '-i', '--network', 'none', '--entrypoint', 'pg_restore',
         record['POSTGRES_IMAGE'], '--list'], folder / 'database.dump.age', identity, True,
    ).decode()
    # The bootstrap already created public and the sole approved extension, btree_gist.
    lines = [line for line in listing.splitlines()
             if not re.search(r'\bEXTENSION\b|\bSCHEMA - public\b', line)]
    runtime = ROOT / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    selection = runtime / 'restore.list'
    selection.write_text('\n'.join(lines) + '\n')
    run(['docker', 'cp', str(selection), f'{database}:/tmp/restore.list'])
    decrypt_to(
        ['docker', 'exec', '-i', database, 'pg_restore', '-U', 'postgres',
         '--role=neurodoc_owner', '--no-owner', '--no-acl', '--no-comments',
         '--exit-on-error', '--use-list=/tmp/restore.list', '-d', 'neurodoc'],
        folder / 'database.dump.age', identity,
    )
    for name in ['media', 'signing', 'letsencrypt']:
        decrypt_to(
            ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0',
             '--entrypoint', 'tar', '--mount',
             f'type=volume,src=neurodoc_v1_{name},dst=/target',
             record['APP_IMAGE'], '-C', '/target', '-xf', '-'],
            folder / f'{name}.tar.age', identity,
        )
    count = run(['docker', 'exec', database, 'psql', '-X', '-qAt', '-U', 'postgres',
                 '-d', 'neurodoc', '-c', 'SELECT count(*) FROM django_migrations;'])
    if not count.isdigit() or int(count) < 1:
        raise RuntimeError('Restored migration history is empty')
    run(['docker', 'service', 'rm', 'neurodoc_restore_db'])
    for attempt in range(60):
        if not run(['docker', 'ps', '-q', '--filter',
                    'label=com.docker.swarm.service.name=neurodoc_restore_db']):
            break
        time.sleep(2)
    else:
        raise RuntimeError('Wait for the recovery database to stop before activation')
    (runtime / 'restore-data.json').write_text(json.dumps(record, indent=2))
    print('Data restored on isolated host; activation and clinical checks remain pending.')


def activate(record):
    config = configuration()
    preflight(config)
    if config['NEURODOC_RECOVERY_MODE'] != 'True':
        raise RuntimeError('Activate recovery mode to hold domain task consumption')
    for key in ['AI_ENABLED', 'EMAIL_ENABLED', 'SMS_ENABLED']:
        if config[key] != 'False':
            raise RuntimeError('Keep all external channels disabled during recovery')
    if run(['git', 'rev-parse', 'HEAD']) != record['RELEASE_ID']:
        raise RuntimeError('Checkout the exact backed-up release before activation')
    marker = json.loads((ROOT / '.runtime/restore-data.json').read_text())
    if marker['RELEASE_ID'] != record['RELEASE_ID']:
        raise RuntimeError('Data restore marker mismatch')
    params = dict(record, ROLLOUT_ID=uuid.uuid4().hex,
                  APP_REPLICAS=config['APP_REPLICAS'])
    for key in ['APP_IMAGE', 'POSTGRES_IMAGE', 'RABBITMQ_IMAGE', 'REDIS_IMAGE', 'TRAEFIK_IMAGE']:
        params[key] = resolve_image(params[key])
    prepare_runtime(config)
    initialize_volumes(params['APP_IMAGE'])
    cidrs = []
    for suffix in ['ips-v4', 'ips-v6']:
        with urllib.request.urlopen(f'https://www.cloudflare.com/{suffix}', timeout=10) as response:
            cidrs.extend(response.read().decode().splitlines())
    params['TRAEFIK_CONFIG'] = create_config(make_traefik(config, cidrs), 'traefik')
    params['POSTGRES_INIT_CONFIG'] = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    params['INFRA_ENTRYPOINT_CONFIG'] = create_config(ROOT / 'ops/infra_entrypoint.sh', 'infra')
    environment = dict(os.environ, **params)
    rendered = run(['docker', 'stack', 'config', '--compose-file', 'docker-stack.yml'], env=environment)
    if '${' in rendered:
        raise RuntimeError('Unresolved recovery configuration')
    run(['docker', 'stack', 'deploy', '--with-registry-auth', '--resolve-image', 'always',
         '--compose-file', 'docker-stack.yml', 'neurodoc_v1'], env=environment)
    wait_for_stack(int(config['DEPLOY_TIMEOUT_SECONDS']))
    (ROOT / '.runtime/last-successful.json').write_text(json.dumps(params, indent=2))
    print('Recovered services healthy; verify origin, records, permissions and files before DNS cutover.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-data', action='store_true')
    group.add_argument('--activate', action='store_true')
    parser.add_argument('--backup-dir', required=True)
    parser.add_argument('--identity')
    args = parser.parse_args()
    folder = Path(args.backup_dir).resolve()
    record = read_manifest(folder)
    if args.prepare_data:
        prepare_data(folder, args.identity, record)
    else:
        activate(record)


if __name__ == '__main__':
    main()
```

### 24.35 — `ops/runtime.py`

```python
import fcntl
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from kombu import Connection
from redis import Redis


MIGRATION_LOCK = 72654001


def wait_until(check, label, seconds=900):
    deadline = time.monotonic() + seconds
    delay = 1
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 10)
    raise RuntimeError(f'Dependency timeout: {label}')


def database_ready():
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT 1')
        return cursor.fetchone()[0] == 1


def schema_ready():
    executor = MigrationExecutor(connections['default'])
    targets = executor.loader.graph.leaf_nodes()
    return not executor.migration_plan(targets)


def broker_ready():
    with Connection(settings.CELERY_BROKER_URL, connect_timeout=5) as broker:
        broker.ensure_connection(max_retries=0)
    return True


def redis_ready():
    client = Redis.from_url(settings.CELERY_RESULT_BACKEND,
                            socket_connect_timeout=5, socket_timeout=5)
    try:
        return client.ping()
    finally:
        client.close()


def wait_dependencies():
    wait_until(database_ready, 'database')
    wait_until(schema_ready, 'schema')
    wait_until(broker_ready, 'broker')
    wait_until(redis_ready, 'redis')


def prepare_release():
    if 'migrations' not in settings.DATABASES:
        raise RuntimeError('Migration credential is unavailable')
    connection = connections['migrations']

    def lock_available():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', [MIGRATION_LOCK])
            return cursor.fetchone()[0]

    wait_until(lock_available, 'migration lock')
    try:
        # call_command uses the same Django connection alias holding the lock.
        call_command('migrate', database='migrations', interactive=False,
                     verbosity=0)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [MIGRATION_LOCK])
        connection.close()
    prepare_staticfiles()


def prepare_staticfiles():
    root = Path('/data/staticfiles')
    root.mkdir(parents=True, exist_ok=True)
    target = Path(settings.STATIC_ROOT)
    if root not in target.parents:
        raise RuntimeError('Invalid static root')
    with (root / '.collectstatic.lock').open('a') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if target.exists():
            marker = target / '.ready'
            if marker.is_file() and marker.read_text() == settings.RELEASE_ID:
                return
            raise RuntimeError('Existing static release is incomplete')
        stage = root / f'.staging-{uuid.uuid4().hex}'
        stage.mkdir(mode=0o750)
        try:
            environment = dict(os.environ, STATIC_PREPARATION_ROOT=str(stage))
            subprocess.run([sys.executable, 'manage.py', 'collectstatic',
                            '--clear', '--noinput', '--verbosity=0'],
                           cwd=settings.BASE_DIR, env=environment, check=True)
            (stage / '.ready').write_text(settings.RELEASE_ID)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def app_ready():
    return (database_ready() and schema_ready()
            and (Path(settings.STATIC_ROOT) / '.ready').is_file())
```

### 24.36 — `ops/scheduler.py`

```python
import time
from pathlib import Path
from celery.beat import PersistentScheduler


class HeartbeatScheduler(PersistentScheduler):
    max_interval = 10

    def tick(self, *args, **kwargs):
        delay = super().tick(*args, **kwargs)
        Path('/tmp/beat-heartbeat').write_text(str(time.time()))
        return min(delay, 10)
```

### 24.37 — `ops/secret_setup.py`

```python
import argparse
import base64
import getpass
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone

import yaml

from ops.env import ROOT, read_env


GENERATED = {
    'NEURODOC_DJANGO_SECRET_KEY', 'NEURODOC_DB_ADMIN_PASSWORD',
    'NEURODOC_DB_OWNER_PASSWORD', 'NEURODOC_DB_APP_PASSWORD',
    'NEURODOC_RABBITMQ_PASSWORD', 'NEURODOC_REDIS_PASSWORD',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--recover')
    parser.add_argument('--identity')
    args = parser.parse_args()
    os.umask(0o077)
    names = list(yaml.safe_load((ROOT / 'docker-stack.yml').read_text())['secrets'])
    existing = []
    if not args.local:
        existing = subprocess.run(['docker', 'secret', 'ls', '--format', '{{.Name}}'],
                                  capture_output=True, text=True, check=True).stdout.splitlines()
        if not args.recover and any(name in existing for name in names):
            raise RuntimeError('Secrets already exist; use the original recovery bundle')
    if args.recover:
        if not args.identity or args.local:
            parser.error('--recover requires --identity and Swarm mode')
        payload = subprocess.run(['age', '-d', '-i', args.identity, args.recover],
                                 capture_output=True, check=True).stdout
        values = json.loads(payload)
        if set(values) != set(names):
            raise RuntimeError('Recovery bundle does not match secret names')
    else:
        values = {}
        for name in names:
            if name in GENERATED:
                values[name] = secrets.token_hex(32)
            elif name == 'NEURODOC_PFX_MASTER_KEY':
                values[name] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            elif name == 'CLOUDFLARE_DNS_API_TOKEN' and not args.local:
                values[name] = getpass.getpass('Cloudflare DNS API token: ')
                if not values[name]:
                    raise RuntimeError('Cloudflare token is required')
            elif not args.local:
                values[name] = getpass.getpass(f'{name} (empty disables channel): ') or 'DISABLED'
            else:
                values[name] = 'DISABLED'
        if not args.local:
            config = read_env(ROOT / '.env')
            recipient = config.get('BACKUP_AGE_RECIPIENT', '')
            if not recipient.startswith('age1'):
                raise RuntimeError('Configure the offline backup public key')
            runtime = ROOT / '.runtime'
            runtime.mkdir(mode=0o700, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            target = runtime / f'bootstrap-secrets-{stamp}.age'
            subprocess.run(['age', '-r', recipient, '-o', str(target)],
                           input=json.dumps(values).encode(), check=True)
            print(f'Encrypted recovery bundle: {target.name}')
    if args.local:
        folder = ROOT / '.secrets'
        folder.mkdir(mode=0o700, exist_ok=True)
        for name, value in values.items():
            target = folder / name
            if not target.exists():
                target.write_text(value)
                target.chmod(0o600)
        print('Development secrets prepared. External channels remain disabled.')
        return
    for name, value in values.items():
        if name not in existing:
            subprocess.run(['docker', 'secret', 'create', name, '-'],
                           input=value.encode(), stdout=subprocess.DEVNULL, check=True)
    print('Swarm secrets prepared. Copy the encrypted recovery bundle off the VPS.')


if __name__ == '__main__':
    main()
```

### 24.38 — `ops/staticfiles.py`

```python
import asyncio
import mimetypes
import re
from pathlib import Path

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.http import FileResponse, HttpResponse, StreamingHttpResponse


async def file_chunks(path):
    source = await asyncio.to_thread(path.open, 'rb')
    try:
        while chunk := await asyncio.to_thread(source.read, 65536):
            yield chunk
    finally:
        await asyncio.to_thread(source.close)


def public_asset(request, asynchronous):
    request.get_host()
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponse(status=405, headers={'Allow': 'GET, HEAD'})
    match = re.fullmatch(r'/static/(dev|[a-f0-9]{40})/(.+)', request.path_info)
    if not match or (match[1] == 'dev' and not settings.DEBUG):
        return HttpResponse(status=404)
    release, relative = match.groups()
    parts = relative.split('/')
    if any(not part or part.startswith('.') or '\\' in part for part in parts):
        return HttpResponse(status=404)
    if parts[-1] == 'staticfiles.json':
        return HttpResponse(status=404)
    root = Path('/data/staticfiles/public/static') / release
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not (root / '.ready').is_file():
        return HttpResponse(status=404)
    if not path.is_file():
        return HttpResponse(status=404)
    content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    headers = {'Cache-Control': 'no-cache' if settings.DEBUG else
               'public, max-age=31536000, immutable',
               'Content-Length': str(path.stat().st_size),
               'X-Content-Type-Options': 'nosniff'}
    if request.method == 'HEAD':
        return HttpResponse(content_type=content_type, headers=headers)
    if asynchronous:
        return StreamingHttpResponse(file_chunks(path), content_type=content_type,
                                     headers=headers)
    return FileResponse(path.open('rb'), content_type=content_type, headers=headers)


class ReleaseStaticMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self.is_async:
            return self.acall(request)
        if request.path_info.startswith('/static/'):
            return public_asset(request, False)
        return self.get_response(request)

    async def acall(self, request):
        if request.path_info.startswith('/static/'):
            return await asyncio.to_thread(public_asset, request, True)
        return await self.get_response(request)
```

### 24.39 — `ops/traefik-local.yml`

```yaml
http:
  routers:
    neurodoc:
      rule: 'Host(`localhost`) || Host(`127.0.0.1`)'
      entryPoints: [web]
      service: neurodoc
  services:
    neurodoc:
      loadBalancer:
        servers:
          - url: http://app:8000
```

### 24.40 — `ops/traefik.example.yml`

```yaml
api:
  dashboard: false
log:
  level: WARN
ping:
  entryPoint: ping
entryPoints:
  web:
    address: :80
    forwardedHeaders:
      trustedIPs: &id001
      - 173.245.48.0/20
      - 103.21.244.0/22
      - 103.22.200.0/22
      - 103.31.4.0/22
      - 141.101.64.0/18
      - 108.162.192.0/18
      - 190.93.240.0/20
      - 188.114.96.0/20
      - 197.234.240.0/22
      - 198.41.128.0/17
      - 162.158.0.0/15
      - 104.16.0.0/13
      - 104.24.0.0/14
      - 172.64.0.0/13
      - 131.0.72.0/22
      - 2400:cb00::/32
      - 2606:4700::/32
      - 2803:f800::/32
      - 2405:b500::/32
      - 2405:8100::/32
      - 2a06:98c0::/29
      - 2c0f:f248::/32
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: :443
    forwardedHeaders:
      trustedIPs: *id001
    transport:
      respondingTimeouts:
        readTimeout: 60s
        writeTimeout: 0s
        idleTimeout: 180s
  ping:
    address: :8082
providers:
  swarm:
    endpoint: unix:///var/run/docker.sock
    exposedByDefault: false
    network: traefik_public
    constraints: Label(`com.neurodoc.platform`, `neurodoc_v1`)
certificatesResolvers:
  cloudflare:
    acme:
      email: CHANGE_ME
      caServer: https://acme-staging-v02.api.letsencrypt.org/directory
      storage: /letsencrypt/acme-staging.json
      dnsChallenge:
        provider: cloudflare
        resolvers:
        - 1.1.1.1:53
        - 8.8.8.8:53
```

### 24.41 — `requirements.in`

```text
Django==6.1.1
langchain==1.4.0
langgraph==1.2.11
celery==5.6.3
dj-celery-panel==0.6.0
dj-control-room
whitenoise==6.12.0
django-environ>=0.12,<1
psycopg[binary]>=3.2,<4
redis>=5.2,<6.2
uvicorn[standard]>=0.35,<1
httpx>=0.28,<1
pydantic>=2.11,<3
langchain-openai>=1,<2
langchain-anthropic>=1,<2
reportlab>=4,<5
pypdf>=6,<8
pyHanko>=0.31,<1
cryptography>=46,<49
django-otp>=1.6,<2
nh3>=0.3,<1
markdown-it-py>=3,<5
Pillow>=12,<14
python-magic>=0.4,<1
defusedxml>=0.7,<1
mkdocs>=1.6,<2
mkdocs-material>=9.6,<10
pymdown-extensions>=10,<11
```

### 24.42 — `scripts/backup.sh`

```sh
#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
exec flock -n .runtime/operation.lock python3 -m ops.backup
```

### 24.43 — `scripts/deploy.sh`

```sh
#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
exec flock -n .runtime/operation.lock python3 -m ops.deploy "$@"
```

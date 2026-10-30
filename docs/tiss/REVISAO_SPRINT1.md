# TISS — revisão da Sprint 1 (antes de qualquer código)

Escrito em 30/10/2026, sobre o commit `22bc32c` (versão 1.29), a partir do
prompt `Prompt_NeuroDoc_TISS_4_Sprints.md`. Este documento é a entrega que o
próprio prompt exige **antes** da implementação (§2, item 5): premissas
conferidas contra o código e contra as fontes oficiais, o desenho proposto,
as decisões que dependem do responsável e o que ainda não foi verificado.

Nenhuma linha de código foi alterada para produzi-lo.

**Classificação usada:** **comprovado** (com arquivo:linha ou página da
fonte), **hipótese** (inferência ainda não exercitada) e **pendência**
(depende de decisão ou de material que não está disponível).

---

## 1. O que foi lido e o que não foi

| Frente | Como | Resultado |
| --- | --- | --- |
| Convênios, financeiro, catálogo TUSS, CNPJ | leitura do código, arquivo a arquivo | §3 e §4 |
| Agenda, permissões, ficha do paciente, eventos, exportação | leitura do código | §3 e §4 |
| Fontes oficiais A1–A9 da ANS | baixadas em 30/10/2026, SHA-256 registrado (§2) | §2 |
| Pacotes XSD 3.04.00 a 4.03.00 | baixados e conferidos `targetNamespace`, `dm_versao`, `maxOccurs` | §2 |
| **Imagens 1–5 e `modelo_guia_tiss.xml` do prompt** | **não recebidos nesta sessão** | **pendência P1** — a validação do anexo (§2 do prompt, item 4) não foi reproduzida |
| Bateria de roteiros (baseline) | última execução completa: **137/137 aprovados** no commit `66ed88d` (1.29); de lá até `22bc32c` só mudou documentação (`git diff --stat`: 4 arquivos em `docs/`) | baseline válido sem nova execução |
| Revisão independente | **não houve.** Esta revisão foi feita por uma única IA, com leitura delegada a subagentes do mesmo contexto. Pelo §2, item 6, do prompt, isso **não** conta como auditoria independente | **pendência P2** |

## 2. Fontes oficiais conferidas (30/10/2026)

| ID | Arquivo | SHA-256 |
| --- | --- | --- |
| A3 | `PadroTISS_ComponenteOrganizacional_202609.pdf` (111 p.) | `fc973a683f772143d3355604e6e0566491756c49c657e1b12b0b33564d63d2d3` |
| A4 | `PadroTISS_ComponentedeContedoeEstrutura_202511.zip` | `6a720ed27da8397fef584e30d794aa56f18906d253ccdf460c30b1019a3a4d3b` |
| A5 | `PadroTISSComunicao_202511.zip` (4.03.00 + 01.06.00) | `db8640e1c3b87085892f54f838bfcea9934439ff365798c8428559f88c13d62d` |
| A7 | `PadroTISSComunicao202301.zip` (4.01.00) | `63f724f73ba66a5040f02c336567665f41ea0f451bda627ad7fb9c02fd2e9862` |
| A8 | `Padrao_TISS_Representacao_de_Conceitos_em_Saude_202609.zip` (408 MB) | `7f3d7a9794a8929fddd6f13af26dd9496087bf8b8670f275bd7ecd9a2f64172d` |
| A9 | `PadroTISS_segurana_202511.zip` | `09af14231ae40b95d055fb3effbadfba1f71bdf676a5a3c69a057bace0d2ff73` |

XSD principal de cada versão (todos com o mesmo namespace,
`http://www.ans.gov.br/padroes/tiss/schemas`):

| Versão | `tissV….xsd` SHA-256 | `dm_versao` aceita |
| --- | --- | --- |
| 3.04.00 | `dc7ba7ba…0d97` (só no endereço antigo de ans.gov.br) | 3.04.00 |
| 3.05.00 | `3c9751d1…2e1d` | 3.05.00 |
| 4.00.00 | `d1446264…e587` | 4.00.00 |
| 4.00.01 | `c56132d3…efe119` | 4.00.00–4.00.01 |
| 4.01.00 | `3293d4a0…58f1` | 4.00.00–4.01.00 |
| 4.02.00 | `193e727c…324b` | 4.00.00–4.02.00 |
| 4.03.00 | `d4c421c7e3cf936551b70d6bd794a419867b6daea554d557b4d928363c54044c` | 4.00.00–4.03.00 |

**Comprovado nas fontes** (conferido também diretamente no XSD 4.03.00):

- **Versão vigente: 04.03.00** — A2; A3 p.7 §7 e p.46 §141. Adoção a partir
  de 01/12/2025, implantação até 30/06/2026 (TUSS Tab 69, termo 027).
- **Qual versão usar:** a vigente **no momento da troca de mensagens**; havendo
  mais de uma, a acordada entre as partes (A3 p.57 §205–206). **Os termos TUSS
  valem pela data do atendimento**, não pela do envio (A3 p.58 §207).
- **Lote:** no máximo **100 guias, todas do mesmo tipo** (A3 p.59 §209;
  `tissGuiasV4_03_00.xsd:518-522`, `maxOccurs="100"` em cada ramo do `choice`).
  Um único prestador de origem e uma única operadora de destino por mensagem
  (estrutura do cabeçalho).
- **CNPJ alfanumérico** em 4.03.00: `st_CNPJ` = `[A-Z0-9]{12}[0-9]{2}`
  (`tissSimpleTypesV4_03_00.xsd:4547-4551`); até 4.02.00 era `[0-9]{14}`.
  Eficácia a partir de 01/07/2026 (A3 p.90 §314).
- **Registro ANS:** `[0-9]{6}`, exatamente seis dígitos — zero à esquerda é
  obrigatório (`:4677-4680`).
- **Carteira:** `st_texto20`, de 1 a 20 caracteres livres.
- **Nome do beneficiário e CNS saíram da mensagem eletrônica na 4.00.00**; o
  modelo **em papel** ainda pede o nome. Mensagem eletrônica e papel são
  documentos diferentes (confirma o aviso do prompt).
- **Hash:** MD5, em hexadecimal, da concatenação literal do **conteúdo** das
  tags, sem os nomes de elementos e atributos, em **ISO-8859-1** (A3 p.48-49).
  O `epilogo/hash` é `string` sem restrição de formato no XSD.
- **Assinatura XML do prestador: recomendada, não obrigatória** (A9 req. 30).
  Se usada: XAdES Enveloped AD-RB, ICP-Brasil (A3 p.47 §143–146). PAdES não
  serve.
- **TUSS com vigência por termo:** toda tabela do pacote A8 traz início de
  vigência, fim de vigência e fim de implantação por código. A Tab 22 tem
  5.969 termos; o XLSX guarda alguns códigos como número e perde zero à
  esquerda — a importação precisa normalizar.

**Contradições e lacunas nas fontes (pendência P3):**

- A3 §205 diz "no máximo duas versões vigentes", mas A6 lista cinco versões
  4.x em vigor na competência set/2026, e o `dm_versao` da 4.03.00 aceita as
  cinco. A ANS **não** publica data de fim de uso por versão.
- O texto do hash **não diz** se o próprio conteúdo de `<hash>`, o
  `ds:Signature` e valores de atributo entram, nem se o hexadecimal é
  minúsculo. Só um validador de operadora real fecha isso.
- 3.04.00 e 3.05.00 **não aparecem** em nenhuma competência desde mai/2023 e
  não são aceitas por nenhum `dm_versao` 4.x.

## 3. Premissa / evidência / risco / correção

| # | Premissa do prompt | Evidência no código | Classificação | Risco | Correção proposta |
| --- | --- | --- | --- | --- | --- |
| 1 | `_price_for` infere convênio pela primeira cobertura vigente | `finance/receivables.py:15-33`: itera `patient.coverages.all()` **sem `order_by`**; ignora `Patient.active_coverage`, `Patient.payment_category`, plano/convênio inativos; não passa `procedure` ao motor de preço; com cobertura e sem regra de convênio **não cai para particular** — não cria cobrança | **comprovado, e pior que o prompt descreve** | paciente com convênio que paga consulta particular é cobrado pela tabela do convênio (ou fica sem cobrança); com duas coberturas vigentes, o resultado depende da ordem física no banco | forma de cobrança **explícita no agendamento** (§4.2); sem escolha registrada, comportamento atual preservado mas determinístico |
| 2 | Recebível criado no check-in, reconciliado na finalização, único por origem e `charge_kind` | `scheduling/services.py:168-173`; `finance/receivables.py:59-227`; constraints parciais `finance_receivable_encounter_uniq` e `finance_receivable_appointment_uniq` (`finance/migrations/0004_cobranca_no_checkin.py:42-56`) + `CheckConstraint finance_receivable_has_origin` | comprovado, com ressalvas | são **duas** unicidades condicionais; check-in pode não criar nada (preço ausente, caso ambíguo); `ChargeKind.PROCEDURE` existe e **nunca é criado** | guia **vincula** recebível existente; procedimento de exame ganha origem própria (§4.4) |
| 3 | `Insurer` já tem registro ANS | `patients/models.py:63`: `ans_registration` CharField(40), opcional, sem validação de formato, sem unicidade | comprovado | registro com 5 dígitos ou com máscara gera XML rejeitado | validar `[0-9]{6}` **só ao configurar TISS** e ao fechar guia, sem tornar obrigatório no cadastro atual |
| 4 | Dois enums de forma de pagamento | `patients.PaymentCategory` = `private`/`plan`; `finance.PaymentCategory` = `private`/`insurance`; nenhum mapeamento entre eles; `reporting/operations.py:80` lê a string literal `'insurance'` | comprovado | renomear qualquer um quebra relatório e snapshots históricos | mapa explícito `plan → insurance` num lugar só; **nenhum enum renomeado** |
| 5 | Limite de 480 min impede PSG | `480` só existe em `AppointmentTypeDuration.minutes` (`scheduling/models.py:68-69`) e `forms.py:58`. **Não há teto no `Appointment`** | **premissa errada do prompt** | — | o obstáculo real é o item 6 |
| 6 | Agenda é por médico | `Appointment.physician_membership` obrigatório; exclusão `scheduling_appointment_no_overlap` por médico; toda a grade (`availability.py`) é por médico e **por dia**; `fits` olha só o dia do início; `week_grid` indexa por `HH:MM`; evento que vira a meia-noite não tem tratamento (só a recusa em `include_extra_hours`) | comprovado | PSG noturna na agenda atual seria recusada pela grade ou desenhada na coluna errada; generalizar `Appointment` toca ~200 pontos em 8 apps e ~50 roteiros | **agenda de recurso aditiva** (§4.5) |
| 7 | Recurso não consome vaga de médico | `tenancy/limits.py:169-175` conta `Membership` com papel `doctor` | comprovado | se o recurso fosse um usuário-médico fictício, consumiria vaga e emprestaria CRM | recurso não é `Membership` |
| 8 | Catálogo TUSS dá vigência histórica | `catalogs/models.py:60-78`: `ProcedureCode` só tem `active`. `integrations/tuss.py:113-123` **lê** `inicio_vigencia`/`fim_vigencia` da ANS e **descarta** | comprovado | impossível validar "código válido na data do serviço" (A3 §207) | gravar as duas datas (§4.6) |
| 9 | Espelho TUSS é confiável | `integrations/tuss.py:309-326`: a versão tem **nome fixo** (`ANS-tuss-22`); toda rodada semanal (domingo 04h) volta a **única** release ativa para rascunho e **apaga os ~5.900 códigos** antes de rebaixá-los. O comentário em `:290-292` promete que "a busca continua respondendo pela release anterior" — **não existe release anterior**. Com honorário ligado a código (`FeeSchedule.procedure`, PROTECT), o `delete()` estoura depois do status já gravado, fora de transação | **comprovado por leitura; não exercitado** | hoje: busca TUSS vazia toda madrugada de domingo enquanto reconstrói; com honorário por procedimento, a tabela deixa de ser atualizada em silêncio. Para o TISS: guia sem código | **defeito preexistente — corrigir antes do TISS** (§4.6) |
| 10 | Secretária não vê prontuário pela ficha | `patients/views.py:251-304`: o contexto da ficha carrega objetos `Encounter` completos para todo papel; o template mostra à secretária só data, tipo, médico e status | comprovado | baixo hoje (o HTML não expõe); mas qualquer template novo que reaproveite esse contexto expõe | a tela TISS **não** reaproveita `_detail_context`; seletor próprio com só os campos de faturamento |
| 11 | Isolamento por FK composta | `base/db.py::composite_tenant_foreign_key` aplicado em `clinical`, `teamchat`, `tenancy/0012` e só `finance_receivable.appointment_id`; **ausente** em `PatientCoverage`, `HealthPlan`, `FeeSchedule`, `Receivable.patient/encounter` | comprovado | — | **toda relação nova do app `tiss` nasce com FK composta**; sem reforma dos apps antigos |
| 12 | Existe mecanismo de liberação gradual | não há feature flag genérica; só `Tenant.settings` JSON e campos ad hoc; o padrão do SNCR é chave no console | comprovado | flag em JSON não tem auditoria nem tela | chave global no console + liberação por clínica (§4.1) |
| 13 | Exportação privada reaproveitável | `reporting/services.py:139-150` grava 0600, mas **expira em 24 h fixo** e `expire_due_exports` apaga o arquivo | comprovado | XML de faturamento apagado em 24 h | armazenamento próprio, sem expiração; reaproveitar só o padrão 0600 + download autorizado |
| 14 | CNPJ do prestador PJ | `base/validators.py:6-41` descarta letras antes de validar | comprovado | CNPJ alfanumérico recusado ou mutilado | validador alfanumérico **novo e só no app `tiss`**; `Tenant.cnpj` intocado |
| 15 | Requisitos de segurança da ANS (A9) são do sistema todo | sessão de 8 h (`core/settings.py:359`, A9 pede encerrar após **10 min** de inatividade, req. 83); senha mínima de 12 caracteres (atende o req. 67 no tamanho); troca a cada 90 dias e histórico de 10 senhas (req. 81–82) **não encontrados**; log de auditoria com **finalidade** (req. 85) — `record_audit_event` aceita `purpose`, mas não é preenchido em todo lugar | comprovado parcialmente | os requisitos são do "sistema que troca informação TISS"; aplicá-los ao NeuroDoc inteiro muda a experiência do prontuário | **pendência P4** — decisão do responsável, fora das quatro sprints |

## 4. Desenho proposto

### 4.1 Liberação: três chaves, conferidas no servidor

1. **Direito comercial:** `tiss_billing` em `tenancy/plans.py`, `False` em
   `free`/`basic`, `True` em `complete`/`custom`; `has_tiss(code)` no mesmo
   padrão de `has_clinical_ai`. Plano desconhecido cai em `free` (já é assim
   em `plan_config`) — nega.
2. **Chave da instalação:** `InstallationSettings.tiss_ativo`, no console
   `/instalacao/operacao/`, no padrão do SNCR: ligar exige digitar e motivo;
   desligar é um clique. É o freio de emergência.
3. **Liberação por clínica:** `Tenant.tiss_liberado` (booleano, padrão
   `False`), ligado pelo superadministrador — a clínica piloto primeiro.

`capabilities_for` ganha `tiss_contracted` (= as três verdadeiras) e veta as
capacidades TISS quando falso, exatamente como `ai_contracted` faz com
`CLINICAL_AI`. Tarefas do worker reconferem as três antes de gravar artefato.

**Rebaixamento:** dados e artefatos ficam; criar, fechar e exportar param;
**ver e baixar o que já foi gerado continua** para quem tinha permissão (o
arquivo é prova de cobrança da clínica).

### 4.2 Forma de cobrança por atendimento

Campos **aditivos e nulos** em `Appointment`: `billing_mode`
(`private`/`insurance`, nulo = "não informado") e `coverage` (FK para
`PatientCoverage`, nula, FK composta). O formulário de marcar sugere a partir
da ficha (`active_coverage`), mas grava a escolha no agendamento.

`_price_for` passa a ler, nesta ordem:

1. escolha explícita do agendamento → usa;
2. sem escolha (todo registro antigo) → **comportamento atual**, só que
   determinístico: `Patient.active_coverage` primeiro, depois a cobertura
   vigente de início mais recente.

Recebíveis já criados **não são recalculados** — o `fee_snapshot` é a
verdade. Atendimento sem agendamento (encaixe direto no prontuário) escolhe a
forma na hora da guia.

### 4.3 Entidades do app `tiss`

Todas `TenantModel`, todas as FKs internas compostas.

| Entidade | Para quê | Cardinalidade |
| --- | --- | --- |
| `Prestador` | o contratado faturador da clínica (PF/PJ, CNPJ/CPF, CNES) | N por clínica |
| `Credenciamento` | prestador × operadora: código do prestador na operadora, versão TISS padrão, ciclo de fechamento, canal (XML no portal / manual), vigência | N por prestador |
| `ProfissionalTiss` | conselho/número/UF/CBO de quem executa ou solicita; liga a `Membership` **ou** é externo (solicitante de fora) | N por clínica |
| `Guia` | tipo (consulta, SP/SADT), paciente, cobertura, credenciamento, autorização, estado, **revisão** (`revisa` → guia anterior), **snapshot** JSON congelado no fechamento | N por paciente |
| `ItemGuia` | data/hora real, tabela, código, descrição e release TUSS usados, quantidade, fator, valor unitário e total (`Decimal`), recebível vinculado | N por guia |
| `Lote` | credenciamento + tipo + versão + número; estado | N por credenciamento |
| `GuiaNoLote` | participação, com `UNIQUE` parcial "uma revisão de guia em no máximo um lote ativo" | — |
| `ArtefatoXml` | bytes finais, SHA-256 interno, hash TISS, tamanho, versão do schema e do gerador; imutável | 1 por geração de lote |
| `Sequencia` | próximo número de guia/lote por credenciamento, reservado com `select_for_update` (nunca `MAX()+1`) | 1 por credenciamento e tipo |

### 4.4 Guia e financeiro

- **Consulta já cobrada:** o item da guia **aponta** para o recebível
  existente (`ItemGuia.recebivel`, FK PROTECT, `UNIQUE` parcial). Não cria
  outro.
- **Procedimento de exame:** o recebível passa a ter uma terceira origem
  possível, a **reserva de recurso** (§4.5). A `CheckConstraint
  finance_receivable_has_origin` é **ampliada** (encounter OU appointment OU
  reserva) e ganha a terceira unicidade parcial `(tenant, reserva,
  charge_kind)`. Nenhuma constraint existente é removida. Origem com vários
  procedimentos = um recebível `procedure` agregado, com os itens na guia.
- **Valor divergente** de recebível já pago: a guia mostra a diferença e exige
  `FinancialAdjustment` com motivo. Nada sobrescreve.
- **Gerar ou baixar XML nunca cria `Payment`.** Protocolo e resultado são
  registrados à mão; pagamento continua pelo caminho de sempre.
- **Ordem de travas:** Encounter → Appointment/Reserva → Receivable → Guia,
  a mesma do check-in e da finalização.

### 4.5 Agendas de exames: recurso aditivo

**Opção escolhida: (a) entidades novas**, com adaptadores. A opção (b),
generalizar `Appointment`, foi recusada pela medida do §3, item 6: ~200
pontos de uso de `physician_membership` em 8 apps, a exclusão por médico, a
grade por dia e ~50 roteiros. Mexer ali para servir a três agendas
arriscaria as agendas que já funcionam.

- `AgendaRecurso` (EEG, ENMG, PSG; duração padrão; capacidade; atravessa a
  meia-noite sim/não) e `ReservaRecurso` (paciente, recurso, início, fim,
  `occupied_range`, estado, executante opcional até faturar).
- Exclusão própria: `ExclusionConstraint` por `(recurso, occupied_range)`.
  Executante reservado entra numa segunda exclusão só quando informado.
- **Sem teto de 480 min e com meia-noite tratada** na grade do recurso, que
  é escrita para isso (a do médico continua igual).
- Lembretes e avisos: os tópicos de `scheduling` ganham equivalentes de
  reserva (`scheduling.reserva_recurso.*`), consumidos pelos mesmos serviços
  de `communications` com o mesmo `um envio por endereço`.

### 4.6 Pré-requisito: corrigir o espelho TUSS

Antes da Sprint 2, dentro da Sprint 1:

1. cada rodada constrói uma release **com nome novo**; a ativa só é trocada
   no fim, numa transação — a busca nunca fica vazia;
2. a release substituída vira `superseded` e **não é apagada** (honorários e
   guias continuam apontando para ela);
3. `ProcedureCode` ganha `inicio_vigencia` e `fim_vigencia` (nulos para o
   histórico), já lidos hoje e descartados;
4. a guia guarda código + descrição + release + datas, e valida **na data do
   serviço**.

### 4.7 XML

- Primeiro adaptador: **4.03.00** (vigente). Validação dos **bytes finais**
  com `lxml` contra o pacote XSD fixado no repositório, com
  `resolve_entities=False`, `no_network=True`, sem DTD.
- 4.00.00 a 4.02.00: adaptadores só se um credenciamento real pedir (P5).
- 3.04.00 e 3.05.00: **sem exportação de produção** — fora de qualquer
  `dm_versao` vigente. Apenas inspeção, se for pedido.
- Hash: implementado segundo A3 p.48-49, com vetores de teste próprios
  (acento, espaço, CR/LF), e conferido contra o validador de uma operadora
  real antes de liberar (P3).

### 4.8 Acesso

| Capacidade nova | Dono | Gestor | Secretária | Médico |
| --- | --- | --- | --- | --- |
| `TISS_VIEW` (fila, guias, artefatos) | sim | sim | sim | sim |
| `TISS_PREPARE` (criar/editar rascunho, itens) | sim | sim | sim | sim |
| `TISS_CLOSE` (validar, fechar, montar lote) | sim | sim | **P6** | sim |
| `TISS_EXPORT` (gerar e baixar XML, registrar protocolo) | sim | sim | sim | **P6** |
| `TISS_CONFIGURE` (prestador, credenciamento, versões) | sim | sim | não | não |

Nenhuma delas implica `READ_CLINICAL`. CID e indicação clínica, quando a guia
pede, vêm de um campo **preenchido pelo médico** (ou do diagnóstico que ele
registrou, copiado com proveniência e revisão dele), nunca de IA nem de
inferência.

## 5. Migrações e reversão

- Todas **aditivas**: tabelas novas, colunas nulas em `Appointment` e
  `ProcedureCode`, booleanos com padrão `False`. Código antigo roda com o
  schema novo (colunas ignoradas).
- A única alteração de constraint existente é ampliar
  `finance_receivable_has_origin` (§4.4). Reversão: só possível se não houver
  recebível com origem em reserva — o `reverse` recusa em vez de apagar.
- Reversão operacional sem deploy: desligar `tiss_ativo` no console.
- Ensaio: banco vazio (instalação nova) **e** cópia restaurada do backup de
  produção em ambiente isolado.

## 6. Pendências que dependem do responsável

| # | Pendência |
| --- | --- |
| P1 | Enviar as imagens 1–5 e o `modelo_guia_tiss.xml` (fora do repositório — têm dado identificável) para reproduzir a validação do anexo |
| P2 | Revisão independente: outra IA ou pessoa, com o roteiro do §7 do prompt |
| P3 | Uma operadora real (validador ou faturista) para conferir o hash e a aceitação do XML antes da produção |
| P4 | Requisitos de segurança do A9 (sessão de 10 min, troca de senha em 90 dias): adotar no NeuroDoc todo, só na área TISS, ou registrar como não atendido |
| P5 | Quais operadoras e versões a clínica do caso principal usa hoje (para saber se só 4.03.00 basta) |
| P6 | Secretária pode **fechar** guia? Médico pode **exportar**? (§4.8) |
| P7 | Aprovar o desenho do §4 — em especial a agenda de recurso aditiva (§4.5) e a terceira origem do recebível (§4.4) |

## 7. Decisões do responsável (30/10/2026)

| # | Decisão |
| --- | --- |
| P1 | Anexos recebidos. As capturas do GuiasTiss têm nomes e carteiras reais: **não entram no repositório** nem viram fixture. O `modelo_guia_tiss.xml` é sintético e vira caso negativo (abaixo) |
| P2 | A revisão independente pedida era esta; dada por feita pelo responsável |
| P4 | Requisitos do A9 **só na área TISS**, que pode ser modular. O resto do NeuroDoc não muda |
| P5 | **Todas as versões**: as operadoras usam versões diferentes (na captura, Unimed Belém em 4.00.00 e Hapvida em 3.04.00). E deve ser possível cadastrar **todas** as operadoras |
| P6, P7 | Seguir a recomendação: agenda de exame separada, terceira origem do recebível, a matriz do §4.8 com a secretária fechando e exportando e o médico exportando |

**Como "todas as versões" fica compatível com o §2:** cada uma das sete
(3.04.00, 3.05.00, 4.00.00, 4.00.01, 4.01.00, 4.02.00, 4.03.00) ganha
adaptador próprio, validado contra **o próprio XSD**. As 4.x saem para
cobrança normalmente. As 3.x não constam de nenhum `dm_versao` vigente; para
elas, o XML de cobrança só sai quando o credenciamento registra que **aquela
operadora aceita a versão** (quem declarou, quando, e o motivo, na trilha).
Sem isso, a geração fica marcada como inspeção. O sistema não afirma uma
aceitação que só a operadora pode dar.

**Diferença de domínio entre versões, medida nos XSDs:** `dm_tipoAtendimento`
tem o código `05` (exame ambulatorial) até a 4.00.01 e não o tem a partir da
4.01.00, que acrescenta o `23`; a 3.x tem vinte códigos. É por diferenças
assim que trocar só a string da versão não é suporte multiversão.

**Validação do anexo, reproduzida** (`lxml` contra `tissV4_01_00.xsd`, sem
rede e sem DTD):

- como veio: reprovado — namespace `padraotiss` em vez de `padroes/tiss`;
- com o namespace corrigido só em memória: reprovado em `versaoPadrao`
  (é `Padrao`), `nomeBeneficiario` (saiu na 4.00.00), `nomeContratado` e
  `profissionalSolicitante` fora de ordem, `codigoprestadorNaOperadora`
  (executante sem `contratadoExecutante`), `tipoAtendimento` `05` (fora do
  domínio da 4.01.00), `dadosAtendimento` incompleto, `sequencialProcedimento`
  (é `sequencialItem`) e `valorTotalGuia` (é `valorTotal`);
- o hash `d41d8cd98f00b204e9800998ecf8427e` é o MD5 da cadeia vazia.

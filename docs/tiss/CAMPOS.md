# TISS — matriz de campos da guia

Fonte da estrutura: os XSDs oficiais de cada versão em `tiss/xsd/`
(`ctm_consultaGuia` e `ctm_sp-sadtGuia`, árvores extraídas em 30/10/2026),
os modelos em papel do Componente de Conteúdo e Estrutura 202511 (Consulta
p.469, SP/SADT p.520) e as terminologias TUSS 202609 (`tiss/terminologia.py`,
gerado da planilha oficial).

**Leitura:** "Origem" é de onde o NeuroDoc tira o valor ao criar a guia;
"Quem" é quem pode alterá-lo; "Obrig." é o que **impede fechar**
(`tiss/guias.py::pendencias`) — "aviso" aparece e não impede. O XSD
continua sendo a régua final, na geração do XML (Sprint 3).

## Cabeçalho, autorização e beneficiário

| Campo (NeuroDoc) | Papel C / S | XML (4.03.00) | Origem | Quem | Obrig. | Versões |
| --- | --- | --- | --- | --- | --- | --- |
| registro ANS | 1 / 1 | `cabecalho*/registroANS` (`[0-9]{6}`) | operadora do credenciamento | gestor (convênios) | sim | todas |
| `numero_prestador` | 2 / 2 | `numeroGuiaPrestador` (texto20) | `Sequencia` da clínica, sob trava | ninguém | — | todas |
| `numero_operadora` | 3 / 7 | `numeroGuiaOperadora` | — | recepção | não | todas |
| `guia_principal` | — / 3 | `guiaPrincipal` | — | recepção | não | todas |
| `data_autorizacao` | — / 4 | `dadosAutorizacao/dataAutorizacao` | — | recepção | se houver senha ou nº da operadora | todas |
| `senha` | — / 5 | `dadosAutorizacao/senha` | — | recepção | não | todas |
| `validade_senha` | — / 6 | `dadosAutorizacao/dataValidadeSenha` | — | recepção | não | todas |
| `cod_validacao` | — | `codValidacao` (texto10) | — | recepção | não | todas |
| `ausencia_cod_validacao` | — | `ausenciaCodValidacao` (Tab 74) | — | recepção | domínio | todas |
| `carteira` | 4 / 8 | `dadosBeneficiario/numeroCarteira` (texto20) | cobertura do paciente | recepção | sim | todas |
| `validade_carteira` | 5 / 9 | — (só papel) | `PatientCoverage.ends_on` | recepção | aviso se vencida | — |
| `atendimento_rn` | 6 / 12 | `atendimentoRN` (S/N) | — | recepção | — | todas |
| nome do beneficiário | 7 / 10 | `nomeBeneficiario` **só 3.x** | `Patient.full_name` (forma canônica) | — | — | papel; XML 3.x |

## Contratado, solicitante e solicitação (SP/SADT)

| Campo | Papel C / S | XML | Origem | Quem | Obrig. |
| --- | --- | --- | --- | --- | --- |
| código do prestador | 9 / 13, 29 | `codigoPrestadorNaOperadora` \| `cpfContratado` \| `cnpjContratado` | credenciamento (`identificacao`) | gestor | sim |
| nome do contratado | 10 / 14, 30 | `nomeContratadoSolicitante` (4.x); `nomeContratado` (3.x) | prestador | gestor | — |
| CNES | 11 / 31 | `CNES` (texto7) | prestador; 9999999 sem CNES | gestor | — |
| `contratado_solicitante_*` | — / 13–14 | `dadosSolicitante/contratadoSolicitante` | o próprio prestador, ou outro | recepção | se "outro" |
| `solicitante` | — / 15–19 | `profissionalSolicitante` (conselho Tab 26, UF IBGE, CBO do XSD) | médico do horário | recepção | sim |
| `data_solicitacao` | — / 22 | `dadosSolicitacao/dataSolicitacao` | data do horário | recepção | não |
| `carater_atendimento` | — / 21 | `caraterAtendimento` (Tab 23) | 1 — eletivo | recepção | domínio |
| `indicacao_clinica` | — / 23 | `indicacaoClinica` (texto500) | — | **só médico** (`READ_CLINICAL`), com autoria | aviso |
| `cobertura_especial` | 27 / 90 | `coberturaEspecial` / `indCobEspecial` (Tab 75) **só 4.x** | — | recepção | domínio |

**Não existe campo de CID**: nenhuma versão das duas guias o tem. O
campo de CID de outros sistemas não vai no XML, e não entra aqui.

## Executante e atendimento

| Campo | Papel C / S | XML | Origem | Quem | Obrig. |
| --- | --- | --- | --- | --- | --- |
| `executante` | 12–16 / 51–55 | `profissionalExecutante` (Consulta); `equipeSadt` (SP/SADT, Sprint 3) | médico do horário | recepção | sim |
| `tipo_atendimento` | — / 32 | `tipoAtendimento` (Tab 50; **05 até 4.00.01, 23 depois**) | — | recepção | sim (SP/SADT) |
| `indicacao_acidente` | 17 / 33 | `indicacaoAcidente` (Tab 36) | 9 — não acidente | recepção | domínio |
| `tipo_consulta` | 19 / 34 | `tipoConsulta` (Tab 52) | tipo do horário: primeira → 1, retorno → 2 | recepção | sim (Consulta) |
| `motivo_encerramento` | — / 35 | `motivoEncerramento` (só 41–43) | — | recepção | domínio |
| `regime_atendimento` | 28 / 91 | `regimeAtendimento` (Tab 76) **só 4.x** | 01 — ambulatorial | recepção | domínio |
| `saude_ocupacional` | 29 / 92 | `saudeOcupacional` (Tab 77) **só 4.x** | — | recepção | domínio |
| `observacao` | 23 / 58 | `observacao` (texto500) | — | recepção | não |

## Procedimentos (`ItemGuia`)

| Campo | Papel C / S | XML | Origem | Obrig. |
| --- | --- | --- | --- | --- |
| `data_execucao` | 18 / 36 | `dataAtendimento` / `dataExecucao` | data do horário | sim |
| `hora_inicial`, `hora_final` | — / 37–38 | `horaInicial`, `horaFinal` | — | não |
| `tabela` | 20 / 39 | `codigoTabela` (Tab 87, domínio da versão) | 22 | sim |
| `codigo` | 21 / 40 | `codigoProcedimento` (texto10) | regra de honorário da consulta cobrada, ou busca TUSS | sim; **vigente na data do serviço** |
| `descricao` | — / 41 | `descricaoProcedimento` (texto150) | termo TUSS da release | sim |
| `quantidade` | — / 42 | `quantidadeExecutada` (numérico3) | 1 | 1 a 999 |
| `via_acesso`, `tecnica` | — / 43–44 | `viaAcesso` (Tab 61), `tecnicaUtilizada` (Tab 48) | — | domínio |
| `fator` | — / 45 | `reducaoAcrescimo` (decimal3-2) | 1,00 | > 0 |
| `valor_unitario` | 22 / 46 | `valorProcedimento` / `valorUnitario` (decimal 8,2 até a 4.01.00; 10,2 a partir da 4.02.00) | honorário do contrato (código + plano + data), ou informado **com motivo** | > 0 |
| `valor_total` | 22 / 47 | `valorTotal` | quantidade × unitário × fator, arredondado uma vez | — |
| `recebivel` | — | — | a cobrança do check-in, quando existe | um recebível, no máximo um item |

Totais (SP/SADT 59–65): procedimentos = soma dos itens; taxas, materiais,
OPME, medicamentos e gases ficam zerados — **outras despesas não são
suportadas** nesta versão, e por isso não se escreve valor nelas.

## O que muda entre as versões (medido nos XSDs)

| Diferença | 3.04.00 / 3.05.00 | 4.00.00 / 4.00.01 | 4.01.00 a 4.03.00 |
| --- | --- | --- | --- |
| nome do beneficiário e CNS na mensagem | sim | não | não |
| regime de atendimento, saúde ocupacional, cobertura especial | não | sim | sim |
| tipo de atendimento "exame" | 05 | 05 | **23** |
| valores | decimal 8,2 | decimal 8,2 | decimal 8,2 na 4.01.00; **10,2 a partir da 4.02.00** |
| CNPJ | numérico | numérico | numérico; **alfanumérico na 4.03.00** |
| CBOs aceitos | 147 | 156 | até 172 |

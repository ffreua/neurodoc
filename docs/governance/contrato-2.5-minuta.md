# Contrato 2.5 — minuta do que muda (para a Dra. Karina conferir)

> **Situação:** minuta redigida em 2026-11-27 a pedido do Dr. Fernando, para
> a aprovação da Dra. Karina Albuquerque Freua (OAB/SP 450.476). **Não
> publicada.** O texto integral, já com as trocas, está em
> `docs/governance/contrato-2.5-proposta.md` (é o 2.4 vigente com
> exatamente as trocas da tabela abaixo, aplicadas por script que confere cada
> trecho). Aprovada, publicar é copiar esse arquivo para
> `tenancy/contrato/contrato-2.5.md` e subir `tenancy/contract.py::VERSAO`
> para `'2.5'`.

## Motivo

1. **Comunicados do console** (NeuroDoc 1.64, 2026-11-27): avisos do sistema e
   **comunicações comerciais** da PRONTDOC aos usuários, no centro de
   notificações e, se o usuário ativou, no aparelho. A Dra. Karina aprovou em
   2026-11-27, **sem opção de recusa**, por integrar a contratação. O
   Aviso de Privacidade 2.4 pede que uso para publicidade seja "informado em
   versão complementar antes de sua ativação": esta é a versão. Detalhe em
   `docs/governance/comunicados-minuta.md`.
2. **Notificações no aparelho** (mesma data): passam pelo serviço de
   notificação do navegador (Google, Apple, Mozilla, Microsoft), cifradas e
   sem dado de paciente — fornecedor novo no Anexo II.
3. **IA, correção de fato:** desde 2026-11-26 a IA padrão usa só a
   OpenRouter (principal DeepSeek, contingência GLM da Z.ai); a 2.4 ainda
   descreve a NVIDIA como principal. Com a troca da contingência para o GLM,
   o sistema passou a excluir também a própria Z.ai como executora (é
   empresa chinesa e servia o modelo), para continuar valendo o "não sediado
   na China" que o contrato promete.

**Efeito no sistema:** a propaganda dos comunicados fica travada até esta
versão ser publicada e, depois, vai só à clínica que aceitar a 2.5 (o
contrato aceito em versão anterior continua regendo quem não aceitou a nova,
cláusula 2.4). O aviso do sistema já vale pela cláusula 18.1.

**Para a senhora decidir na redação:** a base legal no §4 do Aviso
(proposta: execução do contrato e legítimo interesse, art. 7º, V e IX); se
convém um limite de frequência mais objetivo que "não abusiva" na 18.3; e se a
linha COMUNICADOS no quadro-resumo basta como destaque.

## O que muda no texto

| Onde | 2.4 (vigente) | 2.5 (proposta) |
| --- | --- | --- |
| Cabeçalho do contrato | **Versão 2.4 — 18 de novembro de 2026** | **Versão 2.5 — 27 de novembro de 2026** |
| Cabeçalho do Aviso de Privacidade | **Versão 2.4 — data: 18/11/2026. | **Versão 2.5 — data: 27/11/2026. |
| Quadro-resumo: linha nova COMUNICADOS | **PRIVACIDADE:** | **COMUNICADOS:** avisos sobre o funcionamento da plataforma e comunicações comerciais da PRONTDOC, enviados aos usuários no centro de notificações do aplicativo e, quando o usuário os ativar, no aparelho; integram a contratação do serviço (Cláusula 18.3).<br><br>**PRIVACIDADE:** |
| Cláusula 18.3 (nova) | 18.2. O CONTRATANTE manterá e-mail atualizado e monitorará notificações. A PRONTDOC preservará prova de envio, conteúdo e canal para notificações relevantes; simples remessa não prova ciência quando a lei exigir comprovação mais robusta. | 18.2. O CONTRATANTE manterá e-mail atualizado e monitorará notificações. A PRONTDOC preservará prova de envio, conteúdo e canal para notificações relevantes; simples remessa não prova ciência quando a lei exigir comprovação mais robusta.<br><br>18.3. A PRONTDOC poderá enviar aos usuários vinculados à conta do CONTRATANTE, pelo centro de notificações do aplicativo e, quando o usuário ativar os avisos em seu aparelho, por notificação no aparelho: (i) comunicados sobre o funcionamento da plataforma, como manutenções, atualizações e mudanças de funcionalidade; e (ii) comunicações comerciais sobre produtos, planos, recursos e condições da própria PRONTDOC. O recebimento desses comunicados integra a contratação do serviço. As comunicações comerciais serão identificadas como tais, não conterão dados de pacientes, não serão elaboradas a partir de dados clínicos e não serão enviadas com frequência abusiva. |
| Cláusula 9.2 (IA: a rota em uso desde 26/11/2026) | 9.2. Para a configuração padrão informada em 10/11/2026, a plataforma utiliza a API de IA da NVIDIA como provedor principal e OpenRouter, com modelo DeepSeek, como rota de contingência (fallback), acionada somente quando a chamada ao provedor principal falha. Na contingência, a OpenRouter encaminha a requisição a provedor de infraestrutura que executa o modelo, escolhido a cada pedido; | 9.2. Para a configuração padrão informada em 27/11/2026, a plataforma utiliza a OpenRouter como provedor de IA, com o modelo DeepSeek como principal e o modelo GLM, da Z.ai, como rota de contingência (fallback), acionada somente quando a chamada ao modelo principal falha. A OpenRouter encaminha cada requisição a provedor de infraestrutura que executa o modelo, escolhido a cada pedido; |
| Anexo II, data do inventário | **Inventário atualizado em 18/11/2026.** | **Inventário atualizado em 27/11/2026.** |
| Anexo II: IA atualizada e serviços de notificação | \| NVIDIA — API de IA (padrão) \| Inferência de IA via API \| Conteúdo de prompts após desidentificação, metadados técnicos e eventuais dados pessoais residuais \| Rota padrão informada; sujeito aos endpoints, locais de processamento e políticas do fornecedor \|<br>\| OpenRouter — fallback \| Roteamento de requisições para modelo alternativo, somente quando a chamada à NVIDIA falha \| Prompts desidentificados, metadados, potenciais dados pessoais residuais \| Sediada nos EUA; em cada pedido, a PRONTDOC exige provedor de infraestrutura com retenção zero, sem uso para treinamento e não sediado na China \|<br>\| Modelo DeepSeek via OpenRouter \| Execução do modelo de contingência por provedor de infraestrutura escolhido pela OpenRouter a cada pedido \| Conteúdo transmitido ao modelo, conforme cadeia de processamento \| A empresa DeepSeek não recebe a requisição; o modelo é executado por provedor que atenda às exigências de retenção zero, ausência de treinamento e localização fora da China \| | \| OpenRouter — API de IA (padrão) \| Roteamento de cada requisição de IA ao provedor de infraestrutura que executa o modelo, no principal e na contingência \| Prompts desidentificados, metadados, potenciais dados pessoais residuais \| Sediada nos EUA; em cada pedido, a PRONTDOC exige provedor de infraestrutura com retenção zero, sem uso para treinamento e não sediado na China \|<br>\| Modelos DeepSeek (principal) e GLM, da Z.ai (contingência), via OpenRouter \| Execução do modelo por provedor de infraestrutura escolhido pela OpenRouter a cada pedido \| Conteúdo transmitido ao modelo, conforme cadeia de processamento \| As empresas DeepSeek e Z.ai não recebem a requisição; o modelo é executado por provedor que atenda às exigências de retenção zero, ausência de treinamento e localização fora da China \|<br>\| Serviços de notificação dos navegadores (Google Firebase Cloud Messaging, Apple Push Notification service, Mozilla Push Service e Microsoft Windows Push Notification Services) \| Entrega das notificações no aparelho do usuário que ativou os avisos \| Endereço de entrega do aparelho e o aviso, cifrado de ponta a ponta, sem que o serviço leia o conteúdo; o aviso nunca contém dado de paciente \| Escolhido pelo navegador do usuário, e não pela PRONTDOC; processamento nos EUA e em outros países \| |
| Anexo III, item 1.1 | Os fluxos principais de IA utilizam NVIDIA API, com contingência por OpenRouter e modelo DeepSeek; tais rotas envolvem processamento fora do Brasil, e na contingência a PRONTDOC exige provedor com retenção zero, sem treinamento e não sediado na China. | Os fluxos de IA utilizam a OpenRouter, com o modelo DeepSeek como principal e o modelo GLM, da Z.ai, como contingência; tais rotas envolvem processamento fora do Brasil, e a PRONTDOC exige, em cada pedido, provedor com retenção zero, sem treinamento e não sediado na China. As notificações no aparelho passam pelo serviço de notificação do navegador do usuário, cifradas e sem dado de paciente. |
| Aviso de Privacidade, §2 | Dados de cadastro de organizações e usuários, identificadores profissionais, contatos, credenciais protegidas, logs de atividade, metadados de acesso, faturamento e solicitações de suporte. | Dados de cadastro de organizações e usuários, identificadores profissionais, contatos, credenciais protegidas, logs de atividade, metadados de acesso, faturamento, solicitações de suporte e, quando o usuário ativar os avisos no aparelho, o endereço técnico de entrega das notificações. |
| Aviso de Privacidade, §3 (finalidades) | defesa de direitos; e recursos de IA nos planos elegíveis, com desidentificação local e revisão do médico. | defesa de direitos; recursos de IA nos planos elegíveis, com desidentificação local e revisão do médico; e o envio, aos usuários das organizações contratantes, de comunicados sobre o serviço e de comunicações comerciais da própria PRONTDOC (Cláusula 18.3 do contrato), sem uso de dados de pacientes. |
| Aviso de Privacidade, §4 (bases legais) | Para dados administrativos, podem incidir execução de contrato, cumprimento legal, exercício de direitos e outras hipóteses legítimas cabíveis. | Para dados administrativos, podem incidir execução de contrato, cumprimento legal, exercício de direitos e outras hipóteses legítimas cabíveis. Os comunicados aos usuários, inclusive os comerciais, integram a contratação e se fundam na execução do contrato e no legítimo interesse da PRONTDOC (art. 7º, V e IX, da LGPD). |
| Aviso de Privacidade, §5 (compartilhamento) | A rota padrão informada de IA é NVIDIA via API, com fallback OpenRouter/DeepSeek; na contingência, a OpenRouter só encaminha o pedido a provedor com retenção zero, sem treinamento e não sediado na China. | A rota padrão informada de IA é a OpenRouter, com o modelo DeepSeek como principal e o modelo GLM, da Z.ai, como contingência; em cada pedido, a OpenRouter só encaminha a provedor com retenção zero, sem treinamento e não sediado na China. As notificações no aparelho, quando o usuário as ativa, são entregues pelo serviço de notificação do navegador dele (Google, Apple, Mozilla ou Microsoft), cifradas e sem dado de paciente. |
| Aviso de Privacidade, §6 (IA) | A rota principal NVIDIA e o fallback OpenRouter/DeepSeek podem envolver fornecedores, países e políticas diferentes; | Os modelos principal (DeepSeek) e de contingência (GLM, da Z.ai), via OpenRouter, podem envolver fornecedores, países e políticas diferentes; |
| Aviso de Privacidade, §10 (identificadores) | Podem ser utilizados cookies e identificadores estritamente necessários à autenticação, segurança e funcionamento. **Qualquer uso de analytics, publicidade, rastreamento não essencial ou cookies de terceiros deverá ser inventariado e informado em versão complementar antes de sua ativação.** | Podem ser utilizados cookies e identificadores estritamente necessários à autenticação, segurança e funcionamento. Quando o usuário ativa os avisos no aparelho, o endereço técnico de entrega das notificações é usado para levar a ele os avisos do sistema e os comunicados da Cláusula 18.3 do contrato, inclusive os comerciais; ele não é usado para rastreamento nem compartilhado com terceiros para publicidade, e deixa de valer quando o usuário sai do sistema no aparelho ou desativa os avisos. **Qualquer outro uso de analytics, publicidade, rastreamento não essencial ou cookies de terceiros deverá ser inventariado e informado em versão complementar antes de sua ativação.** |

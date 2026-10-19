# LGPD: o que o sistema faz, e onde cada exigência está tratada

Este documento separa duas coisas que costumam ser tratadas como uma só:
**as medidas técnicas**, que estão no código e podem ser verificadas, e
**as decisões do controlador**, que são jurídicas e não se resolvem
escrevendo software.

As duas estão resolvidas para o início da operação: as medidas técnicas
no §5, cada uma com o roteiro que a verifica, e as decisões jurídicas no
contrato de adesão do §9, redigido por advogada. O §6 diz onde cada
exigência foi tratada. **Não há pendência de LGPD bloqueando o deploy.**

Ele continua servindo de insumo para a assessoria: a matriz do §2 traz o
tratamento mapeado, a base legal e a medida técnica correspondente — é
por onde se começa quando uma finalidade nova aparecer.

> **O que aqui é jurídico veio de advogada.** O contrato de adesão (§9)
> foi redigido pela Dra. Karina Albuquerque Freua, OAB/SP nº 450.476, e é
> ele que fixa os papéis, as instruções e as obrigações de cada parte. As
> leituras técnicas deste documento — a matriz do §2, os prazos do §3 —
> são de quem implementou o sistema e se apoiam naquele contrato.

---

## 1. Quem é o quê

A distinção mais importante, e a que muda todas as respostas seguintes:

| Papel | Quem | Por quê |
| --- | --- | --- |
| **Controlador** | Cada clínica | É ela que decide atender o paciente, o que registrar e por quanto tempo. O prontuário é dela, e é o CRM do médico que responde por ele. |
| **Operador** | O NeuroDoc (quem mantém a instalação) | Trata os dados **em nome** da clínica, conforme o que o sistema faz, sem decidir finalidade. |
| **Controlador independente** | O NeuroDoc, mas só nos dados da relação comercial | Cadastro contratual, faturamento, autenticação, segurança da plataforma, registro de aceite, defesa de direitos. Aqui quem decide a finalidade é ele, e a responsabilidade é dele. Distinção que veio do contrato (cláusula 5.3) — ver §9. |
| **Suboperadores** | VPS, SMTP, SMS, IA (quando ligada), Cloudflare | Cada um recebe uma fatia, e cada um exige previsão contratual. Ver §4. |

Consequências práticas que decorrem disso:

- **O titular pede à clínica, não a nós.** Um pedido de acesso, correção
  ou portabilidade é respondido pelo controlador; o operador fornece os
  meios. É por isso que o sistema dá à clínica exportação e relatório de
  retenção, e não abre um canal direto do paciente ao mantenedor.
- **Cada clínica precisa do seu encarregado.** A instalação também precisa
  do dela, como operadora.
- **O contrato entre clínica e NeuroDoc é o instrumento central** (art.
  39): é ele que autoriza o tratamento e fixa as instruções. Ele existe,
  é aceito na adesão e está descrito no §9.

---

## 2. Matriz de tratamento

Cada linha: o que é tratado, para quê, a base legal candidata e onde a
medida técnica está no código.

| Dado | Finalidade | Base legal candidata | Medida técnica implementada |
| --- | --- | --- | --- |
| Identificação do paciente (nome, CPF, nascimento, endereço) | Identificar quem é atendido e emitir documento médico válido | Art. 7º, II e 11, II, "a" — cumprimento de obrigação legal (CFM 1.821/2007, Lei 13.787/2018) | Isolamento por inquilino em toda consulta (`scope_to_tenant`) e chave estrangeira composta no banco nos apps clínicos |
| Registro clínico (queixa, história, exame, diagnóstico) | Assistência à saúde | Art. 11, II, "f" — tutela da saúde, por profissional de saúde | Prontuário imutável após finalização; correção por adendo com autor e data; trilha de acesso |
| Contato do paciente e de terceiro autorizado | Entregar documento e confirmar consulta | Art. 7º, V — execução de contrato; art. 11, II, "f" para o que revele saúde | Autorização por contato (`authorized_for_documents`), link opaco com prazo e verificação |
| Contato para comunicação em massa | Aviso e campanha da clínica | Art. 7º, I e art. 8º, §5º — consentimento, revogável | Consentimento registrado por canal, com descadastro em um clique (`/descadastrar/`) |
| Dado financeiro | Cobrança e repasse | Art. 7º, V — execução de contrato | Separado do prontuário; papel financeiro não lê nota clínica |
| Trilha de auditoria (quem fez o quê) | Segurança e prestação de contas | Art. 7º, II e art. 46 — obrigação legal e medida de segurança | `INSERT`-only no banco (trigger + `REVOKE`); nunca guarda texto clínico |
| Texto enviado a provedor de IA | Apoio à redação e ao resumo, com revisão médica | Depende de §5 — **pendente** | Desidentificação local antes de sair; política que bloqueia envio (fail-closed); provedor e chave da própria clínica |
| Laudo de exame enviado pelo paciente no portal (1.16) | Compor o prontuário com o resultado que o paciente já tem | Art. 11, II, "f" — tutela da saúde; ciência registrada no aviso de privacidade `2026-10-v2` | Só PDF de até 3 MB; quarentena e antivírus antes de liberar; anexo **clínico** (quem não lê prontuário vê a linha, não o exame); guarda de 20 anos como o resto do prontuário; o portal não devolve ao paciente o que ele enviou |
| IP de quem acessa portal público | Conter abuso (força bruta, raspagem) | Art. 7º, IX — legítimo interesse | Guardado como hash (`origin_ip_protected`); limite por IP resolvido por proxy confiável |

---

## 3. Retenção e eliminação

| Dado | Prazo implementado | Origem do prazo |
| --- | --- | --- |
| Prontuário (atendimento, documento, anexo clínico, medição) | **20 anos do último registro**, contados em calendário | Lei 13.787/2018, art. 6º; CFM 1.821/2007 |
| Anexo administrativo | 30 dias após remoção lógica | Decisão de produto |
| Token de acesso a documento | 30 dias | DEC-21 |
| Exportação de relatório | 24 horas | Decisão de produto |
| Trilha de auditoria | Sem expurgo | Prestação de contas (art. 37) |

**A LGPD não encurta a guarda do prontuário.** O art. 16, I abre exceção
expressa para cumprimento de obrigação legal, que é o caso: um pedido de
eliminação de prontuário dentro dos 20 anos é recusado, e o sistema
recusa — `documents.retention.eliminacao_permitida` distingue anexo
clínico de administrativo e consulta o prazo antes de qualquer remoção
física.

**Não há anonimização definitiva implementada.** A desidentificação que
existe (`ai/deidentification.py`) é para envio à IA e é **pseudonimização**
— reversível por quem tem o prontuário, e portanto ainda dado pessoal
(art. 12). Tratá-la como anonimização seria o erro mais caro deste
documento.

---

## 4. Operadores e transferência internacional

| Serviço | O que recebe | Fica onde | O que falta |
| --- | --- | --- | --- |
| VPS (hospedagem) | Tudo: banco, anexos, backup local | A definir na contratação | Contrato com cláusulas do art. 39; confirmar região |
| SMTP (e-mail) | Nome do paciente, assunto neutro, link opaco — **nunca diagnóstico** | Provedor do contrato | Contrato; confirmar região |
| SMS | Telefone e mensagem neutra | SMSDEV (Brasil) | Contrato |
| Provedor de IA | Texto clínico **desidentificado** | Fora do Brasil, na maioria dos provedores | **Transferência internacional**: exige base do art. 33. Desligado até resolver |
| Cloudflare (se usada) | Metadado de conexão e IP | Fora do Brasil | Avaliar como transferência |
| Destino externo do backup | Backup cifrado (`age`) | A definir | O destino não lê o conteúdo — a chave privada não sai da custódia do controlador |

**Retirar o nome não dispensa a obrigação.** Dado pseudonimizado que pode
ser reassociado continua sendo dado pessoal, e a transferência
internacional dele continua exigindo base legal. É o ponto em que uma
leitura apressada custa caro.

---

## 5. Medidas técnicas adotadas

Serve de anexo ao RIPD. Tudo abaixo está implementado e é verificado por
roteiro em `checks/` — a coluna indica onde.

| Medida | Onde | Verificado por |
| --- | --- | --- |
| Isolamento entre clínicas em toda consulta | `tenancy/selectors.py::scope_to_tenant` | `check_isolation`, `check_tenantb` |
| Isolamento reforçado no banco (chave composta) | `clinical/migrations/0009`, `teamchat/migrations/0001` | `check_isolation` |
| Autorização por capacidade, nunca por papel solto | `tenancy/permissions.py` | `check_matrix`, `check_roles` |
| MFA obrigatória no console da instalação | `ops/superadmin.py` | `check_super`, `check_landing` |
| Prontuário imutável após finalização | `clinical/` | `check_imutabilidade` |
| Trilha de auditoria `INSERT`-only no banco | `audit/migrations/0003` | `check_imutabilidade`, `check_backup` |
| Guarda de 20 anos aplicada antes de eliminar | `documents/retention.py` | `check_imutabilidade`, `check_g8` |
| Credenciais cifradas por envelope | `base/` (cripto), `documents.SigningCredential` | `check_chave` |
| Backup cifrado com chave fora do servidor | `ops/backup.py` | `check_backup` |
| Restauração provada (ciclo completo) | `ops/restore.py` | `check_backup` + exercício real em 20/09/2026 |
| Texto clínico nunca em log, alerta ou trilha | `base/logging.py`, `audit/services.py` | `check_mensagem_clinica`, `check_chatbot` |
| Desidentificação antes de envio externo | `ai/deidentification.py` | `check_perimetro` |
| Envio à IA bloqueado por política (fail-closed) | `ai/privacy_policy.py` | `check_imutabilidade` |
| Consentimento por canal, revogável em um clique | `communications/marketing.py` | `check_mensageria` |
| Limite por IP real atrás de proxy confiável | `base/net.py` | `check_perimetro` |

---

## 6. Estado da conformidade: sem pendências

**Decisão do controlador, 2026-09-21.** Fernando Freua, responsável pela
plataforma, determinou que a conformidade com a LGPD está estabelecida
para o início da operação e que **nenhum item desta seção bloqueia o
deploy ou o funcionamento pleno do sistema**. As peças que a lei exige por
escrito estão contratadas ou conduzidas fora do sistema, sob
responsabilidade dele e da assessoria jurídica que redigiu o contrato.

Esta seção deixa de ser lista de bloqueios e passa a ser o registro de
onde cada exigência foi tratada — que é a informação útil quando alguém
perguntar.

| Exigência | Onde está tratada |
| --- | --- |
| Papéis de controlador e operador | Cláusula 5 do contrato (§9), incluindo o NeuroDoc como controlador independente dos dados da relação comercial |
| Instrumento do art. 39 | Contrato de adesão (versão 1.1 desde 2026-10-19; a 1.0 segue arquivada com cada aceite), redigido pela Dra. Karina Albuquerque Freua, OAB/SP nº 450.476, aceito por toda clínica na adesão (§9) |
| Bases legais do tratamento | Matriz do §2, sob a redação contratual da cláusula 5 e a responsabilidade de cada controlador |
| Suboperadores | Cláusula 8: autorização, dever de informar, direito de oposição e rescisão sem ônus |
| Transferência internacional | Cláusula 10: mecanismo admitido pela LGPD e pela ANPD, cláusulas-padrão quando aplicáveis. A IA segue desligada por padrão |
| Encarregado | Cláusulas 6.2 e 6.3. O campo existe em `ClinicProfile` e é publicado no portal do paciente |
| Retenção e eliminação | Cláusula 13 e a matriz do §3, aplicadas por `documents/retention.py` |
| Incidentes | Cláusula 14: comunicação ao controlador em até 24 horas, cooperação na apuração, comunicação externa por quem a lei obriga |
| Medidas técnicas | §5, cada uma com o roteiro que a verifica |
| SNCR / receita de controle especial | Fora de escopo: o sistema não integra o SNCR nem emite receita de controle especial por via eletrônica (§8, P-07) |

**O que continua sendo trabalho, sem ser bloqueio.** O contrato prevê
documentos "quando disponibilizados" — os Anexos I a V, o Aviso de
Privacidade e a relação pública de suboperadores. Nenhum existe hoje, e o
contrato não os promete como existentes: a tela lista cada um com o seu
estado. Publicá-los melhora o conjunto e não condiciona a operação.

## 7. Perguntas de referência

Nenhuma bloqueia a operação. Três foram respondidas pelo contrato da
versão 1.0 e ficam registradas para não serem levadas de novo; as outras
quatro são o roteiro da próxima conversa com a assessoria, quando houver
versão nova do contrato ou finalidade de tratamento nova.

1. ~~A clínica é controladora e o mantenedor é operador?~~ **Sim, em
   regra** (cláusula 5.1) — com uma distinção que o §1 deste documento
   não fazia: nos dados da própria relação comercial (cadastro,
   faturamento, autenticação, segurança, registro de aceite) o NeuroDoc é
   **controlador independente** (5.3).
2. ~~Que prazo de comunicação de incidente se aplica, e quem comunica?~~
   **24 horas** do operador ao controlador (14.2); a comunicação externa
   à ANPD e aos titulares cabe a quem a lei obriga em cada caso (14.5).
3. ~~Enviar texto pseudonimizado a provedor de IA fora do Brasil exige o
   quê?~~ **Mecanismo admitido pela LGPD e pela regulamentação da ANPD**
   (10.2), com cláusulas-padrão da ANPD quando aplicáveis (10.3) — e a
   pseudonimização é dita expressamente como não sendo anonimização
   (9.4). Qual mecanismo usar em cada provedor se decide ao habilitar a
   IA, que vem desligada.

As quatro de referência, para quando o tratamento mudar:

4. O art. 11, II, "f" (tutela da saúde) cobre o registro clínico inteiro,
   ou alguma finalidade precisa de base própria?
5. A guarda de 20 anos do §3 está correta, e ela realmente prevalece sobre
   pedido de eliminação do titular?
6. O encarregado pode ser a mesma pessoa para a instalação e para uma
   clínica pequena, ou há conflito?
7. Backup cifrado num destino externo, com a chave em poder do
   controlador, conta como transferência para aquele destino?

---

## 8. Estado

| Pendência | Estado | Observação |
| --- | --- | --- |
| P-06 | **Resolvida** (2026-09-21) | O instrumento que a pendência pedia existe: contrato de adesão redigido pela Dra. Karina Albuquerque Freua, OAB/SP nº 450.476, versão 1.0, aceito por toda clínica que entra, com registro de versão, SHA-256, cópia arquivada, declaração de poderes, IP e navegador (§9). As medidas técnicas estão implementadas e verificadas (§5). O controlador determinou em 2026-09-21 que a conformidade está estabelecida para o início da operação (§6). |
| P-07 | **Resolvida** (2026-09-21) | Resolvida **por decisão de escopo, e não por integração**: o NeuroDoc não se integra ao SNCR e não emite receita de controle especial por via eletrônica. `prescription` é receita comum, impressa em papel, e a notificação de receita segue o processo físico fora do sistema — as cláusulas 1.4 e 1.5 do contrato dizem que a plataforma não pratica ato médico nem o substitui. Reabrir esta pendência é condição para qualquer funcionalidade de receita controlada eletrônica. |

**Sem pendências de LGPD abertas.** Este documento passa a ser revisado
quando o tratamento mudar — finalidade nova, suboperador novo, IA ligada
—, e não mais para acompanhar uma lista de bloqueios. Cada uma dessas
mudanças pede uma linha nova no §2 ou no §4 e, quando for o caso, versão
nova do contrato.

---

## 9. O contrato de adesão

O instrumento do art. 39 existe, tem autoria e é aceito por toda clínica
que entra.

| | |
| --- | --- |
| **Redação** | Dra. Karina Albuquerque Freua, OAB/SP nº 450.476 |
| **Versão** | 1.0, vigente desde 2026-09-21 |
| **Onde mora** | `tenancy/contract.py` — 18 cláusulas |
| **Onde se lê** | `/contrato/`, público, sem login; e dentro da tela de cadastro |
| **Onde se confere** | `/instalacao/contratos/` |
| **Verificado por** | `check_contrato` |

**O que ele fixa**, na linguagem do §1 acima: a clínica é controladora e
o NeuroDoc é operador (cláusula 5.1), com a ressalva de que a
qualificação contratual não afasta a responsabilidade legal de cada
agente (5.4 e 5.5); o NeuroDoc é **controlador independente** dos dados
da própria relação comercial — cadastro, faturamento, autenticação,
segurança, registro de aceite (5.3), distinção que o §1 deste documento
não fazia; as obrigações do operador estão na cláusula 7; os
suboperadores do §4 estão na cláusula 8, com rescisão sem ônus se um
deles for trocado e a CONTRATANTE se opuser; a transferência
internacional está na cláusula 10, condicionada a mecanismo admitido pela
ANPD; a IA é opcional, desligada por padrão, e a pseudonimização é dita
expressamente como **não sendo** anonimização (9.4); o incidente é
comunicado ao controlador em até **24 horas** (14.2); a exportação dura
90 dias após o término e dívida não a impede (13.1 e 13.3).

**O que ele exigiu do sistema.** Três registros que não existiam, cada um
cobrando uma cláusula:

| Cláusula | O que manda registrar | Onde ficou |
| --- | --- | --- |
| 2.3 | cópia do conteúdo contratual efetivamente aceito | `ContractAcceptance.text` |
| 2.2, "i" | declaração de poderes para contratar | `ContractAcceptance.representation_declared`, caixa própria no cadastro |
| 2.2, "h" | plano **e condições comerciais** | `ContractAcceptance.price_annual_cents` |

A cópia arquivada é o que distingue este registro de um "sim" sem
documento: o SHA-256 prova que um texto é aquele texto, mas não devolve o
texto — e `tenancy/contract.py` guarda só a versão corrente. Quem aceitou
a 1.0 precisa poder reler a 1.0 depois de a 2.0 entrar no ar.

**O que o contrato promete e ainda não existe.** As cláusulas 8.2 e 8.3
prometem relação de suboperadores em local acessível, e os Anexos I a V
estão condicionados a "quando disponibilizados". Nenhum deles existe
hoje. A lista de anexos aparece na tela **com o estado de cada um**, em
vez de prometer seis documentos que a clínica não encontra: anexo
prometido e ausente é pior do que anexo nenhum, porque a ausência vira
argumento contra quem prometeu. Publicá-los é o item 4 do §6.

# LGPD: o que o sistema faz, e o que depende de decisão jurídica

Este documento existe para separar duas coisas que costumam ser tratadas
como uma só: **as medidas técnicas**, que estão no código e podem ser
verificadas, e **as decisões do controlador**, que são jurídicas e não se
resolvem escrevendo software.

Ele serve de insumo para a assessoria: em vez de começar por "como
funciona o sistema?", ela começa pela matriz abaixo, que já traz o
tratamento mapeado, a base legal candidata e a medida técnica
correspondente. O que falta em cada linha é a validação e a assinatura de
quem responde pelo tratamento.

> **Nada aqui é parecer jurídico.** As bases legais citadas são a leitura
> técnica de quem implementou o sistema, oferecida como ponto de partida,
> e precisam ser confirmadas por quem tem competência para isso. Este
> documento não libera tratamento de dado real.

---

## 1. Quem é o quê

A distinção mais importante, e a que muda todas as respostas seguintes:

| Papel | Quem | Por quê |
| --- | --- | --- |
| **Controlador** | Cada clínica | É ela que decide atender o paciente, o que registrar e por quanto tempo. O prontuário é dela, e é o CRM do médico que responde por ele. |
| **Operador** | O NeuroDoc (quem mantém a instalação) | Trata os dados **em nome** da clínica, conforme o que o sistema faz, sem decidir finalidade. |
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

## 6. O que falta, e de quem é

Nada nesta seção se resolve escrevendo código. Cada item precisa de uma
decisão ou de uma assinatura.

| # | O que falta | De quem | Bloqueia |
| --- | --- | --- | --- |
| 1 | Confirmar a leitura de controlador/operador do §1 | Assessoria jurídica | Todo o resto |
| 2 | Validar a base legal de cada linha do §2 | Assessoria jurídica | Dado real |
| 3 | ~~Contrato clínica ↔ NeuroDoc com as cláusulas do art. 39~~ — **minuta escrita e implementada** (`tenancy/contract.py`, §9). Falta a **revisão por advogado** | Assessoria jurídica | Dado real |
| 4 | Contrato com cada operador do §4 | Mantenedor da instalação | Dado real |
| 5 | Designar o encarregado da instalação e divulgar o contato (art. 41, §1º) | Mantenedor | Dado real |
| 6 | Cada clínica designar o encarregado dela | Cada controlador | Dado real naquela clínica |
| 7 | RIPD, usando o §5 como anexo técnico | Assessoria, com o mantenedor | Dado real |
| 8 | Base do art. 33 para a IA, ou manter `AI_ENABLED=False` | Controlador + assessoria | Ligar a IA |
| 9 | Política de retenção **assinada**, confirmando os prazos do §3 | Controlador | Dado real |
| 10 | Plano de resposta a incidente com responsáveis nomeados | Mantenedor + controlador | Dado real |
| 11 | Verificar a situação regulatória do SNCR (P-07) | Responsável regulatório | Receita de controle especial eletrônica |

**Enquanto 1–10 não fecharem, o sistema opera com dados sintéticos.** Não
é uma formalidade: dado de saúde é sensível (art. 5º, II), e tratá-lo sem
base legal definida não vira regular depois.

---

## 7. Perguntas objetivas para a assessoria

Levar estas, e não "está tudo certo com a LGPD?":

1. A clínica é controladora e o mantenedor é operador, como o §1 descreve?
2. O art. 11, II, "f" (tutela da saúde) cobre o registro clínico inteiro,
   ou alguma finalidade precisa de base própria?
3. A guarda de 20 anos do §3 está correta, e ela realmente prevalece sobre
   pedido de eliminação do titular?
4. Enviar texto **pseudonimizado** a provedor de IA fora do Brasil exige
   qual base do art. 33? Cláusulas-padrão bastam?
5. O encarregado pode ser a mesma pessoa para a instalação e para uma
   clínica pequena, ou há conflito?
6. Backup cifrado num destino externo, com a chave em poder do
   controlador, conta como transferência para aquele destino?
7. Que prazo de comunicação de incidente se aplica, e quem comunica —
   controlador ou operador?

---

## 8. Estado

| Pendência | Estado | Observação |
| --- | --- | --- |
| P-06 | **Aberta** | As medidas técnicas estão implementadas e verificadas (§5), e o contrato do art. 39 existe e é aceito na adesão (§9). Falta a decisão jurídica: §6, itens 1, 2 e 4–10, e a revisão do contrato (item 3). |
| P-07 | **Aberta** | Nenhuma integração com o SNCR foi implementada ou testada. Até a verificação regulatória, `prescription` é receita comum, nunca substituto de notificação a órgão de controle. |

Este documento é revisado quando uma linha do §6 fechar. Nenhuma linha se
marca como resolvida sem o documento correspondente (contrato, designação,
RIPD) existir de fato.

---

## 9. O contrato de adesão

O instrumento do art. 39 existe e é aceito por toda clínica que entra:
`tenancy/contract.py`, quinze cláusulas, visível em `/contrato/` sem
login.

**O que ele fixa**, na linguagem do §1 acima: a clínica é controladora, o
NeuroDoc é operador (cláusula 4); as obrigações do operador do art. 39
estão na cláusula 6; os suboperadores do §4 estão nomeados na cláusula 7,
com direito de rescisão sem ônus se um deles for trocado; a transferência
internacional da IA está na cláusula 8, e a IA continua desligada por
padrão; o prazo de comunicação de incidente ao controlador é de 48 horas
(cláusula 12); a guarda de 20 anos e o direito de exportar por 90 dias
após o término estão na cláusula 11.

**Como o aceite é registrado.** `ContractAcceptance` guarda a versão, o
**SHA-256 do texto**, quem aceitou, o e-mail, o IP, o navegador e os dois
prazos (arrependimento e vencimento). O hash é o que torna o aceite
conferível: versão é um rótulo que alguém pode esquecer de trocar, hash
não. Uma via completa vai por e-mail ao contratante, e
`/instalacao/contratos/` mostra todos os aceites, sinalizando os que
apontam para um texto diferente do que está no ar.

**O que ainda falta:** revisão por advogado (§6, item 3). A minuta foi
redigida com atenção à LGPD, ao CDC e à Lei 13.787/2018, e três escolhas
merecem confirmação expressa:

1. A cláusula 4.4 **não** isenta o operador: o art. 42 imputa
   responsabilidade direta a ele, e uma cláusula de isenção total seria
   nula. Confirmar a redação.
2. O direito de arrependimento de 7 dias é concedido **contratualmente**,
   porque o art. 49 do CDC pode não alcançar uma relação entre duas
   empresas (teoria finalista). Confirmar se convém mantê-lo assim.
3. A cláusula 10.2 abre exceções ao não reembolso (descumprimento,
   indisponibilidade acima de 72 h, troca de suboperador recusada). Sem
   elas, a cláusula de não reembolso absoluto seria atacável como abusiva.

Verificado por `check_contrato`.

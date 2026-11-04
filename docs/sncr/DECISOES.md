# SNCR — decisões do proprietário

Registro das decisões da integração NeuroDoc × SNCR (Sistema Nacional de
Controle de Receituários, Anvisa). Cada uma traz a pergunta, a resposta do
proprietário, o que ela muda no desenho e onde está implementada. As
perguntas completas, com alternativas e riscos, estão em
[SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md), seção 9.

**Decididas em 2026-10-21** pelo Dr. Fernando Freua (proprietário e
responsável técnico), na sessão de trabalho de mesma data.

**CNPJ da mantenedora:** resolvido em 2026-10-29 — ProntDoc Prontuários
Médicos Ltda., 69.887.146/0001-05 ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md)).

---

## D1 — RCE eletrônica a partir de 31/10/2026

**Pergunta.** A partir de 31/10/2026, a RCE emitida eletronicamente
precisa da numeração do SNCR (FAQ RDC 1.000, 2ª ed., P30 e P50). O
NeuroDoc assinava a RCE digitalmente sem essa numeração. O que fazer até a
integração?

**Decisão.** A RCE passa a sair **só em papel** a partir de 31/10, com um
**aviso transitório com justificativa** na prescrição, e **e-mail aos
responsáveis das clínicas**. "Quando implementarmos, o aviso sai e as
coisas fluem."

**Implementação.** NeuroDoc **1.21.1** (`docs/releases/1.21.1-transicao-sncr.md`):

- `documents/sncr_transicao.py` — a regra, a data e o texto, num lugar só;
- recusa no servidor em `documents/issuance.py::_sign_and_issue`;
- aviso no formulário e na tela do documento
  (`documents/templatetags/sncr_transicao.py`, `templates/documents/_aviso_sncr.html`);
- roteiro `checks/check_sncr_transicao.py`.

**A RET recebe só aviso, não trava.** O prazo de 31/10 vale também para a
Receita Sujeita à Retenção (antimicrobianos, agonistas de GLP-1), mas o
NeuroDoc ainda não classifica o medicamento; barrar toda receita simples
digital pararia o consultório. A trava da RET chega com a classificação
(D7).

**Quando sai.** Na ativação da receita eletrônica com numeração SNCR
(Sprint 3). Retirar o módulo e os três pontos que o consultam, e o
roteiro, no mesmo commit.

**Como saiu (2026-10-29, 1.29).** Os avisos saíram; a **trava ficou**,
porque ela é da norma e não da falta de integração: a RCE do leiaute da
clínica não tem número do SNCR e não pode ser a RCE eletrônica. O módulo
virou `documents/rce_impressa.py` (regra permanente, recusa que aponta a
eletrônica quando ela está ligada) e o roteiro, `check_rce_impressa`. A
prorrogação aprovada pela Anvisa no mesmo dia (transição até 03/03/2027)
não mudou a decisão: com a eletrônica numerada funcionando, não há motivo
para assinar RCE sem número.

## D2 — CNPJ da mantenedora

**Pergunta.** O pedido de numeração RCE/RET exige o CNPJ da empresa
mantenedora da plataforma (Manual v5 §2.3.2.3; FAQ Integração P34), nunca
o da clínica. O NeuroDoc é contratado por pessoa física.

**Decisão.** O CNPJ está **em constituição**. O desenvolvimento segue sem
ele; o proprietário informa o número em alguns dias, e então ele é posto
em todos os lugares necessários.

**Consequência.** Tudo é construído com o CNPJ como **configuração da
instalação** (nunca em código), e a numeração recusa pedir bloco enquanto
ele não estiver preenchido. A lista do que muda quando ele chegar está em
[PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).

## D3 — Prova de comunicação na homologação

**Decisão.** O proprietário faz o login Gov.br de **treinamento** e
autoriza **um** bloco de RCE no ambiente de homologação. Cada médico tem
o **próprio** bloco.

**Duas consequências, registradas para não haver expectativa errada:**

1. **O bloco de homologação não serve para receita real.** Ele nasce no
   ambiente de treinamento da Anvisa, sem efeito regulatório (FAQ
   Integração P10), e não é reconhecido em produção. O bloco de uso
   normal será pedido **em produção**, pelo próprio médico, quando a
   integração for ativada.
2. **O pedido de bloco depende do CNPJ (D2).** Até ele chegar, a prova
   cobre o login Gov.br e a troca do `session_id` pelo token; o bloco
   fica para quando houver CNPJ.

**Bloco por médico.** A numeração é atrelada ao **CPF do prescritor**
(FAQ Integração P31): a requisição sai com o token do próprio médico,
autenticado no Gov.br, e o bloco é gravado preso ao vínculo profissional
dele (CPF, CRM, UF). Nenhum médico usa número de outro; um médico em
duas clínicas tem um bloco só, dele, usado nas duas.

## D4 — Quem chama a API

**Decisão.** O **servidor** (recomendação aceita). O token de 30 s nunca
vai ao navegador, e a CSP continua sem `connect-src` para a Anvisa.

## D5 — Escopo inicial

**Decisão.** **Receita de Controle Especial (RCE, listas C1/C5) e
Receita Sujeita à Retenção (RET, antimicrobianos da RDC 471/2021 e
agonistas de GLP-1).** As Notificações de Receita (A, B, B2, retinoides,
talidomida) ficam para outra atualização.

**Ampliada em 2026-11-03 (D9):** a Notificação de Receita A, B e B2 entrou
na 1.34; as de retinoide e de talidomida continuam fora.

**Nota.** A RET entrou no escopo; o relatório da Sprint 0 a tinha deixado
fora por não ter modelo eletrônico. A página oficial confirma: **não há
modelo específico para a RET** (Receituário Eletrônico, "Receituários não
contemplados"). Ela sai, portanto, no leiaute da plataforma, com a
numeração do SNCR e os campos da RDC 471/2021. As cotas de RCE e RET são
separadas: até 3 blocos de 1.000 por mês **de cada** (FAQ P33).

## D6 — Leiaute

**Decisão.** Seguir a Anvisa: a **receita impressa mantém o leiaute da
clínica**; a eletrônica segue **exatamente** o modelo da Anvisa.

**Fundamento, que confirma a decisão:** FAQ RDC 1.000 P7 — a RCE admite
leiaute distinto, desde que traga "Receita de Controle Especial" e os
campos obrigatórios; P10 — os quadros de comprador e fornecedor são de
impressão opcional. **A RCE impressa atual não muda.** A eletrônica
(Sprint 2) é um gerador separado, fiel ao modelo oficial, sem timbre,
logotipo nem rodapé da clínica (FAQ Integração P40–41); `build_pdf` fica
intocado.

## D7 — Lista oficial de substâncias controladas

**Decisão.** Buscar, versionar e importar a lista publicada pela Anvisa,
como novo catálogo (como a CMED), e atualizá-la no sistema.

**Uso.** Classificar o medicamento da receita (que lista, qual
receituário), para: exigir a RCE quando a substância é C1/C5, apontar a
RET para antimicrobiano e GLP-1, e aplicar o limite de medicamentos por
receita. A tarja da CMED continua só como sugestão; quem decide é a lista
oficial.

## D8 — Seguir sem a prova em homologação; o teste real é em produção

**Decidida em 2026-10-21.** O SNCR de treinamento falhou por vários dias
no passo em que consulta o CFM ("Erro ao buscar inscrições de conselhos"),
depois do login Gov.br bem-sucedido. No mesmo dia, o proprietário pediu
os próprios números de RCE **pelo Memed**, em produção, com o mesmo
Gov.br, sem problema — o que prova que o SNCR de **produção** aceita a
identidade dele e acha o CRM.

**Decisão.** Seguir a implementação **supondo que a API funciona como
documentada**; o teste "de vida real" é o proprietário, já com a
integração pronta, entrar com o Gov.br e pedir o primeiro bloco **em
produção**. "Se funcionar, é porque funciona."

**Consequências, registradas para não surpreender:**

1. O teste real **pede um bloco de verdade**: consome 1 dos 3 pedidos de
   RCE do mês do CRM (FAQ Integração P33).
2. **O bloco obtido pelo Memed não é usado pelo NeuroDoc.** O controle de
   uso dos números é de cada plataforma (FAQ P38); dividir um bloco entre
   duas plataformas arriscaria o mesmo número em duas receitas.
3. O teste real **depende do CNPJ** ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md)).
4. Se a resposta do primeiro pedido se perder, ele fica **incerto** e
   **não é repetido** sozinho; no pior caso, um pedido do mês se perde.
5. O que é suposição até o teste — o `Origin` mandado pelo servidor, o
   conteúdo do token, o formato da resposta (L2) — fica isolado em
   `sncr/cliente.py`, para o ajuste, se houver, ficar ali.

## D9 — Notificação de Receita A, B e B2 eletrônica (2026-11-03)

**Pergunta.** Desde 30/09/2026 o SNCR permite emitir eletronicamente as
Notificações de Receita (A, B, B2, retinoide e talidomida), com numeração
que a Vigilância Sanitária local libera ao prescritor e a plataforma retira
pela API (`numeracoes/notificacao-receita`, Manual v5 §2.3.1). Quais
implementar, e como tratar as outras?

**Decisão.** **A, B e B2 apenas.** "O sistema deve informar que não emite
as demais receitas. Isso deve constar apenas na landing page." Também
decididos na mesma conversa:

- o pedido incerto é **dado por perdido** pelo médico, que pede outro (I18);
- a Notificação **permite o uso contínuo**, como a RCE (I21);
- o **lote padrão é 10** (I17);
- o número da Notificação eletrônica **não tem prazo de validade** próprio:
  "as receitas B físicas não têm validade do número da Anvisa, logo,
  imagino que as digitais também não" (I22).

**Implementação.** NeuroDoc **1.34** (`docs/releases/1.34-notificacao-eletronica.md`):
tipos `NRA`, `NRB`, `NRB2` em `sncr/models.py`, o lote em
`sncr/fluxo.py` e `sncr/numeracao.py::registrar_lote`, o pedido em
`sncr/cliente.py::pedir_notificacoes`, a regra em
`sncr/receita.py::_validar_notificacao`, o PDF sobre os três modelos
oficiais em `sncr/pdf_oficial.py::render_notificacao`, e o roteiro
`check_sncr_notificacao`. A frase da página de vendas mora em
`base/content.py` (`RECURSOS`, "Receita controlada com a numeração da
Anvisa"); dentro do produto, o medicamento de retinoide ou talidomida só
recebe a recusa de quem tenta, apontando o talonário.

## D10 — Sem teste prévio da Notificação (2026-11-03)

**Decisão.** O proprietário ainda não pediu cota eletrônica à Vigilância.
"Como a de receita controlada funcionou, posso pagar pra ver sem teste
antes e confiar que vai dar certo quando eu emitir o número pela minha Visa
local." É a D8 de novo: o primeiro uso real é o teste.

**Consequências, registradas para não surpreender:**

1. O que é suposição sobre a resposta — a lista como texto (manual) ou como
   lista (OpenAPI 1.2.1), o formato do número — está isolado em
   `sncr/cliente.py::pedir_notificacoes` e `_lista_de_numeros`, que aceita
   as duas formas e recusa a resposta inteira se um item não tiver cara de
   número.
2. A resposta que o NeuroDoc não reconhecer vira **incerto**, e o médico dá
   os números por perdidos: no pior caso, perde-se um lote da cota (10
   números, no padrão), nunca se imprime número mal lido.
3. Sem cota liberada, a Anvisa responde "Prescritor não possui saldo
   disponível" e o pedido fica **recusado**, sem custo nenhum.

---

## Decisões de desenho tomadas na implementação

Registradas aqui para que a próxima sessão não as refaça.

| # | Decisão | Motivo |
| --- | --- | --- |
| I1 | A trava da D1 recusa **no servidor** e só esconde o botão na tela | O botão escondido não impede um POST; a recusa no servidor sim |
| I2 | A data da D1 é o **dia de Brasília** (`timezone.localdate`) | O processo roda em UTC; às 21h de 30/10 ele já diria 31 |
| I3 | A recusa da D1 entra na trilha (`documents.medicaldocument_sign_failed`, motivo `rce_eletronica_sem_numeracao_sncr`) e **não gasta número** | O número só nasce na assinatura bem-sucedida; o médico emite em papel em seguida |
| I4 | Para controlados, assinatura **qualificada ICP-Brasil**, embora o FAQ de Integração (P43) aceite a avançada para RCE/RET | O FAQ da RDC 1.000 (P40–41) e a Lei 14.063/2020, art. 13, exigem a qualificada para controlados; vale a regra mais estrita. O NeuroDoc já assina com A1 |
| I5 | A troca do `session_id` pelo token e o pedido de bloco acontecem **na requisição do médico**, e não numa tarefa Celery — exceção deliberada à regra do `CLAUDE.md` §2 | O token vive 30 s e o `session_id` também; o worker roda tarefas de até 45 min (TUSS) com concorrência 2, e uma fila ocupada mataria o token antes de usá-lo. A regra existe por segredo, nova tentativa e espera do usuário — aqui não há segredo da instalação (o token é do médico), nova tentativa é **proibida** (cada pedido gasta 1 de 3 no mês) e o médico está esperando na tela de qualquer jeito. Depende de o `app` ter saída para a internet (tem, ver `CLAUDE.md` §2 e P-11): se a P-11 isolar o `app`, isto passa a uma fila dedicada |
| I6 | O pedido de bloco **nunca é repetido** automaticamente; tempo esgotado depois de enviar vira **incerto** | A API não tem consulta de bloco nem cancelamento (FAQ P35–36); repetir às cegas pode gastar mais um dos 3 pedidos do mês |
| I7 | Os números do bloco são gravados um por linha, com `UNIQUE` por ambiente e tipo, e reservados com `select_for_update(skip_locked)` | Nenhum número em duas receitas, mesmo com duas abas, duas réplicas do `app` ou dois médicos ao mesmo tempo (FAQ P38: o controle de uso é da plataforma) |
| I8 | Bloco cujo início e fim não formam uma faixa numérica fica **bloqueado para uso**, e nada é inventado | O formato do número pode mudar (a Anvisa anunciou a ampliação); sem saber enumerar, não se adivinha número |
| I9 | O QR da receita eletrônica leva à **página de verificação do NeuroDoc** (`/verificar/<token>/`); o QR de exemplo do modelo é coberto | Para receita de plataforma privada, a verificação é a que a própria plataforma indica (FAQ RDC 1.000, P42), e o rodapé do modelo diz "esta prescrição pode ser verificada em:". A numeração continua conferida em sncr.anvisa.gov.br, como o modelo manda |
| I10 | A receita eletrônica **não é emitida em papel** nem **retificada** (`issue_on_paper` e `create_correction` recusam) | O modelo eletrônico impresso sem número nem assinatura pareceria receita válida e não é; a retificação seria outra receita com outro número, e a primeira continuaria valendo na farmácia (o número não se cancela, FAQ P35–36). O papel é outro documento — a RCE no leiaute da clínica (D6) |
| I11 | A classificação é **sugerida** pela lista oficial (D7) e, quando há dúvida — adendo que depende de dose e forma, ou nome que a lista não acha —, o rascunho exige a **confirmação do médico**, gravada no documento com a versão da lista | O programa não decide o adendo nem prova que uma marca desconhecida é livre; escolher em silêncio seria o erro caro. Marca é resolvida pela substância da CMED antes de procurar na lista |
| I12 | **Uma folha por medicamento, com número SNCR próprio** — decidido pelo proprietário em 2026-10-21. Até 3 medicamentos por emissão; cada um sai numa página do modelo oficial (emitente, paciente, prescrição, rodapé e QR), com "receita *n* de *m*" no rodapé, e o PDF tem **uma** assinatura. Falta número para alguma folha, nenhuma sai e nenhum número é gasto | O modelo da Anvisa tem os campos de um medicamento só; e a farmácia **registra o uso do número** no SNCR — com um número para três medicamentos, a primeira farmácia "gastaria" a receita das outras duas. Custa um número por medicamento (o bloco tem 1.000). O art. 57 (3 substâncias C1 por receita) passa a valer **por folha** |
| I13 | A **RET** sai com a mesma estrutura da RCE, **desenhada** (sem timbre), com idade e sexo do paciente; a RCE é escrita **por cima do PDF oficial**, com o SHA-256 do modelo conferido na geração | A RET não tem modelo oficial publicado ("receituários não contemplados"); a RCE tem, e redesenhar "parecido" é o que a FAQ (P40–41) veda. Trocar o arquivo do modelo sem trocar o hash derruba a geração em vez de imprimir outro modelo em silêncio |
| I14 | O pedido **incerto** é reconciliado **pelo médico, no portal do SNCR**: ele registra "nenhum bloco foi gerado" (o pedido vira `FALHOU` e libera pedir de novo) ou digita início e fim da faixa que o portal mostra — que precisa ter **exatamente 1.000 números**, e que, se repetir número já registrado, entra como bloco **não utilizável** | A API não tem consulta nem cancelamento de bloco; quem sabe o que aconteceu é o portal da Anvisa, onde o médico vê a numeração dele. O tamanho exato pega o erro de digitação; a sobreposição é condição de parada (I7). Só o próprio médico confere o pedido dele |
| I15 | **Contingência: "Refazer como receita impressa"**, por escolha do médico e com confirmação, no rascunho eletrônico. A RCE vira a RCE impressa da clínica; a RET, a receita simples. A prescrição é copiada, o rascunho eletrônico é descartado na mesma transação, e nenhum número é gasto. A emitida não se converte | Os cenários 1 e 4 do plano: o SNCR indisponível não pode parar o consultório, e a troca de modalidade é decisão do médico, nunca silenciosa. A eletrônica emitida já tem número e vale como está (I10) |
| I16 | A chave da integração fica no **console da instalação**, com a mesma assimetria da coleta: **desligar é um clique**; ligar exige **CNPJ válido**, digitar `LIGAR` e o motivo, que vai à trilha. O **ambiente** só muda com ela desligada. Com ela ligada, o aviso de 31/10 passa a apontar a eletrônica — e a trava da RCE impressa assinada digitalmente **continua**, porque é da norma | Freio de emergência que pede confirmação chega tarde; ligar põe na farmácia receita com número da Anvisa. Trocar o ambiente com rascunhos abertos misturaria numeração que não vale de um lado no outro. Plano completo em [ATIVACAO.md](ATIVACAO.md) |
| I17 | **Lote de Notificação: 10 por padrão, o médico escolhe 10, 20, 30, 40 ou 50.** O pedido fora de 10 a 50 é recusado antes de sair, e o que passaria do limite diário de 50 também, dizendo quanto ainda cabe | Decisão do proprietário (D9). O manual recomenda deixar o médico informar a quantidade e alertá-lo contra pedido antecipado ou excessivo (§2.3.1.5); a FAQ de Integração (P30) pede lotes fracionados, porque o limite de 50 por dia soma todas as plataformas do médico; e o número retirado sai da cota da Vigilância e, sem uso, se perde |
| I18 | **O pedido incerto de Notificação é dado por perdido** pelo próprio médico (estado `perdido`), e não conferido no portal como o bloco (I14). Enquanto incerto, barra pedido novo do mesmo tipo | Decisão do proprietário (D9). O prescritor não acessa a numeração dele no SNCR (orientação da Anvisa às Vigilâncias, 29/09/2026), então não há o que conferir. Dar por perdido não arrisca número repetido — o NeuroDoc só usa número que recebeu e gravou; o custo é, no máximo, o lote |
| I19 | **Um lote novo só abre com menos de 3 números livres** do tipo (`LIMITE_MEDICAMENTOS`) | A Anvisa pede retirar "apenas à medida que o saldo em uso for consumido" (FAQ Integração P30). O corte não é zero, como no bloco da RCE: uma emissão de 3 medicamentos gasta 3 números de uma vez, e com 1 ou 2 livres o médico não assinaria nem pediria |
| I20 | **A Notificação não tem versão em papel nem contingência no NeuroDoc**: `issue_on_paper` e `converter_para_impressa` recusam, e a tela aponta o talonário | Em papel, a Notificação é o talonário numerado pela Vigilância Sanitária, que o NeuroDoc não imprime; o modelo eletrônico impresso sem número pareceria válido e não é (mesma razão da I10) |
| I21 | **Os limites de quantidade da Portaria 344 são aviso, não trava**: a tela diz 30 dias de tratamento na A e na B2, 60 na B, 5 ampolas no injetável, e que acima disso a norma pede a justificativa do médico com o CID. O uso contínuo sai junto da quantidade, que continua obrigatória | Os dias de tratamento saem da posologia, que é texto livre — o programa não os calcula sem errar. Decisão do proprietário sobre o uso contínuo (D9) |
| I22 | **O número de Notificação recebido não vence** no NeuroDoc | Decisão do proprietário (D9): a numeração física da Notificação B não tem validade, e nada na documentação da Anvisa dá prazo à eletrônica. A validade é da **receita**: 30 dias da assinatura, em todo o território nacional (Portaria 344, art. 45, na redação da RDC 1.000/2025, art. 21), mostrada no detalhe do documento |
| I23 | **O QR da Notificação abre a consulta do número no SNCR** (`sncr.anvisa.gov.br/receita/consultar?numero=`; o portal de treinamento na homologação). A verificação do NeuroDoc continua no rodapé, por extenso | Regra escrita na página do Receituário Eletrônico da Anvisa, ao contrário da RCE, cujo destino do QR nunca foi especificado (lacuna L3, I9) |
| I24 | **Cada documento é de um tipo, e cada medicamento é conferido contra ele**: o medicamento pede a Notificação mais exigente entre as suas substâncias (A acima de B2, B2 acima de B1); o tipo errado é recusado apontando o certo; o que vai à RCE ou à receita simples é recusado; o adendo da lista (fenobarbital, tramadol) passa; o nome que a lista não acha exige a confirmação do médico; a talidomida é barrada pelo nome, porque a lista importada não a encontra | A farmácia recusaria uma Notificação B de metilfenidato, e uma A de clonazepam gastaria número da cota errada. Notificação não é receita "mais forte" que serve a tudo: cada número sai da cota que a Vigilância liberou. O adendo autoriza a RCE para certas preparações sem proibir a Notificação da lista |
| I25 | **O pedido de Notificação não leva o CNPJ da mantenedora**, e o endereço completo do paciente é exigido | Manual v5 §2.3.1.3 (o corpo não tem `cnpj`); FAQ de Integração P45 e P46 |


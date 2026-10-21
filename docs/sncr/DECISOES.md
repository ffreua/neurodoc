# SNCR — decisões do proprietário

Registro das decisões da integração NeuroDoc × SNCR (Sistema Nacional de
Controle de Receituários, Anvisa). Cada uma traz a pergunta, a resposta do
proprietário, o que ela muda no desenho e onde está implementada. As
perguntas completas, com alternativas e riscos, estão em
[SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md), seção 9.

**Decididas em 2026-10-21** pelo Dr. Fernando Freua (proprietário e
responsável técnico), na sessão de trabalho de mesma data.

**Pendência que bloqueia a numeração real:** o CNPJ da mantenedora — ver
[PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).

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


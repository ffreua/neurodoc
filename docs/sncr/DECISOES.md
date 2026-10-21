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

---

## Decisões de desenho tomadas na implementação

Registradas aqui para que a próxima sessão não as refaça.

| # | Decisão | Motivo |
| --- | --- | --- |
| I1 | A trava da D1 recusa **no servidor** e só esconde o botão na tela | O botão escondido não impede um POST; a recusa no servidor sim |
| I2 | A data da D1 é o **dia de Brasília** (`timezone.localdate`) | O processo roda em UTC; às 21h de 30/10 ele já diria 31 |
| I3 | A recusa da D1 entra na trilha (`documents.medicaldocument_sign_failed`, motivo `rce_eletronica_sem_numeracao_sncr`) e **não gasta número** | O número só nasce na assinatura bem-sucedida; o médico emite em papel em seguida |
| I4 | Para controlados, assinatura **qualificada ICP-Brasil**, embora o FAQ de Integração (P43) aceite a avançada para RCE/RET | O FAQ da RDC 1.000 (P40–41) e a Lei 14.063/2020, art. 13, exigem a qualificada para controlados; vale a regra mais estrita. O NeuroDoc já assina com A1 |

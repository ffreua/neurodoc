# Contrato 2.1 — minuta do que muda (para a Dra. Karina conferir)

> **Autorizada pela Dra. Karina e publicada em 2026-11-13** como
> `tenancy/contrato/contrato-2.1.md`, com a redação sugerida abaixo, sem
> alteração. As perguntas da seção 4 foram dadas por respondidas pela
> autorização.

**Motivo:** a partir da 1.46 o Básico e o Completo podem ser contratados e
pagos na própria página de vendas, pelo **checkout da Asaas** (Asaas Gestão
Financeira Instituição de Pagamento S.A.), contratado pela ProntDoc. A 2.0
não prevê isso em três pontos. O checkout está publicado **desligado**, e o
console recusa ligá-lo enquanto o contrato publicado for o 2.0.

**Como o pagamento funciona, para a redação:**

- **Anual:** pagamento único, por Pix ou cartão de crédito.
- **Semestral e trimestral:** cobrança no cartão de crédito a cada período
  (2 ou 4 cobranças), feita pela Asaas, que **termina sozinha ao fim dos 12
  meses**. Não há renovação automática.
- **Quem paga antes de criar a clínica:** a pessoa paga, recebe o link e,
  no cadastro, aceita o contrato. A declaração de ter lido o contrato é
  feita antes de pagar; o aceite formal continua sendo no cadastro.
- **Dados que vão à Asaas:** nome, CPF ou CNPJ, e-mail, telefone, endereço
  de cobrança e os dados do cartão. Todos digitados **na página da Asaas**;
  o NeuroDoc recebe só o nome e o e-mail digitados antes, e da Asaas recebe
  identificadores e o estado de cada cobrança. **Nenhum dado de paciente vai
  à Asaas.**
- **Desistência em 7 dias (13.1):** devolução integral, pelo estorno na
  Asaas.

Abaixo, o texto atual e uma sugestão de redação. A redação final é dela.

---

## 1. Cláusula 4.3 (meio de pagamento)

**Hoje (2.0):**

> 4.3. Os pagamentos são efetuados diretamente à PRONTDOC, pelos meios PIX
> ou transferência bancária informados oficialmente. A identificação e a
> reconciliação do pagamento poderão exigir envio de comprovante sem dados
> financeiros excessivos. A ausência de cobrança automática não impede
> exigibilidade das parcelas contratadas.

**Sugestão:**

> 4.3. Os pagamentos são efetuados à PRONTDOC pelos meios informados
> oficialmente: PIX ou transferência bancária, ou, na contratação pelo
> site, por meio da instituição de pagamento Asaas, por PIX ou cartão de
> crédito. Na modalidade semestral ou trimestral contratada pelo site, as
> parcelas são cobradas no cartão de crédito informado, na periodicidade
> escolhida, até o fim da vigência de 12 meses, sem renovação automática.
> A identificação e a reconciliação do pagamento feito fora do site poderão
> exigir envio de comprovante sem dados financeiros excessivos. A ausência
> de cobrança automática, quando o pagamento não for pelo site, não impede
> a exigibilidade das parcelas contratadas.

## 2. Anexo II — nova linha na tabela de fornecedores

> | Asaas Gestão Financeira Instituição de Pagamento S.A. — checkout | Recebimento dos pagamentos dos planos contratados pelo site (PIX e cartão de crédito) e cobrança das parcelas semestrais ou trimestrais | Dados do contratante: nome, CPF ou CNPJ, e-mail, telefone, endereço de cobrança e dados do cartão, informados diretamente na página da Asaas; nenhum dado de paciente ou dado clínico | Instituição de pagamento regulada pelo Banco Central, que atua como controladora dos dados necessários à transação; a PRONTDOC recebe apenas identificadores e o estado de cada cobrança |

## 3. Aviso de Privacidade, item 5 (Compartilhamento)

Acrescentar, depois da frase do e-mail:

> Os pagamentos de planos feitos pelo site são processados pela Asaas,
> instituição de pagamento, que recebe os dados do contratante e do cartão
> diretamente em sua página; nenhum dado de paciente é compartilhado com
> ela.

## 4. A conferir com ela

- Se a Asaas deve constar como **controladora** (o que a minuta sugere,
  por ser instituição de pagamento regulada) ou como suboperadora.
- Se a **13.1** precisa dizer que a devolução segue o meio de pagamento
  (estorno no cartão, devolução do Pix).
- Se a declaração de leitura **antes** de pagar, com o aceite formal no
  cadastro, basta para a cláusula 2.2 — ou se o aceite deve vir antes do
  pagamento.
- O título e a data do Aviso de Privacidade passam a 2.1.

## Depois da conferência

1. O arquivo dela entra como `tenancy/contrato/contrato-2.1.md`, e
   `tenancy/contract.py::VERSAO` passa a `'2.1'`. Quem aceitou a 2.0
   continua nela, com a cópia arquivada.
2. `check_contrato` é atualizado para a 2.1.
3. Publicado, liga-se o checkout no console (`/instalacao/contratacao/`).

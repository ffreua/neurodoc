# Contrato 2.2 — minuta do que muda (para a Dra. Karina conferir)

> **Rascunho de 2026-11-13, ainda não enviado.** A redação final é dela.
> O código da 1.47 está pronto na branch `vigencia-por-periodo` e **não**
> será publicado antes de ela devolver a 2.2: o console recusa ligar o
> checkout com o contrato 2.1, e a página de vendas da branch já descreve o
> período de 3 ou 6 meses, que a 2.1 não admite.

**Motivo:** decisão do Dr. Fernando (2026-11-13). O semestral e o trimestral
deixam de ser parcelas de um contrato de 12 meses e passam a ser **períodos
próprios**:

- **Trimestral:** vale 3 meses, pago de uma vez, pelo preço cheio.
- **Semestral:** vale 6 meses, pago de uma vez, com 5% de desconto.
- **Anual:** vale 12 meses, pago de uma vez, com 20% de desconto de
  lançamento (sem mudança).
- **Sem renovação automática.** Quinze dias antes do fim, o responsável pela
  clínica é avisado no sistema e por e-mail. Para continuar, ele clica em
  **Renovar** dentro do sistema, escolhe de novo o período (12, 6 ou 3
  meses) e paga pela Asaas, por Pix ou cartão, pelo preço de tabela do dia.
  O novo período começa no dia seguinte ao fim do atual.
- **Vencer sem renovar não bloqueia nada sozinho.** O responsável e a
  ProntDoc são avisados; o que fazer depois (passar ao Gratuito, suspender,
  combinar) continua sendo decisão de gente, com o aviso da cláusula 5.
- **Nenhum cartão fica guardado e nada se cobra sozinho.** Cada período é
  uma cobrança avulsa na Asaas; a assinatura no cartão da 2.1 deixa de
  existir.
- **Residentes e recém-formados:** continuam combinados diretamente, pelo
  formulário de contato, sem mudança.
- **Quem aceitou a 1.x, a 2.0 ou a 2.1 continua nelas** (cláusula 2.4): o
  contrato de 12 meses delas não muda.

Abaixo, o texto atual (2.1) e uma sugestão de redação.

---

## 1. Quadro-resumo, linha PLANOS

**Hoje:**

> […] Nos planos pagos públicos, a vigência ordinária é de 12 meses;
> pagamento anual, semestral ou trimestral são modalidades de adimplemento
> desse mesmo período, não prazos contratuais diferentes.

**Sugestão:**

> […] Nos planos pagos públicos, o CONTRATANTE escolhe o período de
> vigência — anual (12 meses), semestral (6 meses) ou trimestral (3 meses) —,
> cada um pago integralmente no início, sem renovação automática.

## 2. Cláusula 3.1 e 3.2 (vigência e renovação)

**Hoje (3.1):**

> 3.1. Os planos pagos padronizados têm vigência de 12 meses,
> independentemente do parcelamento anual, semestral ou trimestral. […]

**Sugestão (3.1):**

> 3.1. Os planos pagos padronizados têm a vigência do período escolhido na
> contratação ou na renovação: 12, 6 ou 3 meses, contados do aceite ou do
> fim do período anterior. Planos personalizados seguem proposta expressa.
> O plano gratuito tem duração indeterminada, sujeito às regras de
> continuidade e encerramento.

**Sugestão (3.2, substitui a atual):**

> 3.2. Não há renovação automática. Com antecedência mínima de 15 dias do
> fim do período, a PRONTDOC avisará o CONTRATANTE no aplicativo e por
> e-mail. A renovação ocorre por ato do CONTRATANTE, que escolhe o novo
> período e efetua o pagamento pelo próprio aplicativo, ao preço de tabela
> vigente na data, mantidas as demais condições desta versão; o novo
> período começa no dia seguinte ao fim do anterior, ou na data do
> pagamento, se o anterior já tiver terminado. Terminado o período sem
> renovação, aplicam-se as regras de continuidade e exportação, e qualquer
> restrição de uso será precedida de aviso ao contato administrativo.

## 3. Cláusula 4.3 e 4.4 (pagamento)

**Hoje (4.3, trecho):**

> […] Na modalidade semestral ou trimestral contratada pelo site, as
> parcelas são cobradas no cartão de crédito informado, na periodicidade
> escolhida, até o fim da vigência de 12 meses, sem renovação automática.
> […]

**Sugestão (4.3, trecho):**

> […] Pelo site e pelo aplicativo, cada período é pago integralmente de uma
> vez, por PIX ou cartão de crédito, sem armazenamento do cartão para
> cobranças futuras. […]

**Hoje (4.4):**

> 4.4. O prazo de 12 meses representa obrigação contratual única, podendo
> ser quitada em uma, duas ou quatro parcelas segundo a oferta. O valor
> mensal exibido no site representa equivalência econômica e não cria
> assinatura mensal autônoma.

**Sugestão (4.4):**

> 4.4. Cada período contratado ou renovado representa obrigação única,
> quitada no início do período. O valor mensal exibido no site representa
> equivalência econômica e não cria assinatura mensal autônoma.

## 4. Cláusula 13.2 (encerramento)

**Hoje (trecho):**

> […] não haverá restituição automática do período anual contratado […]. Se
> o pagamento for parcelado, a exigibilidade das parcelas vincendas
> dependerá da validade e proporcionalidade da obrigação anual no caso
> concreto.

**Sugestão (trecho):**

> […] não haverá restituição automática do período contratado em curso […].

(A frase das parcelas sai: não há mais parcela.)

## 5. Anexo II, linha da Asaas

**Hoje:** "[…] e cobrança das parcelas semestrais ou trimestrais"

**Sugestão:** "[…] e das renovações feitas pelo aplicativo"

## 6. A conferir com ela

1. **A renovação dispensa novo aceite?** A sugestão da 3.2 trata o
   pagamento da renovação como ato do CONTRATANTE dentro da mesma versão do
   contrato, ao preço de tabela do dia. O sistema registra quem clicou, o
   período, o valor e a data (`contratacao.Vigencia` e a trilha). Se ela
   preferir um novo aceite a cada renovação, o sistema pode pedir a caixa
   "li e aceito" na tela de renovar.
2. **Arrependimento na renovação (13.1).** Os sete dias valem "desde o
   aceite". Valem também a cada renovação paga pelo aplicativo?
3. **Reajuste (4.5).** Com o preço de tabela do dia na renovação, a regra de
   "a cada 12 meses pelo IPCA" ainda faz sentido para o trimestral e o
   semestral, ou basta a informação prévia do preço na tela de renovar?
4. **Aviso de 15 dias.** A 3.3 (não renovação pela PRONTDOC) fala em 30
   dias. Os 15 dias do aviso ao CONTRATANTE bastam, já que a renovação é
   dele?
5. **Título e data** passam a 2.2; o Aviso de Privacidade não muda.

## Depois da conferência

1. O arquivo dela entra como `tenancy/contrato/contrato-2.2.md`, e
   `tenancy/contract.py::VERSAO` passa a `'2.2'`; `check_contrato` é
   atualizado para a 2.2.
2. A branch `vigencia-por-periodo` é mesclada e publicada (1.47).
3. No console (`/instalacao/contratacao/`), registram-se os períodos das
   clínicas pagantes anteriores à 1.47, que não ganham período por
   migração.
4. Liga-se o checkout no console, que agora exige a 2.2.

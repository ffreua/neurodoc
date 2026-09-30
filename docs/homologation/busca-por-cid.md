# Buscar paciente por diagnóstico (CID)

**Roteiro:** `checks/check_por_cid.py` · **Módulo:** `clinical/por_cid.py` ·
**Tela:** `/app/clinical/por-cid/` — barra lateral, **Buscar por CID**

"Chegou droga nova para esclerose múltipla, quantos pacientes meus se
beneficiariam?" "Preciso revisar todo mundo com epilepsia em uso de
valproato." Eram perguntas que só a memória respondia, e memória de
carteira de mil pacientes não existe.

---

## 1. A decisão que define o recurso: onde a tela mora

**Em `/app/clinical/`, exigindo `READ_CLINICAL` — e não na lista de
pacientes.**

A lista de pacientes do menu administrativo exige `PATIENT_ADMIN`, que os
**quatro** papéis têm, e é certo que tenham: nome, telefone e convênio são
trabalho de recepção. Diagnóstico não é.

Acrescentar um filtro por CID àquela lista custaria uma linha de código, e
entregaria a qualquer pessoa com acesso à agenda a resposta para "quem
aqui tem B24". A separação **é** o recurso; o resto é busca.

A primeira seção do roteiro é essa: a secretária recebe recusa, o gestor
sem papel médico também, o médico entra. Vale mais que todas as outras
asserções somadas.

`clinical.views.TenantScopedView` deriva a capacidade do método HTTP, e por
isso a view é `GET`: a busca não altera nada, e um POST aqui passaria a
exigir `WRITE_CLINICAL` sem que ninguém entendesse por quê.

## 2. O refutado não conta — e filtrar por certeza não basta

`DiagnosisCertainty.REFUTED` é o médico dizendo "investiguei e não é".

O caso que quebra a implementação ingênua: a hipótese é levantada numa
consulta e descartada na seguinte. O registro antigo **continua no
prontuário** dizendo "suspeita" — e uma busca que olhasse cada linha
isoladamente devolveria o paciente como se ele tivesse a doença.

Por isso o que vale é a **última palavra sobre aquele código, por
paciente** (`_ultima_palavra`). O erro contrário sairia caro: um convite
para estudo de esclerose múltipla endereçado a quem foi informado de que
não tem.

A recíproca também vale, e o roteiro a cobra: **refutada antes, confirmada
depois — conta**.

| Leitura | O que devolve |
| --- | --- |
| **Confirmadas e suspeitas** (padrão) | Quem tem, ou pode ter, a doença |
| Só confirmadas | Fecha na certeza |
| Refutadas | De quem se suspeitou e se descartou — atrás de escolha explícita, com a tela dizendo o que significa |

A tela mostra o critério no cabeçalho do resultado: *"vale a última
anotação sobre cada código: quem teve a hipótese afastada depois não
aparece aqui"*. Sem isso, quem procura conclui que faltou gente e procura
de novo por outro caminho.

## 3. Os três caminhos da busca

Um só não basta, e o roteiro cobra os três:

1. **Pelo código, por prefixo.** "G40" traz G40.0, G40.1 e G40.2 — é assim
   que se pergunta "quantos epilépticos eu tenho". "G40.2" traz só aquele.
   Sem o prefixo, a tela precisaria de um botão "incluir subcategorias" que
   ninguém saberia quando marcar.
2. **Pelo texto gravado no prontuário.** Nem todo diagnóstico tem código do
   catálogo — o médico anota à mão. Uma busca só por código os perderia
   **em silêncio**, que é a pior forma de perder.
3. **Pelos códigos que o catálogo devolve para o termo.** É o que faz
   "esclerose multipla", sem acento, achar G35: reaproveita
   `catalogs.selectors.search_diagnosis_codes`, que já resolve acento,
   ponto e variação de token.

**O ponto é pontuação de apresentação.** "G40.2", "G402" e "g40.2" acham a
mesma coisa — quem digita rápido no teclado numérico não digita o ponto, e
o código gravado o tem.

**Mínimo de dois caracteres.** "G" devolveria o capítulo inteiro das
doenças do sistema nervoso, que não é resposta para pergunta nenhuma.

## 4. O que a lista não mostra

- **Arquivados**, por padrão — há uma caixa para incluí-los.
- **Pré-cadastro** (paciente que é só um telefonema com nome), sempre. A
  trava é explícita no código porque esta lista não pode passar a mostrar
  ficha que a lista de pacientes esconde.
- **Paciente de outra clínica.** O filtro por inquilino nasce na consulta,
  e o roteiro confere nos dois sentidos.

## 5. Como a consulta é feita

Quatro colunas via `values_list`, sem instanciar modelo: paciente, código,
certeza e data. É o suficiente para decidir quem entra, e o que torna a
varredura barata mesmo numa carteira grande.

Fazer isso em SQL exigiria função de janela e um subselect — e esconderia
justamente a regra que mais importa aqui, que é a da última palavra. A
paginação vem depois do agrupamento, e só a página corrente busca as
fichas de paciente.

## 6. O que o roteiro cobra

`docker compose exec app python manage.py rodar_roteiros por_cid`

| Seção | Asserções |
| --- | --- |
| 1 | **a fronteira**: secretária recusada, gestor recusado, médico entra, e a recusa não vaza nome |
| 2 | prefixo, ponto dispensável, minúscula, e G40.2 **não** trazendo G40.1 |
| 3 | suspeita→refutada fora; refutada→confirmada dentro; e o inverso na leitura de refutadas |
| 4 | o filtro entre confirmada e suspeita |
| 5 | acento dispensável pelo catálogo; diagnóstico anotado sem código achado pelo texto |
| 6 | arquivado fora por padrão e dentro quando se pede; pré-cadastro sempre fora |
| 7 | fronteira entre clínicas, nos dois sentidos |
| 8 | termo curto não varre o catálogo |
| 9 | a tela responde, lista, avisa sobre o refutado, e sem termo explica em vez de listar |

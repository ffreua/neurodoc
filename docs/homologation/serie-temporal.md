# Série temporal: a evolução em gráfico

**Roteiro:** `checks/check_evolucao.py` · **Módulo:** `clinical/series.py` ·
**Tela:** sobreposto na linha do tempo do paciente, botão **Evolução**

O prontuário já guardava tudo isto — a Barthel de três consultas atrás, a
creatinina de cinco laudos, o peso de cada visita. O que faltava era **ver
junto**: número em linha de tabela não mostra tendência, e tendência é o
que decide conduta em doença crônica.

---

## 1. Por que sobreposto, e não uma aba do atendimento

A tela de consulta já carrega história, exame com quase quatrocentos
itens, escalas, medicações e laudos. Acrescentar gráficos ali empurraria o
que se usa todo dia para baixo em favor do que se olha de vez em quando.

O sobreposto abre a partir da **linha do tempo do paciente**, que é onde a
pergunta "como ele vem evoluindo" nasce, e o conteúdo é **carregado sob
demanda**: a linha do tempo não pode pagar uma varredura de achados e
laudos para quem só queria ver a lista de consultas.

## 2. Gráfico é a forma mais econômica de mentir com dado verdadeiro

Os números estão todos certos e a leitura sai errada. Três decisões
respondem por isso, e o roteiro cobra as três.

### O eixo do tempo é proporcional à data real

Distribuir os pontos por igual é o modo mais fácil de desenhar e o mais
fácil de ler errado: transforma uma piora lenta em despencada e uma
recaída aguda em declínio gradual.

O roteiro mede: três aferições em D-370, D-360 e hoje. A distância
desenhada entre as duas últimas tem de ser **~36 vezes** a distância entre
as duas primeiras, e não igual.

### A escala pontuada usa o próprio domínio no eixo vertical

Uma Barthel que vai de 40 para 60 numa escala de 0 a 100 é o que é.
Esticar o eixo para caber só os dois valores faria a mesma variação ocupar
o gráfico inteiro — e num desenho pequeno, sem ninguém ler o eixo, é a
forma que fica na cabeça.

Quando `ExamScale.min_score` e `max_score` estão preenchidos, eles são o
eixo. O roteiro desenha a mesma série das duas formas e cobra que a
variação apareça **menor** no eixo completo.

### Escala incompleta não entra

O escore parcial de uma Barthel com quatro dos dez itens não é comparável
com o de uma respondida inteira. Plotar os dois na mesma linha inventa uma
piora que não houve. `value_json['complete'] is False` fica de fora.

## 3. O que o sistema não faz: interpretar

Não existe "melhorou" nem "piorou" na tela, e o roteiro tem uma asserção
contra essas palavras.

Subir é melhorar numa Barthel e numa Glasgow; é piorar numa NIHSS e numa
mRS. O sistema não sabe qual, e fingir que sabe seria inventar
interpretação clínica. A tela mostra **o número** e a variação crua no
período, com sinal e sem adjetivo.

A faixa de referência desenhada nos gráficos de laboratório vem do
**próprio laudo**, nunca de tabela interna — ela varia com laboratório,
método, idade e sexo. E o domínio do eixo inclui a faixa mesmo quando
todos os valores estão fora dela: senão a faixa cairia fora do desenho, e
o gráfico não mostraria justamente que o paciente está fora do normal.

## 4. As séries oferecidas

| Origem | De onde vem | Agrupada por |
| --- | --- | --- |
| Escalas pontuadas | `ExaminationFinding` com `item_code` `escala.*` | código da escala |
| Laboratório | `LabValue.numeric_value` | **analito + unidade** |
| Medidas | `patients.Observation` | tipo (peso, altura) |

**A unidade entra na chave do agrupamento.** Creatinina em mg/dL e em
µmol/L na mesma linha seria um salto de duas ordens de grandeza desenhado
como insuficiência renal. São duas séries, e o roteiro confere que nenhuma
delas mistura ordens de grandeza.

**Série com um ponto só não aparece.** É um número, e ele já está na tela
do atendimento; oferecer "Creatinina (1 medida)" encheria o seletor do que
não responde nada.

Atendimento em rascunho entra na linha, com o círculo vazado — o médico
abriu a ficha e registrou o valor; esconder seria perder o mais recente.

## 5. SVG escrito à mão, sem biblioteca

A aritmética inteira mora em `clinical/series.py::desenhar`, em Python.

Uma biblioteca de gráfico resolveria o desenho e tiraria justamente a
parte que mais importa — o eixo do tempo proporcional — do alcance da
verificação. Também penduraria uma tela clínica num script de terceiro, o
que a política de conteúdo (trabalho seguinte) agradece não ter.

O JavaScript da tela tem uma função: buscar o fragmento e trocar o miolo
do modal.

## 6. O que o roteiro cobra

`docker compose exec app python manage.py rodar_roteiros evolucao`

| Seção | Asserções |
| --- | --- |
| 1 | o eixo do tempo segue as datas (a razão ~36×, não 1×), e a série ocupa a largura toda |
| 2 | o domínio da escala vence o dos dados, e a variação desenha menor nele |
| 3 | escala incompleta fora da linha |
| 4 | unidades diferentes viram séries diferentes, nenhuma misturando ordens de grandeza |
| 5 | um ponto não aparece; dois aparecem |
| 6 | a faixa de referência é desenhada e cabe no eixo mesmo com tudo acima dela |
| 7 | série constante abre folga em vez de colar no eixo |
| 8 | fronteira entre clínicas |
| 9 | o fragmento responde e não é página inteira, série inexistente não quebra, **a tela não interpreta**, a linha do tempo tem o botão e o script, e a secretária não abre |

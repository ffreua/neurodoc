# Roteiro de exame estruturado (etapa 1 de 3)

Primeira das três etapas combinadas para tornar o prontuário o ponto mais
robusto do produto:

1. **motor de roteiro + roteiro de neurologia + tela do exame** — esta;
2. escalas funcionais com pontuação na tela (o modelo já existe, ver abaixo);
3. assinatura digital do prontuário na liberação da consulta.

## O problema

O exame neurológico era um catálogo **plano** de cerca de 50 itens, e o
único jeito de registrar um achado era digitar `sensory_superficial` e
`tactile` à mão em dois campos de texto livre. O roteiro de referência
(`docs/reference/roteiro-exame-neurologico.pdf`) é uma **árvore de quatro
eixos, ~400 itens e até cinco níveis** — nível de consciência → avaliação
descritiva → resposta motora → reflexos profundos → item. Um catálogo plano
não comporta isso, e era essa a origem da tela desconexa.

## Modelo

| Modelo | Papel |
| --- | --- |
| `ExamTemplate` | um roteiro: especialidade, versão, status, dono |
| `ExamNode` | a árvore (`parent`), com tipo de nó e tipo de entrada |
| `ExamScale` / `ExamScaleItem` | escala pontuável reutilizável, fora da árvore |

Três decisões estruturais, cada uma com um motivo:

- **Especialidade é dado, não código.** O roteiro inteiro é carregado de
  `exams/data/neurologia.yaml`. Outra especialidade é outro arquivo — sem
  alterar modelo, view ou template. É o "faça em blocos" pedido.
- **A clínica publica, o médico personaliza.** `owner_membership` nulo é o
  roteiro oficial da organização; um médico deriva o seu (`based_on`) e o
  ajusta sem afetar ninguém. `exams.selectors.resolve_template` devolve o
  pessoal quando existe e o da organização caso contrário.
- **O atendimento guarda roteiro e versão.** `ExaminationFinding` ganhou
  `template_node` e `template_version`. Reinstalar o roteiro **não
  sobrescreve**: cria a versão seguinte. Um registro de 2026 continua sendo
  lido com o roteiro de 2026 — requisito de prontuário, não conveniência.

### Onde o valor fica

O tipo de entrada decide a coluna, e isso está documentado no próprio
modelo para quem for ler um achado depois:

| `input_type` | Coluna |
| --- | --- |
| `state` | `state` (não avaliado / não informado / normal / alterado) |
| `number` | `numeric_value` (+ unidade em `value_json`) |
| `choice`, `multichoice`, `boolean`, `text` | `value_json`, com a versão legível em `qualifier` |
| escala | `value_json` com os eixos e o total; total também em `numeric_value` |

`state` só tem significado clínico em item do tipo `state`. Nos demais ele
permanece no padrão e quem lê deve olhar o valor — está dito no docstring
de `ExaminationFinding`.

## O roteiro carregado

```
clinica-a: Exame neurológico — roteiro padrão v1 (published) — 387 nós (75 group, 308 item, 4 scale)
```

Quatro eixos, transcritos das 18 páginas do PDF preservando a hierarquia:
nível de consciência (escalas + avaliação descritiva), cognitivo (testes
padronizados + sete domínios), somático (motricidade, sensibilidade,
coordenação, equilíbrio e marcha, sinais meningorradiculares, autonômico) e
nervos cranianos (I a XII, cada um com seus itens).

Onde o roteiro lista descritores explícitos, eles viraram **lista** em vez
de texto livre — "espontânea, após estímulo, sustentada, não sustentada,
ausente" é um `choice`; "atetose, balismo, coreia, distonia…" é um
`multichoice`; força é `number` com unidade MRC; reflexo profundo é
`choice` de ausente/reduzido/normal/vivo/exaltado.

Quatro escalas já vêm no arquivo `exams/data/escalas.yaml` com pontuação
explícita por opção (nunca inferida da ordem, senão a RASS, que vai de -5 a
+4, precisaria de exceção): **Glasgow**, **FOUR**, **RASS** e **MEEM**. A
etapa 2 amplia o catálogo e trabalha a tela de pontuação.

## Tela

A aba "Exame neurológico" mostra um acordeão por eixo. Dentro dele, a
árvore aninhada com o controle adequado a cada item, uma coluna por lado
quando o item é lateralizado, e um campo de observação por item.

**Cada eixo é um formulário próprio.** Com quase 400 itens, um único envio
obrigaria o médico a esperar a página inteira a cada salvamento; um eixo por
vez mantém o formulário pequeno. Como o navegador envia todos os campos do
eixo, esvaziar um item é o que o apaga — é assim que se desfaz um registro
feito por engano.

**Item deixado em "não avaliado" não gera linha nenhuma.** Isso é o que
sustenta a regra do PRD (RF-03.03) de que nada aparece como normal sem ter
sido examinado: a ausência de registro é a ausência de exame, não um
"normal" implícito.

O registro avulso pelo catálogo antigo continua disponível, recolhido, em
"registrar item fora do roteiro" — nenhum achado existente foi perdido nem
migrado.

## Verificação executada

| Verificação | Resultado |
| --- | --- |
| Carga do roteiro | 387 nós (75 grupos, 308 itens, 4 escalas) em cada um dos 5 tenants |
| Tela | 4 eixos em acordeão, 917 campos de exame renderizados, hierarquia correta (Motricidade → Manobras deficitárias → itens, com Esquerdo/Direito) |
| Gravação por tipo de entrada | `state` → normal; `number` → 4 MRC em `numeric_value`; `choice` → "Hipertonia elástica"; `boolean` → Presente; observação por lado; todos com `template_node` e versão |
| Escala | Glasgow 3+4+5 = **12**, com o detalhamento por eixo em `qualifier` e o total em `numeric_value` |
| Item em branco | não cria linha |
| Esvaziar e salvar | remove os 5 achados daquele eixo e **não toca** no outro eixo |
| Releitura | a árvore volta com os valores e a contagem por eixo |
| Regressão | 61 templates parseiam; 27 páginas renderizam; 26 telas com contexto sintético — 0 falhas |

## Pendências desta etapa

- **A tela do atendimento passou de 40 KB para 544 KB de HTML** com o
  roteiro inteiro no DOM. Funciona, mas é grande; se incomodar na prática,
  o caminho é carregar o eixo sob demanda. Fica registrado em vez de
  escondido.
- **Editor de roteiro pessoal ainda não existe.** O modelo suporta o fork
  (`based_on`, `owner_membership`) e a tela já escolhe o roteiro pessoal
  quando existe, mas a tela de edição entra junto com a área do
  responsável.
- Escalas ainda são registradas pelo formulário genérico do acordeão; a
  etapa 2 traz a tela dedicada, mais escalas (MRC, mRS, NIHSS, Ashworth,
  Hoehn & Yahr) e a interpretação do escore.

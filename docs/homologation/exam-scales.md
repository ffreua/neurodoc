# Escalas funcionais (etapa 2 de 3)

Segunda das três etapas. A etapa 1 criou o motor de roteiro; esta traz as
escalas com pontuação, interpretação e uma tela para aplicá-las. A etapa 3 é
a assinatura digital do prontuário.

## De onde vieram

A estrutura de item e opção foi transcrita das calculadoras publicadas em
`drfernandofreua.com.br/escalas`, e **cada escala foi conferida contra a
referência primária** citada no `source_note` do arquivo de dados.

A conferência não foi formalidade: comparar o teto declarado de cada escala
com a soma dos máximos dos seus itens encontrou três divergências, tratadas
uma a uma — ver "O que a conferência pegou".

## Motor de pontuação (`exams/scoring.py`)

Duas regras que a soma simples não cobre:

- **Itens em média.** A SARA avalia os quatro itens apendiculares nos dois
  lados e leva ao total a **média** dos lados, não a soma. Itens que
  compartilham `score_group` são agrupados assim. É o que faz a SARA fechar
  em 40 e não em 56.
- **Escala incompleta não vira escore fechado.** Faltando item, o total sai
  marcado como parcial (`16 — parcial (4/8 itens)`) e **nenhuma faixa de
  interpretação é atribuída**. Completar o item que faltou seria fabricar
  medida clínica.

`ExamScale` ganhou:

| Campo | Para quê |
| --- | --- |
| `bands` | faixas de interpretação (`0–10 normal`, `11–12 leve`…) como dado, porque mudam com a literatura |
| `higher_is_worse` | Barthel e ALSFRS-R sobem quando o paciente melhora; SARA e NIHSS, quando piora. Sem isso a tela não tem como dizer o que o número significa |
| `instructions` | como pontuar, ao lado do formulário |
| `ExamScaleItem.score_group` | itens que entram no total pela média |
| `ExamScaleItem.help_text` | instrução do item |

## As 14 escalas instaladas

| Código | Escala | Itens | Faixa | Sentido |
| --- | --- | --- | --- | --- |
| `glasgow` | Escala de coma de Glasgow | 3 | 3–15 | maior = melhor |
| `four` | FOUR | 4 | 0–16 | maior = melhor |
| `rass` | RASS | 1 | −5 a +4 | — |
| `meem` | Mini-exame do estado mental | 7 | 0–30 | maior = melhor |
| `epworth` | Sonolência de Epworth | 8 | 0–24 | maior = pior |
| `barthel` | Índice de Barthel | 10 | 0–100 | maior = melhor |
| `mrs` | Rankin modificada | 1 | 0–6 | maior = pior |
| `nihss` | NIHSS | 15 | 0–42 | maior = pior |
| `sara` | SARA | 12 campos / 8 itens | 0–40 | maior = pior |
| `alsfrs_r` | ALSFRS-R | 12 | 0–48 | maior = melhor |
| `mg_adl` | MG-ADL | 8 | 0–24 | maior = pior |
| `pfeffer` | Questionário de Pfeffer | 10 | 0–30 | maior = pior |
| `ashworth` | Ashworth modificada | 1 | 0–5 (grau 0 a 4, com 1+) | maior = pior |
| `hoehn_yahr` | Hoehn e Yahr | 1 | 0–5 | maior = pior |

Epworth, Barthel, NIHSS e Pfeffer têm faixas de interpretação; as demais
exibem o total sem classificar, porque a leitura depende de escolaridade,
contexto ou norma local — o sistema não arbitra isso.

## O que a conferência pegou

1. **SARA** — soma dos máximos 56, teto publicado 40. Não é erro: são os
   quatro itens bilaterais entrando pela média. Foi o que motivou o
   `score_group`, e o teste confirma que a SARA no máximo fecha exatamente
   em 40.
2. **Ashworth modificada** — a escala tem seis graus (0, 1, **1+**, 2, 3, 4).
   Como "1+" fica entre 1 e 2, o valor interno é ordinal de 0 a 5 e o grau
   publicado aparece no rótulo. O teto declarado foi corrigido de 4 para 5,
   com a explicação no próprio arquivo.
3. **BARS — retirada deste lote.** Os oito itens transcritos da calculadora
   somam 35, mas a BARS publicada (Schmahmann, 2009) declara outro máximo e
   tem outro conjunto de itens. Não dá para reconciliar sem saber qual é a
   intenção, e publicar uma escala de ataxia mal pontuada dentro de um
   prontuário é exatamente o tipo de erro silencioso que importa. Ficou em
   `exams/data/_bars_pendente.yaml.txt`, aguardando confirmação do conjunto
   de itens e da pontuação.

## Tela

Painel "Escalas funcionais" na aba do exame: um seletor lista as escalas da
organização e mostra uma por vez. Todas ficam no DOM (~110 campos, contra os
~900 do roteiro), então aplicar uma escala não custa uma ida ao servidor.

- **Total ao vivo** enquanto se pontua, com a faixa de interpretação e o
  aviso de "parcial" quando falta item. O cálculo do navegador segue a mesma
  regra do servidor, inclusive a média por grupo — mas **quem grava é o
  servidor**, e é o valor dele que entra no prontuário.
- **Reabre preenchida.** Escala já aplicada volta com os valores marcados e
  aparece com ✓ no seletor.
- **Enviar sem nenhum item marcado remove a escala** do atendimento — é como
  se desfaz uma aplicação equivocada.
- O nome da escala e a referência ficam visíveis junto ao formulário.

Escalas que pertencem a um ponto do roteiro (Glasgow, FOUR, RASS e MEEM
estão em "Nível de consciência" e "Cognitivo") continuam sendo pontuadas
lá; as demais entram pelo painel, no eixo "Escalas funcionais". O nome viaja
junto com o achado, então o registro continua legível mesmo se a escala for
desativada no cadastro depois.

## Verificação executada

| Verificação | Resultado |
| --- | --- |
| Teto de cada escala | 14 de 14 batem: teto calculado a partir dos itens (com média por grupo) igual ao declarado |
| Epworth | todos os itens em 2 → **16/24**, faixa "Sonolência excessiva acentuada" |
| Epworth parcial | 2 de 8 itens → total 6, marcada parcial, **sem faixa atribuída** |
| Barthel | máximo → **100**, "Independente"; tudo zero → **0**, "Dependência total" |
| NIHSS | tudo zero → **0**, "Sem sintomas" |
| SARA | marcha 4 + postura 3 + sentar 2 + fala 1, apendiculares 4/0 em cada lado → **18** (média por grupo); no máximo → **40** |
| Glasgow | 3+4+5 → **12** |
| ALSFRS-R | máximo → **48** |
| Gravação | grava com nota, resumo e JSON completo; reenviar vazio remove |
| Navegador | seletor com as 14 escalas, formulário abre, total ao vivo mostrou 16/24 com a faixa, gravou e apareceu no grid |
| Regressão | 62 templates parseiam; 27 páginas renderizam — 0 falhas |

## Ponto para você decidir

As escalas foram transcritas do seu site, que é seu. Mas embarcá-las num
produto multi-inquilino distribuído a outras clínicas é uma postura
diferente de mantê-las numa página de referência pessoal. A maior parte do
que entrou é de uso clínico livre com citação (Epworth, Barthel, mRS, NIHSS,
Glasgow, FOUR, RASS, Hoehn & Yahr, Ashworth, SARA, ALSFRS-R, MG-ADL,
Pfeffer), e a referência primária está registrada em cada uma. Duas famílias
que **não** entraram e que exigem licença antes de qualquer uso em produto:
**MDS-UPDRS** (permissão da Movement Disorder Society) e **PDQ-39** (licença
da Oxford University Innovation). O MoCA também exige registro/certificação.

Ficam fora deste lote, disponíveis para uma próxima rodada: ICARS, mFARS,
EDSS, CDR, Bateria Breve de Nitrini, NMDAS, SPRS-BR e Score ICE.

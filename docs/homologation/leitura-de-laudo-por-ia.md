# A leitura de laudo pela IA: forma se normaliza, conteúdo não

**Defeito encontrado em uso real, em 2026-10-05**, durante um
atendimento. O médico anexou um laudo laboratorial e pediu a leitura. A
resposta demorou, e a notificação trouxe isto:

```
Model output failed schema validation: 1 validation error for LabExtractionArtifact
unreadable_sections
  Input should be a valid string [type=string_type, input_value=[], input_type=list]
```

A pergunta que veio junto foi se valia a pena manter a interpretação de
exames pela IA. A resposta curta é que **o modelo não errou a leitura** —
o sistema jogou fora o trabalho dele.

## O que os dados mostraram

Os dois únicos jobs de `lab_extraction` que já rodaram na instalação, e
os dois falharam, por motivos diferentes e nenhum deles "leu errado":

| Data | Limite | Como terminou |
| --- | --- | --- |
| 2026-09-28 | 90 s | `Model call exceeded 90s` — prazo estourado |
| 2026-10-05 | 180 s | respondeu no prazo, e o sistema descartou |

No segundo, a mensagem diz **`1 validation error`**. Uma. Todo o resto
do objeto passou na validação, inclusive a lista de analitos — que é o
laudo lido. Foi descartado junto, porque a validação era tudo-ou-nada:
um campo fora de forma anulava o artefato inteiro.

O campo era `unreadable_sections` — aquele onde o modelo declara **o que
não conseguiu ler**. Voltou `[]`. O modelo disse "nada ficou ilegível",
em forma de lista.

## A causa, em três camadas

1. **O prompt não declarava o tipo.** No `LAB_EXTRACTION_PROMPT`,
   `analytes` vinha anotado como "lista de objetos com…" e
   `unreadable_sections` vinha sem anotação nenhuma. O nome é plural e a
   regra 5 mandava "nomear o que ficou de fora" — tudo nesse campo
   convidava a uma lista. Dos seis prompts, **os dois únicos sem tipos
   declarados eram os dois de leitura de documento**, que são exatamente
   os dois que nunca tiveram um sucesso.
2. **Não se pedia o esquema ao provedor.** O modelo recebia uma descrição
   em prosa e a conformidade era conferida depois, por Pydantic. A API
   compatível com OpenAI aceita `response_format: json_schema`, e não
   estávamos usando.
3. **A recusa era ilegível e descartável.** O texto cru do
   `ValidationError`, em inglês, ia direto para a linha do exame na tela
   do médico — contra a regra do repositório de que mensagem de erro é em
   português (§1 do `CLAUDE.md`; `check_idioma.py` não varre este
   caminho). E a resposta do modelo não ficava em lugar nenhum, de modo
   que nem era possível dizer se a leitura estava certa.

**A demora** era outra coisa: o modelo configurado é
`nvidia/nemotron-3-super-120b-a12b:free` no OpenRouter — a faixa
gratuita, que fica em fila atrás do tráfego pago. O PDF tinha camada de
texto (31.815 caracteres; o OCR nem rodou), então os 2 min 6 s foram a
chamada ao provedor. É característica do endpoint escolhido, não da
tarefa.

## A correção

### 1. A forma é normalizada; o conteúdo, não

`ai/schemas.py` ganhou `ArtifactModel`, base de todos os esquemas de
saída, com um `model_validator(mode='before')` que converte, **apenas em
campo declarado como `str`**:

| Veio | Vira | Por quê |
| --- | --- | --- |
| `[]`, `["a", "b"]` | `''`, `'a; b'` | o defeito relatado |
| `null` | `''` | `null` e `""` dizem a mesma coisa num campo de texto livre |
| `13.2`, `2026` | `'13.2'`, `'2026'` | data ou resultado escrito sem aspas |

E **não** converte lista de objetos: `str(dict)` poria um `repr` de
Python dentro do prontuário, e aí a diferença entre o que o laudo diz e
o que a tela mostra deixaria de ser cosmética. Isso segue reprovando.

A fronteira é a decisão inteira. **Forma** é como o modelo serializou —
não temos contrato executável sobre isso. **Conteúdo** é o que o
prontuário não pode deixar de cumprir. Os `field_validator` rodam em modo
`after`, isto é, depois da conversão: a faixa de referência vinda do
laudo, a recusa de probabilidade numérica e a recusa de marcador de
desidentificação continuam valendo integralmente, inclusive sobre o texto
que nasceu de uma lista. O roteiro cobra as duas metades.

Vale nos esquemas aninhados (`ExtractedAnalyte`, `ReportSection`) porque
é lá que o campo fora de forma costuma estar — dentro da lista, não ao
lado dela.

### 2. Os prompts declaram o tipo de cada campo

Nos dois prompts de documento, e a regra 5 passou a dizer, com todas as
letras, que o campo é uma string e que "nada ilegível" se escreve `""`.

O roteiro não confere os dois: confere **os seis**. O próximo prompt
escrito sem tipos seria o próximo defeito.

### 3. O esquema vai junto do pedido

`STRUCTURED_OUTPUT_TASKS` liga `response_format: json_schema` nas duas
tarefas de leitura de documento. Três escolhas dentro disso:

- **Só nessas duas.** São as que devolvem o objeto mais longo, as que
  mais erravam a forma e — o que decide — as duas que nunca tiveram um
  sucesso. Ligar de saída no resumo e no relatório, que funcionam hoje,
  arriscaria derrubá-los por um parâmetro.
- **`strict: False`.** O modo estrito da OpenAI exige
  `additionalProperties: false` em todo objeto e todos os campos em
  `required`; estes esquemas têm padrão e `Optional[float]`. Gerar uma
  variante estrita seria um segundo esquema para manter em sincronia com
  o primeiro, e esquema duplicado diverge.
- **Com recuo.** Se o provedor recusar o parâmetro, a chamada é repetida
  sem ele, com o tempo que sobrou. "Suporta `json_schema`" é propriedade
  do modelo, não do provedor: o mesmo OpenRouter atende modelo que aceita
  e modelo que devolve 400. Sem o recuo, ligar o esquema trocaria "às
  vezes sai torta" por "nunca sai".

  **Não é troca silenciosa de provedor** (RT-04): é o mesmo provedor, o
  mesmo modelo e o mesmo prompt, sem um parâmetro de formatação que ele
  disse não entender — e o que garante a saída continua sendo a
  validação do esquema, do nosso lado. O recuo é reconhecido por texto do
  erro, que é feio; a alternativa é não pedir esquema a ninguém, porque a
  API não diz de antemão se o modelo por trás suporta.

### 4. A recusa fica legível e diagnosticável

Duas coisas separadas, porque servem a duas pessoas:

- **O médico** lê, na linha do exame, "A resposta do modelo não tem o
  formato esperado." Em português, como manda o §1.
- **Quem conserta** abre o rascunho e encontra, num bloco fechado,
  `AIJob.failure_diagnostics`: qual campo, que tipo veio, que tipo se
  esperava, e a forma do objeto inteiro.

**O que esse campo não guarda é a decisão.** Guardar a resposta crua
resolveria o diagnóstico e criaria um depósito novo de conteúdo clínico,
com retenção, acesso e exportação próprios para pensar. Mas o que falta
quando uma extração é recusada não é o conteúdo — é a forma:
`unreadable_sections` veio `list[0]`, esperava-se `str`. Nenhuma linha
disso identifica ninguém, e por isso pode aparecer na tela e ir num
pedido de suporte. O `input` que o Pydantic põe em cada erro **é** o
valor recusado, e é descartado em vez de repassado; o roteiro confere
isso procurando os valores do laudo dentro do diagnóstico gravado.

## O que isto não resolve

- **A demora continua**, e ela é do endpoint `:free`. Trocar para um
  modelo pago é uma linha na tela de configuração da clínica, e é
  decisão de custo de quem opera — não de código.
- **A qualidade clínica da leitura segue por provar.** Esta entrega
  garante que uma leitura correta não é mais descartada por formatação.
  Se o que o modelo transcreve está certo é o que a próxima execução
  real vai dizer, e é para isso que o rascunho exige revisão médica
  antes de entrar no prontuário.

## Verificação

`checks/check_leitura_laudo.py`, em onze seções. As que importam:

1. **O defeito relatado, reproduzido** — o mesmo payload de 05/10,
   passando, com os analitos intactos.
4. **O que a conversão não pode engolir** — lista de objetos em campo de
   texto, `limitations` vazio e texto em `numeric_value` continuam
   reprovando.
5. **As guardas de conteúdo sobre o texto convertido** — probabilidade
   numérica e marcador de desidentificação recusados mesmo chegando
   dentro de uma lista. É a seção que impede a correção de virar um
   relaxamento geral.
6. **Varredura**: nenhum esquema de `ai.schemas` pode ficar fora de
   `ArtifactModel` — lista escrita à mão envelhece.
8. **O recuo**, com um provedor falso que recusa `response_format` e
   responde bem sem ele; e a contraprova, um erro 502 que **não** pode
   virar segunda chamada.
9. **O diagnóstico sem valor do laudo** — a asserção procura os valores
   de teste dentro do JSON gravado e reprova se achar algum.

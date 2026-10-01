# Relatório do paciente, escrito pela IA e assinado pelo médico

**Roteiro:** `checks/check_relatorio_ia.py` ·
**Módulos:** `ai/relatorio.py`, `ai/tools/clinical.py`, `ai/privacy_policy.py` ·
**Telas:** Prontuário do paciente → **Relatório com IA**

---

## 1. O problema

O paciente precisa de um relatório para a perícia do INSS. Escrevê-lo à mão
significa reler dez anos de prontuário atrás da data do diagnóstico, dos
exames que sustentam o quadro e da evolução — meia hora por relatório, com
o paciente esperando no balcão.

Quase tudo de que isso precisa já existia e não se falava: de um lado, o
motor de IA com revisão médica obrigatória; do outro, o documento médico
com numeração, assinatura PAdES, QR, verificação pública e a opção de
imprimir para assinar à caneta. **O trabalho foi a ponte.**

## 2. O fluxo

```
Prontuário do paciente → "Relatório com IA"
  ↓ finalidade + o que o relatório precisa conter
  ↓ worker: monta o contexto · desidentifica · chama o modelo · valida o esquema
  ↓ revisão: o texto numa caixa editável, com o recorte ao lado
  ↓ aprovar  →  RASCUNHO de relatório (documents)
  ↓ assinar digitalmente  ou  imprimir e assinar à caneta
```

**O aprovar não emite nada.** Ele produz um rascunho que entra no caminho
que já existia. Não é capricho: está escrito em `ai/review.py` desde antes
desta funcionalidade, e é o que mantém o médico como *autor* do documento
e não como revisor de um documento que a IA emitiu.

## 3. As cinco decisões

### 3-A. A identificação nunca chega ao modelo

O contexto vai desidentificado, como todo o resto da IA aqui. Nome, CPF e
data de nascimento são impressos pelo sistema no cabeçalho do PDF, que os
lê da ficha. A IA nunca precisa vê-los.

**A consequência não é óbvia, e é o defeito mais embaraçoso que este
recurso podia produzir.** O prontuário chega ao modelo com o nome trocado
por `[PACIENTE]`. Um rascunho que repita o marcador viraria, sem mais
nenhuma barreira, um relatório entregue na perícia dizendo *"[PACIENTE]
evoluiu com hemiparesia"*.

Reinserir o nome por substituição cega seria pior — erraria em "a mãe do
paciente", "o filho relata". A solução é instruir e conferir:

| Camada | Onde |
| --- | --- |
| O prompt proíbe o marcador e manda escrever "o paciente" | `ai/graphs.py::REPORT_PROMPT`, regra 2 |
| O esquema recusa o artefato que trouxer marcador | `ai/schemas.py::_reject_deidentification_markers` |
| A aprovação recusa o que o médico colar | `ai/views.py::RelatorioAprovarView` |

A guarda do esquema roda **antes de o artefato existir**: um rascunho
gravado é um rascunho que alguém pode aprovar sem reparar, e a tela de
revisão é exatamente onde a vista cansada passa batido.

### 3-B. Vale a última palavra sobre cada diagnóstico

Um código confirmado em março e refutado em agosto **não é diagnóstico do
paciente**. Listá-lo num relatório afirmaria doença que o próprio médico já
excluiu — num papel que vai para uma perícia.

É a mesma regra de `clinical/por_cid.py`, pelo mesmo motivo: lá ela evita
que a busca devolva quem não tem a doença; aqui, que o papel diga que tem.

E a data que o relatório precisa é a do registro **mais antigo** — "desde
quando" é a pergunta do perito. A do registro mais recente diz quando se
falou do assunto pela última vez, que é outra coisa.

O refutado não some: volta separado, porque o que foi investigado e
afastado também é informação clínica. Quem decide se cabe no relatório é o
médico.

### 3-C. A trava de privacidade passou a ter uma porta

`ai/privacy_policy.py` recusa o job quando encontra marcador de doença rara
ou consanguinidade confirmada. É uma trava *fail-closed* deliberada, e ela
nasceu para o que sai dali como **análise** — resumo, apoio diagnóstico —,
onde reidentificar alguém por combinação de dados raros é risco sem
contrapartida.

**O relatório é outro caso.** É o próprio paciente pedindo um documento
sobre si, para levar na mão. E, em neurologia, quem vai ao INSS é com
frequência exatamente quem tem doença rara: recusar significaria negar o
documento a quem mais precisa dele.

A decisão foi **avisar, não liberar**: a tela mostra qual marcador foi
encontrado, explica por que a trava existe, e o médico confirma. A
confirmação entra na trilha (`ai.privacy_risk_confirmed`) com nome e hora,
**antes** de o job ser enfileirado.

O que não mudou: a trava segue fechada por padrão, segue valendo inteira
para as demais tarefas, e nenhuma delas tem como passar a confirmação.

### 3-D. O recorte é declarado antes de assinar

Até 20 atendimentos (`ai/tools/clinical.MAX_ENCOUNTERS`, e não uma
constante própria — duas constantes para o mesmo limite divergem na
primeira vez que alguém mexe numa delas).

Quando sobra coisa de fora, a tela diz quanto e desde quando, **antes** de
gerar e de novo na revisão, e o recorte fica gravado junto com o artefato.
Um relatório construído sobre os vinte atendimentos mais recentes de um
paciente que tem sessenta é um documento legítimo — desde que quem assina
saiba disso. Daqui a um ano, a pergunta sobre um relatório assinado vai ser
exatamente essa.

### 3-E. Mesma prateleira, etiqueta diferente

O documento gerado **não** vai para um repositório separado. Fica na lista
dos outros, com a etiqueta `content_snapshot['ai_artifact_id']`.

Separá-los custaria numeração, assinatura, QR, verificação pública,
retificação e arquivo morto — produziria documentos de segunda classe. A
etiqueta é também a trilha: dado um relatório, chega-se ao rascunho que a
IA escreveu, ao pedido que o originou e a quem o aprovou.

O documento nasce **sem atendimento** (`encounter=None`, que
`MedicalDocument` já admitia): o relatório é sobre o histórico, não sobre
uma consulta. Amarrá-lo à última consulta diria no papel que saiu dali.

## 4. As finalidades

Não são rótulo: cada uma carrega as seções que aquele destinatário espera.
O mesmo prontuário responde ao perito, à operadora e ao colega em ordens
diferentes.

| Código | Destinatário |
| --- | --- |
| `inss` | Perito do INSS — diagnóstico com data, evolução, exames, repercussão funcional, prognóstico |
| `escola_trabalho` | Escola ou empregador — sem detalhe clínico, em termos do que o paciente precisa |
| `plano_saude` | Auditoria médica — o que já foi tentado e com que resultado |
| `outro_medico` | Colega — o raciocínio, o que foi afastado e por quê |
| `livre` | Sem modelo |

Moram em código pelo mesmo motivo dos planos e do contrato: mudá-las é um
commit com autor e data. **São um ponto de partida do médico** — quem sabe
o que o perito procura é ele.

Em todas, o prompt proíbe concluir sobre incapacidade, aptidão, direito a
benefício ou cobertura: o relatório descreve o quadro; quem decide é quem
recebe.

## 5. Quem pode

**`CLINICAL_AI` e `ISSUE_DOCUMENT`, as duas.** A primeira porque lê o
prontuário inteiro e manda o conteúdo ao provedor; a segunda porque o
produto é um documento médico que alguém vai assinar, e a responsabilidade
é de quem assina.

A secretária tem a segunda e não a primeira; o gestor não tem nenhuma. Só
`CLINICAL_AI` abriria a geração a quem não emite documento, e o rascunho
ficaria pendurado esperando um médico que não pediu nada.

Vale também o plano: a IA clínica é do Completo e do Personalizado.

## 6. O que o roteiro cobra

`rodar_roteiros relatorio_ia`

| Seção | Asserções |
| --- | --- |
| 1 | marcador no corpo e no título é recusado pelo esquema; texto limpo passa |
| 2 | nome e CPF não entram no contexto; nome escrito no texto é removido antes do envio |
| 3 | o refutado sai dos vigentes e volta separado; a data é a do registro mais antigo |
| 4 | pedidos diferentes geram jobs diferentes; o mesmo pedido não duplica |
| 5 | a trava bloqueia por padrão, diz qual marcador, e só a confirmação abre |
| 6 | paciente curto cobre tudo; paciente longo declara o que ficou de fora |
| 7 | rascunho pendente não vira documento; aprovado vira **rascunho**, sem número, sem atendimento, etiquetado |
| 8 | **o texto editado na tela é o que vai para o documento**, não o original da IA |
| 9 | marcador colado pelo médico é recusado, e nenhum documento é criado |
| 10 | a secretária não abre; paciente de outra clínica dá 404 |
| 11 | pedido vazio não vira job |
| 12 | as finalidades estão completas; código desconhecido cai na livre |

Além disso, a verificação da verificação: cada guarda foi removida em
memória para confirmar que, sem ela, o defeito passaria. Um teste que não
falha com o defeito presente não é teste.

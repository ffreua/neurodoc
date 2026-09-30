# Declaração de comparecimento

**Roteiro:** `checks/check_declaracao.py` ·
**Módulo:** `scheduling/declaracao.py` ·
**Onde:** menu do horário na agenda e botão no balcão do dia

O paciente falta meio dia de serviço para consultar, e o empregador quer
prova. Até aqui isso saía escrito à mão num papel timbrado, ou não saía.

---

## 1. Por que a secretária emite — e por que isso não é lapso

Declaração de comparecimento e atestado médico são documentos diferentes,
e a diferença é quem pode assiná-los:

| | Afirma | Quem assina |
| --- | --- | --- |
| **Atestado** | incapacidade para o trabalho | médico — é juízo clínico, e responde por ele no CRM |
| **Declaração de comparecimento** | que a pessoa esteve aqui, das 14h às 16h30 | a clínica — é fato administrativo |

Quem registrou a chegada e a saída foi a recepção, e é a recepção que sabe.
Por isso a capacidade exigida é `SCHEDULE`, a mesma da agenda, e a
assinatura no papel é **da clínica**, não do médico.

## 2. O que o papel não carrega, e por quê

**Nada de diagnóstico, CID ou motivo da consulta.**

Ele vai para a mão do empregador. Informação de saúde é dado pessoal
sensível (LGPD art. 5º, II), e uma declaração que dissesse "para avaliação
de epilepsia" entregaria ao patrão exatamente o que a lei protege — com o
próprio paciente carregando o papel, sem saber que carregava.

O timbre da clínica já diz o que ela é, e isso é inevitável. O resto não é.

O roteiro cria um paciente **com CID no prontuário** e depois varre o HTML
da declaração atrás do código e do texto do diagnóstico. Nenhum dos dois
pode aparecer.

## 3. O texto não dá margem à leitura errada

O corpo afirma presença e horário. Nada de "atestamos", "afastamento",
"repouso", "apto" ou "inapto" — o roteiro tem asserção contra essas
palavras.

E o rodapé fecha a porta com todas as letras:

> Este documento declara exclusivamente o comparecimento e a permanência
> acima, para fins de justificativa de ausência. **Não constitui atestado
> médico** e não atesta incapacidade para o trabalho ou para qualquer outra
> atividade. Por proteção ao titular, não contém diagnóstico, código de
> doença nem o motivo do atendimento.

Sem isso, um departamento pessoal apressado lê a folha como abono de falta
— e não é isso que ela diz.

## 4. Ver não é emitir

| Método | O que faz |
| --- | --- |
| `GET` | mostra a folha com os horários do agendamento, para conferir e corrigir. **Não registra nada** |
| `POST` | é o "emitir": grava o ato na trilha e devolve a folha pedindo impressão |

A separação existe por dois motivos concretos: ajustar o horário três vezes
não pode deixar três emissões registradas, e atualizar a página depois de
imprimir não pode emitir de novo.

## 5. O arquivo não fica; o ato fica

Não há PDF armazenado — o papel se imprime e acabou, que foi o que se
pediu e é o certo.

Mas a **emissão** entra na trilha de auditoria
(`scheduling.attendance_statement_issued`) com data, entrada e saída
declaradas. "A clínica me deu um papel dizendo que saí às 18h" é conversa
que existe, e quando ela acontece alguém precisa saber o que foi emitido.
Registrar o ato custa uma linha; não registrar custa a palavra de alguém
contra a de outro.

O metadado da trilha **não** carrega conteúdo clínico, pelo mesmo motivo
que o papel não carrega.

A trilha é imutável, inclusive para os roteiros: o usuário da aplicação não
tem `DELETE` em `audit_auditevent`, e a limpeza do roteiro não tenta. As
linhas ficam apontando para agendamentos que já não existem, que é o
comportamento correto de um registro imutável.

## 6. Os horários

O padrão vem do agendamento — é o que a secretária confirma nove vezes em
dez. Quando o paciente chegou adiantado ou o atendimento passou da hora,
ela corrige, e **o que ela digitou vence a grade**: quem viu a pessoa
entrar e sair foi ela.

- Hora malformada cai no padrão, em vez de virar erro 500 ou, pior, sair
  impressa como `None` num papel que vai para o empregador.
- A **duração** sai calculada ("1h30", "40 minutos") porque é o número que
  o departamento pessoal usa, e obrigá-lo a subtrair dois horários é
  convidar a conta errada.
- **Saída antes da entrada não imprime.** A tela avisa e o ato não é
  registrado: papel dizendo "das 16h às 14h" chegaria ao RH como erro da
  clínica.

## 7. O acompanhante

Campo opcional. Existe porque em neurologia ele é a regra, não a exceção:
quem falta ao serviço para trazer o paciente é ele, e é ele que precisa do
papel. Em branco, a frase não aparece.

## 8. Impressão sem script embutido

O gatilho é um atributo no `<body>`, posto pelo servidor só na resposta do
`POST`, lido por um arquivo estático (`static/scheduling/declaracao.js`).

Não é `onclick` nem `<script>` inline de propósito: a política de conteúdo
recusa script embutido, e uma tela que imprime é justamente a que ninguém
testa de novo depois.

## 9. O que o roteiro cobra

`docker compose exec app python manage.py rodar_roteiros declaracao`

| Seção | Asserções |
| --- | --- |
| 1 | horários do agendamento como padrão, correção manual vencendo, hora malformada, duração legível, inversão sinalizada |
| 2 | **o CID e o texto do diagnóstico não aparecem**; nome, CPF e médico aparecem |
| 3 | título, rodapé negando atestado e incapacidade, e a ausência de linguagem de atestado |
| 4 | GET não registra, POST registra uma vez, só o POST pede impressão |
| 5 | horário invertido: avisa, não imprime, não registra |
| 6 | acompanhante opcional |
| 7 | fronteira entre clínicas (404 no agendamento alheio) |
| 8 | as duas portas: balcão do dia e menu do horário na agenda |

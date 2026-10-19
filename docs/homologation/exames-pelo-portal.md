# Laudos de exame enviados pelo paciente no portal (1.16)

O portal de solicitações recebia só pedidos: receita, relatório e pedido
de exame. O resultado do exame chegava pelo WhatsApp da recepção ou no
papel, na consulta. A partir da 1.16, o paciente anexa os laudos em PDF e
eles entram direto no prontuário dele.

## O que o paciente vê

`/solicitacoes/<clínica>/exames/`, depois da mesma identificação dos
pedidos (CPF e data de nascimento). O caminho aparece:

- no topo da tela de solicitação ("Já fez exames?");
- na tela que recusa o pedido por consulta antiga (janela de 180 dias).

A tela abre com um **aviso vermelho**, antes do formulário: anexar
**apenas laudos de exames e resultados finais**, nada de pedido médico,
receita, foto ou documento pessoal; **somente PDF**, até **5 arquivos por
envio**, **3 MB** cada.

Para cada arquivo, o paciente informa:

| Campo | Regra |
| --- | --- |
| Qual exame | Lista fechada (ressonância, tomografia, eletroneuromiografia, eletroencefalograma, laboratoriais, líquor, doppler/ultrassom, polissonografia, potencial evocado, avaliação neuropsicológica, raio-X) ou **Outro**, com o nome escrito |
| Data de realização | Obrigatória; não aceita data futura nem anterior a 1950 |
| Onde foi realizado | Obrigatório: laboratório, clínica ou profissional |

Quem preenche pode ser o próprio paciente ou um familiar, cuidador ou
responsável, com o nome registrado.

## O que o médico vê

- **Aviso no sino**, para quem tem acesso clínico (a secretária não é
  avisada), levando à lista de anexos do paciente.
- **Alerta vermelho no topo do prontuário**: na linha do tempo, nos dois
  tipos de atendimento e na ficha do paciente. Ele lista cada exame com
  tipo, data, local e quando foi enviado, com o link para baixar quando o
  antivírus já liberou. O alerta some quando alguém com acesso clínico
  aperta **Ciente**, que fica registrado com quem e quando.
- **Na lista de anexos**, o envio do portal aparece pelo tipo do exame
  (e não pelo nome do arquivo), com data e local de realização, a marca
  "Enviado pelo paciente" e "Novo" até o ciente.

A secretária vê a linha, a data e a marca "Enviado pelo paciente", mas não
qual exame é, como em qualquer anexo clínico.

## Decisões

- **Direto ao prontuário, sem fila de aprovação.** O pedido de receita
  passa pela fila porque é ato médico. O laudo é fato que o paciente já
  tem; o que impede que ele entre calado é o alerta.
- **A janela de retorno não se aplica ao envio.** Ela barra pedido de ato
  médico (CEM, art. 37). Quem volta depois de muito tempo é justamente
  quem mais traz exame novo. Para isso, a identificação de quem é barrado
  **não é mais descartada**: o pedido continua recusado nas três portas, e
  a mesma sessão abre o envio de exames. Quem foi barrado e volta à
  primeira tela vê o formulário de identificação, para poder identificar
  outra pessoa (a mãe com dois filhos).
- **Tudo ou nada.** Um arquivo ruim recusa o envio inteiro, e a mensagem
  diz qual linha corrigir. Se gravar os bons e recusar o ruim, o paciente
  manda de novo e o médico recebe em dobro.
- **Os arquivos seguem o caminho de qualquer anexo clínico:** quarentena,
  antivírus no worker, guarda de vinte anos e cota da clínica. Cota
  esgotada aparece ao paciente como "não foi possível receber agora", sem
  dizer quanto a clínica usa.
- **O nome gravado é gerado** (`ressonancia-magnetica_2026-10-17_1.pdf`).
  O nome original fica só de registro, porque costuma ter acento e
  parêntese, que o validador de nome recusa.
- **`Attachment.uploaded_by` passou a aceitar nulo.** Quem envia pelo
  portal não tem conta, e inventar um usuário dono do arquivo poria na
  trilha alguém que nunca o tocou. A migração `documents/0008` é só de
  expansão.
- **Limite por endereço:** 6 envios por hora (até 30 arquivos).

## Verificação

`checks/check_exames_do_portal.py`, 76 asserções:

- a janela de retorno barra o pedido e não o laudo;
- o aviso vermelho vem antes do formulário, com os limites;
- onze recusas sem gravar nada: sem arquivo, linha sem arquivo, texto
  renomeado para `.pdf`, extensão errada, mais de 3 MB, data futura, sem
  data, sem local, tipo inválido, "Outro" sem nome, seis arquivos;
- tudo ou nada;
- o formulário aberto para um paciente não grava na ficha de outro;
- o envio certo: ficha, clínica, clínico, sem autor de conta, data do
  documento, quarentena, nome gerado, antivírus pedido ao worker;
- o médico avisado e a secretária não;
- o alerta para o médico e não para a secretária;
- o ciente: a secretária não marca, outra clínica não marca, `GET` não
  marca, `next` de fora do domínio é ignorado, e o alerta some;
- portal desligado responde 404;
- o limite por endereço responde 429.

Também na 1.16, a coluna **Anexado em** antes do nome na lista de anexos
(`documents/list.html` e `documents/patient_documents.html`).

## 1.16.1: o primeiro envio real

O primeiro envio em produção foi recusado pelo token CSRF: o formulário
estava aberto antes de um login no mesmo navegador, e o login troca o
token. A identificação do portal sobreviveu ao login. As correções e a
linha do tempo estão em `docs/releases/1.16.1-o-primeiro-envio-real.md`.

**A lição para quem escreve roteiro de formulário público:** o
`Client()` do Django dispensa o CSRF. Formulário que o paciente envia se
testa também com `Client(enforce_csrf_checks=True)`, como fazem as seções
12 a 15 de `check_exames_do_portal.py`.

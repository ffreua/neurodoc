# LME — laudo do medicamento de alto custo (CEAF)

Decisões e fontes da emissão da LME (Laudo de Solicitação, Avaliação e
Autorização de Medicamento(s) do Componente Especializado da Assistência
Farmacêutica). Implantada em 2026-11-25 (NeuroDoc 1.60 / ProntDoc 1.14.0).

## O que é

O formulário com que o paciente pede, na farmácia do Estado, o
medicamento do CEAF ("alto custo"). O sistema preenche o **próprio modelo
publicado pelo Ministério da Saúde** com os dados do paciente, os
medicamentos e as quantidades, e o médico completa o que é dele (CID,
anamnese, tratamento prévio, atestado de capacidade).

## Decisões

1. **Sempre impressa, assinada à mão e carimbada** (decisão do titular,
   2026-11-25). A LME não é assinada digitalmente: a tela não oferece a
   assinatura, `issuance._sign_and_issue` a recusa (motivo na trilha:
   `lme_somente_impressa`) e o caminho é "Emitir para assinar e carimbar".
   Por isso não há QR nem envio por link — o envio ao paciente já é só do
   documento assinado digitalmente. Os campos 17 (assinatura e carimbo do
   médico) e 23 (assinatura de quem preencheu) ficam em branco para a
   caneta. (Uma nota técnica da CIB/SP de 2023 admite LME nato-digital com
   assinatura ICP-Brasil; a escolha aqui é o papel, que toda farmácia aceita.)

2. **O modelo oficial, preenchido — nunca um redesenho.** O arquivo é
   `documents/modelos/lme_ministerio_2026-03.pdf`, baixado em 2026-11-25 de
   `https://www.gov.br/saude/pt-br/composicao/sectics/daf/publicacoes/lme.pdf/@@download/file`
   (revisão de 13/03/2026), travado por SHA-256 em `documents/lme.py`. O
   gerador tira os campos interativos e os botões do Acrobat e escreve os
   valores numa camada por cima, cada um no retângulo que o próprio modelo
   define. Fora da moldura entram só: no alto, o número do documento no
   sistema e a data; no pé, a linha "Para suporte… ceaf.daf@saude.gov.br"
   do modelo (que era um campo e sumiria); no rascunho, a tarja.

3. **Medicamento livre; a lista do modelo é só sugestão.** O modelo traz
   344 apresentações (revisão 2026-03); a tela as oferece ao digitar, mas
   aceita qualquer texto. A lista do Ministério muda e o médico sabe o que
   o protocolo cobre; travar na lista faria o sistema recusar o que a
   farmácia aceita.

4. **Texto que não cabe é recusado, não cortado.** Cada valor encolhe até
   6,5 pt para caber no campo (o medicamento e o diagnóstico em até duas
   linhas, a anamnese em várias); abaixo disso a tela recusa e pede para
   encurtar. Cortar entregaria à farmácia um laudo pela metade.

5. **Raça/cor e CNS do paciente ficam só na LME.** São dados que só este
   formulário pede, e raça/cor é dado pessoal sensível (LGPD, art. 5º, II):
   não se criou campo no cadastro de todo paciente. A próxima LME do mesmo
   paciente reaproveita o que a anterior registrou (sempre na mesma clínica).

6. **Preenchimento inicial**: nome, mãe e CPF do cadastro; peso e altura da
   ficha (altura convertida para cm); telefones e e-mail do contato do
   próprio paciente; CNS do médico e CNES da LME anterior **do mesmo médico
   na mesma clínica** (o CNES cai no do prestador TISS, se houver); CID-10
   da primeira hipótese do atendimento; "Nova LME a partir desta" copia a
   LME inteira (só do mesmo paciente e da mesma clínica) — é a renovação.

7. **Atestado de capacidade (item 13).** O próprio modelo prevê o
   responsável pelo paciente incapaz, que poderá realizar a solicitação; com
   "sim", o nome do responsável é obrigatório. A retirada por terceiro quando
   o paciente é capaz é tratada pela farmácia (em SP, a declaração
   autorizadora) e está fora desta fase.

## Atualização do modelo

Quando o Ministério publicar uma revisão: baixar o PDF novo, trocar o
arquivo e o `SHA256_MODELO`/`VERSAO_MODELO` no mesmo commit e rodar
`checks/check_lme.py` — ele falha se algum campo que o código usa sumir do
modelo (`lme.campos_que_faltam`) e confere a posição de cada valor. Cada
LME guarda em `modelo` a revisão em que saiu.

## Verificação

`checks/check_lme.py`: o modelo travado e completo; a validação (cada
obrigatório, CNES/CNS/CPF, CID-10, os "sim" sem complemento, quantidade,
sete linhas, texto que não cabe, medicamento fora da lista aceito); o PDF
sem campos nem botões, cada valor dentro do seu campo pela posição do
texto, as caixas marcadas; a assinatura digital recusada no servidor; o
papel com número e data de Brasília; as telas, botões, secretária, outra
clínica e "a partir desta".

# Prescrição: catálogo da CMED, emissão avulsa e o QR

> **Homologado na pilha local (2026-09-17).** Evidência de
> `checks/check_receitas.py` (12 seções, `EXIT=0`), da suíte inteira — 39
> roteiros, todos verdes — e de um Chrome de verdade, no portal público e
> na tela de receita.

## O que já existia

Boa parte do que se pediu estava de pé antes desta entrega, e vale
registrar para não parecer que foi feito agora: receita **simples** e de
**controle especial** (duas vias, Portaria SVS/MS 344/98, com recusa se
faltar endereço do paciente), pedido de exame, encaminhamento, relatório,
guarda no prontuário, assinatura PAdES e o logotipo da clínica no timbre
do PDF.

O que faltava era o catálogo de medicamentos, os pontos de entrada, e três
correções.

## O catálogo da CMED/Anvisa

26.242 apresentações, importadas da lista de conformidade publicada pela
Secretaria Executiva da CMED. Uma linha por **apresentação**, não por
medicamento — que é o que se quer numa receita, onde "500 mg comprimido
revestido, caixa com 20" é justamente a informação que falta na hora.

```bash
# no worker, que é quem alcança a internet
docker exec $(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) \
  python manage.py import_cmed --dry-run     # lê e conta, sem gravar
  python manage.py import_cmed               # importa e ativa
```

**As colunas são localizadas pelo nome, nunca pela posição.** A CMED
republica todo mês e já mudou a ordem das colunas de preço entre
publicações; um importador por índice leria laboratório na coluna da
substância e gravaria 26 mil linhas erradas sem falhar em nada. O
cabeçalho também não está numa linha fixa — as primeiras 41 são texto
explicativo, e o importador acha a linha por ser a primeira com mais de
vinte células preenchidas.

**Os preços não entram.** São 52 das 74 colunas, envelhecem a cada
publicação e ninguém prescreve por preço. Guardá-los transformaria um
catálogo clínico numa tabela de valores desatualizada que alguém acabaria
mostrando ao paciente.

**Uma publicação nova é sempre uma release nova**, pelo mesmo motivo do
CID-10: a receita emitida em março guarda o texto que o medicamento tinha
em março, e reescrever a linha antiga mudaria retroativamente o que foi
prescrito.

Descoberto importando: a substância de uma vacina pneumocócica lista todos
os sorotipos e chega a **1.419 caracteres**. O campo é `TextField` — um
teto escolhido a dedo seria um `value too long` numa publicação futura,
com a release pela metade.

## A tarja avisa, não decide

A planilha traz a coluna TARJA. Na lista de 09/2026: 13.602 vermelhas,
5.427 vermelhas sob restrição, 4.670 não informadas, 1.816 sem tarja e
**727 pretas**.

Escolher um item de tarja preta ou vermelha sob restrição numa receita
simples faz aparecer um aviso com dois botões: *trocar para controle
especial* e *dispensar*. **Quem troca é o médico.**

A alternativa — trocar o formato sozinho — foi recusada. A coluna TARJA é
atributo da lista de **preços** da Anvisa, não o enquadramento da Portaria
344/98 que vale para o receituário: ela acompanha o registro daquela
apresentação e pode divergir. Um sistema que trocasse o formato a partir
dela estaria transformando dado comercial em decisão clínica, e a decisão
é de quem assina.

`- (*)` da planilha vira `NAO_INFORMADA`, e não `SEM_TARJA`: é ausência de
classificação, e afirmar "sem tarja" a partir dela seria o sistema
inventando que o medicamento é isento de prescrição.

## O autocomplete, em três telas

Um componente só (`static/catalogs/medicamentos.js`), usado no portal
público do paciente, na receita do atendimento e na receita avulsa. Três
contextos diferentes — um sem sessão, dois dentro de `/app/` —, mas a
interação é a mesma, e três cópias divergiriam na primeira correção.

**O campo continua livre.** É ajuda para escrever, não seletor:
manipulado, fitoterápico e importado continuam sendo digitados à mão, e
quando a busca não acha nada a própria lista diz isso — "pode escrever à
mão, o campo aceita".

No portal, escolher preenche nome e apresentação em campos separados; na
receita, acrescenta uma linha ao texto da prescrição sem apagar o que já
estava escrito.

Desde 27/09/2026, a lista mostra somente **nome e concentração** — por
exemplo, `KEPPRA 250 mg` — e elimina opções repetidas que diferiam apenas
pelo tamanho da caixa. A apresentação CMED integral continua preservada no
catálogo; blister, material e quantidade não ocupam mais o autocomplete, e
o campo de dose do portal recebe somente a concentração.

O destino de cada campo é declarado no HTML por **seletor dentro do
grupo**, e não por id. O portal CLONA a linha de medicação para
acrescentar outra, e ids clonados se repetem: com `getElementById`, a
segunda linha passaria a preencher a dose da primeira. Conferido no
navegador — duas linhas, cada uma preenchendo a sua.

## Emitir a partir da ficha do paciente

`MedicalDocument.encounter` passou a ser opcional. A renovação de receita
pedida por telefone é o caso real do balcão, e exigir um atendimento
levava a abrir uma consulta que não houve só para poder imprimir —
consulta inventada no prontuário é pior do que documento sem consulta.

O paciente continua obrigatório. O formulário mostra **"sem atendimento
vinculado"** em destaque enquanto se digita: o risco de emitir para o
paciente errado é maior justamente quando não se veio do prontuário.

Ao tornar o campo opcional, um lugar quebrou — `pdf/common.py` montava a
data como `document.encounter.occurred_at` direto, e um documento sem
atendimento estourava `AttributeError` no meio de gerar o PDF, com o
rascunho já criado no banco e nenhum arquivo. Agora usa a data do
atendimento quando há um, e a da emissão quando não há.

## Emissão em papel, e o QR

**O QR passou a sair só em documento assinado digitalmente.** Antes saía
em qualquer PDF: o `validation_token` é atribuído já na criação do
rascunho, e a única condição era ele existir. Um QR no rascunho leva o
balconista da farmácia a conferir e receber "documento não emitido" — ou,
pior, a tratar o papel como conferido.

Isso abriu um buraco que precisou ser fechado: quem imprime para assinar à
caneta usava o rascunho, e o rascunho sai com **"RASCUNHO SEM VALIDADE"**
em vermelho. Entregar ao paciente uma receita que declara não valer é pior
do que não ter a funcionalidade.

Daí o terceiro estado: `ISSUED_ON_PAPER`. Ganha número e data como
qualquer documento, sai **sem** a tarja de rascunho e **sem** QR, e o
rodapé diz o que de fato vale ali: *"Documento emitido para assinatura de
próprio punho. Válido apenas com a assinatura e o carimbo do
profissional."*

## O que o roteiro conferiu

`checks/check_receitas.py`, 12 seções, `EXIT=0`:

- [x] release CMED ativa com 26.242 apresentações
- [x] busca acha por substância (`clonazepam`) e por nome comercial (`rivotril`)
- [x] a sugestão de controle especial bate com a tarja em 100% dos resultados; dipirona não sugere
- [x] termo de uma letra devolve vazio; `'; DROP TABLE --`, acentuação repetida e `%%%` não estouram
- [x] documento criado **sem atendimento**, com paciente e inquilino certos
- [x] rascunho: traz a tarja de rascunho, **não** traz QR nem bloco de verificação
- [x] papel: número atribuído, sem tarja de rascunho, diz que vale pela assinatura de próprio punho, **sem** QR
- [x] emitir em papel duas vezes é recusado (gastaria dois números para a mesma receita)
- [x] o timbre traz o nome da clínica, e o logotipo entra quando há um
- [x] endpoint autenticado responde; sem sessão, 302 para o login
- [x] endpoint do portal responde 200 com o portal publicado e **404** com ele desligado
- [x] controle especial continua exigindo endereço completo
- [x] a ficha do paciente oferece emitir, e o formulário traz a busca
- [x] paciente de outra clínica responde 404

O conteúdo do PDF é conferido extraindo o texto com `pypdf`. A primeira
versão do roteiro procurava a palavra nos bytes crus — o ReportLab comprime
os fluxos de texto, e `b'RASCUNHO' in pdf` dá `False` com a tarja impressa
na página. O roteiro passava dizendo que tinha conferido.

## Verificado no navegador

- [x] receita avulsa: digitar "clonazepam 2" traz 30 apresentações; escolher escreve a linha na prescrição, limpa a busca e **mantém o formato em simples**
- [x] o aviso aparece: *"Tarja preta na lista da CMED. Medicamentos assim costumam exigir Receituário de Controle Especial"*
- [x] "Trocar para controle especial" muda o formato e o aviso some
- [x] portal público: duas linhas de medicação, cada uma com o seu autocomplete, preenchendo os seus próprios campos

## Dois roteiros que estavam quebrados

**`check_g10` travava para sempre com o próprio lixo.** A limpeza apagava
os atendimentos que ele abre, com `delete()` direto. Uma execução
interrompida deixava um atendimento no banco; um roteiro posterior, que
pega "o primeiro atendimento do paciente", pendurava nele um achado de
exame; e a partir daí a limpeza falhava com `ProtectedError` em toda
execução futura — com uma mensagem que não diz nada sobre isso. Agora
apaga os achados antes.

**`check_g6` falhava só dentro da suíte.** A página pública de verificação
limita tentativas por IP na cache compartilhada, e os roteiros anteriores
que abrem `/verificar/` esgotavam a cota do `127.0.0.1`: este chegava com
**HTTP 429** em tudo e acusava quatro falhas que não existiam. Passava
sozinho e quebrava em conjunto — o pior tipo de roteiro, o que só falha
quando ninguém está olhando só para ele. Agora limpa a chave antes da
seção: o que ali se testa é a página, e quem testa o limitador é a seção
dele.

**E tinha uma asserção impossível.** Exigia que o nome do
paciente não aparecesse na página pública de verificação, comparando por
substring. A máscara de "Fernando F" é "Fernando F***", que **contém**
"Fernando F": bastava um paciente de sobrenome curto no banco para o
roteiro falhar para sempre, escondendo as falhas de verdade que ele testa.
A pergunta certa é se o nome aparece **fora** da máscara, e é essa que ele
faz agora.

## O que ficou de fora

- A CMED publica mensalmente e o nome do arquivo carrega a data; a URL
  padrão é ponto de partida e pode ser trocada por `--url`. Não há
  sincronização automática agendada como a da TUSS — fica para quando o
  endereço da publicação for estável.
- O medicamento escolhido entra na receita como texto. Não há vínculo do
  documento com a linha do catálogo, e portanto não há como perguntar
  depois "quantas receitas de clonazepam esta clínica emitiu". Seria outra
  entrega, com decisão de retenção envolvida.

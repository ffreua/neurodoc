# Fotografia do paciente

Cadastro e ficha do paciente passam a guardar um retrato. Serve à
identificação no balcão e, no cabeçalho do atendimento, a confirmar antes
de escrever que a nota está indo para a ficha certa — que é o erro que
nenhuma validação pega, porque os dois cadastros são válidos.

Evidências desta etapa: `checks/check_foto.py`, executado contra a pilha
Docker local com o banco de demonstração.

## Onde ela vive, e por que não é anexo

`patients/photo.py`, ao lado de `tenancy/branding.py` (o logotipo da
clínica) e **fora** de `documents.storage`. Anexo de prontuário passa por
quarentena, antivírus e cota do inquilino, e é assim que tem de ser: chega
de fora, do paciente ou de um exame externo. A fotografia é uma por
paciente, enviada por quem faz o cadastro, e substituir a anterior é o
comportamento certo. Pelo fluxo de anexo, cada troca de retrato viraria um
anexo novo no prontuário, e a ficha acumularia um histórico de fotos que
ninguém pediu.

Há uma diferença honesta em relação ao logotipo, e ela justifica repetir as
defesas em vez de afrouxá-las: o logotipo vem de quem administra a clínica,
e este retrato pode ter vindo do celular de um familiar. Por isso:

- o tipo é conferido pelos **bytes** (`magic`), não pela extensão nem pelo
  que o navegador declarou;
- só PNG, JPEG e WebP. SVG fica de fora pelo mesmo motivo do logotipo — é
  XML e executa script servido inline;
- 2 MB de limite, com o número da tela lido de `MAX_PHOTO_BYTES` em vez de
  escrito no template, para os dois não divergirem;
- quem serve o arquivo manda `X-Content-Type-Options: nosniff` e
  `Content-Security-Policy: default-src 'none'`, e `Cache-Control: private`
  — o retrato identifica um paciente e não pode cair em cache compartilhado.

A gravação é atômica (`os.replace` sobre um arquivo temporário): um envio
interrompido não deixa meia imagem no lugar do retrato que funcionava.

## Duas entradas, uma gravação

| Situação | Caminho | Por quê |
| --- | --- | --- |
| Paciente já cadastrado | `POST /app/patients/<id>/foto/`, formulário próprio | Efeito imediato, sem `row_version` e sem depender de o resto do cadastro estar válido |
| Cadastro novo | Campo no POST do cadastro, gravado depois do `save()` | Não existe paciente a que anexar o arquivo antes de ele existir |

As duas passam por `photo.store_photo`. Três decisões merecem registro:

**Trocar o retrato não é editar o cadastro.** O cadastro usa `row_version`
para recusar edição concorrente com 409. Fazer a foto passar por ali daria
conflito entre duas pessoas mexendo em coisas diferentes do mesmo paciente,
e obrigaria quem só quer atualizar o retrato a carregar a ficha inteira. A
gravação usa `update_fields` com os campos da foto, e o roteiro confere que
`row_version` não se move.

**O arquivo não sobrevive ao re-render, e a captura sim.** Quando o cadastro
volta com aviso de duplicidade ou erro de campo, o navegador esvazia todo
`<input type="file">`. A captura pela câmera vai num campo oculto (data
URL) e volta preenchida — verificado com um CPF duplicado de propósito. Para
o arquivo escolhido não há como: o bloco avisa na tela, em vez de o cadastro
ser salvo sem o retrato em silêncio.

**Arquivo inválido não grava paciente nenhum.** A validação acontece antes
de a transação abrir: descobrir que o "PNG" é um PDF renomeado depois de
gravar o paciente obrigaria a desfazer a gravação, e a alternativa — gravar
e engolir a foto — salvaria o cadastro sem retrato sem dizer nada. A
gravação no disco fica por último dentro da transação, porque disco não
entra em rollback.

## Consentimento — em papel, e a tela lembra

Decisão do produto (setembro/2026): a autorização do paciente para o uso da
imagem é colhida **em papel**, fora do sistema, e arquivada junto ao
prontuário. O sistema não guarda esse consentimento.

O que o sistema faz é não deixar esquecer: o bloco da fotografia traz um
aviso fixo, acima do campo de envio, pedindo o termo assinado pelo paciente
— ou pelo responsável legal, quando for menor — antes do envio. O aviso fica
ali, e não num rodapé, porque é ali que a pessoa está prestes a guardar a
imagem de alguém. `check_foto.py` confere que ele não sumiu da tela.

A trilha de auditoria registra `patients.patient_photo_updated` e
`patients.patient_photo_removed`, com mime e tamanho — nunca a imagem.

**Pendência explícita:** uma fotografia usada para identificar o paciente é
dado pessoal e, discutivelmente, biométrico (LGPD art. 5º, II). A base legal
entra em **P-06**, que segue aberta. Com dados sintéticos não há questão;
antes do piloto com paciente real, este recurso deve entrar na mesma revisão
de P-06, junto com o formato do termo em papel.

## Captura pela câmera

`static/patients/photo.js`. Botão "Usar a câmera" → `getUserMedia` →
`<canvas>` → JPEG de qualidade 0,85 no campo oculto, com prévia.

- **Reduz para 900 px de maior lado antes de gravar.** Uma webcam de 1080p
  gera um JPEG acima de 1 MB; sem a redução, a pessoa tiraria a foto, veria
  a prévia e só então receberia "a imagem passa de 2 MB", com a câmera já
  fechada.
- **Três erros nomeados**, porque um botão que não reage se lê como sistema
  quebrado: permissão negada (resolve-se no navegador), nenhuma câmera
  encontrada (não se resolve), e contexto não seguro — `getUserMedia` só
  existe em HTTPS ou localhost, e um acesso por IP na rede da clínica cai
  aqui. Em produção há HTTPS.
- **A câmera é desligada** ao capturar, ao fechar e ao sair da página. Sem o
  último, a luz do equipamento ficaria acesa depois de a pessoa navegar.
- Escolher um arquivo descarta a captura e vice-versa. A regra também está
  no servidor (a captura ganha quando as duas chegam), porque o navegador
  não é de confiança para garantir o que o JS combinou.

## Dois defeitos encontrados ao montar a tela

**`enctype` ausente no formulário do cadastro.** `templates/patients/form.html`
era `method="post"` sem `enctype="multipart/form-data"`. Um campo de arquivo
ali dentro seria enviado como nome sem conteúdo, `request.FILES` chegaria
vazio, e o paciente seria gravado sem o retrato sem que nada na tela dissesse
isso. `check_foto.py` passou a conferir o atributo — é o tipo de linha que
some numa reorganização de template e cujo efeito só aparece semanas depois.

**`.avatar-text` anula o tamanho.** A classe do tema traz
`width:auto!important; height:auto!important`, e ela está em todos os
avatares de inicial do produto. Aplicada a um `<img>`, o retrato sairia no
tamanho natural do arquivo — uma foto de celular ocupando a tela inteira. O
cabeçalho usa `avatar-xl`/`avatar-md` (que fixam as medidas) sem
`avatar-text`, mais `object-fit: cover` em estilo inline: o tema traz
Bootstrap 5.2.0-beta1, e a utilitária `object-fit-*` só existe a partir da
5.3.

## O que foi verificado

`checks/check_foto.py`, dez seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | PDF renomeado, arquivo vazio e acima do limite entram? | Recusados; PNG legítimo passa |
| 2 | Captura vazia, corrompida ou que não é data URL? | `None`, erro, erro |
| 3 | Médico e secretária conseguem enviar? | 200, arquivo no disco |
| 4 | O arquivo é servido com que cabeçalhos? | `image/png`, `private, max-age=300`, `nosniff`, CSP |
| 5 | Paciente de outra clínica | 404 na leitura **e** no envio |
| 6 | O formulário entrega o arquivo? | `enctype` presente, campo presente, aviso presente |
| 7 | Substituir acumula arquivo? | Mesmo caminho, arquivo existe |
| 8 | Trocar a foto mexe em `row_version`? | Não |
| 9 | Remover apaga do disco? | Campo limpo e arquivo removido |
| 10 | Arquivo sumido derruba a ficha? | `foto.img` 404, ficha 200 |

Fora do roteiro, exercitados na mesma pilha: cadastro novo com arquivo
(paciente criado, foto servida, ficha exibindo), captura devolvida ao
formulário após re-render por CPF duplicado, arquivo inválido não gravando
paciente nenhum, cabeçalho do atendimento mostrando o retrato do paciente
daquele atendimento e caindo para a inicial quando não há foto.

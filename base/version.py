"""A versão do produto. Uma linha, e o motivo de ela existir.

**Não confundir com `RELEASE_ID`.** São dois números com trabalhos
diferentes, e o sistema precisava dos dois:

- `RELEASE_ID` é o SHA do commit publicado. Identifica **um build**, muda
  a cada publicação, entra no caminho dos estáticos e serve para responder
  "qual código exatamente está rodando neste servidor?". É de quem opera.
- `VERSION` é a versão do **produto**. Muda quando o que a clínica recebe
  muda de forma que importe para ela, e serve para responder "que
  NeuroDoc é este?". É de quem usa, de quem vende e de quem escreve a
  documentação — e é o número que aparece num e-mail de suporte, num
  contrato e numa nota de versão.

Um SHA não responde a segunda pergunta: `2436d01` não diz a ninguém se
faltam funcionalidades, e ninguém o repete ao telefone.

**Regra de incremento.** A partir da entrega imediatamente posterior à
1.0, funcionalidade compatível avança a versão menor (1.1, 1.2...). Uma
mudança relevante e incompatível avança a maior (2.0, 3.0...). Correção sem
funcionalidade nova não muda `VERSION`: o `RELEASE_ID` já identifica o
build exato, e uma terceira casa que muda toda semana deixa de ser lida.

Por decisão de produto, a retirada da captura local, o campo narrativo do
exame e a agenda visual ainda compõem a consolidação da 1.0.

A **1.1** é a primeira atualização funcional depois da publicação: retorno
programado, busca de paciente por diagnóstico, a evolução em gráfico, a
declaração de comparecimento emitida no balcão, e a política de conteúdo
entrando em modo de relatório. Nenhuma delas muda o que já existia — por
isso a versão menor, e não a maior.

A **1.2** traz o nome do paciente numa forma só (caixa alta, gravada) e a
migração de cadastro de outro sistema. O nome muda de aparência para quem
já usa, mas nada deixa de funcionar — busca, documento e mensagem seguem
achando e imprimindo o mesmo paciente —, então a versão menor avança e a
maior não.

A **1.5** é a primeira entrega que muda o que o produto mostra a quem
ainda não é cliente: título, descrição, canônica e dados estruturados em
toda página, `robots.txt` e `sitemap.xml` na raiz, a família de ícones da
marca, o cartão de compartilhamento, e a seção que diz que o sistema
serve a qualquer especialidade. Nada do que já existia muda de
comportamento — por isso a menor.

Ela carrega também a correção de um defeito antigo que nenhuma versão
tinha: o `<title>` nunca chegava à página, porque o bloco que o definia
morava dentro de um `{% include %}`. Fosse só isso, não mudaria a versão.

A **1.6** fecha duas entregas que tinham a mesma causa: o servidor fazia a
coisa certa e a tela não mostrava. O atendimento de texto livre aceitava
adendo desde sempre e a tela não oferecia o bloco; o campo de impressões
existia no modelo e nenhuma aba do estruturado o desenhava — a ponto de o
que vinha da consulta anterior ser gravado invisível. Entra também o
"trazer tudo" da consulta anterior, que é função nova de verdade, e é ele
que faz a versão menor avançar: as outras duas, sozinhas, seriam correção.

Mora em código, como os preços e o contrato, e pelo mesmo motivo: mudá-la
é um commit com autor e data. Este módulo não importa nada de propósito —
`ops/deploy.py` roda no host, fora do Django, e precisa ler a versão para
carimbá-la na publicação.
"""

#: A versão do produto. O primeiro deploy é a 1.0.
#:
#: A **1.12.3** fecha o lote 2 da mesma auditoria: IA pelo papel
#: clínico, consulta relida sob trava, SMS conferido com a chave de quem
#: enviou, exportação vencida e duplicada, prazo da retomada de IA,
#: descarte de texto livre e a falha de assinatura na trilha.
#:
#: A **1.12.2** fecha o lote 1 da auditoria independente de 2026-10-09:
#: o PDF de documento médico (a recepção imprime o emitido, e só), a
#: finalização sobre o autosave, o reenvio com link morto, o `next` do
#: MFA, o pedido do portal na ficha errada e o envio duplicado.
#:
#: A **1.12.1** corrige o despachante da outbox e os consumidores dele,
#: a partir da auditoria externa de 2026-10-09: posse do lease, consumidor
#: fora de transação externa, lembrete que não sai para consulta cancelada
#: e job de IA parado na fila retomado. Terceira casa pela mesma regra da
#: 1.6.1: quem pediu a auditoria é quem usa, e o suporte precisa
#: distinguir quem já tem a correção.
#:
#: A **1.12** põe a assinatura do médico (com o QR) e o quadro da farmácia
#: no rodapé da folha, em todo documento. Muda o que a clínica imprime, e
#: por isso a casa menor, e não uma correção.
#:
#: A **1.11** acrescenta "limpar todas" à caixa de notificações, no sino e
#: na central. Funcionalidade compatível, casa menor.
#:
#: A **1.10** é da recepção: o tipo de um horário marcado passa a se
#: trocar no próprio modal da agenda, antes da chegada e sem mexer no
#: horário. Entra junto a recusa de CRM já registrado em outra conta, que
#: saía em inglês e sem dizer o caminho. Funcionalidade compatível, casa
#: menor. Depois da 1.9 vem a 1.10, e não a 2.0: a casa maior é para o que
#: quebra, e nada quebrou.
#:
#: A **1.9** abre a comunicação em massa a **todos os planos**, com uma
#: condição que vale para todos: o servidor SMTP da própria clínica.
#: Funcionalidade nova para o Gratuito e o Básico, e por isso a casa menor.
#: Uma coisa deixa de funcionar, e é deliberado: a clínica com remetente
#: próprio e **sem** servidor não dispara mais campanha — ela saía pelo
#: SMTP da instalação, que entrega a confirmação de conta de todas as
#: outras. Não chega a ser incompatível no sentido da casa maior: nada é
#: apagado, a campanha antiga continua legível, e cadastrar o servidor
#: devolve tudo.
#:
#: A **1.8** é a entrega de véspera de venda: intervalo pontual na agenda,
#: naturalidade do paciente, os dados de cadastro numa gaveta durante o
#: atendimento, aviso automático de horário marcado e cancelado, e o nome
#: fantasia nas mãos do inquilino. Funcionalidade compatível — nada do
#: que existia mudou de comportamento —, por isso a casa menor.
#:
#: A **1.7** troca o provedor de IA padrão da instalação pelo console, com
#: verificação contra o catálogo do provedor: é funcionalidade nova para
#: quem administra a instalação, e por isso a casa menor avança. Vem de
#: dois defeitos do mesmo tipo -- tudo que só quem depende do padrão da
#: instalação exercita estava quebrado.
#:
#: A terceira casa aparece contra a regra escrita acima, e de propósito:
#: a 1.1.1 corrigiu o dia errado na agenda, que a 1.1 publicou; a 1.6.1,
#: o logotipo da clínica anterior que ficava no cache do navegador depois
#: de trocar de organização; a 1.6.2, a leitura de laudo descartada
#: inteira por um campo vazio fora de forma. Dizer "1.6" para as três
#: faria o chamado de suporte não distinguir quem já tem a correção de
#: quem ainda vê o defeito -- que é exatamente o que a versão existe para
#: responder. Nos três casos o defeito foi relatado por quem usa, que é a
#: condição: correção que ninguém notou não precisa de casa nova.
#: A **1.13** é da recepção outra vez: trocar o tipo do horário passa a
#: mudar a duração (encolher libera as células; esticar só onde couber),
#: o botão "Incluir horário" ao lado do dia nas três visões da agenda, e a
#: idade do paciente ao lado do nome na ficha e no prontuário. A troca de
#: tipo muda de comportamento, mas no sentido que quem usa esperava -- o
#: antigo era relatado como defeito --, e nada deixa de funcionar: casa
#: menor.
#: A **1.14** acrescenta o avesso do "Incluir horário": excluir o horário
#: livre do próprio modal de marcar. Funcionalidade nova, nada muda para
#: quem não a usa: casa menor.
#: A **1.14.1** corrige o que o médico achou testando a 1.14 no mesmo
#: dia: o horário excluído aparecia "fechado" (no mês, o dia inteiro) e
#: Incluir horário no mesmo lugar era recusado. Agora ele some e volta.
#: A **1.14.2**: o aviso de cancelamento chegava duas vezes na mesma
#: caixa quando o paciente tinha dois contatos com o mesmo e-mail. Um
#: envio por endereço, em todo envio automático.
#: A **1.15**: "Bloquear este horário" ao lado de Excluir -- o bloqueado
#: conta na estatística, o excluído não --, liberado com um clique na
#: célula; e a consulta futura gravada com a duração de outro tipo volta à
#: do seu (migração `scheduling/0007`), com a remarcação seguindo o tipo.
#: A **1.16**: o paciente envia laudos de exame em PDF pelo portal, que
#: entram direto no prontuário com tipo, data e local, e acendem um alerta
#: para o médico até ele marcar "Ciente" (migração `documents/0008`, só de
#: expansão); e a lista de anexos ganha a data de envio antes do nome.
#: A **1.16.1** corrige o que o primeiro envio real mostrou: o formulário
#: aberto antes de um login no mesmo navegador era recusado pelo token CSRF,
#: e a identificação do portal sobrevivia ao login. Entrar no sistema agora
#: encerra a identificação, a recusa no portal explica e oferece o caminho
#: de volta, há "Encerrar identificação" nas telas do portal, e os textos
#: dizem que ele também recebe laudos.
#: A **1.16.2** é de texto: a urgência manda ao serviço de urgência e
#: emergência mais próximo (e não à clínica), o rodapé do portal deixa de
#: oferecer remarcar consulta, que ele não faz, e a página de vendas e a
#: central de ajuda passam a contar que o portal também recebe laudos.
#: A **1.17**: alterar uma medicação do atendimento pelo lápis ao lado da
#: lixeira, no lugar -- mudar a dose não exige mais excluir e incluir de
#: novo, nem perde o "em uso desde", a indicação e a observação. E toda
#: confirmação passa a ser só o modal do sistema: o `nd-inline.js` fazia a
#: mesma pergunta pela caixa do navegador, antes e depois do modal.
#: A **1.18**: o chat de apoio sem paciente passa a responder também sobre o
#: uso do sistema, pelos trechos do manual e da documentação técnica que a
#: busca escolhe para cada pergunta (`ai/conhecimento.py`). E a leitura do
#: laudo anexado pela IA sai: falhava mais do que lia (migração `ai/0009`,
#: só de dados, encerra o que ela deixou pendente).
VERSION = '1.18'

#: Nome do marco, quando houver. Aparece ao lado da versão nas telas de
#: instalação; vazio não mostra nada, e é o padrão — inventar um apelido
#: para cada correção é ruído.
CODENAME = 'o chat que conhece o sistema'


def version_display():
    """Como a versão aparece para uma pessoa: `1.0` ou `1.0 (apelido)`."""
    return f'{VERSION} ({CODENAME})' if CODENAME else VERSION

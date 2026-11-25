"""Tutorial do WhatsApp pela Twilio da clínica, para a central de ajuda.

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc): o texto recebe o
nome do produto, e `help_content.py` de cada lado o inclui. Mudou um passo
aqui, copie o arquivo inteiro para o outro repositório — a diferença entre os
dois fica toda no argumento `produto`.

Regras deste texto, que valem para quem for editá-lo:

- **Só nome de menu confirmado na documentação oficial** (fontes em
  `docs/governance/whatsapp-twilio.md`). Onde o caminho pode variar com a
  versão do Console, o texto manda usar a busca do Console, e diz isso.
- **Sem captura de tela inventada.** Não há captura da Twilio nem da Meta
  aqui: elas mudam sem aviso e não podemos tirá-las de uma conta real.
- **Preço não é escrito**: muda, e o vigente está nas páginas oficiais.
"""

LINKS = {
    'self_signup': 'https://www.twilio.com/docs/whatsapp/self-sign-up',
    'templates': 'https://www.twilio.com/docs/whatsapp/tutorial/message-template-approvals-statuses',
    'preco_twilio': 'https://www.twilio.com/en-us/whatsapp/pricing',
    'preco_meta': 'https://developers.facebook.com/docs/whatsapp/pricing',
    'politica': 'https://whatsappbusiness.com/pt-br/policy/',
    'limites': 'https://developers.facebook.com/docs/whatsapp/messaging-limits',
    'erros': 'https://www.twilio.com/docs/api/errors',
    'token': 'https://www.twilio.com/docs/iam/api/authtoken',
    'sandbox': 'https://www.twilio.com/docs/whatsapp/sandbox',
}


def artigo(produto):
    """O artigo `whatsapp-twilio`, no formato de `help_content.ARTICLES`."""
    L = LINKS
    passos = [
        # ------------------------------------------------------- o que é
        ('**O que é.** O {p} pode mandar, sozinho, avisos de horário (marcado, '
         'remarcado, cancelado e lembrete) e o aviso de "documento disponível" pelo '
         '**número de WhatsApp da própria clínica**. Para isso a clínica abre uma conta '
         'na **Twilio** — empresa autorizada pela Meta a ligar números à API oficial do '
         'WhatsApp — e informa ao {p} as credenciais dessa conta. É opcional: sem ele, '
         'os avisos continuam por e-mail e SMS como sempre. Não confunda com o botão '
         '**WhatsApp** da agenda, que abre a conversa para a secretária enviar à mão e '
         'continua igual.'),
        ('**O que a clínica contrata e paga.** A conta Twilio é **da clínica**, em nome '
         'dela, e a cobrança vai para o cartão que ela cadastrar lá. Cada mensagem tem a '
         'tarifa da Twilio mais a tarifa da Meta (cobrada por mensagem entregue). O {p} '
         'não cobra nada a mais por este canal e não intermedeia o pagamento. Os preços '
         f'mudam; os vigentes estão em [{L["preco_twilio"]}]({L["preco_twilio"]}) e '
         f'[{L["preco_meta"]}]({L["preco_meta"]}).'),
        ('**O que vai e o que não vai na mensagem.** Só o nome da clínica, a data e a '
         'hora do horário (ou o link seguro do documento). **Nada clínico**: nem o '
         'médico, nem o tipo de consulta, nem o nome do exame, nem o nome do paciente — '
         'quem recebe pode ser um parente, e a política do WhatsApp proíbe trafegar '
         f'informação de saúde ([{L["politica"]}]({L["politica"]})). O documento nunca '
         'vai anexado: vai o link de sempre, que pede os 4 últimos dígitos do CPF. O '
         'sistema **não lê respostas** — escreva isso no modelo, para ninguém esperar '
         'atendimento por ali.'),
        # ------------------------------------------------------- número
        ('**Qual número usar — leia antes de começar.** O número precisa **não estar '
         'registrado no WhatsApp** (nem no aplicativo WhatsApp nem no WhatsApp Business) '
         'e precisa receber SMS ou ligação para o código de verificação. A Twilio manda '
         'apagar a conta do WhatsApp do número antes de cadastrá-lo '
         f'([{L["self_signup"]}]({L["self_signup"]})), e **não documenta** o uso do mesmo '
         'número no aplicativo e na API ao mesmo tempo. **Recomendação: use um número '
         'novo, só para os avisos automáticos**, e mantenha o WhatsApp da recepção no '
         'número de sempre.'),
        ('**Se mesmo assim quiser usar o número que a recepção já usa no aplicativo:** '
         'apagar a conta do WhatsApp no aplicativo faz o celular perder as conversas e os '
         'grupos daquele número, e a recepção deixa de atender por ele no aplicativo. '
         'Exporte o que precisar guardar antes. Faça isso só com a decisão de quem '
         'responde pela clínica, e nunca no meio do expediente.'),
        # ------------------------------------------------------- conta
        ('**Passo 1 — Abrir a conta na Twilio.** Crie a conta em twilio.com com o e-mail '
         'da clínica (não o pessoal de um funcionário) e passe-a para o modo pago: no '
         'Console, **Upgrade**, ou **Admin → Account billing**. Contas de teste (Trial) '
         'não cadastram número de WhatsApp.'),
        ('**Passo 2 — Ter um portfólio empresarial na Meta.** O cadastro pede acesso de '
         'administrador a um **Meta Business Portfolio** (antigo Gerenciador de Negócios). '
         'Se a clínica não tem, ele pode ser criado durante o próprio passo 3. Sem a '
         '**verificação da empresa** pela Meta (que pode levar semanas), o número fica '
         f'limitado e envia a poucas pessoas por dia ([{L["limites"]}]({L["limites"]})); '
         'para uma clínica com muitos pacientes, peça a verificação logo no início.'),
        ('**Passo 3 — Cadastrar o número na Twilio (Self Sign-up).** No Console da '
         'Twilio: **Communications → Numbers & Senders → Overview**, aba **WhatsApp** '
         '(no Console antigo: **Messaging → Senders → WhatsApp Senders**). Clique em '
         '**Create new sender**, escolha o número, clique em **Continue with Facebook**, '
         'entre com o Facebook de quem administra o portfólio, escolha (ou crie) o '
         'portfólio e o perfil do WhatsApp Business, preencha o **nome de exibição** (o '
         'nome que o paciente vê — use o nome da clínica), confirme o código que chega '
         'no número e aceite o acesso da Twilio. Passo a passo oficial, com as condições '
         f'atuais: [{L["self_signup"]}]({L["self_signup"]}).'),
        ('Ao final, o número aparece na lista de WhatsApp Senders. Ele só envia quando a '
         'situação for **Online**; enquanto a Meta analisa o nome de exibição, pode '
         'aparecer outra situação. O {p} confere isso sozinho no passo 6.'),
        # ------------------------------------------------------- credenciais
        ('**Passo 4 — Copiar as credenciais.** Na página inicial do Console da Twilio, '
         'na área de informações da conta (**Account Info**), estão o **Account SID** '
         '(começa com AC) e o **Auth Token** (clique para mostrar e copie). O Auth Token '
         'é uma senha da conta: não mande por e-mail nem por WhatsApp; cole direto no '
         '{p} e mais nada.'),
        ('**Passo 5 — Informar ao {p}.** Em **Integrações → SMS, e-mail e WhatsApp**, '
         'cartão **WhatsApp automático (Twilio)**, botão **Configurar**. Preencha Account '
         'SID, Auth Token e o número (com DDD). O campo **Messaging Service SID** fica em '
         'branco, a não ser que a Twilio peça um. Clique em **Salvar e verificar**. O '
         'Auth Token fica guardado cifrado e nunca mais aparece inteiro na tela — só os '
         '4 últimos caracteres, para conferir.'),
        ('**Passo 6 — A verificação.** O {p} pergunta à Twilio se a conta está ativa e se '
         'o número está **Online**, e mostra o resultado em alguns segundos (a tela se '
         'atualiza sozinha). Preencher os campos não basta: a situação só passa de '
         '**Pendente** para **Validado** quando a Twilio confirma. Se algo falhar, a tela '
         'diz o quê e o código do erro.'),
        # ------------------------------------------------------- modelos
        ('**Passo 7 — Criar os modelos de mensagem.** Fora de uma conversa iniciada pelo '
         'paciente, o WhatsApp só entrega **modelos aprovados pela Meta**. Para cada '
         'ocasião que quiser usar, a tela do {p} mostra o **texto sugerido** e as '
         '**variáveis, na ordem** — `{{1}}` nome da clínica, `{{2}}` data, '
         '`{{3}}` hora (ou `{{2}}` link, no documento). No Console da Twilio, '
         'procure **Content Template Builder** (pela busca do Console), crie um modelo de '
         'texto em **português (Brasil)**, cole o texto e envie para aprovação do '
         'WhatsApp na categoria **Utility** (utilidade). O nome do modelo só aceita letras '
         'minúsculas, números e "_" (ex.: `lembrete_consulta`).'),
        ('Regras da Meta que mais reprovam modelo: variável no começo ou no fim do texto, '
         'duas variáveis coladas, numeração fora de ordem, mais de 10 emojis, link para '
         'wa.me e texto vago. A aprovação costuma sair em minutos, e pode levar até 48 '
         'horas. Um nome reprovado fica bloqueado por 30 dias — use outro nome. Detalhes: '
         f'[{L["templates"]}]({L["templates"]}).'),
        ('**Passo 8 — Ligar as ocasiões.** Copie o identificador de cada modelo (começa '
         'com **HX**, aparece no Content Template Builder) para o campo da ocasião no '
         '{p}, marque **Usar nesta ocasião** e salve. O {p} confere na Twilio se o '
         'modelo está **aprovado** e se tem o mesmo número de variáveis; só então a '
         'ocasião aparece como **Aprovado**. Você pode ligar só algumas (por exemplo, só '
         'o lembrete).'),
        ('**Passo 9 — Teste e ativação.** No cartão **Envio de teste**, escolha a ocasião, '
         'informe o **seu** celular e envie: chega o modelo com dados de exemplo, e a tela '
         'mostra a situação (aceita, entregue, lida ou o erro). Funcionou? Clique em '
         '**Ativar**. A situação vira **Operacional**.'),
        # ------------------------------------------------------- pacientes
        ('**Passo 10 — O aceite de cada paciente.** O WhatsApp só permite falar com quem '
         'autorizou. Na ficha do paciente, em cada contato, marque **Autoriza receber '
         'avisos da clínica pelo WhatsApp** e escreva **como** o aceite foi obtido (ex.: '
         '"autorizou por telefone na marcação, em 12/03"). "Aceita SMS" **não** vale como '
         'aceite de WhatsApp. Sem o aceite, o contato continua recebendo por e-mail e SMS '
         'como antes. Desmarcar revoga na hora.'),
        ('**Como os canais se combinam.** Numa ocasião ligada, quem tem o aceite de '
         'WhatsApp recebe por **WhatsApp no lugar do SMS** (para não ser avisado duas '
         'vezes no mesmo celular) e continua recebendo o **e-mail**. Quem não tem o '
         'aceite recebe como sempre. Se o WhatsApp falhar na hora do envio (modelo '
         'reprovado, número inválido, conta com problema), quem tem SMS habilitado recebe '
         'o **SMS de reserva** — ninguém fica sem o aviso por causa do WhatsApp. O aviso '
         'de horário marcado, remarcado e cancelado, que antes era só por e-mail, passa a '
         'ir também por WhatsApp a quem tem o aceite.'),
        ('**Exemplo de mensagem adequada:** "Olá! Este é um lembrete de Clínica Exemplo: '
        'você tem um horário marcado em 14/03/2027 às 09:00. Se não puder comparecer, '
         'avise a clínica pelos canais habituais. Esta mensagem é automática e não lê '
         'respostas." **Inadequada:** qualquer menção a exame, diagnóstico, medicamento, '
         'especialidade, resultado ou ao nome do paciente.'),
        # ------------------------------------------------------- problemas
        ('**Diagnóstico — situação "Inválido".** *"A Twilio recusou o Account SID ou o '
         'Auth Token"*: copie os dois de novo (o token pode ter sido trocado na Twilio). '
         '*"O número não aparece entre os remetentes"*: confira o número com DDD e se o '
         'cadastro do passo 3 terminou. *"O número está … e só envia quando estiver '
         'ONLINE"*: a Meta ainda está analisando; verifique de novo mais tarde. *"A conta '
         'Twilio está suspended"*: resolva o pagamento no Console da Twilio.'),
        ('**Diagnóstico — modelo "Não utilizável".** Está **pending** (aguarde), '
         '**rejected** (veja o motivo na tela, ajuste e crie com outro nome) ou com '
         '**número de variáveis diferente** do que a ocasião preenche (refaça o modelo '
         'com as variáveis da lista).'),
        ('**Diagnóstico — entrega "Falhou".** Em **Entregas recentes**, a linha mostra o '
         f'código da Twilio; a explicação oficial de cada código está em [{L["erros"]}]'
         f'({L["erros"]}). O mais comum, **63016**, quer dizer que a mensagem não estava '
         'num modelo aprovado. Entrega **Sem confirmação** quer dizer que a Twilio aceitou '
         'e não avisou o resultado em uma hora; confira no Console da Twilio (Monitor → '
         'Logs → Messaging) pelo horário. Entrega **Canal indisponível** quer dizer que o '
         'WhatsApp estava suspenso, não verificado ou não liberado na hora do envio.'),
        # ------------------------------------------------------- manutenção
        ('**Trocar o Auth Token (rotação).** Na Twilio, o token é trocado criando um '
         f'token secundário e **promovendo-o** a principal ([{L["token"]}]({L["token"]})). '
         'Assim que promover, cole o token novo no {p} e salve: até lá, os envios '
         'falham e a tela mostra **Inválido**. Troque o token se ele tiver sido exposto e '
         'sempre que alguém com acesso a ele deixar a clínica.'),
        ('**Suspender ou desligar.** **Suspender** para o envio na hora e guarda tudo '
         '(para reativar depois). **Apagar credenciais e desligar** remove a conta Twilio '
         'do {p}; para encerrar de vez, troque também o Auth Token na Twilio. Em '
         'qualquer caso, os avisos voltam a sair só por e-mail e SMS. Encerrar a conta na '
         'Twilio e o número na Meta é feito lá, pela clínica.'),
        # ------------------------------------------------------- perguntas
        ('**Perguntas frequentes.** *Dá para testar sem número próprio, no Sandbox da '
         'Twilio?* Não com os modelos da clínica: o Sandbox só aceita os modelos prontos '
         f'da Twilio ([{L["sandbox"]}]({L["sandbox"]})). *O paciente pode responder?* Pode '
         'escrever, mas o sistema não lê; o modelo deve dizer isso. *Dá para confirmar a '
         'consulta por botão?* Não nesta versão. *O link do vídeo do teleatendimento vai pelo '
         'WhatsApp?* Não, só por e-mail: o link da sala pode dar acesso à chamada. *Quem '
         'responde pela conta Twilio?* A clínica, como pela própria chave de SMS ou '
         'servidor de e-mail.'),
    ]
    return {
        'slug': 'whatsapp-twilio',
        'title': 'WhatsApp automático pela Twilio da clínica',
        'summary': 'Passo a passo para a clínica ligar os avisos pelo próprio número de '
                   'WhatsApp, com a própria conta Twilio.',
        'audience': 'Dono, gestor',
        'steps': [(texto.replace('{p}', produto), '', '') for texto in passos],
    }

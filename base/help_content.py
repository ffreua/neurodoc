"""O manual do usuário: os processos do NeuroDoc, passo a passo.

Fica em Python, e não em arquivos Markdown soltos nem no banco, por duas
razões práticas:

1. **É conferível.** `checks/check_ajuda.py` percorre esta estrutura e
   afirma que toda captura referenciada existe em `static/help/`. O modo
   como um manual apodrece é exatamente esse — o texto muda, a imagem some,
   e ninguém percebe até um usuário abrir a página e ver o ícone quebrado.

2. **Versiona junto com a tela que ele descreve.** Um manual num banco de
   dados descreve a versão de quando foi escrito, e o commit que muda a
   tela não o toca. Aqui, quem muda a tela vê o texto no mesmo diff.

## O que este manual promete

Descrever o que **existe**, com a tela ao lado. Nenhum passo aqui fala de
função que não está no produto — e é isso que `check_ajuda` protege ao
conferir que cada captura foi tirada de uma rota real.

As capturas saem do banco de demonstração, com pacientes sintéticos. Não
há dado de pessoa real em imagem nenhuma, e não pode haver: o manual é
público.
"""

from tenancy.plans import PUBLIC_ORDER, has_clinical_ai, has_sms, has_tiss, plan_label


def _planos_com(recurso):
    """Os nomes dos planos que têm o recurso, por extenso: "Básico, Completo e
    Personalizado".

    Lidos de `tenancy/plans.py`, e não escritos aqui: o manual diria "a IA
    vem no Completo" no dia em que ela passasse a vir também no Básico, e
    quem lê ajuda acredita nela mais do que na tabela de preços.
    """
    nomes = [plan_label(codigo) for codigo in PUBLIC_ORDER if recurso(codigo)]
    if len(nomes) < 2:
        return ''.join(nomes)
    return '%s e %s' % (', '.join(nomes[:-1]), nomes[-1])


#: Cada artigo: um processo do sistema, do começo ao fim.
#:
#: `passos` é uma lista de (texto, imagem, legenda). `imagem` vazia é um
#: passo sem captura — nem todo passo merece uma, e uma imagem por
#: parágrafo transforma o manual numa apresentação de slides.
ARTICLES = [
    # Primeiro da lista, de propósito: é o artigo para onde o e-mail de
    # boas-vindas (`tenancy/boas_vindas.py`) e o aviso de clínica sem médico
    # (`templates/base.html`) apontam, e é o "Começar pelo início" da
    # central. Sem capturas: descreve uma ordem de trabalho, e cada passo
    # leva ao artigo que tem a tela.
    {
        'slug': 'primeiros-passos',
        'title': 'Primeiros passos: da conta criada ao uso pleno',
        'summary': 'O que fazer, e em que ordem, logo depois de cadastrar a clínica.',
        'audience': 'Responsável pela clínica',
        'steps': [
            ('A conta que cadastrou a clínica é a do **Responsável**. Confirme o '
             'endereço de e-mail pelo link que chegou na sua caixa de entrada e, no '
             'menu do seu nome (canto superior direito), ative o **Segundo fator '
             '(MFA)** — um prontuário guarda dados de saúde, e senha sozinha é pouca '
             'proteção para eles.',
             '', ''),
            ('**Conheça os perfis de usuário.** São quatro, e se acumulam — a mesma '
             'pessoa pode ser responsável e médica:\n\n'
             '- **Responsável**: administra a clínica — equipe, identidade, '
             'integrações, convênios, valores, financeiro e exportação dos dados. '
             '**Não abre prontuário** se não for também médico.\n'
             '- **Médico**: o único perfil que abre o prontuário, registra '
             'atendimentos, emite e assina documentos e usa a IA clínica. Também '
             'agenda, cadastra pacientes e vê os indicadores.\n'
             '- **Secretaria**: pacientes, agenda, balcão do dia e financeiro do '
             'dia a dia. Não vê prontuário.\n'
             '- **Gestor**: o mesmo que o responsável, menos a gestão da equipe e da '
             'identidade da clínica. Não vê prontuário.',
             '', ''),
            ('**Cadastre um usuário com perfil médico — sem ele o prontuário não '
             'funciona.** Enquanto a clínica não tiver médico, um aviso fica no alto '
             'de toda tela. Em **Organização → Equipe e papéis**, convide o médico '
             'pelo e-mail dele, ou, se você mesmo atende, conceda-se o papel de '
             'médico. Cada plano tem um número máximo de médicos, mostrado na mesma '
             'tela. Detalhes em [Equipe, papéis e registro profissional](/ajuda/equipe/).',
             '', ''),
            ('**Cadastre e valide o CRM.** Ter o papel de médico abre o prontuário '
             'para leitura; para **finalizar atendimentos e assinar documentos** o '
             'registro profissional (CRM e UF) precisa estar cadastrado **e '
             'validado**, também em Equipe e papéis. São ações separadas: gravar '
             'corrige um número digitado errado; validar afirma que o CRM foi '
             'conferido junto ao conselho.',
             '', ''),
            ('**Instale o certificado digital** do médico em **Assinatura** (no '
             'menu, e também no menu do nome). É ele que assina receitas, laudos e '
             'relatórios com validade jurídica e gera o QR Code que a farmácia '
             'confere. Sem certificado, o documento ainda pode ser impresso e '
             'assinado à mão.',
             '', ''),
            ('**Preencha a identidade da clínica** em **Organização → Identidade da '
             'clínica**: endereço, telefone, logotipo e o encarregado de dados da '
             'LGPD. Esses dados saem no cabeçalho de todo documento e no aviso de '
             'horário que o paciente recebe — vale conferir antes do primeiro. Ver '
             '[Identidade da clínica](/ajuda/clinica/).',
             '', ''),
            ('**Monte a agenda.** Em **Agenda → Configurar horários**, defina os dias '
             'e horas de cada médico, a duração de cada tipo de consulta e os '
             'intervalos (o almoço, por exemplo). Sem grade, a agenda não oferece '
             'horário. Ver [A grade de horários do médico](/ajuda/disponibilidade/). '
             'Se a clínica atende convênio, cadastre-os em **Convênios e valores**.',
             '', ''),
            ('**Convide o restante da equipe** — secretaria, gestor, outros médicos '
             '— pela mesma tela de Equipe e papéis. Cada pessoa usa a própria conta: '
             'é o que permite a trilha de auditoria dizer quem fez o quê.',
             '', ''),
            ('**IA nativa.** O apoio clínico por inteligência artificial (resumo do '
             'atendimento, apoio diagnóstico, relatório do paciente e o chat de '
             'apoio) faz parte dos planos ' + _planos_com(has_clinical_ai) + ', e '
             '**funciona sem configurar nada**: usa o provedor de IA do NeuroDoc. '
             'Os dados do paciente são desidentificados antes de sair, e todo texto '
             'gerado passa pela revisão do médico antes de entrar no prontuário. Se '
             'preferir usar a sua própria conta de um provedor de IA, cadastre-a em '
             '**Integrações → Inteligência artificial**; desligando, a clínica volta '
             'ao provedor do NeuroDoc.',
             '', ''),
            ('**SMS nativo.** O SMS de confirmação e de lembrete de consulta faz '
             'parte dos planos ' + _planos_com(has_sms) + ' e também **funciona sem '
             'configurar nada**, pelo envio do NeuroDoc. Se quiser usar a sua '
             'própria conta de SMS, cadastre a chave em **Integrações → SMS e '
             'e-mail**. No plano sem SMS, nem a chave própria o libera.',
             '', ''),
            ('**E-mail.** Confirmação de horário, entrega de documento e '
             'recuperação de senha saem pelo e-mail do NeuroDoc em todos os planos. '
             'Para que saiam com o remetente da clínica, cadastre o servidor de '
             'e-mail (SMTP) dela em **Integrações → SMS e e-mail**. Ver [E-mail e SMS '
             'da clínica](/ajuda/mensageria/).',
             '', ''),
            ('**E-mail marketing só com SMTP próprio.** A **Comunicação em massa** '
             'está em todos os planos, mas sai **apenas** pelo servidor de e-mail da '
             'própria clínica — nunca pelo do NeuroDoc, para que uma campanha não '
             'comprometa a entrega dos e-mails de todas as clínicas. E só alcança os '
             'pacientes que autorizaram receber comunicação. Ver [Comunicação em '
             'massa](/ajuda/campanhas/).',
             '', ''),
            ('**Portal do paciente.** Em Identidade da clínica você pode publicar o '
             'portal, por onde o paciente pede receita, relatório ou exame e envia '
             'os laudos que fez fora — sem precisar de conta. Os pedidos caem em '
             '**Solicitações**. Ver [Portal do paciente](/ajuda/solicitacoes/).',
             '', ''),
            ('**Pronto para o primeiro atendimento:** cadastre o paciente, marque na '
             'agenda e, na ficha dele, abra **Novo atendimento**. Dúvidas? Este '
             'manual cobre cada tela; nos planos com IA, o **Chat de apoio** do '
             'médico também responde sobre o uso do sistema; e no rodapé do menu o '
             '**Fale com a NeuroDoc** chega até nós.',
             '', ''),
        ],
    },
    {
        'slug': 'entrar',
        'title': 'Entrar e escolher a clínica',
        'summary': 'Como acessar o sistema e trocar de organização quando você atende em mais de uma.',
        'audience': 'Todos',
        'steps': [
            ('Acesse o endereço da sua clínica e informe o e-mail e a senha. '
             'Se você esqueceu a senha, o link "Esqueci minha senha" envia um '
             'e-mail de recuperação — e a tela nunca diz se aquele endereço tem '
             'conta ou não, o que impede alguém de descobrir quem trabalha aqui.',
             'entrar-login.png', 'Tela de entrada'),
            ('Quem trabalha em mais de uma clínica escolhe qual vai abrir. Cada '
             'organização é separada: pacientes, agenda e documentos de uma nunca '
             'aparecem na outra. Para trocar depois, use o nome da clínica no topo '
             'da tela.',
             'entrar-organizacao.png', 'Escolha da organização'),
            ('Primeiro acesso da clínica? A conta é criada a partir de um código de '
             'convite, na página inicial. O código já traz o plano contratado.',
             '', ''),
        ],
    },
    {
        'slug': 'paciente',
        'title': 'Cadastrar um paciente',
        'summary': 'O cadastro completo, o número de prontuário e a fotografia.',
        'audience': 'Secretaria, médico, gestor',
        'steps': [
            ('Em **Pacientes → Lista de pacientes** você busca por nome, por CPF ou '
             'pelo número do prontuário — pode digitar `000123` ou só `123`. No nome, '
             'basta parte das palavras, em qualquer ordem e sem acento: "maria silva" '
             'acha MARIA DE FÁTIMA DA SILVA. Vale também para a busca da agenda.',
             'paciente-lista.png', 'Lista de pacientes'),
            ('**Novo paciente** abre o cadastro em seções. O CPF é obrigatório e '
             'conferido pelos dígitos verificadores; o CEP preenche município e UF '
             'sozinho. Se o paciente é menor e não tem CPF, cadastre o responsável '
             'na aba de contatos.',
             'paciente-cadastro.png', 'Cadastro em seções'),
            ('A fotografia é opcional e fica no topo do formulário. Você pode enviar '
             'um arquivo ou usar a câmera do computador. **Colha a autorização por '
             'escrito antes** — o sistema não guarda esse consentimento, e o termo '
             'assinado fica em papel junto ao prontuário.',
             'paciente-foto.png', 'Bloco da fotografia'),
            ('Salvo, o paciente recebe um **número de prontuário** sequencial da '
             'clínica. Esse número é o que se diz ao telefone e se escreve na pasta '
             '— ele nunca muda, e nunca é reaproveitado por outro paciente.',
             'paciente-ficha.png', 'Ficha do paciente'),
            ('Paciente que não é mais acompanhado se **arquiva**, nunca se apaga: '
             'arquivar tira da carteira ativa e libera uma vaga no plano, e todo o '
             'histórico continua inteiro e legível.',
             '', ''),
        ],
    },
    {
        'slug': 'agenda',
        'title': 'Marcar e remarcar na agenda',
        'summary': 'Grade por médico, reserva de horário e confirmação com o paciente.',
        'audience': 'Secretaria, médico, gestor',
        'steps': [
            ('A agenda mostra a semana por médico. Cada médico tem a própria grade '
             'de horários, com duração de consulta própria — configurada em '
             '**Agenda → Horários**.',
             'agenda-semana.png', 'Agenda da semana'),
            ('Clique num horário livre para marcar. Você escolhe o paciente (por '
             'nome ou número de prontuário) e o tipo de atendimento. Se o paciente '
             'ainda não estiver cadastrado, dá para fazer um **pré-cadastro** ali '
             'mesmo, com nome e telefone — o cadastro completo é pedido na recepção.',
             'agenda-marcar.png', 'Marcação de horário'),
            ('O sistema **recusa horário sobreposto** para o mesmo médico. Se duas '
             'pessoas tentarem marcar o mesmo horário ao mesmo tempo, só a primeira '
             'consegue, e a segunda recebe um aviso — nunca as duas.',
             '', ''),
            ('Na linha do horário marcado há os botões de **confirmar por e-mail ou '
             'SMS**. A mensagem vai para os contatos do paciente que têm aquele '
             'canal cadastrado.',
             '', ''),
        ],
    },
    {
        'slug': 'atendimento',
        'title': 'Atender: escrever o prontuário',
        'summary': 'Abrir o atendimento, aproveitar a consulta anterior e finalizar.',
        'audience': 'Médico',
        'steps': [
            ('Na ficha do paciente, **Novo atendimento** abre um rascunho. O '
             'rascunho é seu: ninguém mais o vê enquanto não for finalizado, e ele '
             'fica salvo mesmo se você fechar o navegador.',
             'atendimento-abas.png', 'Atendimento aberto'),
            ('As abas separam **História**, **Exame**, **Hipóteses** e **Conduta**. '
             'Hábitos e vícios têm campo próprio na História: em neurologia, álcool '
             'e sono explicam crise, tremor e cefaleia, e diluídos no texto livre '
             'somem na releitura.',
             '', ''),
            ('O que foi registrado na consulta anterior pode ser **trazido para esta** '
             '— medicações em uso, por exemplo. Cada item vem para revisão, e você '
             'aceita ou descarta um a um. O sistema nunca copia nada sozinho.',
             '', ''),
            ('Na aba **Medicações em uso**, o **lápis** ao lado de cada medicação abre o '
             'cadastro dela já preenchido: mude a dose, a posologia ou a situação e '
             'salve, sem excluir e incluir de novo — o "em uso desde", a indicação e a '
             'observação continuam. Vale enquanto o atendimento está aberto; depois de '
             'finalizado, a correção é por retificação.',
             '', ''),
            ('Na aba **Resultados de exames**, registre o exame com o laudo em PDF '
             'anexado. Os valores do laboratorial entram na **tabela de analitos**, '
             'com a faixa de referência do próprio laudo, e o que estiver fora dela '
             'fica destacado; de imagem, EEG e ENMG, cole ou resuma o laudo no campo '
             'Laudo. O PDF fica guardado junto, para conferência.',
             '', ''),
            ('**Finalizar** fecha o atendimento com sua autoria, a data e a versão. '
             'Depois disso o texto não é apagado: uma correção entra como '
             '**retificação**, que preserva o que estava escrito antes e registra o '
             'motivo. É o que a lei espera de prontuário.',
             '', ''),
            ('Com o atendimento finalizado, **Resumo por IA** gera um resumo do caso '
             'para sua revisão. Aprovar não escreve nada no prontuário — a IA nunca '
             'escreve no registro sozinha —, mas o resumo aprovado fica guardado no '
             'próprio atendimento, no quadro **Resumos por IA aprovados**, no alto da '
             'página: clique para abrir e copie o que quiser usar.',
             '', ''),
        ],
    },
    {
        'slug': 'exame',
        'title': 'O exame neurológico estruturado',
        'summary': 'Roteiro por eixo, "tudo normal" por grupo e escalas pontuadas.',
        'audience': 'Médico',
        'steps': [
            ('A aba **Exame** traz um roteiro em árvore, organizado por eixo — '
             'estado mental, nervos cranianos, motor, sensitivo, coordenação, '
             'marcha. São centenas de itens, e você só toca nos que examinou.',
             'exame-roteiro.png', 'Roteiro de exame'),
            ('Cada grupo tem **"tudo normal"**: um clique marca o grupo inteiro como '
             'sem alteração. O achado alterado fica destacado, em vez de se perder '
             'num parágrafo de texto corrido.',
             '', ''),
            ('O que você **não** avaliou fica em branco — e em branco não vira '
             '"normal". É uma diferença que importa: registrar como normal o que não '
             'foi examinado é afirmar algo que não se verificou.',
             '', ''),
            ('As **escalas funcionais** ficam no mesmo lugar. São 14, com pontuação '
             'automática e faixa de interpretação. Aplicada, a escala fica na '
             'história do paciente e dá para comparar entre consultas.',
             'exame-escalas.png', 'Escalas funcionais'),
            ('Abaixo da árvore há **Exame neurológico em texto livre**. Use-o para '
             'uma descrição narrativa que não caiba bem nos itens; ele complementa '
             'o roteiro, aparece no resumo e integra o registro finalizado.',
             '', ''),
        ],
    },
    {
        'slug': 'documento',
        'title': 'Emitir e assinar um documento',
        'summary': 'Receita, laudo, pedido de exame e encaminhamento, com assinatura digital.',
        'audience': 'Médico',
        'steps': [
            ('Dentro do atendimento, **Documentos** lista o que já foi emitido e '
             'permite criar um novo. O formulário muda conforme o tipo escolhido — '
             'receita, laudo, pedido de exame ou encaminhamento.',
             'documento-novo.png', 'Novo documento'),
            ('Antes de assinar pela primeira vez, cadastre seu **certificado digital** '
             'em Assinatura. Depois, habilite uma **sessão de assinatura** de 2, 4, 6 '
             'ou 12 horas — dentro dela, cada documento ainda exige a sua ação, um a '
             'um.',
             'documento-assinatura.png', 'Certificados e sessão'),
            ('Ao assinar, o documento recebe número, data e um **código de '
             'verificação** impresso em QR. Qualquer pessoa — a farmácia, outro '
             'médico — confere a autenticidade em `/verificar/`, sem ter conta no '
             'sistema. A página mostra tipo, número, médico, CRM e data, e **nenhum '
             'conteúdo clínico**.',
             'documento-verificar.png', 'Verificação pública'),
            ('Documento de mais de uma folha traz o **cabeçalho** (clínica e médico) e o '
             '**rodapé** (documento, paciente e "Página N de M") em **todas** as folhas, '
             'para uma folha solta continuar dizendo de quem é e de quem trata. A '
             'assinatura e o QR ficam no pé da última folha.',
             '', ''),
            ('A receita de **controle especial** sai em duas vias, com o endereço '
             'completo do paciente e o quadro de identificação do comprador exigido '
             'pela Portaria 344/98. O sistema recusa emiti-la se o endereço estiver '
             'incompleto — descobrir isso com o paciente no balcão significa que ele '
             'volta ao consultório.',
             '', ''),
            ('**A receita de controle especial impressa sai para assinar e carimbar.** A '
             'Anvisa exige a numeração do SNCR na receita de controle especial **eletrônica** '
             '(RDC 1.000/2025); para assinar digitalmente um controlado, use a **receita '
             'eletrônica com numeração do SNCR** — ver o artigo dela neste manual.',
             '', ''),
            ('A captura direta por **scanner foi retirada do NeuroDoc**. Digitalize '
             'pelo aplicativo do fabricante ou pelo sistema do computador e envie '
             'o arquivo pronto em **Anexos**. O sistema não procura, pareia nem '
             'compartilha equipamentos locais ou da rede.',
             '', ''),
        ],
    },
    {
        'slug': 'receita-sncr',
        'title': 'Receita eletrônica com numeração do SNCR',
        'summary': 'Receita controlada no modelo da Anvisa, com o seu número.',
        'audience': 'Médico',
        'steps': [
            ('**Peça o seu bloco de números.** No menu, **Numeração SNCR** → **Pedir bloco '
             'com o Gov.br**. Uma página leva você ao Gov.br; depois do login, a Anvisa traz '
             'você de volta e entrega **1.000 números**, que são **seus**: valem em todas as '
             'clínicas em que você atende, e só você os usa. São até 3 pedidos por mês de cada '
             'tipo (RCE e RET), e um bloco não pode ser devolvido — peça outro quando os '
             'números estiverem acabando.',
             '', ''),
            ('**Se o pedido ficar "Resultado incerto"**, não peça de novo: a Anvisa pode ter '
             'gerado o bloco sem a resposta chegar. Entre em **sncr.anvisa.gov.br** com o '
             'Gov.br, veja se há bloco gerado nessa data e registre no painel — **Nenhum bloco '
             'foi gerado**, ou o primeiro e o último número que o portal mostra.',
             '', ''),
            ('**Na receita.** No atendimento, em **Conduta**, o botão **Receita controlada '
             '(SNCR)** abre o formulário já no formato eletrônico; fora do atendimento, em '
             '**Emitir documento**, escolha **Controle especial — eletrônica** (listas C1 e C5, '
             'e os adendos) ou **Sujeita à retenção — eletrônica** (antimicrobiano, GLP-1). A '
             'tela mostra quantos números você tem livres de cada tipo.',
             '', ''),
            ('Preencha até **3 medicamentos**. Digite o nome e escolha na lista da Anvisa '
             '(CMED): a substância, a concentração e a forma farmacêutica entram sozinhas, e '
             'você ajusta. A quantidade vai em algarismos (o extenso entra sozinho); marque '
             '**Uso contínuo** quando for o caso — ele sai impresso junto da quantidade, que a '
             'norma continua exigindo (até 60 dias de tratamento; anticonvulsivante e '
             'antiparkinsoniano, até 6 meses). O NeuroDoc '
             'procura cada um na **lista oficial da Portaria 344**. Medicamento que pede '
             '**Notificação de Receita** (lista B1, como o clonazepam) não sai aqui — use o '
             'talonário. Se o medicamento depende de dose para entrar no adendo, ou não foi '
             'encontrado, marque a confirmação: a decisão é sua e fica registrada.',
             '', ''),
            ('**Assine.** Cada medicamento sai **na sua folha**, com o **seu número SNCR** — o '
             'paciente pode levar cada folha a uma farmácia. Todas as folhas vão numa '
             'assinatura digital só, com o seu certificado ICP-Brasil, no modelo da Anvisa e '
             'sem o cabeçalho da clínica. O número só é gasto quando a assinatura dá certo.',
             '', ''),
            ('**Sem número livre, ou sem certificado agora?** Use **Refazer como receita '
             'impressa**: a prescrição é copiada para a receita impressa da clínica, para '
             'assinar e carimbar, e nenhum número é gasto. A receita eletrônica emitida **não '
             'é corrigida** — o número dela já foi usado —: emita uma nova.',
             '', ''),
            ('**O que a farmácia confere:** o número na plataforma da Anvisa '
             '(sncr.anvisa.gov.br), onde ela registra a utilização, e a assinatura digital no '
             'validar.iti.gov.br. O QR de cada folha abre a página de verificação do NeuroDoc.',
             '', ''),
        ],
    },
    {
        'slug': 'modelos',
        'title': 'Modelos de documento',
        'summary': 'Emitir pelo modelo, de dentro da Conduta, com os dados do paciente.',
        'audience': 'Médico',
        'steps': [
            ('**Modelos**, no menu, guarda os textos prontos: **pedidos de exame**, '
             'separados por categoria — Laboratório (sangue e urina), Imagem, '
             'Neurofisiologia, Líquor, Cardiologia, Sono e Outros —, **relatórios**, '
             '**receitas** e **solicitações de cirurgia**. Os do sistema são iguais em '
             'todas as clínicas; para mudar um deles, use **Copiar para meus modelos**.',
             '', ''),
            ('Os **conjuntos** — Queixa cognitiva, Neuropatia, Rastreio paraneoplásico — '
             'pedem exames de mais de uma categoria. Na emissão, **cada categoria sai num '
             'pedido separado**: o laboratório não recebe a ressonância, e o serviço de '
             'imagem não recebe o hemograma.',
             '', ''),
            ('Para criar o seu, **Novo modelo**: uma linha por item. O código TUSS, se '
             'houver, vai no começo da linha (`40304361 HEMOGRAMA COMPLETO`), e a busca '
             'TUSS da própria tela o insere onde o cursor estava. Na solicitação de '
             'cirurgia entram também os **materiais e OPME** (`4 x PARAFUSO PEDICULAR`), '
             'o caráter, o regime, a anestesia e os dias de internação — salvos para usar '
             'sempre. O modelo é **seu**: vale em todas as clínicas em que você atende.',
             '', ''),
            ('No atendimento, em **Conduta** (no texto livre, no cartão **Impressões e '
             'conduta**), use **Documentos por modelo**: escolha o modelo e clique em '
             '**Usar modelo**. O que estiver digitado e ainda não salvo é salvo antes de '
             'abrir a emissão.',
             '', ''),
            ('A tela de emissão abre **um documento por categoria**, já preenchido, para '
             'você mudar o que quiser. O pedido de **imagem exige a indicação clínica**; o '
             'CID só sai impresso se você escolher uma das hipóteses do atendimento. O '
             'convênio e a carteirinha do paciente saem no pedido quando cadastrados.',
             '', ''),
            ('**Emitir em papel** dá número ao documento e gera o PDF sem a tarja de '
             'rascunho, pronto para imprimir e assinar à caneta. **Preparar para assinatura '
             'digital** deixa cada documento pronto para assinar pela tela dele. Nos dois '
             'casos o PDF fica nos **Anexos** do paciente.',
             '', ''),
            ('O texto de cada documento entra **na conduta** do atendimento — o prontuário '
             'registra o que foi pedido. Se o atendimento já foi finalizado, entra como '
             '**adendo**, e o corpo finalizado não muda. Editar ou excluir um modelo nunca '
             'altera documento já emitido.',
             '', ''),
        ],
    },
    {
        'slug': 'entrega',
        'title': 'Entregar o documento ao paciente',
        'summary': 'Link protegido, segundo fator e reenvio.',
        'audience': 'Médico, secretaria',
        'steps': [
            ('Emitido o documento, o envio dispara sozinho para o contato autorizado '
             'do paciente. A mensagem é neutra — ela não diz do que se trata — e leva '
             'um **link**, não o arquivo.',
             'entrega-documento.png', 'Entregas do documento'),
            ('Para abrir, o paciente confirma os **quatro últimos dígitos do CPF**. '
             'Paciente sem CPF, em geral criança, responde a data de nascimento. '
             'O link vale 30 dias e trava depois de cinco tentativas erradas.',
             '', ''),
            ('**Reenviar gera um link novo e revoga o anterior.** Dois links vivos '
             'para o mesmo documento dobram a superfície — e revogar é a saída quando '
             'se suspeita que o link vazou.',
             '', ''),
        ],
    },
    {
        'slug': 'solicitacoes',
        'title': 'Portal do paciente: solicitações e envio de exames',
        'summary': 'O paciente pede documentos e envia laudos; o médico decide e é avisado.',
        'audience': 'Médico, gestor',
        'steps': [
            ('O portal é publicado por clínica e vem **desligado**. Ligue-o em '
             '**Organização → Identidade da clínica**. Enquanto estiver desligado, o '
             'endereço responde como inexistente.',
             '', ''),
            ('O paciente se identifica com CPF **e** data de nascimento — as duas '
             'coisas juntas, sempre. A resposta é idêntica para CPF inexistente e '
             'data errada, o que impede usar o formulário para descobrir quem é '
             'paciente da clínica.',
             'solicitacoes-portal.png', 'Portal público'),
            ('O pedido entra numa **fila** que só quem atende alcança. O portal não '
             'mostra prontuário, não lista receitas anteriores e não confirma nada '
             'sobre o tratamento: ele aceita pedido, e só.',
             'solicitacoes-fila.png', 'Fila de solicitações'),
            ('Na revisão, o texto do paciente aparece **ao lado** do rascunho que '
             'você vai emitir — e o rascunho é editável antes de virar documento. '
             'Você também pode recusar, com motivo registrado.',
             '', ''),
            ('Pelo mesmo portal, o paciente **envia os laudos dos exames** que já fez: '
             'até **5 PDFs por vez, de até 3 MB cada**, informando qual exame é, a data '
             'de realização e onde foi feito. A tela avisa, em vermelho, que só se '
             'mandam laudos e resultados finais — pedido médico, receita e foto, não.',
             '', ''),
            ('O laudo **entra direto no prontuário**, sem fila: é resultado que o '
             'paciente já tem, e não pedido de ato médico. Ele passa pela mesma '
             'verificação de vírus de qualquer anexo e aparece em **Anexos** pelo nome '
             'do exame, com as marcas *Enviado pelo paciente* e *Novo*.',
             '', ''),
            ('Quem tem acesso clínico recebe o aviso no sino, e o prontuário mostra um '
             '**alerta vermelho** no topo — na linha do tempo, no atendimento e na '
             'ficha — até alguém apertar **Ciente**, que fica registrado com quem e '
             'quando. A secretária vê que chegou um anexo do paciente, mas não qual '
             'exame é.',
             '', ''),
            ('A regra dos **180 dias sem consulta** barra os pedidos, e **não** o '
             'envio de laudo: quem volta depois de muito tempo é justamente quem traz '
             'exame novo. A identificação do paciente se encerra ao concluir o envio, '
             'pelo botão *Encerrar identificação* ou em trinta minutos.',
             '', ''),
        ],
    },
    {
        'slug': 'codigos',
        'title': 'Buscar códigos CID-10 e TUSS',
        'summary': 'Encontrar o código pelo nome, mesmo quando a tabela abrevia.',
        'audience': 'Todos',
        'steps': [
            ('**Apoio → Busca de códigos** tem duas abas. O CID-10 traz mais de 14 mil '
             'códigos; procure pelo código (`G40`, `G40.0`) ou por parte do nome '
             '(`epilepsia`). Acento é opcional.',
             'codigos-cid.png', 'Busca no CID-10'),
            ('A aba TUSS traz os procedimentos da tabela da ANS. Ela **abrevia** — '
             '"RM - Crânio (encéfalo)" —, e a busca sabe disso: digitar "ressonancia '
             'cranio" encontra o mesmo que digitar "RM cranio".',
             'codigos-tuss.png', 'Busca na TUSS'),
            ('Digitar mais palavras **restringe** o resultado. Procedimento com '
             'vigência encerrada aparece com marca, em vez de sumir — some-lo '
             'esconderia por que a operadora glosou um código usado até o mês '
             'passado.',
             '', ''),
            ('**Copiar** leva código e descrição juntos: o código sozinho, colado num '
             'laudo, obriga quem lê a procurar o que ele significa.',
             '', ''),
        ],
    },
    {
        'slug': 'chat',
        'title': 'Chat de apoio',
        'summary': 'Conversar com a IA sobre um paciente ou sobre o uso do sistema.',
        'audience': 'Médico — planos Completo e Personalizado',
        'steps': [
            ('Abra uma conversa e escolha o paciente pelo nome. Com paciente, a IA '
             'consulta o prontuário **dele** — atendimentos, exames, medicações e '
             'diagnósticos registrados. Sem paciente, ela ajuda com dúvidas de neurologia, '
             'redação e **o uso do próprio NeuroDoc**, sem acessar prontuário nenhum.',
             'chat-nova.png', 'Nova conversa'),
            ('Na conversa **sem paciente**, pergunte como fazer algo no sistema — '
             '"como bloqueio um horário?", "onde fica o laudo que o paciente mandou?". '
             'Para cada pergunta, a IA consulta este manual e a documentação técnica e '
             'responde a partir do que está escrito, citando a página. Se não estiver '
             'documentado, ela diz que não encontrou, em vez de descrever uma tela de '
             'memória.',
             '', ''),
            ('Na conversa **com paciente**, quatro atalhos ficam acima do campo de '
             'mensagem: **Revisar diagnóstico**, **Revisar evolução**, **Preparar '
             'retorno** e **Explicar ao paciente**. O atalho só escreve um pedido pronto '
             'no campo — nada é enviado sozinho. Leia, ajuste o que quiser e envie como '
             'qualquer mensagem. Se o campo já tiver texto, o pedido entra depois dele, '
             'sem apagar o que você escreveu. A IA vê um recorte do prontuário (os '
             'atendimentos mais recentes, os exames e as medicações e diagnósticos do '
             'último atendimento), e o pedido manda dizer o que faltou nesse recorte.',
             '', ''),
            ('Cada conversa é isolada: nenhuma herda o contexto de outra. A resposta '
             'aparece sendo escrita, e você pode parar no meio.',
             'chat-conversa.png', 'Conversa aberta'),
            ('A IA responde **a partir do que está registrado**. Quando a informação '
             'não está no prontuário, ela diz que não encontrou — em vez de preencher '
             'com o que seria provável. Ela não dá diagnóstico nem prescreve conduta: '
             'a decisão é sempre sua, e o que ela escreve é material que você revisa.',
             '', ''),
            ('Antes de sair da clínica, o texto passa por uma remoção de dados que '
             'identificam o paciente — nome, CPF, telefone. É melhor esforço, e não '
             'anonimização completa: evite digitar dados identificáveis que não '
             'estejam no cadastro.',
             '', ''),
            ('Terminada a conversa, **Arquivar** tira da lista e guarda tudo — é o '
             'caminho normal, porque a conversa é material de revisão. **Apagar** '
             'remove a conversa e as mensagens de vez, para o caso da conversa aberta '
             'por engano; o prontuário do paciente não é afetado, e o registro de que '
             'a conversa existiu fica na trilha, sem o conteúdo.',
             '', ''),
            ('**Não encontra o Chat de apoio no menu?** O apoio por IA faz parte dos '
             'planos Completo e Personalizado. Nos demais ele não aparece — e nada do '
             'que já está no prontuário muda por isso. Em Organização → Inteligência '
             'artificial, o dono e o gestor veem qual plano inclui o recurso.',
             '', ''),
        ],
    },
    {
        'slug': 'convenios',
        'title': 'Convênios, planos e valores',
        'summary': 'Cadastrar operadoras, planos aceitos e a tabela de honorários.',
        'audience': 'Dono, gestor, médico (valores)',
        'steps': [
            ('**Convênios e valores → Convênios e planos**. A operadora ("Bradesco '
             'Saúde") e o plano ("Nacional Plus") são dois níveis: o que carrega '
             'carência, coparticipação e valor é o plano.',
             'convenios-lista.png', 'Convênios e planos'),
            ('Para tirar um plano de circulação, desmarque **"Aceito pela clínica"**: '
             'ele some das listas de escolha e continua legível onde já foi usado. '
             'O botão **Excluir** só aparece para plano que nunca foi usado por '
             'ninguém — apagar um plano em uso apagaria o registro de sob qual '
             'cobertura o paciente foi atendido.',
             '', ''),
            ('Em **Valores**, a regra mais específica que se aplica na data é a que '
             'vale: médico + plano + procedimento, afrouxando até a regra geral da '
             'clínica. Campo em branco não é campo esquecido — é o que faz a regra '
             'valer para todos.',
             'convenios-valores.png', 'Tabela de valores'),
            ('Valor não se apaga: uma regra sai de vigor recebendo data final. O '
             'recebimento guarda um retrato do que valia, e a regra explica de onde '
             'aquele retrato veio.',
             '', ''),
        ],
    },
    # Faturamento TISS e agenda de exames (1.30). Nos planos que os incluem,
    # depois de a clínica ser liberada pela equipe do NeuroDoc.
    {
        'slug': 'faturamento-tiss',
        'title': 'Faturamento de convênio (TISS): guias e lotes',
        'summary': 'Guia de Consulta e SP/SADT, o arquivo XML do lote e o envio à operadora.',
        'audience': 'Recepção e gestor',
        'steps': [
            ('**Quem tem.** O faturamento TISS vem nos planos ' + _planos_com(has_tiss) + ', e a clínica precisa ser '
             'liberada pela equipe do NeuroDoc. Aparece no menu como **Faturamento TISS**. Por '
             'segurança (padrão da ANS), a área pede o segundo fator de novo depois de dez '
             'minutos sem uso.',
             '', ''),
            ('**Configure uma vez (responsável ou gestor).** Em **Faturamento TISS**: o '
             '**prestador** (quem fatura: a empresa da clínica, ou o médico como pessoa '
             'física), o **credenciamento** de cada operadora (o código que ela deu ao '
             'prestador, a **versão do padrão** que ela aceita, o ciclo de fechamento e o '
             'portal) e os **profissionais** que pedem e executam — inclusive o médico de fora '
             'que pediu o exame. A operadora precisa estar em **Convênios e planos** com o '
             'registro ANS; dá para buscá-la na lista oficial da ANS.',
             '', ''),
            ('**Gere a guia.** Na ficha do paciente, no horário da agenda ou no atendimento, '
             '**Gerar guia TISS**; para exame da agenda de exames, **Gerar guia TISS** no '
             'próprio exame realizado. A guia já vem com convênio, carteira, credenciamento e '
             'profissionais; na de Consulta de quem fez check-in, a consulta cobrada entra '
             'vinculada à cobrança — nenhuma cobrança nova é criada.',
             '', ''),
            ('**Resolva as pendências.** O que falta aparece no alto da guia, dizendo quem '
             'resolve: a recepção (senha, tipo de atendimento), o médico (a indicação clínica, '
             'que só ele escreve) ou o gestor (cadastro). Os procedimentos vêm da busca TUSS, '
             'conferidos na data do atendimento, com o preço do contrato; valor diferente pede '
             'o motivo. **Fechar** congela a guia; para corrigir, **abra uma revisão**.',
             '', ''),
            ('**Monte o lote.** Em **Faturar guias**, filtre pela operadora e pelo período (o '
             'ciclo do credenciamento está a um clique), marque as guias e confira o **plano**: '
             'um lote por operadora, tipo de guia e versão, até 100 guias cada, e as guias que '
             'não entram com o motivo. Confirmado, o arquivo XML é gerado e conferido contra o '
             'padrão oficial da versão. Baixar de novo devolve o mesmo arquivo.',
             '', ''),
            ('**Envie e registre.** O envio é feito por você, no portal da operadora. Depois, '
             'no lote, registre a **data e o protocolo**, e, quando vier, o **retorno** (aceito, '
             'em parte, recusado). Guia glosada é **liberada** com o motivo para ir num lote '
             'novo; lote recusado inteiro pode ser cancelado. **Nada disso baixa pagamento**: o '
             'recebimento continua sendo lançado no **Financeiro**.',
             '', ''),
        ],
    },
    {
        'slug': 'agenda-exames',
        'title': 'Agenda de exames: EEG, ENMG e polissonografia',
        'summary': 'Uma agenda por equipamento, com a polissonografia atravessando a noite.',
        'audience': 'Recepção e gestor',
        'steps': [
            ('**O que é.** Cada exame com equipamento próprio tem a sua agenda — o EEG, a ENMG, '
             'a polissonografia —, separada da agenda dos médicos. Ela **não conta vaga de '
             'médico** do plano e não ocupa a agenda de ninguém. Vem com o faturamento TISS, '
             'nos planos ' + _planos_com(has_tiss) + '.',
             '', ''),
            ('**Configure (responsável ou gestor).** Em **Agenda de exames** → **Configurar '
             'agendas** → **Nova agenda**: o nome, a duração padrão (a polissonografia costuma '
             'ter 600 minutos), o intervalo entre exames e o código TUSS do procedimento. Depois, '
             'os **horários de atendimento** por dia da semana — fim antes do início é '
             'atravessar a meia-noite (20:00 até 07:00) — e os **bloqueios** (manutenção, '
             'férias do técnico).',
             '', ''),
            ('**Marque.** Na ficha do paciente, **Agendar exame**, ou direto na **Agenda de '
             'exames**: escolha a agenda e o dia, e clique num horário livre. Informe quem pediu '
             'o exame e, se já souber, a forma de cobrança (particular ou convênio). Fora do '
             'horário, só como **encaixe**, com o motivo. A polissonografia das 21h às 7h '
             'aparece nos dois dias da tela, e o mesmo equipamento nunca recebe dois exames no '
             'mesmo horário.',
             '', ''),
            ('**No dia.** **Confirmar**, **Paciente chegou** e, ao final, **Exame realizado**, '
             'com quem executou. É a realização que cria a **cobrança no Financeiro** (com o '
             'valor da tabela de honorários para o procedimento) e permite gerar a **guia '
             'TISS**. Faltou, cancelou ou remarcou: o horário volta a ficar livre. O paciente '
             'recebe um lembrete na véspera, se tiver contato autorizado.',
             '', ''),
        ],
    },
    {
        'slug': 'equipe',
        'title': 'Equipe, papéis e registro profissional',
        'summary': 'Convidar colaboradores e liberar a assinatura de documentos.',
        'audience': 'Dono',
        'steps': [
            ('**Organização → Equipe** lista quem trabalha na clínica e permite '
             'convidar. Os papéis são acumuláveis: a mesma pessoa pode ser dona e '
             'médica.',
             'equipe-lista.png', 'Equipe da clínica'),
            ('Conceder o papel de **médico não libera a assinatura**. É preciso '
             'cadastrar o registro profissional (CRM e UF) e **validá-lo** — cadastrar '
             'e validar são ações separadas de propósito: gravar corrige um telefone '
             'digitado errado; validar afirma que o CRM foi conferido junto ao '
             'conselho.',
             'equipe-registro.png', 'Registro profissional'),
            ('**Suspender** é diferente de **revogar**. Suspender serve a férias e '
             'afastamento, e devolve o acesso depois; revogar encerra o vínculo, e o '
             'vínculo novo não é o mesmo vínculo — o que quebra a leitura de quem '
             'assinou o quê.',
             '', ''),
            ('Ninguém altera o próprio vínculo. Um dono que se revoga deixa a clínica '
             'sem quem conceda papel.',
             '', ''),
        ],
    },
    {
        'slug': 'indicadores',
        'title': 'Os indicadores da clínica',
        'summary': 'O painel de início: consumo do plano, atendimentos, faltas e faturamento do período.',
        'audience': 'Dono, gestor, médico',
        'steps': [
            ('**Início** é o painel. Ele abre no mês corrente, e o seletor de período '
             'no topo muda todos os números de uma vez — não há um filtro por gráfico.',
             'indicadores-painel.png', 'Painel de indicadores'),
            ('O primeiro bloco é o **consumo do plano**: quantos pacientes ativos você '
             'tem e quantos cabem. Ele fica no topo porque responde a uma pergunta que '
             'não tem outro lugar na tela — "quanto ainda cabe?". Descobrir o limite na '
             'hora de cadastrar é descobrir com a pessoa na sua frente.',
             'indicadores-plano.png', 'Consumo do plano'),
            ('Arquivar um paciente **libera vaga**; nada é apagado. A partir de 80% do '
             'limite a barra avisa, e no limite o cadastro é recusado — com o caminho '
             'para falar sobre o plano na mesma tela.',
             '', ''),
            ('Os números de faturamento são **por competência**, e os de caixa são por '
             'recebimento. São perguntas diferentes: um diz quanto você produziu no '
             'mês, o outro quanto entrou. Ver os dois lado a lado é o que explica a '
             'diferença entre agenda cheia e conta magra no fim do mês.',
             '', ''),
            ('A secretaria não vê esta tela. Ela abre direto no **balcão do dia**, que é '
             'o que o trabalho dela pede — indicador agregado de faturamento não é '
             'informação de recepção.',
             '', ''),
        ],
    },
    {
        'slug': 'financeiro',
        'title': 'Financeiro: recebíveis, pagamentos e ajustes',
        'summary': 'O que foi faturado, o que entrou, e como corrigir sem apagar história.',
        'audience': 'Dono, gestor, secretaria, médico',
        'steps': [
            ('**Financeiro** lista os recebíveis: um por atendimento faturável, com o '
             'valor que a tabela de honorários definia **naquela data**. O recebível '
             'guarda um retrato do que valia; mudar a tabela hoje não reescreve o que '
             'já foi lançado.',
             'financeiro-recebiveis.png', 'Lista de recebíveis'),
            ('Registrar um pagamento abre a baixa: valor, data, forma e observação. '
             'Pagamento **parcial** é aceito — o recebível fica com saldo e continua '
             'aparecendo em aberto até fechar.',
             'financeiro-pagamento.png', 'Registro de pagamento'),
            ('Um **ajuste** é o que corrige valor sem apagar história: desconto, glosa '
             'do convênio, acréscimo combinado. Ele entra como linha própria, com '
             'motivo e autor, e o recebível original continua legível.',
             '', ''),
            ('Todo valor é decimal, nunca ponto flutuante. É a diferença entre fechar o '
             'mês e passar a tarde procurando um centavo.',
             '', ''),
        ],
    },
    {
        'slug': 'disponibilidade',
        'title': 'A grade de horários do médico',
        'summary': 'Dias e horas de atendimento, duração por tipo, bloqueios e feriados.',
        'audience': 'Médico, dono, gestor',
        'steps': [
            ('**Agenda → Disponibilidade** define em que dias e horas o médico atende. '
             'A grade é semanal e se repete; o que ela produz são os horários que a '
             'marcação oferece.',
             'disponibilidade-grade.png', 'Grade semanal'),
            ('A **duração da consulta** é por tipo de atendimento: primeira consulta, '
             'retorno, procedimento. Definir aqui evita a conta de cabeça a cada '
             'marcação — e evita a sobreposição que só se descobre no dia.',
             'disponibilidade-duracao.png', 'Duração por tipo'),
            ('**Bloqueios** tiram horário da grade sem apagá-la: férias, congresso, uma '
             'tarde de cirurgia. O horário bloqueado some da oferta e volta sozinho '
             'quando o bloqueio termina.',
             'disponibilidade-bloqueio.png', 'Bloqueio de horário'),
            ('Feriados nacionais já vêm carregados, e **não bloqueiam sozinhos** — quem '
             'atende em feriado continua atendendo. A tela mostra quais ainda estão '
             'abertos, para você decidir um a um.',
             '', ''),
            ('Cada médico configura a própria grade. Dono e gestor configuram a de '
             'qualquer um; o médico, só a dele.',
             '', ''),
        ],
    },
    {
        'slug': 'clinica',
        'title': 'Identidade da clínica e o encarregado de dados',
        'summary': 'Cabeçalho dos documentos, logotipo, portal do paciente e o contato da LGPD.',
        'audience': 'Dono',
        'steps': [
            ('**Organização → Identidade da clínica** guarda o que sai no cabeçalho de '
             'toda receita, laudo e relatório: razão social, CNPJ, endereço, telefone e '
             'e-mail. Conferir isto antes do primeiro documento poupa reimprimir o que '
             'já foi assinado.',
             'clinica-identidade.png', 'Dados da clínica'),
            ('O **logotipo** aparece no documento e no menu. Envie PNG ou JPG; a tela '
             'mostra como ele vai sair antes de você salvar.',
             'clinica-logotipo.png', 'Logotipo'),
            ('O **encarregado de dados pessoais** é exigência da LGPD (art. 41, §1º): a '
             'identidade e o contato precisam ser divulgados publicamente. Preencha nome '
             'e e-mail — enquanto estiver vazio, o portal do paciente diz, com todas as '
             'letras, que a clínica ainda não designou ninguém.',
             'clinica-encarregado.png', 'Encarregado de dados'),
            ('Na mesma tela fica a **publicação do portal** do paciente, em botão '
             'próprio — o portal recebe os pedidos e os laudos de exames que o paciente '
             'envia. É ação separada de propósito: trocar o CEP corrige uma impressão; '
             'publicar o portal abre um endereço na internet que aceita CPF e data de '
             'nascimento de pacientes.',
             '', ''),
        ],
    },
    {
        'slug': 'mensageria',
        'title': 'E-mail e SMS da clínica',
        'summary': 'Configurar o remetente da clínica e acompanhar o que foi entregue.',
        'audience': 'Dono, gestor',
        'steps': [
            ('**Mensagens → Configuração** guarda as credenciais de SMTP da clínica. '
             'Elas são da clínica, e não da instalação: confirmação de consulta que sai '
             'de um remetente genérico cai em spam e não parece da sua clínica.',
             'mensageria-config.png', 'Credenciais de e-mail'),
            ('O botão de **testar** abre a conexão de verdade antes de salvar. Senha de '
             'SMTP errada só se descobre no dia em que um paciente não recebe a '
             'confirmação — e aí ninguém liga uma coisa à outra.',
             '', ''),
            ('**Entregas** mostra cada mensagem que saiu: destino, canal, estado e '
             'tentativa. Uma entrega recusada aparece com o motivo, e é daqui que se '
             'descobre um e-mail digitado errado na ficha.',
             'mensageria-entregas.png', 'Fila de entregas'),
            ('Nada é enviado de dentro da requisição: tudo passa por fila. É o que '
             'permite o sistema responder na hora e tentar de novo quando o servidor do '
             'outro lado está fora.',
             '', ''),
        ],
    },
    {
        'slug': 'campanhas',
        'title': 'Comunicação em massa',
        'summary': 'Avisar muitos pacientes de uma vez, com consentimento e descadastro.',
        'audience': 'Dono, gestor',
        'steps': [
            ('**Mensagens → Campanhas** monta um envio para muitos pacientes. A lista '
             'sai **apenas** de quem autorizou receber comunicação — quem nunca '
             'autorizou não entra, e não há como incluí-lo.',
             'campanhas-nova.png', 'Nova campanha'),
            ('Está em **todos os planos**, e exige o **servidor de e-mail da própria '
             'clínica** (SMTP), cadastrado em **Integrações → SMS e e-mail**. Sem ele, a '
             'tela abre e explica o que falta, mas não cria, não testa e não dispara: '
             'envio em massa não sai pelo e-mail do NeuroDoc, para a reputação do '
             'remetente ser a da clínica que escreve. O e-mail do dia a dia — horário, '
             'documento, senha — continua saindo normalmente sem esse cadastro.',
             '', ''),
            ('O consentimento é reconferido **no instante do envio**, e não só na '
             'montagem: entre criar a campanha e disparar podem passar dias, e quem se '
             'descadastrou nesse intervalo não recebe.',
             '', ''),
            ('O link de **descadastro** é acrescentado pelo sistema, não digitado por '
             'você — mensagem sem ele não sai. A LGPD (art. 8º, §5º) manda que revogar '
             'seja tão fácil quanto consentir.',
             '', ''),
            ('O envio é **fatiado por minuto**. Mil mensagens de uma vez, saindo de um '
             'remetente novo, fazem o provedor marcar o domínio da clínica como spam — e '
             'isso atinge também o e-mail de confirmação de consulta.',
             'campanhas-andamento.png', 'Campanha em andamento'),
            ('**Pausar** interrompe sem perder o que já saiu; retomar continua de onde '
             'parou, e quem já recebeu não recebe de novo. Campanha em envio não dispara '
             'duas vezes, nem com dois cliques.',
             '', ''),
        ],
    },
    {
        'slug': 'notificacoes',
        'title': 'Notificações',
        'summary': 'O sino: o que o sistema avisa e o que fica esperando você.',
        'audience': 'Todos',
        'steps': [
            ('O **sino**, no topo da tela, acende quando há algo esperando: um pedido do '
             'portal, um exame que o paciente enviou, uma exportação pronta, um '
             'documento que terminou de ser assinado. '
             'As cinco últimas aparecem ali mesmo.',
             'notificacoes-sino.png', 'Sino de notificações'),
            ('A **central** lista tudo, com as não lidas primeiro. Ordenar só por data '
             'faria cinco avisos de hoje esconderem o pendente de ontem — que é '
             'justamente o que ainda precisa de alguém.',
             'notificacoes-lista.png', 'Central de notificações'),
            ('Notificação **não carrega conteúdo clínico**: ela diz que algo aconteceu, '
             'de quem se trata — nome e número do prontuário — e leva até lá. Trecho de '
             'prontuário nunca entra, porque o sino aparece numa tela que outra pessoa '
             'pode estar vendo por cima do seu ombro.',
             '', ''),
            ('**Limpar** (no sino) e **Limpar todas** (na central) tiram todos os avisos '
             'da sua caixa nesta clínica, lidos e não lidos, depois de uma confirmação. '
             'Não volta — mas o que eles apontavam continua onde está: o pedido do '
             'portal segue na fila, a tarefa da IA e a exportação seguem abertas. '
             'Sem limpar, os lidos saem sozinhos em 7 dias e os não lidos em 15.',
             '', ''),
        ],
    },
    {
        'slug': 'equipe-chat',
        'title': 'Mensagens internas da equipe',
        'summary': 'Conversar com quem trabalha na mesma clínica, sem sair do sistema.',
        'audience': 'Todos',
        'steps': [
            ('O botão ao lado do sino abre a **janela de mensagens**. A conversa é entre '
             'duas pessoas da mesma clínica, e a entrega é ao vivo — sem recarregar a '
             'página.',
             'equipe-chat-janela.png', 'Janela de mensagens'),
            ('A lista mostra quem está online e quantas mensagens você não leu. Há uma '
             'conversa por par de pessoas: procurar alguém duas vezes abre a mesma '
             'conversa.',
             'equipe-chat-lista.png', 'Lista de conversas'),
            ('**Isto não é prontuário, e a tela diz isso.** Combinar um encaixe ou avisar '
             'que o paciente chegou é o uso; registrar conduta clínica não é — o que vale '
             'como registro é o atendimento, não a conversa.',
             '', ''),
            ('As mensagens são **apagadas sozinhas 72 horas** depois de enviadas — o '
             'recado de sexta à tarde ainda está lá na segunda de manhã, e depois disso '
             'some. Para apagar antes, use **Apagar conversa**, no alto da conversa, e '
             'clique de novo em "Confirmar?". Apaga só a **sua** janela: o colega mantém '
             'a cópia dele até completar as 72 horas.',
             '', ''),
            ('O **ícone de alto-falante**, ao lado do X, liga e desliga o **aviso sonoro** '
             'de mensagem nova. O som toca quando a janela está **fechada** — com ela '
             'aberta a mensagem já está à vista. Ao ligar, ele toca uma vez para você '
             'ouvir como é. A escolha vale para este computador: dá para deixar som na '
             'recepção e silêncio no consultório.',
             '', ''),
            ('Mensagem não atravessa clínicas. Quem trabalha em duas organizações tem '
             'duas listas separadas, e a de uma nunca aparece na outra.',
             '', ''),
        ],
    },
    {
        'slug': 'exportar',
        'title': 'Exportar os dados da clínica',
        'summary': 'Levar embora o cadastro e o prontuário, em Markdown ou JSON.',
        'audience': 'Dono',
        'steps': [
            ('**Organização → Exportar dados** entrega o acervo da clínica. É o direito '
             'da cláusula 13.1 do contrato de adesão: obter o que é seu em formato de uso '
             'comum, sem depender de ninguém.',
             'exportar-tela.png', 'Exportar dados'),
            ('São dois acervos. O **cadastro de pacientes** traz a ficha completa de cada '
             'um, com contatos e convênios. Os **atendimentos** trazem todas as anotações '
             'clínicas, agrupadas por paciente e em ordem de data.',
             '', ''),
            ('**JSON** é para levar a outro sistema: a estrutura é preservada campo a '
             'campo. **Markdown** é para ler: o cadastro vira uma ficha por paciente, e o '
             'prontuário vira um documento que abre em qualquer editor e imprime.',
             '', ''),
            ('A exportação vai para a fila e avisa quando fica pronta. O arquivo **expira '
             'em 24 horas** e some do servidor — baixe e guarde.',
             'exportar-pronta.png', 'Exportação pronta'),
            ('Exportar o prontuário exige ler prontuário. Quem administra a clínica sem '
             'ser médico leva o cadastro, não as anotações — seria estranho não poder '
             'abrir uma nota na tela e poder baixar todas num arquivo. **O arquivo sai do '
             'sistema com você, e a proteção dele passa a ser sua.**',
             '', ''),
        ],
    },
    {
        'slug': 'suporte',
        'title': 'Falar com a NeuroDoc',
        'summary': 'Pedir ajuda e sugerir melhorias, de dentro do sistema.',
        'audience': 'Todos',
        'steps': [
            ('No rodapé do menu há duas portas: **Fale com a NeuroDoc**, para pedir '
             'ajuda, e **Envie sugestões**, para propor melhoria. São separadas porque um '
             'chamado tem alguém esperando hoje, e uma ideia entra numa lista que se lê '
             'com calma.',
             'suporte-mensagem.png', 'Fale com a NeuroDoc'),
            ('**Não escreva dado de paciente.** Nome, CPF, telefone, diagnóstico ou '
             'trecho de prontuário. Quem lê a mensagem opera o servidor e não tem acesso '
             'a prontuário — se precisar citar um atendimento, mande o número dele.',
             '', ''),
            ('A resposta vai para o e-mail da sua conta. Junto da mensagem seguem apenas '
             'o nome da clínica, o seu nome e os seus papéis.',
             '', ''),
        ],
    },
]


#: Perguntas que chegam no dia a dia. Diferente do FAQ comercial da página
#: inicial (`base/content.py`), que responde a quem ainda não é cliente:
#: este responde a quem já está usando.
FAQ_USO = [
    {
        'pergunta': 'Apaguei um paciente por engano. Como recupero?',
        'resposta': 'Paciente não é apagado — é arquivado. Procure-o na lista usando o '
                    'filtro de arquivados e reative. Todo o histórico continua lá, '
                    'inclusive atendimentos e documentos.',
    },
    {
        'pergunta': 'Finalizei um atendimento com erro. Dá para corrigir?',
        'resposta': 'Dá, por retificação. O texto anterior é preservado e a correção fica '
                    'registrada com o motivo e a autoria. Prontuário finalizado não se '
                    'reescreve por cima: é registro, e a trilha do que mudou faz parte dele.',
    },
    {
        'pergunta': 'Por que não consigo assinar um documento?',
        'resposta': 'Três coisas precisam estar no lugar: você tem o papel de médico, seu '
                    'registro profissional foi validado por quem administra a clínica, e há '
                    'um certificado digital cadastrado com sessão de assinatura aberta. A '
                    'tela de Assinatura diz qual dos três está faltando.',
    },
    {
        'pergunta': 'O paciente não recebeu o e-mail com a receita.',
        'resposta': 'Abra o documento e veja a lista de entregas: ela mostra canal, destino, '
                    'estado e o erro, quando houve. As causas mais comuns são contato sem '
                    'e-mail cadastrado, contato não autorizado a receber documentos, e o '
                    'servidor de e-mail da clínica ainda não configurado.',
    },
    {
        'pergunta': 'A busca não encontra um código que eu sei que existe.',
        'resposta': 'Tente por partes do nome em vez do nome inteiro, e lembre que a tabela '
                    'TUSS abrevia: "RM" para ressonância, "TC" para tomografia, "US" para '
                    'ultrassom. A busca já traduz os mais comuns, mas o nome exato da tabela '
                    'sempre funciona.',
    },
    {
        'pergunta': 'Atingi o limite de pacientes do plano. O que acontece?',
        'resposta': 'Novos cadastros são recusados; nada do que já existe é apagado, '
                    'arquivado ou escondido. Arquivar um paciente que não é mais acompanhado '
                    'libera uma vaga. Para ampliar o plano, fale com contato@neurodoc.app.br.',
    },
    {
        'pergunta': 'Trabalho em duas clínicas. Os dados se misturam?',
        'resposta': 'Não. Cada clínica é separada — pacientes, agenda, documentos e '
                    'financeiro. Você troca de organização pelo nome da clínica no topo da '
                    'tela, e o que você vê é sempre o da organização aberta.',
    },
    {
        'pergunta': 'Quem consegue ver o prontuário dos meus pacientes?',
        'resposta': 'Apenas quem tem vínculo clínico na sua clínica. Secretaria e gestor '
                    'fazem o trabalho administrativo — cadastro, agenda, financeiro — e não '
                    'abrem nota clínica. Quem hospeda o sistema vê quantas organizações '
                    'existem e a trilha de quem fez o quê, nunca o conteúdo.',
    },
    {
        'pergunta': 'Esqueci minha senha.',
        'resposta': 'Use "Esqueci minha senha" na tela de entrada. O link chega por e-mail, '
                    'vale por tempo limitado e é de uso único. Se você usa segundo fator, '
                    'ele continua sendo pedido depois da nova senha.',
    },
    {
        'pergunta': 'A IA inventou uma informação sobre o paciente?',
        'resposta': 'Ela é instruída a responder apenas a partir do prontuário registrado e '
                    'a dizer quando não encontra. Se você vir uma resposta com informação '
                    'que não está no prontuário, não a aceite — e avise o suporte com a '
                    'pergunta que gerou. Toda sugestão de IA é material para revisão: nada '
                    'entra no prontuário sem você aceitar.',
    },
    {
        'pergunta': 'O paciente disse que enviou um exame pelo portal. Onde ele está?',
        'resposta': 'Em Anexos, no prontuário dele, pelo nome do exame e com a marca '
                    '"Enviado pelo paciente". Enquanto nenhum médico marcar "Ciente", o '
                    'prontuário mostra um alerta vermelho no topo. Se não estiver lá, o '
                    'envio não foi concluído: o portal só grava quando o paciente chega à '
                    'tela de "Exames enviados", e um arquivo que não é PDF ou passa de '
                    '3 MB é recusado na hora, sem gravar nenhum dos outros.',
    },
    {
        'pergunta': 'Como digitalizo um exame pelo scanner?',
        'resposta': 'A captura direta por scanner foi retirada. Digitalize o documento '
                    'no aplicativo do fabricante ou no sistema do computador; depois, '
                    'abra o paciente no NeuroDoc, entre em Anexos e envie o arquivo '
                    'pronto. Nenhum equipamento local ou da rede é pareado pelo sistema. '
                    'O laudo que o próprio paciente tem em PDF ele mesmo pode enviar, '
                    'pelo portal do paciente: entra direto no prontuário dele.',
    },
]


def article_by_slug(slug):
    for artigo in ARTICLES:
        if artigo['slug'] == slug:
            return artigo
    return None


def screenshots():
    """Todas as capturas referenciadas. Usada pelo roteiro de verificação."""
    return [
        imagem
        for artigo in ARTICLES
        for _, imagem, _ in artigo['steps']
        if imagem
    ]

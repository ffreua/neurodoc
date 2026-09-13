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

#: Cada artigo: um processo do sistema, do começo ao fim.
#:
#: `passos` é uma lista de (texto, imagem, legenda). `imagem` vazia é um
#: passo sem captura — nem todo passo merece uma, e uma imagem por
#: parágrafo transforma o manual numa apresentação de slides.
ARTICLES = [
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
             'pelo número do prontuário — pode digitar `000123` ou só `123`.',
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
            ('**Finalizar** fecha o atendimento com sua autoria, a data e a versão. '
             'Depois disso o texto não é apagado: uma correção entra como '
             '**retificação**, que preserva o que estava escrito antes e registra o '
             'motivo. É o que a lei espera de prontuário.',
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
            ('A receita de **controle especial** sai em duas vias, com o endereço '
             'completo do paciente e o quadro de identificação do comprador exigido '
             'pela Portaria 344/98. O sistema recusa emiti-la se o endereço estiver '
             'incompleto — descobrir isso com o paciente no balcão significa que ele '
             'volta ao consultório.',
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
        'title': 'Portal de solicitações do paciente',
        'summary': 'O paciente pede renovação de receita; o médico decide.',
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
        'summary': 'Conversar com a IA sobre um paciente, com o prontuário como fonte.',
        'audience': 'Médico',
        'steps': [
            ('Abra uma conversa e escolha o paciente pelo nome. Com paciente, a IA '
             'consulta o prontuário **dele** — atendimentos, exames, medicações e '
             'diagnósticos registrados. Sem paciente, ela ajuda com redação e dúvidas '
             'gerais, sem acessar prontuário nenhum.',
             'chat-nova.png', 'Nova conversa'),
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

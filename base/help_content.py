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
            ('Terminada a conversa, **Arquivar** tira da lista e guarda tudo — é o '
             'caminho normal, porque a conversa é material de revisão. **Apagar** '
             'remove a conversa e as mensagens de vez, para o caso da conversa aberta '
             'por engano; o prontuário do paciente não é afetado, e o registro de que '
             'a conversa existiu fica na trilha, sem o conteúdo.',
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
            ('Na mesma tela fica a **publicação do portal** de solicitações, em botão '
             'próprio. É ação separada de propósito: trocar o CEP corrige uma impressão; '
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
             'portal, uma exportação pronta, um documento que terminou de ser assinado. '
             'As cinco últimas aparecem ali mesmo.',
             'notificacoes-sino.png', 'Sino de notificações'),
            ('A **central** lista tudo, com as não lidas primeiro. Ordenar só por data '
             'faria cinco avisos de hoje esconderem o pendente de ontem — que é '
             'justamente o que ainda precisa de alguém.',
             'notificacoes-lista.png', 'Central de notificações'),
            ('Notificação **não carrega conteúdo clínico**: ela diz que algo aconteceu e '
             'leva até lá. O título não traz nome de paciente nem trecho de prontuário, '
             'porque ele aparece numa tela que outra pessoa pode estar vendo por cima do '
             'seu ombro.',
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
             'conversa, com todo o histórico.',
             'equipe-chat-lista.png', 'Lista de conversas'),
            ('**Isto não é prontuário, e a tela diz isso.** Combinar um encaixe ou avisar '
             'que o paciente chegou é o uso; registrar conduta clínica não é — o que vale '
             'como registro é o atendimento, não a conversa.',
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
        'slug': 'scanner',
        'title': 'Digitalizar documentos do paciente',
        'summary': 'Mandar para o prontuário o que chegou em papel.',
        'audience': 'Secretaria, médico',
        'steps': [
            ('**Integrações → Captura** registra os aparelhos que enviam documento '
             'digitalizado para o sistema. Cada aparelho tem credencial própria: um '
             'scanner da recepção que some não leva junto o acesso dos outros.',
             'scanner-dispositivos.png', 'Aparelhos de captura'),
            ('O documento digitalizado entra como **anexo do paciente**, passa pelo '
             'antivírus e só fica disponível depois de liberado. Arquivo reprovado não é '
             'entregue a ninguém.',
             '', ''),
            ('O mesmo arquivo enviado duas vezes não cria dois anexos: o sistema '
             'reconhece pelo conteúdo. Scanner que repete a página por falha de rede é '
             'caso comum, e o prontuário não pode ficar com a duplicata.',
             '', ''),
            ('Sem scanner, o caminho continua sendo **anexar pela ficha do paciente** — a '
             'captura é conveniência, não requisito.',
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

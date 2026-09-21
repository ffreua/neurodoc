"""O contrato de adesão, em Python e versionado.

**Redação de advogada.** O texto abaixo é o da Dra. Karina Albuquerque
Freua, OAB/SP nº 450.476, contratada para redigir e responder pela minuta.
Não é paráfrase nem adaptação: é a redação dela, transcrita item a item.
Quem for mexer aqui mexe num documento jurídico — correção de redação
passa por ela, não pelo código.

Fica em código, e não num PDF solto ou dentro do template, pelo mesmo
motivo que o texto da página de vendas fica em `base/content.py`: o que a
clínica aceitou precisa ser **conferível**. `ContractAcceptance` guarda a
versão, o SHA-256 e — por exigência da cláusula 2.3 — uma cópia do texto
efetivamente aceito; com o texto também em código, um roteiro consegue
afirmar que a tela, o e-mail e o console mostram os três o mesmo
documento.

**Versionamento.** `VERSAO` muda quando o texto muda, e nunca se edita uma
versão já aceita — quem aceitou a `1.0` aceitou aquele texto, e ele
precisa continuar existindo para ser reproduzido numa eventual discussão.
A cláusula 17.6 diz isso com todas as letras. Texto novo é versão nova, e
as clínicas existentes seguem na que assinaram até aceitarem a próxima.

**Por que o hash não está dentro do texto.** A minuta traz um campo
"Identificador de integridade SHA-256" no cabeçalho. Ele não pode ser
calculado sobre um texto que já o contenha — o resultado mudaria o
insumo. O hash é calculado sobre `texto_simples()` e apresentado ao lado
dele, na tela, no e-mail e no console. É o mesmo documento; o carimbo fica
fora da folha, como num selo de conferência.
"""

#: Identificador da versão. Deixou de ser data quando a redação passou a
#: ser da advogada: a minuta dela separa "versão" de "data de vigência", e
#: juntar as duas num campo só obrigaria a inventar uma versão nova a cada
#: correção de vigência.
VERSAO = '1.0'

#: Início da vigência desta redação, no formato ISO.
VIGENCIA_DESDE = '2026-09-21'

TITULO = 'Contrato de Adesão ao NeuroDoc'

SUBTITULO = (
    'Licença de uso de software como serviço — SaaS e acordo de tratamento '
    'de dados pessoais'
)

#: Quem contrata de um lado. Dados do responsável pela plataforma, como
#: qualificados na minuta.
CONTRATADO = {
    'nome': 'Fernando Freua',
    'qualificacao': 'brasileiro, médico neurologista',
    'cpf': '311.515.098-92',
    'endereco': 'Rua Cubatão, nº 86, conjunto 409',
    'papel': 'responsável pela plataforma de software denominada NeuroDoc',
}

#: Quem contrata do outro. Não há dados fixos: a CONTRATANTE é quem estiver
#: aceitando, e é o registro eletrônico do aceite que a identifica.
CONTRATANTE = (
    'A pessoa física ou jurídica, clínica, consultório ou profissional '
    'regularmente cadastrado no sistema, identificado no momento da '
    'contratação por seu nome, razão social, CPF ou CNPJ, endereço '
    'eletrônico e demais dados registrados eletronicamente.'
)

PREAMBULO = (
    'As partes acima qualificadas têm entre si celebrado o presente Contrato '
    'de Adesão ao NeuroDoc — Licença de Uso de Software como Serviço e '
    'Acordo de Tratamento de Dados Pessoais, mediante as cláusulas e '
    'condições seguintes.'
)

#: Quem respondeu pela redação. Fica no documento, e não só no histórico do
#: repositório: a cláusula é de quem a escreveu, e quem lê o contrato tem o
#: direito de saber quem o redigiu.
REVISAO_JURIDICA = {
    'nome': 'Dra. Karina Albuquerque Freua',
    'oab': 'OAB/SP nº 450.476',
    'papel': 'Advogada responsável pela redação e pela revisão jurídica desta versão.',
    'ressalva': (
        'A identificação da profissional não constitui, isoladamente, '
        'declaração de aprovação ou assinatura. A indicação como versão '
        'juridicamente revisada ocorre após sua efetiva conferência e '
        'assinatura.'
    ),
}

#: Resumo honesto, exibido acima do contrato.
#:
#: Existe porque ninguém lê dezoito cláusulas antes de clicar, e fingir o
#: contrário é como se escrevem os contratos que depois são discutidos por
#: falta de informação clara. O resumo não substitui o texto — ele diz o
#: que mais importa e aponta a cláusula.
RESUMO = [
    ('Quem responde pelo prontuário é a clínica',
     'Você decide o que registrar e responde pelo conteúdo clínico. O NeuroDoc '
     'trata esses dados em seu nome, como operador, seguindo suas instruções '
     '(cláusulas 5 e 6).'),
    ('Você pode desistir em 7 dias',
     'Contratou e se arrependeu? Até 7 dias corridos, devolução integral, sem '
     'justificativa. Depois disso o plano anual segue até o fim, salvo as '
     'hipóteses da cláusula 12.3 (cláusulas 11 e 12).'),
    ('Os dados são seus, e saem com você',
     'A qualquer momento você exporta o que é seu. Se o contrato acabar, você '
     'tem 90 dias para levar os dados — dívida não impede a exportação do '
     'prontuário (cláusula 13).'),
    ('Ninguém de fora lê o prontuário por rotina',
     'O acesso a conteúdo clínico é excepcional, limitado ao necessário e '
     'submetido a auditoria; incidente é comunicado a você em até 24 horas '
     '(cláusulas 7 e 14).'),
]


def _item(entrada):
    """Normaliza um item de cláusula.

    A redação da advogada mistura itens corridos e itens com alíneas. Em
    vez de dois formatos no catálogo — e de todo template e todo roteiro
    precisar distinguir os dois —, a fonte aceita as duas formas e aqui
    elas viram uma só: sempre `{'texto', 'alineas'}`, com a lista vazia
    quando não há alíneas.

    A letra de cada alínea é atribuída aqui, e não escrita na fonte nem
    calculada no template: acrescentar uma alínea no meio reletra as
    seguintes sozinho, e a tela, o texto puro e o roteiro leem a mesma
    letra sem cada um repetir a conta.

    Vinte e seis bastam, e nenhuma cláusula desta minuta chega perto — a
    maior tem dez. Estourar o alfabeto seria sinal de que a cláusula
    precisa ser dividida, não de que a numeração precisa de mais um
    dígito.
    """
    if isinstance(entrada, str):
        return {'texto': entrada, 'alineas': []}
    texto, alineas = entrada
    return {
        'texto': texto,
        'alineas': [
            {'letra': chr(ord('a') + i), 'texto': t}
            for i, t in enumerate(alineas)
        ],
    }


#: As cláusulas, na redação da Dra. Karina Albuquerque Freua.
#:
#: O número sai da ordem, e não está escrito em cada uma: acrescentar uma
#: cláusula no meio renumera tudo sozinho, em vez de deixar duas cláusulas
#: 12 até alguém reparar. Vale igual para as alíneas.
_CLAUSULAS = [
    {
        'titulo': 'Do objeto',
        'itens': [
            'O CONTRATADO concede à CONTRATANTE licença de uso não exclusiva, '
            'intransferível e limitada ao período de vigência deste contrato para '
            'utilização do sistema NeuroDoc, plataforma de prontuário eletrônico e '
            'gestão destinada principalmente a clínicas e profissionais de '
            'neurologia e neurocirurgia, disponibilizada na modalidade Software as '
            'a Service — SaaS.',

            ('A licença compreende, conforme o plano contratado:', [
                'utilização do sistema pela CONTRATANTE e por seus profissionais e '
                'colaboradores autorizados;',
                'hospedagem da aplicação e dos dados;',
                'manutenção corretiva;',
                'atualizações ordinárias disponibilizadas pelo NeuroDoc;',
                'ferramentas de exportação dos dados;',
                'demais funcionalidades especificadas no plano vigente no momento '
                'da contratação.',
            ]),

            'Os limites funcionais, quantitativos e comerciais de cada plano serão '
            'aqueles informados na página de contratação e registrados '
            'eletronicamente no momento do aceite.',

            'O CONTRATADO, por meio da plataforma NeuroDoc, não presta serviço '
            'médico aos pacientes da CONTRATANTE, não substitui o julgamento '
            'profissional e não assume responsabilidade por diagnóstico, indicação '
            'terapêutica ou qualquer decisão assistencial tomada pelos '
            'profissionais que utilizam o sistema.',

            'As funcionalidades do sistema destinadas a auxiliar documentação, '
            'organização de informações ou raciocínio clínico constituem '
            'instrumentos de apoio e não transferem ao CONTRATADO a '
            'responsabilidade pelo ato médico praticado pelo usuário.',
        ],
    },
    {
        'titulo': 'Da adesão eletrônica e da prova do contrato',
        'itens': [
            'A adesão ocorre mediante aceite eletrônico realizado pela própria '
            'CONTRATANTE ou por pessoa que declare possuir poderes para '
            'representá-la.',

            ('O NeuroDoc registrará, para fins de comprovação da contratação:', [
                'identificação da CONTRATANTE;',
                'identificação do usuário responsável pelo aceite;',
                'data e hora do aceite;',
                'endereço IP de origem;',
                'informações técnicas do dispositivo ou navegador, quando '
                'disponíveis;',
                'versão contratual aceita;',
                'identificador criptográfico do documento;',
                'plano e condições comerciais aplicáveis;',
                'declaração eletrônica de que o aceitante possui poderes para '
                'contratar em nome da CONTRATANTE, quando aplicável.',
            ]),

            'Uma cópia do conteúdo contratual efetivamente aceito permanecerá '
            'vinculada ao respectivo registro de contratação.',

            'O identificador SHA-256 será calculado segundo procedimento técnico '
            'determinístico, permitindo demonstrar a integridade do texto '
            'contratual aceito.',
        ],
    },
    {
        'titulo': 'Da vigência e da renovação',
        'itens': [
            'Os planos pagos terão vigência de 12 (doze) meses, contados da data '
            'da contratação.',

            'O contrato será renovado automaticamente por períodos sucessivos de '
            '12 (doze) meses, salvo manifestação contrária de qualquer das partes '
            'com antecedência mínima de 30 (trinta) dias em relação ao vencimento.',

            'O plano gratuito terá prazo indeterminado e poderá ser encerrado nos '
            'termos deste contrato.',

            'O encerramento da relação comercial não elimina as obrigações de '
            'confidencialidade, segurança, proteção de dados, preservação de '
            'evidências, responsabilidade ou demais disposições destinadas a '
            'produzir efeitos após o término.',
        ],
    },
    {
        'titulo': 'Dos planos, preços e pagamento',
        'itens': [
            'O plano, os limites quantitativos, as funcionalidades contratadas e o '
            'preço aplicável serão registrados eletronicamente no momento da '
            'contratação.',

            'Nos planos pagos, o valor da contratação será anual e devido '
            'integralmente na data de contratação ou renovação, salvo condição '
            'comercial expressamente registrada.',

            'O eventual valor mensal exibido na página comercial será apresentado '
            'apenas como referência econômica equivalente do plano anual e não '
            'implica modalidade mensal de contratação.',

            'O atingimento de limite quantitativo do plano poderá impedir novos '
            'cadastros ou determinadas novas operações, mas não poderá ocasionar '
            'eliminação, retenção ou indisponibilidade dos dados anteriormente '
            'registrados exclusivamente em razão desse limite.',

            'A mudança para plano superior poderá produzir efeito imediato, '
            'mediante cobrança proporcional do período restante.',

            'A redução de plano produzirá efeitos, como regra, no ciclo contratual '
            'seguinte.',

            'O atraso superior a 15 (quinze) dias poderá resultar em suspensão das '
            'funcionalidades de escrita, preservado o acesso necessário à consulta '
            'e exportação dos registros existentes, ressalvadas restrições '
            'tecnicamente necessárias à segurança.',

            'O NeuroDoc não utilizará prontuários ou dados pessoais como garantia '
            'de pagamento.',

            'Os valores poderão ser reajustados anualmente pela variação positiva '
            'do IPCA ou índice oficial que venha a substituí-lo, mediante '
            'comunicação prévia.',
        ],
    },
    {
        'titulo': 'Dos papéis no tratamento de dados pessoais',
        'itens': [
            'Em relação aos dados pessoais de pacientes, responsáveis, '
            'acompanhantes e demais informações inseridas pela CONTRATANTE no '
            'contexto da assistência à saúde e da gestão de sua atividade, a '
            'CONTRATANTE atuará, em regra, como CONTROLADORA, e o CONTRATADO, por '
            'meio do NeuroDoc, como OPERADOR, nos termos da Lei nº 13.709/2018 — '
            'Lei Geral de Proteção de Dados Pessoais.',

            ('O CONTRATADO tratará esses dados conforme:', [
                'este contrato;',
                'as funcionalidades disponibilizadas pelo sistema;',
                'as configurações efetuadas pela CONTRATANTE;',
                'outras instruções lícitas e documentadas da CONTROLADORA.',
            ]),

            'Em relação aos dados necessários à própria relação comercial e '
            'operacional do NeuroDoc, incluindo cadastro contratual, faturamento, '
            'autenticação, segurança da plataforma, prevenção a fraude, '
            'atendimento técnico, registro de aceite, defesa de direitos e '
            'cumprimento de obrigações legais próprias, o CONTRATADO poderá atuar '
            'como controlador independente.',

            'A definição contratual dos papéis das partes não afasta as '
            'responsabilidades que a legislação atribuir diretamente a cada agente '
            'de tratamento.',

            'O CONTRATADO responderá pelas obrigações que lhe forem legalmente '
            'atribuídas, inclusive quando atuar em desacordo com instruções '
            'lícitas da CONTROLADORA ou em violação à LGPD.',
        ],
    },
    {
        'titulo': 'Das obrigações da CONTRATANTE',
        'itens': [
            ('Compete à CONTRATANTE:', [
                'determinar as finalidades do tratamento de dados sob sua '
                'responsabilidade;',
                'identificar as bases legais aplicáveis;',
                'registrar apenas informações relacionadas a finalidade legítima e '
                'compatível com sua atividade;',
                'manter atualizados e corretos os dados que inserir;',
                'controlar os acessos concedidos a profissionais e colaboradores;',
                'revogar acessos de pessoas que deixarem de possuir vínculo ou '
                'necessidade funcional;',
                'adotar autenticação multifator quando disponibilizada ou exigida;',
                'atender aos direitos dos titulares nos casos em que atuar como '
                'controladora;',
                'obter consentimento quando essa for efetivamente a base legal '
                'exigida;',
                'não utilizar o sistema para finalidade ilícita.',
            ]),

            'A CONTRATANTE deverá indicar encarregado pelo tratamento de dados '
            'pessoais quando essa indicação for exigida pela legislação ou '
            'regulamentação aplicável.',

            'Quando houver hipótese válida de dispensa, a CONTRATANTE deverá '
            'manter canal apropriado para atendimento das obrigações previstas na '
            'LGPD.',
        ],
    },
    {
        'titulo': 'Das obrigações do NeuroDoc como operador',
        'itens': [
            'O CONTRATADO deverá tratar os dados de acordo com as instruções '
            'documentadas da CONTROLADORA e comunicar eventual instrução que '
            'entenda manifestamente contrária à legislação aplicável.',

            'O NeuroDoc manterá controles técnicos e organizacionais destinados a '
            'segregar as organizações existentes na plataforma e reduzir o risco '
            'de acesso entre ambientes pertencentes a contratantes distintas.',

            'O CONTRATADO não acessará rotineiramente o conteúdo clínico para '
            'finalidade própria.',

            ('O acesso excepcional a conteúdo clínico somente poderá ocorrer '
             'quando:', [
                 'tecnicamente necessário;',
                 'compatível com finalidade de suporte, manutenção ou segurança;',
                 'autorizado nos termos deste contrato ou pela CONTRATANTE;',
                 'limitado ao mínimo necessário;',
                 'submetido a mecanismos de controle e auditoria.',
             ]),

            'O NeuroDoc manterá trilhas de auditoria, medidas de segurança, '
            'mecanismos de backup e procedimentos de recuperação compatíveis com a '
            'natureza sensível dos dados tratados.',

            'O CONTRATADO manterá dever de confidencialidade sobre as informações '
            'pessoais ou clínicas às quais tenha acesso.',

            ('O CONTRATADO não utilizará dados clínicos tratados em nome da '
             'CONTRATANTE para:', [
                 'publicidade própria;',
                 'comercialização de dados;',
                 'enriquecimento de bases comerciais;',
                 'treinamento próprio de modelos de inteligência artificial;',
                 'finalidade estranha à prestação contratada.',
             ]),
        ],
    },
    {
        'titulo': 'Dos suboperadores',
        'itens': [
            'A CONTRATANTE autoriza a utilização de suboperadores tecnicamente '
            'necessários à prestação dos serviços.',

            'A relação atualizada de suboperadores será disponibilizada em local '
            'acessível à CONTRATANTE.',

            ('A relação deverá indicar, sempre que aplicável:', [
                'identidade do prestador;',
                'finalidade;',
                'categorias gerais de informações processadas;',
                'localização relevante do tratamento;',
                'existência de transferência internacional.',
            ]),

            'A inclusão ou substituição material de suboperador será comunicada '
            'previamente à CONTRATANTE.',

            'Caso a CONTRATANTE apresente oposição fundamentada e razoável a novo '
            'suboperador que trate dados sensíveis ou clínicos, as partes buscarão '
            'solução técnica alternativa.',

            'Não sendo possível solução alternativa razoável, a CONTRATANTE poderá '
            'rescindir o contrato sem multa, com restituição proporcional do '
            'período pago e não utilizado.',
        ],
    },
    {
        'titulo': 'Da inteligência artificial',
        'itens': [
            'Os recursos de inteligência artificial serão opcionais e poderão '
            'permanecer desabilitados por padrão.',

            'A ativação do recurso não transfere ao CONTRATADO qualquer '
            'responsabilidade pela decisão clínica.',

            'Antes de transmitir conteúdo clínico a provedor externo, o NeuroDoc '
            'aplicará localmente medidas automatizadas destinadas à minimização e '
            'pseudonimização das informações.',

            ('Essas técnicas:', [
                'não constituem anonimização;',
                'não eliminam integralmente o risco de identificação;',
                'não transformam necessariamente o conteúdo em dado anônimo para '
                'fins legais.',
            ]),

            'Nenhum resultado produzido por inteligência artificial será '
            'incorporado automaticamente ao prontuário.',

            'A incorporação ou utilização clínica de conteúdo produzido por '
            'inteligência artificial dependerá de revisão e ação expressa do '
            'profissional responsável.',

            'Quando a CONTRATANTE utilizar provedor ou credencial próprios, ela '
            'permanecerá responsável pela relação contratual direta com esse '
            'provedor, sem prejuízo das obrigações técnicas que continuarem '
            'cabendo ao NeuroDoc.',

            'Quando o provedor de inteligência artificial for contratado '
            'diretamente pelo CONTRATADO para integração ao NeuroDoc, caberá a ele '
            'observar as obrigações que legalmente lhe forem aplicáveis em relação '
            'a esse fornecedor.',
        ],
    },
    {
        'titulo': 'Da transferência internacional de dados',
        'itens': [
            'Determinados suboperadores poderão realizar tratamento de dados fora '
            'do território brasileiro.',

            'A transferência internacional somente deverá ocorrer mediante '
            'mecanismo juridicamente admitido pela LGPD e pela regulamentação da '
            'Agência Nacional de Proteção de Dados — ANPD.',

            'Quando aplicáveis cláusulas contratuais padrão aprovadas pela ANPD, '
            'estas deverão ser incorporadas ao relacionamento correspondente nos '
            'termos exigidos pela regulamentação.',

            'O CONTRATADO disponibilizará informações razoavelmente necessárias '
            'para que a CONTRATANTE conheça as operações internacionais realizadas '
            'em seu nome.',
        ],
    },
    {
        'titulo': 'Do direito contratual de arrependimento',
        'itens': [
            'Independentemente de discussão sobre eventual incidência do Código de '
            'Defesa do Consumidor, a CONTRATANTE poderá desistir da contratação no '
            'prazo de até 7 (sete) dias corridos do aceite eletrônico.',

            'A desistência poderá ser exercida sem justificativa e dará direito à '
            'devolução integral dos valores pagos.',

            'O exercício desse direito não prejudicará qualquer proteção adicional '
            'que a legislação aplicável eventualmente assegure.',

            'Após o encerramento decorrente de arrependimento, serão observadas as '
            'mesmas regras de exportação previstas para as demais hipóteses de '
            'término contratual.',
        ],
    },
    {
        'titulo': 'Da rescisão',
        'itens': [
            'Após o período inicial de 7 (sete) dias, a CONTRATANTE poderá '
            'solicitar o encerramento antecipado do contrato.',

            'Quando o encerramento decorrer exclusivamente de conveniência da '
            'CONTRATANTE, não haverá restituição dos valores referentes ao período '
            'anual contratado, permanecendo o serviço disponível até o término do '
            'período pago, salvo solicitação de encerramento imediato.',

            ('Será devida restituição proporcional do período não utilizado quando '
             'a rescisão decorrer de:', [
                 'descumprimento contratual relevante pelo CONTRATADO;',
                 'indisponibilidade contínua superior a 72 horas causada '
                 'diretamente pelo NeuroDoc;',
                 'alteração material de suboperador não aceita nas condições deste '
                 'contrato;',
                 'alteração contratual material desfavorável recusada pela '
                 'CONTRATANTE;',
                 'descontinuação definitiva do serviço pelo CONTRATADO.',
             ]),

            ('O CONTRATADO poderá rescindir o contrato em caso de:', [
                'inadimplemento superior a 60 dias;',
                'utilização comprovadamente ilícita;',
                'uso deliberado destinado a comprometer a segurança da plataforma;',
                'violação contratual grave não sanada após notificação.',
            ]),

            'Sempre que compatível com a gravidade da situação, será concedido '
            'prazo razoável para regularização.',

            'A descontinuação planejada do produto deverá ser comunicada com '
            'antecedência mínima de 180 dias, salvo impossibilidade decorrente de '
            'força maior, ordem legal ou situação equivalente.',
        ],
    },
    {
        'titulo': 'Do término, da exportação e da retenção',
        'itens': [
            'Encerrado o contrato, a CONTRATANTE terá direito, pelo período de 90 '
            '(noventa) dias, à obtenção dos dados sob sua gestão em formato '
            'tecnicamente adequado e de uso comum.',

            'O NeuroDoc poderá disponibilizar ambiente restrito exclusivamente '
            'para consulta e exportação, sem possibilidade de criação de novos '
            'registros.',

            'A existência de dívida não impedirá a exportação de prontuários e '
            'demais dados necessários à continuidade assistencial e ao cumprimento '
            'das obrigações legais da CONTRATANTE.',

            'O término do contrato não transfere ao CONTRATADO a responsabilidade '
            'da CONTRATANTE quanto à guarda legal do prontuário.',

            ('A eliminação dos dados mantidos pelo NeuroDoc somente ocorrerá de '
             'acordo com:', [
                 'instrução lícita da CONTROLADORA;',
                 'legislação aplicável;',
                 'prazos obrigatórios de guarda;',
                 'limitações técnicas relativas a backups e cópias residuais;',
                 'política de retenção aplicável.',
             ]),

            'Quando necessária a manutenção temporária de dados em backup após a '
            'exclusão do ambiente principal, esses dados permanecerão protegidos, '
            'inacessíveis para uso ordinário e sujeitos ao ciclo técnico de '
            'sobrescrita ou expurgo correspondente.',

            'A CONTRATANTE deverá providenciar, antes do término do período de '
            'exportação, meios adequados para preservar o acervo que esteja '
            'sujeito a obrigação legal de guarda.',
        ],
    },
    {
        'titulo': 'Da segurança e dos incidentes',
        'itens': [
            ('O CONTRATADO adotará medidas técnicas e administrativas '
             'proporcionais à natureza dos dados tratados, incluindo, conforme '
             'aplicável:', [
                 'controles de acesso;',
                 'segregação de organizações;',
                 'autenticação multifator para funções administrativas;',
                 'proteção de credenciais;',
                 'trilhas de auditoria;',
                 'mecanismos de integridade do prontuário;',
                 'backup cifrado;',
                 'procedimentos de restauração;',
                 'proteção de segredos e credenciais;',
                 'controles contra acesso indevido.',
             ]),

            'Ao tomar ciência de incidente confirmado ou razoavelmente suspeito '
            'que possa envolver dados pessoais tratados em nome da CONTRATANTE, o '
            'CONTRATADO comunicará a CONTRATANTE sem demora injustificada e, '
            'sempre que razoavelmente possível, em até 24 horas.',

            'A comunicação inicial poderá ser complementada à medida que novas '
            'informações tecnicamente confiáveis se tornem disponíveis.',

            ('O CONTRATADO prestará cooperação razoável para:', [
                'contenção do incidente;',
                'preservação de evidências;',
                'análise de causa;',
                'identificação das categorias de dados potencialmente afetados;',
                'avaliação do impacto;',
                'preparação de eventual comunicação à ANPD e aos titulares.',
            ]),

            'A responsabilidade pela comunicação externa caberá ao agente '
            'legalmente obrigado a fazê-la em cada situação.',
        ],
    },
    {
        'titulo': 'Da disponibilidade e da responsabilidade',
        'itens': [
            'O CONTRATADO adotará esforços tecnicamente razoáveis para manter o '
            'serviço disponível de forma contínua, ressalvadas manutenções, '
            'incidentes, eventos de força maior e demais situações tecnicamente '
            'inevitáveis.',

            'Falhas de suboperadores contratados diretamente pelo CONTRATADO não '
            'serão automaticamente consideradas eventos excludentes de '
            'responsabilidade.',

            ('O CONTRATADO não responde:', [
                'pelo conteúdo clínico inserido pela CONTRATANTE;',
                'por diagnóstico ou conduta assistencial dos profissionais '
                'usuários;',
                'pela exatidão das informações inseridas pelos usuários;',
                'por atos praticados em desacordo com as instruções da plataforma '
                'ou com este contrato;',
                'por comprometimento decorrente de credencial mantida '
                'inadequadamente pelo próprio usuário, ressalvada responsabilidade '
                'concorrente do CONTRATADO quando existente.',
            ]),

            'Exceto nas hipóteses previstas no item seguinte, eventual '
            'responsabilidade patrimonial do CONTRATADO poderá ser limitada ao '
            'total efetivamente pago pela CONTRATANTE nos 12 meses anteriores ao '
            'fato gerador.',

            ('A limitação anterior não se aplica, na extensão proibida por lei, '
             'a:', [
                 'dolo;',
                 'culpa grave;',
                 'violação deliberada de confidencialidade;',
                 'responsabilidade legalmente inderrogável;',
                 'violação de dados pessoais decorrente de descumprimento das '
                 'obrigações do CONTRATADO;',
                 'infração de propriedade intelectual de terceiros imputável ao '
                 'CONTRATADO.',
             ]),
        ],
    },
    {
        'titulo': 'Da propriedade intelectual, dos dados e da confidencialidade',
        'itens': [
            'O software NeuroDoc, seu código-fonte, identidade visual, '
            'documentação, elementos técnicos e demais ativos intelectuais '
            'pertencem ao CONTRATADO ou aos respectivos titulares de direitos '
            'eventualmente licenciados para utilização na plataforma.',

            'Este contrato concede direito de uso do sistema, mas não transfere '
            'sua propriedade intelectual.',

            'O CONTRATADO não adquire titularidade nem direito de exploração '
            'econômica própria sobre os dados clínicos e pessoais tratados em nome '
            'da CONTRATANTE.',

            ('Permanecem preservados:', [
                'os direitos dos titulares dos dados;',
                'os direitos dos pacientes;',
                'as obrigações legais de guarda e tratamento atribuídas à '
                'CONTRATANTE;',
                'as obrigações do CONTRATADO enquanto agente de tratamento.',
            ]),

            'As partes manterão confidenciais as informações comerciais não '
            'públicas pelo prazo de 5 anos após o término.',

            'Quanto a prontuários, dados pessoais, dados pessoais sensíveis, '
            'informações médicas, credenciais, segredos de segurança e informações '
            'protegidas por sigilo legal ou profissional, o dever de '
            'confidencialidade persistirá enquanto essas informações permanecerem '
            'legalmente protegidas.',
        ],
    },
    {
        'titulo': 'Das alterações contratuais',
        'itens': [
            'O presente contrato será identificado por número de versão e '
            'identificador criptográfico.',

            'Alterações materiais serão comunicadas previamente à CONTRATANTE.',

            'Alterações exigidas por lei, regulamentação ou determinação de '
            'autoridade poderão entrar em vigor no prazo necessário ao cumprimento '
            'da obrigação correspondente.',

            'Correções meramente formais que não reduzam direitos nem ampliem '
            'obrigações poderão ser implementadas sem necessidade de novo aceite, '
            'mantendo-se registro histórico.',

            'Alteração material desfavorável dará à CONTRATANTE direito de '
            'rescindir o contrato sem multa antes da entrada em vigor da nova '
            'condição.',

            'A versão anteriormente aceita permanecerá vinculada à respectiva '
            'evidência histórica de contratação.',
        ],
    },
    {
        'titulo': 'Do foro e das disposições finais',
        'itens': [
            'Este contrato será interpretado de acordo com as leis da República '
            'Federativa do Brasil.',

            'Nenhuma disposição será interpretada como renúncia a direito que não '
            'possa ser validamente renunciado.',

            'A eventual nulidade ou ineficácia de disposição específica não '
            'prejudicará as demais cláusulas, sempre que juridicamente separáveis.',

            'Quando aplicável norma de proteção do consumidor, prevalecerão as '
            'garantias legalmente inderrogáveis.',

            'Fica eleito o foro do domicílio da CONTRATANTE para dirimir '
            'controvérsias decorrentes deste contrato, sem prejuízo de foro '
            'diverso imposto por norma de ordem pública.',
        ],
    },
]

CLAUSULAS = [
    {'titulo': c['titulo'], 'itens': [_item(i) for i in c['itens']]}
    for c in _CLAUSULAS
]

#: Documentos integrantes. A minuta os condiciona a "quando
#: disponibilizados", e hoje nenhum deles existe. Por isso a lista carrega
#: o estado de cada um em vez de prometer seis documentos que a clínica
#: não encontra em lugar nenhum: anexo prometido e ausente é pior do que
#: anexo nenhum, porque a ausência vira argumento contra quem prometeu.
#:
#: Virar `True` é trabalho de publicar o documento, não de editar esta
#: linha — `check_contrato` cobra o endereço de quem estiver marcado.
ANEXOS = [
    ('Anexo I — Acordo de Tratamento de Dados Pessoais (DPA)', False),
    ('Anexo II — Relação de Suboperadores', False),
    ('Anexo III — Regras de Transferência Internacional de Dados', False),
    ('Anexo IV — Política de Retenção e Exclusão', False),
    ('Anexo V — Níveis de Serviço e Disponibilidade, quando aplicável', False),
    ('Aviso de Privacidade do NeuroDoc', False),
]

#: O que a CONTRATANTE declara ao marcar o aceite. A terceira linha é a
#: que o formulário precisa colher em campo próprio: sem ela, a cláusula
#: 2.2, "i" — declaração de poderes para contratar — fica sem registro.
DECLARACAO_ACEITE = [
    'ter lido o contrato;',
    'ter compreendido suas condições;',
    'possuir poderes suficientes para contratar, quando representar terceiro;',
    'aceitar a versão identificada no registro eletrônico;',
    'reconhecer a validade do aceite eletrônico e dos respectivos registros '
    'técnicos.',
]


def texto_simples():
    """O contrato em texto puro, para o e-mail e para a cópia arquivada.

    Gerado do mesmo catálogo que a tela renderiza: um segundo texto escrito
    à mão divergiria do primeiro, e a divergência apareceria exatamente
    onde não pode — entre o que a pessoa leu e o que ela recebeu por
    escrito.

    O SHA-256 é calculado **sobre o que esta função devolve**, e por isso
    o campo de conferência da minuta não aparece aqui: um hash impresso
    dentro do texto que ele identifica mudaria o próprio insumo. O carimbo
    fica ao lado da folha.
    """
    linhas = [
        TITULO.upper(),
        SUBTITULO,
        '',
        f'Versão: {VERSAO}',
        f'Data de vigência: {VIGENCIA_DESDE}',
        '',
        'QUALIFICAÇÃO DAS PARTES',
        '',
        'De um lado,',
        '',
        f'{CONTRATADO["nome"].upper()}, {CONTRATADO["qualificacao"]}, inscrito no '
        f'CPF sob nº {CONTRATADO["cpf"]}, com endereço profissional na '
        f'{CONTRATADO["endereco"]}, {CONTRATADO["papel"]}, doravante denominado '
        f'simplesmente "NEURODOC" ou "CONTRATADO";',
        '',
        'e, de outro lado,',
        '',
        f'{CONTRATANTE} Doravante denominado simplesmente "CONTRATANTE".',
        '',
        PREAMBULO,
        '',
    ]

    for numero, clausula in enumerate(CLAUSULAS, start=1):
        linhas.append(f'CLÁUSULA {numero} — {clausula["titulo"].upper()}')
        for indice, item in enumerate(clausula['itens'], start=1):
            linhas.append(f'   {numero}.{indice}. {item["texto"]}')
            for alinea in item['alineas']:
                linhas.append(f'       {alinea["letra"]}) {alinea["texto"]}')
        linhas.append('')

    linhas += ['DOCUMENTOS INTEGRANTES', '']
    for nome, disponivel in ANEXOS:
        estado = 'disponível' if disponivel else 'ainda não disponibilizado'
        linhas.append(f'   {nome} ({estado})')
    linhas += [
        '',
        'Os documentos acima integram este contrato quando disponibilizados.',
        '',
        'DECLARAÇÃO DE ACEITE',
        '',
        'Ao selecionar a opção eletrônica de aceite, a CONTRATANTE ou seu '
        'representante declara:',
        '',
    ]
    for item in DECLARACAO_ACEITE:
        linhas.append(f'   - {item}')

    linhas += [
        '',
        'IDENTIFICAÇÃO DO CONTRATADO',
        '',
        CONTRATADO['nome'],
        'Médico Neurologista',
        f'CPF nº {CONTRATADO["cpf"]}',
        f'Endereço profissional: {CONTRATADO["endereco"]}',
        'Responsável pela plataforma NeuroDoc',
        '',
        'REVISÃO JURÍDICA',
        '',
        REVISAO_JURIDICA['nome'],
        REVISAO_JURIDICA['oab'],
        '',
        REVISAO_JURIDICA['papel'],
        '',
        REVISAO_JURIDICA['ressalva'],
        '',
    ]
    return '\n'.join(linhas)

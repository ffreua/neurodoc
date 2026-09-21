"""O contrato de adesão, em Python e versionado.

Fica aqui, e não num PDF solto ou dentro do template, pelo mesmo motivo
que o texto da página de vendas fica em `base/content.py`: o que a
clínica aceitou precisa ser **conferível**. `ClinicContractAcceptance`
guarda a versão aceita; com o texto em código, um roteiro consegue
afirmar que a versão registrada existe, que ela não mudou depois de
aceita, e que o que a tela mostra é o mesmo que o e-mail envia.

**Versionamento.** `VERSAO` muda quando o texto muda, e nunca se edita uma
versão já aceita — quem aceitou a `2026-09-20` aceitou aquele texto, e ele
precisa continuar existindo para ser reproduzido numa eventual discussão.
Texto novo é versão nova, e as clínicas existentes seguem na que
assinaram até aceitarem a próxima.

**Esta minuta não substitui revisão jurídica.** Ela foi redigida com
atenção à LGPD, ao CDC e às resoluções do CFM aplicáveis, e as escolhas
difíceis estão comentadas abaixo — mas quem responde por um contrato é
quem o assina, e a revisão por advogado é o passo que falta antes de ele
valer contra alguém.
"""

#: Data da versão, no formato ISO. É o que fica gravado no aceite.
VERSAO = '2026-09-20'

TITULO = 'Contrato de Adesão — NeuroDoc'

SUBTITULO = (
    'Licença de uso de software como serviço e acordo de tratamento de dados '
    'pessoais (LGPD, art. 39)'
)

#: Resumo honesto, exibido acima do contrato.
#:
#: Existe porque ninguém lê catorze cláusulas antes de clicar, e fingir o
#: contrário é como se escrevem os contratos que depois são anulados por
#: falta de informação clara (CDC, art. 46). O resumo não substitui o
#: texto — ele diz o que mais importa e aponta a cláusula.
RESUMO = [
    ('Quem responde pelo prontuário é a clínica',
     'Você decide o que registrar e responde pelo conteúdo clínico. A NeuroDoc '
     'guarda e processa esses dados em seu nome, seguindo suas instruções '
     '(cláusulas 4 e 5).'),
    ('Você pode desistir em 7 dias',
     'Contratou e se arrependeu? Até 7 dias corridos, devolvemos tudo, sem '
     'pergunta. Depois disso o plano anual segue até o fim (cláusula 9).'),
    ('Os dados são seus, e saem com você',
     'A qualquer momento você exporta o que é seu. Se o contrato acabar, você '
     'tem 90 dias para levar os dados — não retemos prontuário como garantia '
     '(cláusula 11).'),
    ('Ninguém de fora lê o prontuário',
     'Quem mantém o servidor não tem acesso ao conteúdo clínico, e o sistema é '
     'construído para que não tenha (cláusula 6).'),
]

#: As cláusulas. Cada item é uma frase completa — o número sai da ordem,
#: para não existirem dois lugares dizendo qual é a cláusula 7.
CLAUSULAS = [
    {
        'titulo': 'Do objeto',
        'itens': [
            'A NeuroDoc concede à CONTRATANTE licença de uso, não exclusiva e '
            'intransferível, do sistema NeuroDoc — prontuário eletrônico e gestão '
            'para clínicas de neurologia e neurocirurgia —, na modalidade software '
            'como serviço, pelo prazo e nas condições deste contrato.',

            'A licença compreende o uso do sistema pela CONTRATANTE e por seus '
            'profissionais vinculados, nos limites do plano contratado, e inclui a '
            'hospedagem, a manutenção corretiva e as atualizações que a NeuroDoc '
            'publicar durante a vigência.',

            'A NeuroDoc não presta serviço médico, não emite documento clínico e '
            'não interfere em decisão assistencial. O sistema é ferramenta de '
            'registro e organização; o ato médico é e permanece da CONTRATANTE e '
            'de seus profissionais.',
        ],
    },
    {
        'titulo': 'Da adesão e da vigência',
        'itens': [
            'A adesão se dá pelo aceite eletrônico deste contrato no momento da '
            'criação da organização no sistema, registrado com data, hora, '
            'endereço IP de origem e identificação de quem aceitou.',

            'O contrato vigora por 12 (doze) meses contados da data do aceite, '
            'renovando-se automaticamente por períodos iguais, salvo manifestação '
            'em contrário de qualquer das partes com 30 (trinta) dias de '
            'antecedência do vencimento.',

            'O plano Gratuito não tem prazo determinado e pode ser encerrado por '
            'qualquer das partes a qualquer tempo, observado o disposto na '
            'cláusula 11 quanto à devolução dos dados.',
        ],
    },
    {
        'titulo': 'Dos planos, preços e pagamento',
        'itens': [
            'Os planos, seus limites e seus preços são os publicados na página de '
            'vendas da NeuroDoc na data do aceite, e ficam registrados no sistema '
            'junto ao aceite.',

            'O valor é anual, devido integralmente na contratação, e o vencimento '
            'ocorre na data de aniversário do aceite. O valor mensal eventualmente '
            'exibido é referência de cálculo, não modalidade de pagamento.',

            'Os limites do plano (número de pacientes ativos e de médicos) são '
            'aplicados pelo sistema. Atingido o limite, novos cadastros são '
            'recusados; nenhum dado já registrado é apagado, arquivado ou tornado '
            'inacessível por causa do limite.',

            'A mudança para plano superior tem efeito imediato e o valor é ajustado '
            'proporcionalmente ao período restante. A mudança para plano inferior '
            'tem efeito no vencimento seguinte.',

            'O atraso no pagamento superior a 15 (quinze) dias autoriza a NeuroDoc '
            'a suspender a escrita no sistema, mantida a leitura de todo o conteúdo '
            'já registrado e mantida a possibilidade de exportação. Prontuário não '
            'é retido como garantia de dívida.',

            'O reajuste anual observará a variação do IPCA no período, ou índice '
            'que o substitua, e será comunicado com 30 (trinta) dias de '
            'antecedência do vencimento.',
        ],
    },
    {
        'titulo': 'Dos papéis no tratamento de dados pessoais',
        'itens': [
            'Para os fins da Lei 13.709/2018 (LGPD), a CONTRATANTE é a '
            'CONTROLADORA dos dados pessoais tratados no sistema, e a NeuroDoc é a '
            'OPERADORA, tratando-os exclusivamente em nome e conforme as instruções '
            'da CONTRATANTE.',

            'Cabe à CONTROLADORA definir as finalidades do tratamento, a base legal '
            'aplicável a cada uma delas, o conteúdo do que é registrado e por '
            'quanto tempo, observada a guarda mínima legal do prontuário.',

            'A CONTRATANTE declara que dispõe de base legal para o tratamento dos '
            'dados que inserir no sistema, e responde perante os titulares e a '
            'autoridade nacional pelo conteúdo clínico e pelas decisões de '
            'tratamento que adotar.',

            'A qualificação das partes neste contrato não afasta a '
            'responsabilidade que a lei atribui diretamente à OPERADORA (LGPD, art. '
            '42), notadamente quando ela descumprir as instruções da CONTROLADORA '
            'ou a própria lei. Nenhuma cláusula deste contrato deve ser lida como '
            'renúncia da CONTRATANTE a direito que a LGPD ou o Código de Defesa do '
            'Consumidor lhe assegurem.',
        ],
    },
    {
        'titulo': 'Das obrigações da CONTRATANTE',
        'itens': [
            'Registrar no sistema apenas dados necessários à finalidade assistencial '
            'ou administrativa a que se destinam, e manter a exatidão do que '
            'registrar.',

            'Zelar pelas credenciais de acesso de seus profissionais, revogando '
            'vínculos de quem deixar a clínica, e manter ativa a autenticação em '
            'dois fatores onde o sistema a oferecer.',

            'Designar seu encarregado pelo tratamento de dados pessoais (LGPD, art. '
            '41) e manter o contato dele atualizado no sistema, para divulgação '
            'pública conforme exige o §1º daquele artigo.',

            'Responder aos titulares que exercerem direitos (LGPD, art. 18), '
            'utilizando os recursos que o sistema oferece para localizar, exportar '
            'e corrigir dados.',

            'Obter o consentimento do titular quando a finalidade o exigir — '
            'notadamente para comunicação em massa —, hipótese em que o sistema '
            'registra o consentimento e oferece a revogação.',

            'Não utilizar o sistema para tratar dado pessoal alheio à sua atividade '
            'assistencial ou administrativa, nem para finalidade ilícita.',
        ],
    },
    {
        'titulo': 'Das obrigações da NeuroDoc como operadora',
        'itens': [
            'Tratar os dados pessoais exclusivamente conforme as instruções da '
            'CONTROLADORA, expressas neste contrato e nas funcionalidades do '
            'sistema, e comunicá-la caso entenda que uma instrução viola a lei.',

            'Manter o isolamento entre as organizações do sistema, de modo que dado '
            'de uma clínica não seja acessível a outra, com controles aplicados '
            'também no banco de dados.',

            'Não acessar o conteúdo clínico. O console de administração da '
            'instalação não abre prontuário, e o acesso a conteúdo clínico por quem '
            'opera o servidor só se admite em hipótese de suporte expressamente '
            'solicitada e autorizada pela CONTRATANTE, registrada em trilha de '
            'auditoria.',

            'Manter trilha de auditoria de acessos e operações, protegida contra '
            'alteração e exclusão.',

            'Manter cópia de segurança cifrada, com rotina diária e procedimento de '
            'restauração testado, permanecendo a chave de recuperação sob custódia '
            'apartada do servidor.',

            'Manter sigilo sobre os dados a que tiver acesso, inclusive após o '
            'término do contrato, estendendo a obrigação a seus prepostos.',

            'Não utilizar os dados da CONTRATANTE para finalidade própria, '
            'notadamente para treinamento de modelos de inteligência artificial, '
            'publicidade, cessão ou comercialização a terceiros.',
        ],
    },
    {
        'titulo': 'Dos suboperadores',
        'itens': [
            'A CONTRATANTE autoriza a NeuroDoc a contratar terceiros para a '
            'execução de parte do tratamento, mantida a responsabilidade da '
            'NeuroDoc perante a CONTRATANTE, e observada equivalência de obrigações '
            'de segurança e sigilo.',

            'São suboperadores desta contratação: o provedor de infraestrutura que '
            'hospeda o sistema; o provedor de envio de e-mail; o provedor de envio '
            'de SMS; e, quando a CONTRATANTE habilitar o recurso, o provedor de '
            'inteligência artificial que ela escolher.',

            'A relação atualizada de suboperadores fica disponível à CONTRATANTE, '
            'que será comunicada com 30 (trinta) dias de antecedência sobre '
            'inclusão ou substituição, podendo rescindir sem ônus caso não '
            'concorde.',
        ],
    },
    {
        'titulo': 'Da inteligência artificial e da transferência internacional',
        'itens': [
            'Os recursos de inteligência artificial são opcionais e vêm desligados. '
            'Habilitá-los é ato da CONTRATANTE, que assume a decisão de tratamento '
            'correspondente.',

            'Antes de qualquer envio a provedor de inteligência artificial, o '
            'sistema remove identificadores diretos do texto. Essa remoção é '
            'pseudonimização, não anonimização: o dado permanece pessoal para os '
            'fins da LGPD, e a CONTRATANTE reconhece essa qualificação.',

            'Provedores de inteligência artificial podem estar sediados fora do '
            'Brasil, hipótese em que o envio configura transferência internacional '
            'de dados (LGPD, art. 33). A CONTRATANTE é responsável por verificar a '
            'base legal aplicável antes de habilitar o recurso, e pode utilizar '
            'provedor e credencial próprios.',

            'Nenhum dado é enviado a provedor de inteligência artificial sem '
            'revisão médica do resultado antes de sua incorporação ao prontuário. '
            'Sugestão não aceita não integra o registro clínico.',
        ],
    },
    {
        'titulo': 'Do direito de arrependimento',
        'itens': [
            'A CONTRATANTE pode desistir da contratação em até 7 (sete) dias '
            'corridos contados do aceite, sem necessidade de justificativa, '
            'mediante comunicação pelos canais do sistema ou por e-mail, com '
            'devolução integral do valor pago.',

            'Exercido o arrependimento, a CONTRATANTE terá 30 (trinta) dias para '
            'exportar os dados que houver registrado, findos os quais a organização '
            'e seus dados serão eliminados, observada a cláusula 11.',

            'Este prazo é concedido contratualmente e se soma, sem prejudicar, ao '
            'que o Código de Defesa do Consumidor assegure quando aplicável à '
            'relação.',
        ],
    },
    {
        'titulo': 'Da rescisão',
        'itens': [
            'Decorrido o prazo de arrependimento, a rescisão por iniciativa da '
            'CONTRATANTE antes do vencimento não gera direito a reembolso das '
            'parcelas já pagas, permanecendo o acesso disponível até o fim do '
            'período contratado.',

            'A regra acima não se aplica, cabendo devolução proporcional ao período '
            'não usufruído, quando a rescisão decorrer de: descumprimento '
            'contratual pela NeuroDoc; indisponibilidade do sistema por período '
            'superior a 72 (setenta e duas) horas consecutivas por causa imputável '
            'à NeuroDoc; alteração de suboperador não aceita pela CONTRATANTE; ou '
            'alteração deste contrato que lhe seja desfavorável e que ela recuse.',

            'A NeuroDoc pode rescindir por inadimplemento superior a 60 (sessenta) '
            'dias, ou por uso do sistema para finalidade ilícita, mediante '
            'comunicação prévia de 30 (trinta) dias, ressalvada a cláusula 11.',

            'A descontinuidade do produto pela NeuroDoc exige comunicação com 180 '
            '(cento e oitenta) dias de antecedência, devolução proporcional do '
            'valor pago e manutenção do acesso à exportação durante todo o período.',
        ],
    },
    {
        'titulo': 'Do término, da devolução e da guarda do prontuário',
        'itens': [
            'Encerrado o contrato por qualquer motivo, a CONTRATANTE terá 90 '
            '(noventa) dias de acesso para exportar os dados registrados, em '
            'formato de uso comum e leitura automatizada.',

            'Findo esse prazo, e mediante instrução expressa da CONTROLADORA, a '
            'NeuroDoc eliminará os dados, salvo os que devam ser conservados por '
            'obrigação legal.',

            'A CONTRATANTE reconhece que o prontuário está sujeito à guarda mínima '
            'de 20 (vinte) anos contados do último registro (Lei 13.787/2018, art. '
            '6º), e que essa obrigação é sua, como controladora, e não se extingue '
            'com o término deste contrato. Cabe à CONTRATANTE, antes da eliminação, '
            'exportar e conservar o acervo, ou contratar sua custódia.',

            'A NeuroDoc não condiciona a exportação ao pagamento de valores em '
            'aberto. Prontuário não é retido como garantia.',
        ],
    },
    {
        'titulo': 'Da segurança e dos incidentes',
        'itens': [
            'A NeuroDoc adota medidas técnicas e administrativas de segurança '
            'compatíveis com o tratamento de dados de saúde, entre elas: controle '
            'de acesso por papel e capacidade; autenticação em dois fatores para '
            'acesso administrativo; isolamento entre organizações aplicado também '
            'no banco de dados; imutabilidade do registro clínico finalizado, com '
            'correção por adendo identificado; trilha de auditoria protegida contra '
            'alteração; cifragem de credenciais; e cópia de segurança cifrada com '
            'restauração testada.',

            'Verificado incidente de segurança que possa acarretar risco ou dano '
            'relevante aos titulares, a NeuroDoc comunicará a CONTRATANTE em até 48 '
            '(quarenta e oito) horas da ciência, com as informações necessárias '
            'para que ela cumpra o dever de comunicação à autoridade nacional e aos '
            'titulares (LGPD, art. 48).',

            'A comunicação à Autoridade Nacional de Proteção de Dados e aos '
            'titulares compete à CONTRATANTE, na qualidade de controladora, com o '
            'apoio técnico da NeuroDoc.',
        ],
    },
    {
        'titulo': 'Da disponibilidade e da responsabilidade',
        'itens': [
            'A NeuroDoc empreenderá esforços para manter o sistema disponível de '
            'forma contínua, ressalvadas as interrupções programadas, comunicadas '
            'com antecedência sempre que possível, e as decorrentes de caso '
            'fortuito, força maior ou falha de terceiros.',

            'A NeuroDoc não responde pelo conteúdo clínico registrado, pela conduta '
            'médica adotada, pela exatidão do que a CONTRATANTE inserir, nem pelo '
            'uso que ela faça do sistema em desacordo com este contrato.',

            'Ressalvadas as hipóteses de dolo, de culpa grave e a responsabilidade '
            'que a lei imponha independentemente de previsão contratual, a '
            'responsabilidade da NeuroDoc por perdas e danos fica limitada ao valor '
            'pago pela CONTRATANTE nos 12 (doze) meses anteriores ao evento.',

            'A limitação acima não se aplica a dano decorrente de violação de dados '
            'pessoais causada por descumprimento, pela NeuroDoc, de suas obrigações '
            'de operadora.',
        ],
    },
    {
        'titulo': 'Da propriedade intelectual e da confidencialidade',
        'itens': [
            'O sistema, seu código, sua identidade visual e sua documentação são de '
            'titularidade da NeuroDoc. Este contrato concede licença de uso, e não '
            'transfere propriedade.',

            'Os dados registrados pela CONTRATANTE são dela, e nada neste contrato '
            'transfere sua titularidade à NeuroDoc.',

            'As partes manterão sigilo sobre as informações a que tiverem acesso em '
            'razão deste contrato, pelo prazo de sua vigência e por 5 (cinco) anos '
            'após o término.',
        ],
    },
    {
        'titulo': 'Das alterações e do foro',
        'itens': [
            'Este contrato é identificado por versão. Alteração de texto gera '
            'versão nova, comunicada à CONTRATANTE com 30 (trinta) dias de '
            'antecedência; a versão aceita permanece válida até que ela aceite a '
            'seguinte.',

            'Alteração que seja desfavorável à CONTRATANTE lhe assegura rescindir '
            'sem ônus até o início da vigência da nova versão, com devolução '
            'proporcional.',

            'Fica eleito o foro da comarca do domicílio da CONTRATANTE para dirimir '
            'controvérsias oriundas deste contrato.',
        ],
    },
]


def texto_simples():
    """O contrato em texto puro, para o corpo do e-mail e para o anexo.

    Gerado do mesmo `CLAUSULAS` que a tela renderiza: um segundo texto
    escrito à mão divergiria do primeiro, e a divergência apareceria
    exatamente onde não pode — entre o que a pessoa leu e o que ela
    recebeu por escrito.
    """
    linhas = [TITULO, SUBTITULO, f'Versão {VERSAO}', '']
    for numero, clausula in enumerate(CLAUSULAS, start=1):
        linhas.append(f'{numero}. {clausula["titulo"].upper()}')
        for indice, item in enumerate(clausula['itens'], start=1):
            linhas.append(f'   {numero}.{indice}. {item}')
        linhas.append('')
    return '\n'.join(linhas)

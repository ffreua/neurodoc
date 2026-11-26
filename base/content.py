"""O texto da página de vendas.

Fica em Python, e não dentro do template, por uma razão prática: o que a
página promete precisa ser conferível. Um roteiro de verificação consegue
afirmar que nenhum item de `RECURSOS` fala de coisa não homologada, e
consegue comparar a lista com a documentação; dentro do HTML, a mesma
conferência viraria uma busca por substring no markup.

**Nada aqui é promessa.** Cada item corresponde a funcionalidade que
existe no produto e tem documento de homologação em `docs/homologation/`.
Quando algo estiver em desenvolvimento, ele não entra nesta lista — entra
quando estiver pronto. Esta regra vale para quem escreve o texto; ela não
precisa estar escrita **na página**, onde soaria como quem se defende de
uma acusação que ninguém fez.

**Sem depoimento e sem estatística.** Depoimento fabricado de médico é
falso testemunho sobre produto de saúde; um contador em zero anuncia que
não há clientes. Quando houver clínicas no piloto, os números entram
medidos.

**O tom é de vendas, e direto** (2026-11-18, pedido do titular): a página
existe para converter, e diz isso sem pudor — o ganho na rotina, em verbo de
ação, e o chamado para começar. O que não muda é o de cima: chamativo é dizer
sem rodeio o que o produto faz, nunca aumentar o que ele faz. Quem lê
examina pacientes com queixa neurológica e reconhece exagero de longe.

**O NeuroDoc é de neurologia e neurocirurgia.** Até 2026-11-18 a página dizia
que ele servia a qualquer especialidade; para isso existe o ProntDoc, do mesmo
time (`PRONTDOC`), e a página aponta para ele.
"""

#: Quem escreveu o sistema.
#:
#: A única seção da página que fala de pessoa, e ela existe por uma razão
#: comercial concreta: prontuário é a coisa mais sensível que um médico
#: entrega a um fornecedor, e a primeira pergunta de quem avalia um é
#: "quem está do outro lado". Um CNPJ não responde isso.
#:
#: As linguagens entram porque contam uma história que o currículo médico
#: sozinho não conta — Clipper e COBOL não são enfeite de nostalgia: são
#: a prova de que quem escreveu isto programa há décadas, e não aprendeu a
#: programar para fazer este produto.
#:
#: Aqui, e não no template, pela mesma razão do resto deste módulo: um
#: roteiro de verificação consegue afirmar que a seção existe e que a
#: frase de impacto está na página.
AUTOR = {
    'nome': 'Dr. Fernando Freua',
    'foto': 'onboarding/fernando-freua.jpeg',
    'frase': 'Feito por um neurologista para neurologistas e neurocirurgiões',
    'resumo': 'Neurologista pelo HC-FMUSP e doutor em Ciências pela USP. '
              'Programa em Clipper, COBOL e Python — o prontuário que você está '
              'vendo foi escrito por quem atende há muitos anos e sabe, de '
              'consulta em consulta, qual informação faz falta na hora de '
              'conduzir um caso e de acompanhá-lo ao longo do tempo.',
    'linguagens': ['Clipper', 'COBOL', 'Python'],
    'credenciais': [
        'Médico neurologista pelo Hospital das Clínicas da Universidade de São Paulo (HC-FMUSP)',
        'Doutor em Ciências pela Universidade de São Paulo (USP), programa de Neurologia',
        'Coordenador executivo do ambulatório de doenças neurológicas raras e '
        'neurogenética do HC-FMUSP (Ambulatório NCL6500) e vice-coordenador do '
        'fellow em neurogenética e doenças raras da USP',
        'Cocoordenador da disciplina de Neurogenética da pós-graduação da USP',
        'Neurologista do pronto atendimento de neurologia do HC-FMUSP',
        'Neurologista do grupo de interconsultas neurológicas do HC-FMUSP',
        'Médico e pesquisador da Divisão de Neurologia Clínica do HC-FMUSP',
        'Professor dos residentes de neurologia da USP e dos alunos do sexto ano',
        'Médico do corpo clínico do Hospital Sírio-Libanês de São Paulo',
        'Neurologista do núcleo de neurogenética e doenças raras do Hospital Sírio-Libanês',
        'Líder da Neurologia no Hospital Samaritano Higienópolis',
        'MSL no Laboratório de Neurodiagnóstico Senne Liquor',
        'CEO do Centro de Pesquisa Raros Brasil',
    ],
    'site': {'rotulo': 'rarosbrasil.com.br', 'url': 'https://www.rarosbrasil.com.br'},
}

#: O código-fonte é público, e a página diz onde.
#:
#: Até 2026-10-19 o repositório era privado e a página mandava escrever
#: pedindo acesso. Aberto, o pedido muda de natureza: quem usa o código
#: sem pagar nada é convidado a dizer que usou (a estrela) e, se quiser, a
#: contribuir com qualquer valor. O PIX é a chave e não um QR: uma chave
#: se copia e se confere a olho; um QR numa página que qualquer um pode
#: imitar pede confiança no desenho.
#:
#: Desde 2026-11-18 a página cita o código aberto numa linha discreta, na
#: seção do autor, e não num destaque: quem chega para comprar quer saber o
#: que o sistema faz por ele, e a licença é argumento de confiança, não de
#: venda (pedido do titular).
#:
#: Aqui, e não no template, pela razão do resto do módulo — e porque o
#: README repete os mesmos dois endereços, e `check_landing` confere que a
#: página mostra exatamente estes.
CODIGO_ABERTO = {
    'licenca': 'MIT',
    'repositorio': 'https://github.com/ffreua/neurodoc',
    'repositorio_rotulo': 'github.com/ffreua/neurodoc',
    'pix': 'fernando.freua@gmail.com',
}

#: Onde o NeuroDoc fala fora do produto (2026-11-06). Um endereço só, lido
#: pela faixa da página de vendas, pelo rodapé de toda página pública e pelo
#: `sameAs` do JSON-LD — escrito à mão em três lugares, o primeiro perfil
#: renomeado deixaria dois links quebrados e o Google apontando para o velho.
INSTAGRAM = {
    'usuario': '@neurodoc_prontuario',
    'url': 'https://www.instagram.com/neurodoc_prontuario/',
}

#: O aviso que a página mostra uma vez a cada visitante (fechado, não volta:
#: `static/onboarding/landing.js` guarda a `chave` no navegador). Uma novidade
#: de cada vez, e só o que **já funciona** em produção — a regra do topo deste
#: módulo vale também aqui. Trocar a `chave` faz o aviso aparecer de novo
#: para quem fechou o anterior; `None` tira o aviso da página.
#:
#: 2026-10-29: o primeiro bloco real do SNCR foi pedido em produção e a
#: primeira RCE eletrônica numerada foi assinada e conferida no portal da
#: Anvisa (`docs/sncr/ESTADO_EXECUCAO.md`).
#:
#: 2026-10-30 (1.30): o faturamento TISS e a agenda de exames. A chave nova
#: faz o aviso aparecer também para quem fechou o do SNCR.
#:
#: 2026-11-25 (1.60): a LME do medicamento de alto custo e o WhatsApp pela
#: conta Twilio da clínica. O WhatsApp é dito "em liberação": a chave da
#: instalação nasce recolhida (`docs/governance/whatsapp-twilio.md`), e a
#: vitrine não promete o que a clínica ainda não consegue ligar sozinha.
NOVIDADE = {
    'chave': 'lme-whatsapp-2026-11',
    'selo': 'Novidade',
    'titulo': 'LME de alto custo no modelo do Ministério e WhatsApp automático',
    'texto': 'A LME sai no formulário oficial do Ministério da Saúde, já com os dados do '
             'paciente e os medicamentos, para imprimir, assinar e carimbar. E, em '
             'liberação, os lembretes por WhatsApp pela conta Twilio da própria clínica.',
    'link': '/ajuda/lme/',
    'link_rotulo': 'Como emitir a LME',
}

#: O produto irmão, para as outras especialidades (2026-11-18). O NeuroDoc é
#: de neurologia e neurocirurgia; quem chega aqui de outra especialidade é
#: encaminhado, e não convencido a usar um prontuário que não foi feito para
#: ele. A vitrine, as páginas de entrada da busca e o `llms.txt` leem daqui.
PRONTDOC = {
    'nome': 'ProntDoc',
    'url': 'https://prontdoc.app.br/',
    'rotulo': 'prontdoc.app.br',
    'titulo': 'Não é da neurologia? Conheça o ProntDoc.',
    'texto': 'O mesmo time, a mesma segurança, para qualquer especialidade: prontuário '
             'em texto livre, receita controlada no SNCR, TISS, portal do paciente e IA. '
             'O NeuroDoc continua sendo o especialista em neurologia e neurocirurgia.',
    'cta': 'Conhecer o ProntDoc',
}

#: Os cinco trunfos da página (2026-11-18): o que mais vende, cada um com a
#: prévia ao lado. A ordem é a decisão do titular — a IA primeiro.
TRUNFOS = [
    {
        'chave': 'ia',
        'selo': 'IA clínica · plano Completo',
        'titulo': 'Uma IA que escreve o rascunho. Você só revisa e assina.',
        'texto': 'Resumo do atendimento, relatório para o paciente, apoio diagnóstico e '
                 'conversa sobre o caso — em segundos. O texto sai sem nome nem documento, '
                 'e nada entra no prontuário sem a sua revisão.',
        'itens': [
            'Resumo do atendimento pronto para aprovar',
            'Relatório do paciente redigido, revisado e assinado por você',
            'Apoio diagnóstico com hipóteses para você avaliar',
            'Chat do caso com o prontuário como fonte — e que ensina a usar o sistema',
            'Desidentificação antes de sair; provedor e chave próprios, se a clínica quiser',
        ],
        'link': '/recursos/inteligencia-artificial/', 'rotulo': 'Ver a IA em detalhe',
    },
    {
        'chave': 'portal',
        'selo': 'Portal do paciente + WhatsApp',
        'titulo': 'Recepção desafogada: menos telefone, menos WhatsApp.',
        'texto': 'O paciente pede a receita pelo portal, sem conta e sem ligar. A '
                 'secretária manda o lembrete pelo WhatsApp da clínica com um clique, a '
                 'mensagem já escrita.',
        'itens': [
            'Pedido de receita, relatório e exame pelo portal, sem conta',
            'Laudos em PDF direto no prontuário, com aviso ao médico',
            'Botão WhatsApp na agenda e no balcão, com o lembrete pronto',
            'Confirmação por e-mail e, nos planos pagos, por SMS',
            'Regra dos 180 dias do CFM, se a clínica quiser exigir',
        ],
        'link': '/recursos/portal-do-paciente/', 'rotulo': 'Ver o portal',
    },
    {
        'chave': 'receita',
        'selo': 'SNCR · Anvisa',
        'titulo': 'Receita controlada eletrônica, com a numeração da Anvisa.',
        'texto': 'Receita de Controle Especial e Notificação de Receita A, B e B2 '
                 'eletrônicas, no modelo oficial do SNCR. Sem talonário, sem caneta.',
        'itens': [
            'Os números do médico, pedidos pelo Gov.br',
            'Portaria 344 conferida na hora: o tipo certo de receita apontado',
            'Uma folha e um número por medicamento',
            'Assinada com o seu certificado digital',
            'Vinte e seis mil apresentações da CMED na busca',
        ],
        'link': '/recursos/receita-controlada-sncr/', 'rotulo': 'Como funciona',
    },
    {
        'chave': 'tiss',
        'selo': 'TISS · ANS · plano Completo',
        'titulo': 'Convênio faturado no padrão TISS, sem redigitar nada.',
        'texto': 'Guias de Consulta e SP/SADT preenchidas com o que o sistema já sabe, e '
                 'lotes em XML validados no esquema da ANS, na versão que cada operadora aceita.',
        'itens': [
            'Da versão 3.04 à 4.03, validadas no XSD oficial',
            'Consulta do check-in vinculada, sem cobrança duplicada',
            'Agenda de EEG, ENMG e polissonografia por equipamento',
            'Exame realizado vira cobrança e guia SP/SADT',
        ],
        'link': '/recursos/faturamento-tiss/', 'rotulo': 'Ver o TISS',
    },
    {
        'chave': 'registro',
        'selo': 'Estruturado ou texto livre',
        'titulo': 'Do seu jeito: exame estruturado ou texto livre — e 14 escalas.',
        'texto': 'Gosta de estrutura? 387 itens por eixo, com "tudo normal" por grupo. '
                 'Prefere escrever? Folha em branco com a consulta anterior ao lado. As '
                 'escalas valem nos dois, e viram gráfico.',
        'itens': [
            'Primeira consulta, seguimento e texto livre no mesmo editor',
            'NIHSS, Glasgow, Rankin, Hoehn e Yahr, MEEM, ALSFRS-R, SARA e mais',
            'Escore e interpretação calculados, evolução em gráfico',
            'Consulta anterior a um clique, aceita item a item',
        ],
        'link': '/recursos/escalas-neurologicas/', 'rotulo': 'Ver as 14 escalas',
    },
]

#: Os três cartões de "Novo no NeuroDoc". Cada um leva ao artigo do manual
#: que mostra a função — a regra do topo deste módulo: só o que existe, e
#: conferível.
NOVIDADES = [
    {
        'icone': 'LME',
        'titulo': 'LME do medicamento de alto custo',
        'texto': 'O laudo do CEAF no formulário oficial do Ministério da Saúde, com os dados '
                 'do paciente, até seis medicamentos e a quantidade de seis meses. Sai para '
                 'imprimir, assinar e carimbar. Em todos os planos.',
        'link': '/ajuda/lme/', 'rotulo': 'Como emitir',
    },
    {
        'icone': 'WA',
        'titulo': 'WhatsApp automático pela sua conta Twilio',
        'texto': 'Em liberação: lembrete, aviso de horário e documento disponível por '
                 'WhatsApp, com modelos aprovados pela Meta, pela conta e pelo número da '
                 'própria clínica — que paga a mensagem direto à Twilio. Sem dado clínico.',
        'link': '/ajuda/whatsapp-twilio/', 'rotulo': 'Como configurar',
    },
    {
        'icone': '℞',
        'titulo': 'Receita digital com numeração da Anvisa',
        'texto': 'Receita de Controle Especial, de Retenção e Notificação de Receita A, B e '
                 'B2 eletrônicas no modelo do SNCR, com os números do médico e o seu '
                 'certificado digital.',
        'link': '/ajuda/receita-sncr/', 'rotulo': 'Como emitir',
    },
]

#: Cada item: o que a clínica ganha, não o que o código faz.
RECURSOS = [
    {
        'titulo': 'Exame neurológico estruturado em árvore',
        'texto': 'Trezentos e oitenta e sete itens por eixo — pares cranianos, motor, '
                 'sensibilidade, coordenação, marcha —, com "tudo normal" por grupo. O '
                 'achado anormal salta aos olhos, em vez de se perder num parágrafo que '
                 'ninguém relê daqui a um ano. Prefere escrever? O texto livre está a um clique.',
    },
    {
        'titulo': 'Quatorze escalas com pontuação automática',
        'texto': 'NIHSS, Glasgow, FOUR, RASS, Rankin, Barthel, Hoehn e Yahr, MEEM, '
                 'Pfeffer, Epworth, SARA, ALSFRS-R, MG-ADL e Ashworth, aplicadas no '
                 'atendimento estruturado ou em texto livre. Escore e interpretação '
                 'calculados, e a evolução em gráfico.',
    },
    {
        'titulo': 'Inteligência artificial como copiloto, nunca como autor',
        # "A partir do Completo" fica aqui, e nao so no quadro de planos.
        # Este bloco descreve o produto solto, fora da vitrine, e um
        # visitante que le a lista de recursos e assina o Gratuito
        # descobriria a diferenca depois de pagar. E a mesma divergencia
        # que `plans.has_clinical_ai` corrige do lado do servidor.
        'texto': 'A partir do plano Completo: resumo do atendimento, relatório para o '
                 'paciente, apoio diagnóstico e conversa sobre o caso — e um chat que '
                 'também ensina a usar o sistema —, sempre com revisão médica antes de '
                 'qualquer coisa entrar no prontuário. O texto é desidentificado antes de '
                 'sair, e a clínica pode usar o próprio provedor e a própria chave.',
    },
    {
        'titulo': 'Portal do paciente que desafoga a recepção',
        'texto': 'O paciente pede receita, relatório ou pedido de exames sem criar conta e '
                 'sem ligar — o pedido entra numa fila que só o médico revisa, e quem '
                 'decide o que será emitido continua sendo ele. Pelo mesmo portal, ele '
                 'envia em PDF os laudos dos exames que já fez, direto para o prontuário.',
    },
    {
        'titulo': 'Lembrete pelo WhatsApp da clínica, em um clique',
        'texto': 'Na agenda e no balcão, o botão WhatsApp abre a conversa no número da '
                 'própria clínica com o lembrete já escrito — nome, data, horário, médico '
                 'e endereço. A secretária confere e envia. Em todos os planos. E, em '
                 'liberação, o envio automático pela conta Twilio da própria clínica, com '
                 'modelos aprovados pela Meta e sem dado clínico na mensagem.',
    },
    {
        'titulo': 'LME do medicamento de alto custo, já preenchida',
        'texto': 'O laudo do Componente Especializado (CEAF) sai no formulário oficial do '
                 'Ministério da Saúde com o nome, a mãe, o peso, a altura e o documento do '
                 'paciente, até seis medicamentos com a quantidade de seis meses, CID-10, '
                 'anamnese e o responsável pelo paciente incapaz. O médico completa, imprime, assina e '
                 'carimba; a renovação parte da LME anterior.',
    },
    {
        'titulo': 'Receita controlada com a numeração da Anvisa',
        # A decisão D9 (2026-11-03) manda dizer **aqui** que as Notificações
        # de retinoide e de talidomida não são emitidas: quem procura isso
        # sabe antes de contratar, e dentro do produto a recusa só aparece a
        # quem tenta.
        'texto': 'Integrado ao SNCR (RDC 1.000/2025): o médico pede os próprios números '
                 'com o Gov.br e emite a Receita de Controle Especial, a de Retenção e a '
                 'Notificação de Receita A, B e B2 eletrônicas no modelo oficial, uma folha '
                 'por medicamento, assinadas com o seu certificado digital e com a lista da '
                 'Portaria 344 conferida na hora. As Notificações de retinoide e de '
                 'talidomida não são emitidas pelo NeuroDoc.',
    },
    {
        # "No Completo" no texto, pela mesma razão da IA: quem lê a lista de
        # recursos fora da vitrine não pode descobrir o plano depois de pagar.
        'titulo': 'Faturamento de convênio no padrão TISS',
        'texto': 'No plano Completo: a guia de Consulta e a de SP/SADT nascem com o '
                 'convênio, a carteira e os profissionais que o sistema já conhece, e '
                 'a consulta cobrada no check-in entra sem cobrança duplicada. O lote '
                 'sai em XML na versão que cada operadora aceita — da 3.04 à 4.03 —, '
                 'conferido contra o padrão oficial da ANS antes de você enviar.',
    },
    {
        'titulo': 'Agenda de exames: EEG, ENMG e polissonografia',
        'texto': 'No plano Completo: uma agenda por equipamento, separada da dos '
                 'médicos e sem ocupar vaga de médico. A polissonografia que atravessa '
                 'a noite é um exame só, o equipamento nunca recebe dois pacientes no '
                 'mesmo horário, e o exame realizado vira cobrança quando há honorário.',
    },
    {
        'titulo': 'Receita e laudo assinados, com QR de verificação',
        'texto': 'Receita, laudo, pedido de exame e encaminhamento assinados em PAdES com o '
                 'certificado digital do próprio médico, e com QR de verificação pública: a '
                 'farmácia confere tipo, número, CRM e data sem ter conta no sistema.',
    },
    {
        'titulo': 'A consulta anterior a um toque de distância',
        'texto': 'Conduta, impressões, hipóteses e medicação em uso da última consulta '
                 'aparecem para revisão item a item, e cada um entra no registro de hoje só '
                 'se o médico aceitar. Retorno deixa de começar pela releitura do prontuário.',
    },
    {
        'titulo': 'Agenda por médico, sem sobreposição',
        'texto': 'Grade própria por profissional, com duração por tipo de atendimento, '
                 'bloqueio de horário sobreposto, lista de espera, remarcação visual e '
                 'confirmação por e-mail ou SMS. A recepção marca sem perguntar se cabe.',
    },
    {
        'titulo': 'Guarda de vinte anos, e a trilha de quem fez o quê',
        'texto': 'Prontuário finalizado não se reescreve: correção é adendo, com autor e '
                 'data. Cada alteração e cada emissão ficam numa trilha que o próprio banco '
                 'impede de alterar, e o backup é diário, cifrado e copiado para fora do '
                 'servidor.',
    },
]

#: Para quem o NeuroDoc é, e para onde vai quem não é (2026-11-18).
#:
#: Até aqui esta seção dizia "Nasceu na neurologia. Funciona em qualquer
#: consultório", e convencia o clínico e o ortopedista a ficar. Decisão do
#: titular: o NeuroDoc é de neurologia e neurocirurgia, e quem é de outra
#: especialidade vai para o ProntDoc (`PRONTDOC`), feito para ele. `areas`
#: são as páginas de entrada da busca (`base/paginas_seo.py::AREAS`), lidas
#: de lá para a lista não divergir.
ESPECIALIDADES = {
    'titulo': 'Feito para a neurologia. Inteiro.',
    'texto': 'Do pronto atendimento ao ambulatório de subespecialidade: escalas, exame '
             'por eixo, agenda de EEG, ENMG e polissonografia, receita controlada e o '
             'seguimento de anos. Escolha a sua área.',
    'fecho': 'Atende outra especialidade? O ProntDoc é o prontuário eletrônico do mesmo '
             'time para qualquer especialidade — com texto livre, receita controlada no '
             'SNCR, TISS, portal do paciente e IA.',
}

def _resposta_pagamento(checkout=False):
    """A regra de pagamento, com os números de `tenancy/plans.py`.

    Montada, e não escrita: a resposta cita percentuais e valores, e uma
    cópia à mão diria "20%" no dia em que o anual passasse a 15%.

    `checkout` é a chave do checkout da Asaas (1.46): ligada, a resposta
    diz como se contrata pela página; desligada, continua dizendo que não há
    pagamento on-line. Quem decide é `faq()`, lendo a chave a cada página.
    """
    from tenancy.plans import PERIODICIDADES, PLANS, PlanCode, parcelas_no_cartao, preco_na_periodicidade

    def valores(code):
        partes = []
        for periodicidade in PERIODICIDADES:
            v = preco_na_periodicidade(code, periodicidade)
            mensal, ano = v['mensal'], v['ano']
            partes.append('%s R$ %d,%02d/mês (R$ %s no ano)' % (
                periodicidade.label.lower(), mensal // 100, mensal % 100,
                f'{ano // 100:,}'.replace(',', '.') + ',%02d' % (ano % 100)))
        return '; '.join(partes)

    anual = PERIODICIDADES['anual']['desconto']
    semestral = PERIODICIDADES['semestral']['desconto']
    # O parcelamento só é dito quando o contrato vigente o prevê
    # (`parcelas_no_cartao`): a vitrine não promete o que o checkout não faz.
    p_anual, p_semestral = parcelas_no_cartao('anual'), parcelas_no_cartao('semestral')
    parcelamento = (
        'No cartão, o anual pode ser parcelado em até %dx sem juros e o semestral em '
        'até %dx sem juros; o trimestral e o Pix são à vista. ' % (p_anual, p_semestral)
    ) if p_anual > 1 else ''
    if checkout:
        como = (
            'O Gratuito não tem cobrança, e o Personalizado é combinado. O Básico e o '
            'Completo podem ser contratados na própria página, pela Asaas, por Pix ou '
            'cartão. ' + parcelamento + 'Pago, o link para criar a clínica chega na hora. Também dá para '
            'combinar conosco e receber um código de convite; nos dois casos, plano e '
            'período ficam registrados no aceite do contrato. Trinta e quinze dias antes '
            'do fim do período, o responsável pela clínica é avisado no sistema e por '
            'e-mail, e renova ali mesmo, escolhendo de novo o período e aceitando de novo '
            'o contrato. '
        )
    else:
        como = (
            'O Gratuito não tem cobrança, e o Personalizado é combinado. Não há pagamento '
            'on-line: o acesso é liberado por um código de convite com o plano e o período '
            'combinados, que ficam registrados no aceite do contrato. '
        )
    como += (
        'Sem renovação, quinze dias depois do fim do período a clínica passa ao plano '
        'Gratuito: nada é apagado, e renovar devolve o plano.'
    )
    return (
        'Você escolhe o período, e cada um é pago de uma vez, sem renovação '
        f'automática: 12 meses, com {anual}% de desconto de lançamento; 6 meses, com '
        f'{semestral}% de desconto; ou 3 meses, pelo preço cheio. Os descontos valem só '
        'para o período em que estão escritos. '
        f'No Básico: {valores(PlanCode.BASIC)}. No Completo: {valores(PlanCode.COMPLETE)}. '
        + como
    )


def _resposta_residentes():
    """A promoção de início de carreira, com os números de `tenancy/plans.py`."""
    from tenancy.plans import PROMOCAO_INICIO_DE_CARREIRA as promo, preco_inicio_de_carreira

    precos = '; '.join(
        f'{p["label"]} por {p["mensal"]}/mês ({p["ano"]} no ano)'
        for p in map(preco_inicio_de_carreira, promo['planos'])
    )
    return (
        f'Sim, e é permanente: {promo["publico"]} têm {promo["desconto"]}% de desconto '
        f'sobre o preço cheio dos planos Básico e Completo, no pagamento anual — {precos}. '
        'O desconto substitui o de lançamento do anual, não se soma a ele. Para '
        f'comprovar, basta a {promo["comprovacao"]}.'
    )


#: Perguntas que um médico faz antes de confiar o prontuário a alguém. As
#: respostas dizem o que o sistema faz — inclusive quando a resposta é
#: desconfortável, como a do item sobre o que ainda não existe.
from tenancy import degustacao as _degustacao  # noqa: E402
from tenancy.plans import PLANS as _PLANS, PlanCode as _PlanCode  # noqa: E402

#: Os limites do Gratuito, lidos do catálogo: a resposta dizia "até 50" à mão.
_GRATUITO = _PLANS[_PlanCode.FREE]

FAQ = [
    # Esta vem primeiro porque é a pergunta que decide se as outras
    # importam. Quem não é neurologista chega ao FAQ depois de ler uma
    # página inteira sobre exame neurológico, e enquanto não souber se o
    # sistema serve ao consultório dele, nenhuma resposta sobre sigilo ou
    # assinatura muda coisa alguma.
    {
        'pergunta': 'O NeuroDoc serve para outras especialidades?',
        'resposta': 'O NeuroDoc é feito para neurologia e neurocirurgia: roteiro de exame '
                    'neurológico com trezentos e oitenta e sete itens, catorze escalas '
                    'pontuadas e agenda de EEG, ENMG e polissonografia. Para as outras '
                    'especialidades existe o ProntDoc (prontdoc.app.br), do mesmo time, com '
                    'prontuário em texto livre, receita controlada no SNCR, TISS, portal do '
                    'paciente e inteligência artificial.',
    },
    {
        'pergunta': 'Dá para reduzir as ligações e o WhatsApp da recepção?',
        'resposta': 'Dá. Pelo portal, o paciente pede receita, relatório ou pedido de exame e '
                    'envia os laudos em PDF, sem criar conta e sem ligar — o pedido chega numa '
                    'fila que só o médico revisa. E o lembrete de consulta sai pelo WhatsApp '
                    'da própria clínica num clique, com a mensagem já escrita; quem envia é a '
                    'recepção, do número que o paciente conhece. A confirmação automática sai '
                    'por e-mail e, nos planos pagos, por SMS. Em liberação, o envio automático '
                    'por WhatsApp pela conta Twilio da própria clínica.',
    },
    {
        'pergunta': 'O NeuroDoc emite a LME de medicamento de alto custo?',
        'resposta': 'Emite. A LME sai no formulário oficial do Ministério da Saúde, preenchida '
                    'com os dados do paciente e os medicamentos com a quantidade de cada mês, '
                    'para o médico imprimir, assinar à mão e carimbar. A lista de medicamentos '
                    'do formulário aparece como sugestão, e o médico pode escrever qualquer outro.',
    },
    {
        'pergunta': 'Quem consegue ler o prontuário dos meus pacientes?',
        'resposta': 'Apenas quem tem vínculo clínico na sua clínica. Quem opera o '
                    'servidor vê quantas organizações existem, quem tem conta e a '
                    'trilha de quem fez o quê — nunca o conteúdo clínico. O console '
                    'de administração não abre prontuário, e isso é verificado a cada '
                    'versão.',
    },
    {
        'pergunta': 'Os documentos assinados têm validade?',
        'resposta': 'A assinatura é PAdES, o padrão usado em documento eletrônico '
                    'brasileiro, aplicada com o certificado do próprio médico. Cada '
                    'documento sai com um código de verificação pública: qualquer '
                    'farmácia confere tipo, número, médico, CRM e data sem ter conta '
                    'no sistema. Para assinar, basta cadastrar o seu certificado digital.',
    },
    {
        'pergunta': 'E se eu passar do limite de pacientes do plano?',
        'resposta': 'O sistema avisa quando você chega a 80% da cota e recusa apenas '
                    'o cadastro seguinte quando o limite é atingido. Nada do que já '
                    'está registrado é apagado, arquivado ou escondido — prontuário '
                    'tem guarda legal de vinte anos, e ela não conhece plano de '
                    'assinatura. Arquivar um paciente que não é mais acompanhado '
                    'libera uma vaga.',
    },
    {
        'pergunta': 'A inteligência artificial dá diagnóstico?',
        'resposta': 'Não, e não é isso que ela se propõe a fazer. Ela redige, resume '
                    'e organiza; o médico aceita, edita ou rejeita cada sugestão, e o '
                    'registro guarda o que foi feito. Sugestão não aceita não entra no '
                    'prontuário.',
    },
    {
        'pergunta': 'Meus dados vão para onde?',
        'resposta': 'O prontuário fica no banco de dados da instalação. Para a IA, o '
                    'texto passa por desidentificação local antes de sair, e sua '
                    'clínica pode cadastrar o próprio provedor e a própria chave — os '
                    'dados vão então para o contrato que você escolheu, não para o '
                    'nosso.',
    },
    {
        'pergunta': 'Como faço backup?',
        'resposta': 'O backup é automático, cifrado com uma chave que fica fora do '
                    'servidor, e a restauração é um procedimento documentado e testado. '
                    'A chave que abre o backup fica sob a guarda da mantenedora, fora do '
                    'servidor, e a exportação do acervo está sempre à mão do responsável.',
    },
    {
        'pergunta': 'Posso começar de graça?',
        'resposta': f'Pode, e agora mesmo. O plano Gratuito atende até {_GRATUITO["max_patients"]} '
                    f'pacientes e {_GRATUITO["max_doctors"]} médico, sem cartão de crédito e sem prazo para acabar. Clique '
                    'em "Começar agora" no cartão do plano e você cai direto na tela '
                    'de criação da clínica — nenhum contato comercial no caminho.',
    },
    # Os números da degustação vêm de `tenancy/degustacao.py`, que é onde o
    # servidor os cobra: a resposta não pode prometer um dia ou um pedido de
    # IA a mais do que o oitavo dia entrega.
    {
        'pergunta': 'Posso testar o plano Completo antes de contratar?',
        'resposta': f'Pode, por {_degustacao.DIAS} dias e sem cartão. Clique em "Testar o '
                    'Completo" no cartão do plano: a clínica nasce no Completo, com a IA '
                    f'clínica ({_degustacao.TETO_IA} pedidos) e o SMS ({_degustacao.TETO_SMS} '
                    'mensagens) incluídos. Ao fim da degustação ela volta ao plano Gratuito, '
                    'que é o contrato aceito no cadastro, e nada é apagado. Se houver mais '
                    'de um médico, o responsável escolhe quem continua com o perfil médico; '
                    'os outros voltam ao contratar.',
    },
    {
        'pergunta': 'Dá para migrar depois, se a clínica crescer?',
        'resposta': 'Dá, e nada se perde na troca. Mudar de plano altera os limites '
                    'e libera o que o plano novo inclui; paciente, atendimento, '
                    'documento e agenda continuam exatamente onde estavam. Rebaixar '
                    'também não apaga nada: o que passou do limite fica legível, o '
                    'sistema deixa de aceitar cadastro novo e, acima do limite de médicos, '
                    'o perfil médico fica com quem o responsável escolher.',
    },
    {
        'pergunta': 'Como funciona o pagamento dos planos?',
        'resposta': _resposta_pagamento(),
    },
    {
        'pergunta': 'Há desconto para residentes e recém-formados?',
        'resposta': _resposta_residentes(),
    },
    {
        'pergunta': 'O NeuroDoc envia o lote TISS direto para a operadora?',
        'resposta': 'Ainda não. O NeuroDoc preenche as guias, monta os lotes e gera o '
                    'arquivo XML conferido contra o padrão oficial da ANS, na versão que '
                    'a operadora aceita; você envia o arquivo pelo portal da operadora e '
                    'registra o protocolo no lote. O faturamento TISS e a agenda de '
                    'exames fazem parte do plano Completo.',
    },
    {
        'pergunta': 'O que ainda não existe?',
        'resposta': 'Pagamento on-line, teleconsulta, integração com PACS/DICOM e o '
                    'envio automático do lote TISS ao webservice das operadoras não '
                    'fazem parte desta versão.',
    },
]


def faq():
    """O FAQ como a página deve dizê-lo agora — com a chave do checkout lida.

    Duas respostas dependem de o checkout da Asaas estar ligado no console
    (1.46): a do pagamento e a do que ainda não existe. A chave muda sem
    deploy, e `FAQ` é montado na importação; por isso as três portas que o
    publicam — a página de vendas, o JSON-LD e o `llms-full.txt` — leem
    daqui, e não da lista. Sem banco (a chave não pode ser lida), vale a
    redação de chave desligada: é a que nunca promete o que não há.
    """
    try:
        from contratacao.views import checkout_ligado

        ligado = checkout_ligado()
    except Exception:  # noqa: BLE001
        ligado = False
    if not ligado:
        return FAQ
    itens = []
    for item in FAQ:
        if item['pergunta'] == 'Como funciona o pagamento dos planos?':
            item = dict(item, resposta=_resposta_pagamento(checkout=True))
        elif item['pergunta'] == 'O que ainda não existe?':
            item = dict(item, resposta='Teleconsulta, integração com PACS/DICOM e o envio '
                                       'automático do lote TISS ao webservice das operadoras '
                                       'não fazem parte desta versão.')
        itens.append(item)
    return itens

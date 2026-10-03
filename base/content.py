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

**O tom é de especialista para especialista.** Quem lê isto examina
pacientes com queixa neurológica e sabe o que é um reflexo assimétrico.
Não há por que explicar o que ele faz melhor do que nós, nem adjetivar o
que o produto faz: o ganho aparece quando se diz exatamente o que
acontece na tela e o que deixa de acontecer na rotina.
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

#: Cada item: o que a clínica ganha, não o que o código faz.
RECURSOS = [
    {
        'titulo': 'Exame neurológico estruturado em árvore',
        'texto': 'Trezentos e oitenta e sete itens organizados por eixo — pares '
                 'cranianos, motor, sensibilidade, coordenação, marcha —, com '
                 '"tudo normal" por grupo para o que veio sem alteração. O achado '
                 'anormal fica destacado no registro, em vez de se diluir num '
                 'parágrafo de texto corrido que ninguém relê daqui a um ano.',
    },
    {
        'titulo': 'Quatorze escalas com pontuação automática',
        'texto': 'NIHSS, Rankin, Hoehn e Yahr, MEEG e outras dez, aplicadas dentro '
                 'do atendimento. O escore e a faixa de interpretação saem '
                 'calculados, e ficam na história do paciente — a comparação entre '
                 'a consulta de hoje e a de seis meses atrás deixa de depender de '
                 'procurar o número num texto antigo.',
    },
    {
        'titulo': 'Receita e laudo assinados com PAdES',
        'texto': 'Receita, laudo, pedido de exame e encaminhamento assinados com o '
                 'certificado do próprio médico, no padrão PAdES, e com QR de '
                 'verificação pública: a farmácia confere tipo, número, CRM e data '
                 'sem ter conta no sistema. Controle especial sai em duas vias, com '
                 'o quadro da Portaria 344/98.',
    },
    {
        'titulo': 'A consulta anterior a um toque de distância',
        'texto': 'Conduta, impressões, hipóteses e medicação em uso da última '
                 'consulta aparecem para revisão item a item, e cada um entra no '
                 'registro de hoje só se o médico aceitar. Retorno de seguimento '
                 'deixa de começar pela releitura do prontuário inteiro.',
    },
    {
        'titulo': 'Agenda por médico, sem sobreposição',
        'texto': 'Grade própria por profissional, com duração por tipo de '
                 'atendimento, bloqueio de horário sobreposto, remarcação visual e '
                 'confirmação por e-mail ou SMS. A recepção marca sem precisar '
                 'perguntar se o horário cabe.',
    },
    {
        'titulo': 'Portal do paciente para renovação de receita',
        'texto': 'O paciente pede a renovação sem criar conta e sem ligar para a '
                 'recepção. O pedido entra numa fila que exige capacidade clínica: '
                 'quem decide o que será emitido, e se será, continua sendo o '
                 'médico.',
    },
    {
        'titulo': 'Inteligência artificial como copiloto, nunca como autor',
        # "A partir do Completo" fica aqui, e nao so no quadro de planos.
        # Este bloco descreve o produto solto, fora da vitrine, e um
        # visitante que le a lista de recursos e assina o Gratuito
        # descobriria a diferenca depois de pagar. E a mesma divergencia
        # que `plans.has_clinical_ai` corrige do lado do servidor.
        'texto': 'A partir do plano Completo: resumo do atendimento, leitura de laudo '
                 'e conversa sobre o caso, sempre com revisão médica antes de '
                 'qualquer coisa entrar no prontuário. O texto é desidentificado '
                 'antes de sair, e o envio é recusado quando não satisfaz a política '
                 'de privacidade — a clínica pode usar o próprio provedor e a '
                 'própria chave.',
    },
    {
        'titulo': 'Guarda de vinte anos, e a trilha de quem viu o quê',
        'texto': 'Prontuário finalizado não se reescreve: correção é adendo, com '
                 'autor e data. Cada acesso e cada emissão ficam numa trilha que o '
                 'próprio banco impede de alterar, e o backup é automático e '
                 'cifrado com uma chave que fica fora do servidor.',
    },
]

#: O que, neste sistema, não é de neurologia.
#:
#: Existe por uma razão medida em visitante perdido: a página inteira fala
#: de neurologia, e um clínico, um ortopedista ou um psiquiatra que chegue
#: aqui por busca conclui em dez segundos que o produto não é para ele — e
#: vai embora sem procurar a resposta. A resposta é sim, e é conferível:
#: atendimento em texto livre, agenda, receita com a lista da Anvisa,
#: assinatura, portal e financeiro não sabem o que é um reflexo.
#:
#: **Sem prometer o que não existe**, que é a regra do topo deste módulo.
#: Não há roteiro de exame de outra especialidade, e a ressalva diz isso
#: com todas as letras — em vez de deixar o ortopedista descobrir depois
#: de migrar o cadastro.
ESPECIALIDADES = {
    'titulo': 'Nasceu na neurologia. Funciona em qualquer consultório.',
    'texto': 'A neurologia é a especialidade mais exigente em registro de exame '
             'físico — são trezentos e oitenta e sete verificações, catorze '
             'escalas e um seguimento que dura anos. Um prontuário que dá conta '
             'disso dá conta do resto com folga. Tudo que não é o roteiro '
             'neurológico serve a qualquer especialidade, sem configuração e sem '
             'versão diferente do produto.',
    'comum': [
        ('Atendimento em texto livre',
         'O prontuário tem dois tipos, e o segundo é uma folha em branco com a '
         'consulta anterior ao lado. É como a maior parte das especialidades '
         'registra, e é o padrão de quem não usa o roteiro.'),
        ('Agenda por profissional',
         'Grade própria por médico, duração por tipo de atendimento, bloqueio de '
         'horário sobreposto, feriado, retorno programado e confirmação por '
         'e-mail ou SMS.'),
        ('Receita com a lista inteira da Anvisa',
         'Vinte e seis mil apresentações da CMED, com a tarja de cada uma. '
         'Receita simples e de controle especial, esta em duas vias e com o '
         'quadro da Portaria 344/98.'),
        ('Documento assinado digitalmente',
         'Laudo, atestado, declaração de comparecimento, pedido de exame e '
         'encaminhamento, assinados em PAdES com o certificado do próprio '
         'médico e verificáveis por QR.'),
        ('CID-10 e TUSS completos',
         'O catálogo inteiro, não um recorte de neurologia: diagnóstico, '
         'procedimento e o espelho da TUSS atualizado toda semana.'),
        ('Convênio, honorário e recebível',
         'Tabela de honorários com vigência, convênios por paciente, '
         'recebíveis, pagamentos e ajustes — tudo em centavos, sem ponto '
         'flutuante.'),
        ('Portal do paciente e entrega por link',
         'O paciente pede receita, relatório ou exame sem criar conta, e recebe '
         'o documento por link com código de acesso.'),
        ('IA que redige, médico que assina',
         'Resumo do atendimento, leitura de laudo e relatório para o paciente. '
         'O texto sai desidentificado e nada entra no prontuário sem o médico '
         'aceitar — o que vale para qualquer especialidade.'),
    ],
    'neuro': [
        ('Roteiro de exame neurológico em árvore',
         'Trezentos e oitenta e sete itens por eixo, com "tudo normal" por grupo '
         'e o achado anormal destacado.'),
        ('Catorze escalas com pontuação automática',
         'NIHSS, Rankin, Hoehn e Yahr, MEEM e outras dez, com escore e faixa de '
         'interpretação calculados dentro do atendimento.'),
    ],
    'ressalva': 'Não existe roteiro de exame de outra especialidade, e não vamos '
                'dizer que existe. Quem atende fora da neurologia usa o '
                'atendimento em texto livre — que é como quase todo prontuário do '
                'mercado funciona. O roteiro é o que há a mais aqui, não uma '
                'condição para usar o resto.',
}

#: Perguntas que um médico faz antes de confiar o prontuário a alguém. As
#: respostas dizem o que o sistema faz — inclusive quando a resposta é
#: desconfortável, como a do item sobre o que ainda não existe.
FAQ = [
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
                    'no sistema. A emissão com certificado ICP-Brasil real depende de '
                    'você cadastrar o seu.',
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
                    'A chave de recuperação é do responsável pela clínica.',
    },
    {
        'pergunta': 'Posso começar de graça?',
        'resposta': 'Pode, e agora mesmo. O plano Gratuito atende até 50 pacientes e '
                    'um médico, sem cartão de crédito e sem prazo para acabar. Clique '
                    'em "Começar agora" no cartão do plano e você cai direto na tela '
                    'de criação da clínica — nenhum contato comercial no caminho.',
    },
    {
        'pergunta': 'Dá para migrar depois, se a clínica crescer?',
        'resposta': 'Dá, e nada se perde na troca. Mudar de plano altera os limites '
                    'e libera o que o plano novo inclui; paciente, atendimento, '
                    'documento e agenda continuam exatamente onde estavam. Rebaixar '
                    'também não apaga nada: o que passou do limite fica legível, e o '
                    'sistema apenas deixa de aceitar cadastro novo.',
    },
    {
        'pergunta': 'O que ainda não existe?',
        'resposta': 'Pagamento on-line, faturamento TISS, teleconsulta e integração com '
                    'PACS/DICOM não fazem parte desta versão. Receita de substância '
                    'sujeita a controle especial sai em papel, com as duas vias exigidas, '
                    'e não por transmissão eletrônica a órgão regulador.',
    },
]

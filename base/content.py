"""O texto da pagina de vendas.

Fica em Python, e nao dentro do template, por uma razao pratica: o que a
pagina promete precisa ser conferivel. Um roteiro de verificacao consegue
afirmar que nenhum item de `RECURSOS` fala de coisa nao homologada, e
consegue comparar a lista com a documentacao; dentro do HTML, a mesma
conferencia viraria uma busca por substring no markup.

**Nada aqui e promessa.** Cada item corresponde a funcionalidade que
existe no produto e tem documento de homologacao em `docs/homologation/`.
Quando algo estiver em desenvolvimento, ele nao entra nesta lista - entra
quando estiver pronto.

**Sem depoimento e sem estatistica.** Depoimento fabricado de medico e
falso testemunho sobre produto de saude; um contador em zero anuncia que
nao ha clientes. Quando houver clinicas no piloto, os numeros entram
medidos.
"""

#: Cada item: o que a clinica ganha, nao o que o codigo faz.
RECURSOS = [
    {
        'titulo': 'Exame neurologico estruturado',
        'texto': 'Roteiro em arvore com 387 itens, organizado por eixo, com '
                 '"tudo normal" por grupo. O achado alterado aparece destacado '
                 'em vez de se perder num paragrafo de texto corrido.',
    },
    {
        'titulo': 'Escalas funcionais pontuadas',
        'texto': 'Quatorze escalas com pontuacao automatica e faixa de '
                 'interpretacao, aplicadas dentro do atendimento e guardadas na '
                 'historia do paciente.',
    },
    {
        'titulo': 'Documentos assinados digitalmente',
        'texto': 'Receita, laudo, pedido de exame e encaminhamento com assinatura '
                 'PAdES e QR de verificacao publica. Receita de controle especial '
                 'sai em duas vias, com o quadro da Portaria 344/98.',
    },
    {
        'titulo': 'Agenda por medico',
        'texto': 'Grade propria por profissional, bloqueio de horario sobreposto, '
                 'remarcacao visual e confirmacao por e-mail ou SMS.',
    },
    {
        'titulo': 'Portal do paciente',
        'texto': 'O paciente pede a renovacao de receita sem criar conta. O pedido '
                 'entra numa fila que exige capacidade clinica: quem decide o que '
                 'sera emitido e o medico.',
    },
    {
        'titulo': 'Apoio de inteligencia artificial',
        'texto': 'Resumo do atendimento, leitura de laudo e chat sobre o caso, '
                 'sempre com revisao do medico antes de aceitar. O texto e '
                 'desidentificado antes de sair, e o envio e recusado quando nao '
                 'satisfaz a politica de privacidade.',
    },
]

#: Perguntas que um medico faz antes de confiar o prontuario a alguem. As
#: respostas dizem o que o sistema faz -- inclusive quando a resposta e
#: desconfortavel, como a do item sobre o que ainda nao existe.
FAQ = [
    {
        'pergunta': 'Quem consegue ler o prontuario dos meus pacientes?',
        'resposta': 'Apenas quem tem vinculo clinico na sua clinica. Quem opera o '
                    'servidor ve quantas organizacoes existem, quem tem conta e a '
                    'trilha de quem fez o que -- nunca o conteudo clinico. O console '
                    'de administracao nao abre prontuario, e isso e verificado a cada '
                    'versao.',
    },
    {
        'pergunta': 'Os documentos assinados tem validade?',
        'resposta': 'A assinatura e PAdES, o padrao usado em documento eletronico '
                    'brasileiro, aplicada com o certificado do proprio medico. Cada '
                    'documento sai com um codigo de verificacao publica: qualquer '
                    'farmacia confere tipo, numero, medico, CRM e data sem ter conta '
                    'no sistema. A emissao com certificado ICP-Brasil real depende de '
                    'voce cadastrar o seu.',
    },
    {
        'pergunta': 'E se eu passar do limite de pacientes do plano?',
        'resposta': 'O sistema avisa quando voce chega a 80% da cota e recusa apenas '
                    'o cadastro seguinte quando o limite e atingido. Nada do que ja '
                    'esta registrado e apagado, arquivado ou escondido -- prontuario '
                    'tem guarda legal de vinte anos, e ela nao conhece plano de '
                    'assinatura. Arquivar um paciente que nao e mais acompanhado '
                    'libera uma vaga.',
    },
    {
        'pergunta': 'A inteligencia artificial da diagnostico?',
        'resposta': 'Nao, e nao e isso que ela se propoe a fazer. Ela redige, resume '
                    'e organiza; o medico aceita, edita ou rejeita cada sugestao, e o '
                    'registro guarda o que foi feito. Sugestao nao aceita nao entra no '
                    'prontuario.',
    },
    {
        'pergunta': 'Meus dados vao para onde?',
        'resposta': 'O prontuario fica no banco de dados da instalacao. Para a IA, o '
                    'texto passa por desidentificacao local antes de sair, e sua '
                    'clinica pode cadastrar o proprio provedor e a propria chave -- os '
                    'dados vao entao para o contrato que voce escolheu, nao para o '
                    'nosso.',
    },
    {
        'pergunta': 'Como faco backup?',
        'resposta': 'O backup e automatico, cifrado com uma chave que fica fora do '
                    'servidor, e a restauracao e um procedimento documentado e testado. '
                    'A chave de recuperacao e do responsavel pela clinica.',
    },
    {
        'pergunta': 'Posso comecar de graca?',
        'resposta': 'Pode. O plano Gratuito atende ate 50 pacientes e um medico, sem '
                    'cartao de credito. O acesso e liberado por um codigo de convite -- '
                    'preencha o formulario e devolvemos o seu.',
    },
    {
        'pergunta': 'O que ainda nao existe?',
        'resposta': 'Pagamento on-line, faturamento TISS, teleconsulta e integracao com '
                    'PACS/DICOM nao fazem parte desta versao. Receita de substancia '
                    'sujeita a controle especial sai em papel, com as duas vias exigidas, '
                    'e nao por transmissao eletronica a orgao regulador.',
    },
]

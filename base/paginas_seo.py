"""Páginas de entrada da busca: uma por área da neurologia e uma por recurso.

**Por que existem** (2026-11-18, trazidas do ProntDoc). A raiz vende o
produto inteiro, e quem procura "prontuário para epilepsia" ou "receita
controlada eletrônica" não a encontra, porque ela não fala de epilepsia nem
de receita como assunto principal. Cada página daqui responde a **uma**
busca, com título, descrição e `<h1>` na língua dessa busca, e leva aos
planos.

**O que nenhuma delas pode fazer: prometer o que o produto não faz.** Toda
frase descreve um recurso que existe e está nos roteiros de `checks/`: as
catorze escalas pelo nome (`exams/data/escalas.yaml`), a agenda de EEG, ENMG
e polissonografia, a receita do SNCR, o portal, o WhatsApp da recepção — que
**abre** a conversa com a mensagem pronta, e não envia sozinho. Sem
depoimento, sem número de clientes, sem nota: num produto de saúde isso é
promessa falsa com outro nome. Copy agressiva, aqui, é dizer sem rodeio o
que o produto faz, não aumentar o que ele faz.

**Áreas, e não especialidades.** O NeuroDoc é de neurologia e
neurocirurgia; para as outras especialidades existe o ProntDoc
(`prontdoc.app.br`), e cada página aponta para ele no rodapé.

**Por que dados, e não um template por página.** A página é uma só
(`templates/onboarding/tematica.html`); o que muda mora aqui, e o catálogo
de SEO (`base/seo.py`) lê a mesma lista para o título, o sitemap, o JSON-LD
e o `llms.txt`.

Limites que `check_seo` cobra de toda página do sitemap: título até 70
caracteres, descrição entre 70 e 175.
"""

#: Áreas da neurologia: `/neurologia/<slug>/`.
AREAS = [
    {
        'slug': 'avc',
        'nome': 'AVC e neurovascular',
        'titulo': 'Prontuário para AVC com NIHSS e Rankin automáticos | NeuroDoc',
        'descricao': 'Prontuário eletrônico para neurologia vascular: NIHSS, Rankin modificada e '
                     'Barthel calculados no atendimento, em gráfico de evolução. Comece grátis.',
        'h1': 'Prontuário eletrônico para AVC e neurologia vascular',
        'chamada': 'NIHSS da admissão, Rankin da alta, Barthel do retorno — calculados na hora '
                   'e enfileirados num gráfico. Chega de caçar o escore num texto de seis meses atrás.',
        'intro': [
            'O NeuroDoc aplica a NIHSS, a escala de Rankin modificada e o índice de Barthel '
            'dentro do atendimento. O escore e a faixa de interpretação saem calculados, e '
            'cada aplicação entra na série do paciente: a evolução aparece em gráfico, com o '
            'tempo na escala certa.',
            'O exame neurológico estruturado registra o déficit por eixo, com o achado '
            'anormal destacado. No seguimento, a consulta anterior aparece para revisão item a '
            'item — medicação, hipóteses, conduta — e você só aceita o que continua valendo.',
        ],
        'destaques': [
            ('NIHSS, Rankin e Barthel', 'Escore e interpretação calculados, sem planilha à parte.'),
            ('Gráfico de evolução', 'Cada escala vira curva ao longo do tempo, na data real.'),
            ('Espasticidade na mesma ficha', 'Ashworth modificada para quem acompanha a reabilitação.'),
            ('Relatório que a IA redige', 'Para o paciente e a família, revisado e assinado por você.'),
        ],
        'perguntas': [
            ('Consigo comparar a NIHSS de hoje com a de meses atrás?',
             'Sim. Cada aplicação fica na história do paciente, e a tela de evolução mostra a série em gráfico, com as datas reais.'),
            ('Preciso usar o exame estruturado para aplicar as escalas?',
             'Não. As escalas funcionam também no atendimento em texto livre e entram na mesma série do gráfico.'),
        ],
    },
    {
        'slug': 'epilepsia',
        'nome': 'Epilepsia',
        'titulo': 'Prontuário para epilepsia com agenda de EEG | NeuroDoc',
        'descricao': 'Prontuário eletrônico para epileptologia: agenda de EEG por equipamento, '
                     'receita controlada no SNCR da Anvisa e consulta anterior em um clique.',
        'h1': 'Prontuário eletrônico para epilepsia',
        'chamada': 'Seguimento longo, controlado na receita e EEG na agenda. O NeuroDoc foi '
                   'feito para o paciente que você acompanha por anos.',
        'intro': [
            'A receita de controle especial e a Notificação de Receita B saem eletrônicas, no '
            'modelo oficial do SNCR, com a numeração que a Anvisa libera ao médico e '
            'assinatura com o seu certificado digital. A lista da Portaria 344 é conferida na hora, e o '
            'medicamento é classificado sozinho.',
            'No plano Completo, o EEG tem agenda própria, por equipamento e separada da dos '
            'médicos: o aparelho nunca recebe dois pacientes no mesmo horário, e o exame '
            'realizado vira cobrança quando há honorário para ele.',
        ],
        'destaques': [
            ('Receita controlada eletrônica', 'RCE e Notificação B no modelo do SNCR, assinadas.'),
            ('Agenda de EEG', 'Por equipamento, sem ocupar vaga de médico.'),
            ('Retorno sem releitura', 'A conduta e a medicação da última consulta, para revisar.'),
            ('Portal para a receita', 'O paciente pede a renovação sem ligar nem mandar WhatsApp.'),
        ],
        'perguntas': [
            ('O paciente consegue pedir a renovação da receita sem ligar?',
             'Sim. Pelo portal do paciente, sem criar conta. O pedido cai numa fila que só o médico revisa, e quem decide o que é emitido é você.'),
            ('O NeuroDoc emite a Notificação de Receita B?',
             'Sim, eletrônica, com a numeração que a Vigilância Sanitária libera ao médico. As Notificações de retinoide e de talidomida não são emitidas.'),
        ],
    },
    {
        'slug': 'parkinson-e-ataxias',
        'nome': 'Distúrbios do movimento',
        'titulo': 'Prontuário para Parkinson e ataxias: Hoehn e Yahr e SARA | NeuroDoc',
        'descricao': 'Prontuário eletrônico para distúrbios do movimento: Hoehn e Yahr e SARA '
                     'calculadas, exame neurológico estruturado e evolução em gráfico.',
        'h1': 'Prontuário eletrônico para Parkinson, ataxias e distúrbios do movimento',
        'chamada': 'O estadiamento de hoje ao lado do de dois anos atrás. A progressão '
                   'deixa de ser impressão e vira curva.',
        'intro': [
            'O estadiamento de Hoehn e Yahr e a escala SARA, para as ataxias, são aplicados '
            'dentro do atendimento, com o escore calculado. Cada aplicação entra na série do '
            'paciente e aparece em gráfico na tela de evolução.',
            'O roteiro de exame neurológico tem coordenação, marcha e motricidade por eixo, '
            'com "tudo normal" por grupo e o achado anormal destacado — o que mudou desde a '
            'última consulta salta aos olhos.',
        ],
        'destaques': [
            ('Hoehn e Yahr e SARA', 'Escore calculado e guardado na história do paciente.'),
            ('Gráfico de evolução', 'A progressão em curva, com o tempo na escala certa.'),
            ('Exame estruturado por eixo', 'Coordenação e marcha com o achado destacado.'),
            ('Medicação em uso a um clique', 'A prescrição da última consulta para revisar.'),
        ],
        'perguntas': [
            ('As escalas ficam no prontuário?',
             'Sim. Cada aplicação fica registrada no atendimento e entra na série do paciente, que aparece em gráfico.'),
            ('Posso escrever em texto livre e ainda assim usar as escalas?',
             'Pode. O atendimento em texto livre também aplica as escalas, que entram na mesma série.'),
        ],
    },
    {
        'slug': 'demencias',
        'nome': 'Demências e cognição',
        'titulo': 'Prontuário para demências com MEEM e Pfeffer | NeuroDoc',
        'descricao': 'Prontuário eletrônico para neurologia cognitiva: MEEM e questionário de '
                     'Pfeffer calculados, evolução em gráfico e relatório para a família.',
        'h1': 'Prontuário eletrônico para demências e neurologia cognitiva',
        'chamada': 'O MEEM de cada retorno numa linha só, e o relatório para a família '
                   'redigido em minutos — revisado e assinado por você.',
        'intro': [
            'O mini-exame do estado mental (MEEM) e o questionário de Pfeffer são aplicados '
            'no atendimento, com o escore calculado. A tela de evolução mostra a série em '
            'gráfico, e a comparação entre os retornos deixa de depender de memória.',
            'No plano Completo, a inteligência artificial redige o relatório para o paciente '
            'e a família a partir do prontuário, sem nome nem documento no texto que sai. '
            'Você edita, aprova e assina; nada entra sem a sua revisão.',
        ],
        'destaques': [
            ('MEEM e Pfeffer', 'Escore e interpretação calculados no atendimento.'),
            ('Evolução em gráfico', 'Cada aplicação na série do paciente.'),
            ('Relatório pela IA', 'Para a família, revisado e assinado pelo médico.'),
            ('Funcionalidade com Barthel', 'Atividades de vida diária na mesma ficha.'),
        ],
        'perguntas': [
            ('A IA escreve o relatório sozinha?',
             'Ela redige um rascunho a partir do prontuário desidentificado. Você edita, aprova e assina — sem a sua aprovação nada é emitido.'),
            ('Em qual plano está a IA?',
             'No Completo e no Personalizado. Dá para testar o Completo por 7 dias, sem cartão.'),
        ],
    },
    {
        'slug': 'neuromuscular',
        'nome': 'Doenças neuromusculares',
        'titulo': 'Prontuário para ELA e miastenia: ALSFRS-R e MG-ADL | NeuroDoc',
        'descricao': 'Prontuário eletrônico para doenças neuromusculares: ALSFRS-R e MG-ADL '
                     'calculadas, agenda de ENMG por equipamento e evolução em gráfico.',
        'h1': 'Prontuário eletrônico para ELA, miastenia e doenças neuromusculares',
        'chamada': 'ALSFRS-R e MG-ADL a cada retorno, a ENMG na agenda do aparelho e a '
                   'evolução numa curva que fala por si.',
        'intro': [
            'A escala funcional da ELA revisada (ALSFRS-R) e a MG-ADL, para miastenia gravis, '
            'são aplicadas no atendimento com o escore calculado, e cada aplicação entra na '
            'série do paciente.',
            'No plano Completo, a eletroneuromiografia tem agenda própria por equipamento, '
            'separada da dos médicos e sem ocupar vaga de médico; o exame realizado vira '
            'cobrança quando há honorário cadastrado, e a guia TISS sai dele.',
        ],
        'destaques': [
            ('ALSFRS-R e MG-ADL', 'Escore calculado e guardado a cada retorno.'),
            ('Agenda de ENMG', 'Por equipamento, sem sobreposição.'),
            ('Guia TISS do exame', 'SP/SADT a partir da reserva realizada.'),
            ('Gráfico de evolução', 'A funcionalidade em curva ao longo do tempo.'),
        ],
        'perguntas': [
            ('A agenda de ENMG ocupa a agenda do médico?',
             'Não. É uma agenda por equipamento, à parte, e não consome vaga de médico.'),
            ('A ENMG realizada gera cobrança?',
             'Sim, quando há honorário cadastrado para o procedimento, casado pelo código TUSS. Sem honorário, nada é inventado.'),
        ],
    },
    {
        'slug': 'sono',
        'nome': 'Medicina do sono',
        'titulo': 'Prontuário para medicina do sono e polissonografia | NeuroDoc',
        'descricao': 'Prontuário eletrônico para o sono: escala de Epworth calculada e agenda de '
                     'polissonografia que atravessa a noite como um exame só. Comece grátis.',
        'h1': 'Prontuário eletrônico para medicina do sono',
        'chamada': 'A polissonografia das 21h às 7h é um exame só, numa linha só da agenda. '
                   'E a Epworth sai calculada em segundos.',
        'intro': [
            'A escala de sonolência de Epworth é aplicada dentro do atendimento, com o escore '
            'e a faixa calculados, e entra na série do paciente.',
            'No plano Completo, a polissonografia tem agenda por equipamento que atravessa a '
            'meia-noite sem quebrar o exame em dois. O aparelho nunca recebe dois pacientes, '
            'o paciente recebe o lembrete na véspera, e o exame realizado vira cobrança '
            'quando há honorário para ele.',
        ],
        'destaques': [
            ('Epworth calculada', 'Escore e interpretação no atendimento.'),
            ('Agenda noturna', 'A polissonografia da noite inteira, sem dividir o exame.'),
            ('Lembrete na véspera', 'O paciente avisado antes do exame.'),
            ('Guia TISS do exame', 'SP/SADT a partir da reserva realizada.'),
        ],
        'perguntas': [
            ('A agenda aceita exame que atravessa a meia-noite?',
             'Sim. A janela da polissonografia pode ir das 21h às 7h e aparece como um exame só, nos dois dias.'),
            ('A agenda de exames está em qual plano?',
             'No Completo e no Personalizado, junto com o faturamento TISS.'),
        ],
    },
    {
        'slug': 'neurocirurgia',
        'nome': 'Neurocirurgia',
        'titulo': 'Prontuário para neurocirurgia com pedido de cirurgia TUSS | NeuroDoc',
        'descricao': 'Prontuário eletrônico para neurocirurgiões: solicitação de cirurgia com '
                     'procedimentos TUSS e materiais, Glasgow e FOUR, guias TISS e laudos assinados.',
        'h1': 'Prontuário eletrônico para neurocirurgia',
        'chamada': 'Do ambulatório à solicitação de cirurgia com procedimentos TUSS e '
                   'materiais — e a guia do convênio pronta para o lote.',
        'intro': [
            'A solicitação de cirurgia sai de modelos seus, com os procedimentos da TUSS e os '
            'materiais, direto da conduta do atendimento. O documento vai para os anexos, '
            'assinado com o seu certificado e verificável por QR.',
            'A escala de coma de Glasgow e a escala FOUR ficam à mão no atendimento. No plano '
            'Completo, as guias de Consulta e SP/SADT nascem com o convênio, a carteira e os '
            'profissionais que o sistema já conhece, e o lote sai em XML no padrão da ANS.',
        ],
        'destaques': [
            ('Solicitação de cirurgia', 'Procedimentos TUSS e materiais, a partir de modelos seus.'),
            ('Glasgow e FOUR', 'Escore calculado no atendimento.'),
            ('Guias TISS', 'Consulta e SP/SADT, com lote em XML validado.'),
            ('Documento assinado', 'PAdES com o seu certificado e verificação por QR.'),
        ],
        'perguntas': [
            ('Os modelos de solicitação de cirurgia são meus?',
             'Sim. Os modelos do médico seguem você em todas as clínicas em que atende, e o sistema também traz modelos prontos.'),
            ('O NeuroDoc envia o lote TISS para a operadora?',
             'Ele gera o XML conferido contra o padrão oficial, na versão que a operadora aceita; o envio é pelo portal da operadora.'),
        ],
    },
    {
        'slug': 'neurointensivismo',
        'nome': 'Neurointensivismo e urgência',
        'titulo': 'Prontuário neurológico com Glasgow, FOUR e RASS | NeuroDoc',
        'descricao': 'Escala de coma de Glasgow, FOUR e RASS calculadas no atendimento, exame '
                     'neurológico estruturado e NIHSS para a neurologia de urgência.',
        'h1': 'Escalas de Glasgow, FOUR e RASS no prontuário neurológico',
        'chamada': 'Nível de consciência, sedação e déficit focal registrados em segundos, '
                   'com o escore calculado e guardado.',
        'intro': [
            'A escala de coma de Glasgow, a FOUR e a escala de agitação e sedação de Richmond '
            '(RASS) são aplicadas dentro do atendimento, com o escore e a interpretação '
            'calculados. A NIHSS está na mesma lista, para o déficit focal.',
            'O exame neurológico estruturado registra pares cranianos, motricidade e '
            'reflexos por eixo, e o achado anormal fica destacado no registro, em vez de '
            'perdido num parágrafo.',
        ],
        'destaques': [
            ('Glasgow e FOUR', 'Nível de consciência com o escore calculado.'),
            ('RASS', 'Agitação e sedação no mesmo atendimento.'),
            ('NIHSS', 'O déficit focal quantificado.'),
            ('Exame por eixo', 'O achado anormal em destaque.'),
        ],
        'perguntas': [
            ('As escalas ficam na história do paciente?',
             'Sim. Cada aplicação fica no atendimento e entra na série que aparece no gráfico de evolução.'),
            ('O NeuroDoc é um sistema hospitalar?',
             'Não. É prontuário e gestão de consultório e clínica; as escalas servem a quem atende o paciente neurológico em qualquer contexto.'),
        ],
    },
    {
        'slug': 'doencas-raras',
        'nome': 'Neurogenética e doenças raras',
        'titulo': 'Prontuário para neurogenética e doenças raras | NeuroDoc',
        'descricao': 'Feito por neurologista de doenças raras do HC-FMUSP: CID-10 e CID-11, '
                     'busca de pacientes por diagnóstico, escala SARA e seguimento de anos.',
        'h1': 'Prontuário eletrônico para neurogenética e doenças raras',
        'chamada': 'Escrito por quem coordena um ambulatório de doenças neurológicas raras. '
                   'O seguimento de décadas cabe aqui.',
        'intro': [
            'O NeuroDoc foi escrito pelo Dr. Fernando Freua, coordenador executivo do '
            'ambulatório de doenças neurológicas raras e neurogenética do HC-FMUSP. A CID-10 '
            'e a CID-11 estão inteiras, e a busca encontra os pacientes por diagnóstico, '
            'pelo código ou pelo nome da doença.',
            'A escala SARA acompanha as ataxias, o exame estruturado registra cada achado por '
            'eixo, e o histórico inteiro fica num resumo do caso, do atendimento mais recente '
            'ao primeiro. Antes de qualquer texto ir à IA, o trecho que fala de '
            'consanguinidade é retirado, junto com nome e documento.',
        ],
        'destaques': [
            ('CID-10 e CID-11', 'As duas classificações inteiras, com busca por diagnóstico.'),
            ('Escala SARA', 'Ataxias com o escore calculado e em gráfico.'),
            ('Resumo do caso', 'Todos os atendimentos numa folha, do mais recente ao primeiro.'),
            ('Privacidade na IA', 'Consanguinidade, nome e documento ficam fora do texto que sai.'),
        ],
        'perguntas': [
            ('Consigo encontrar todos os pacientes com um diagnóstico?',
             'Sim. A busca por CID encontra os pacientes por código, com ou sem ponto, ou pelo nome da doença.'),
            ('O NeuroDoc tem a CID-11?',
             'Tem, ao lado da CID-10. O código diz de qual classificação é, e a busca é feita em uma de cada vez.'),
        ],
    },
]

#: Recursos: `/recursos/<slug>/`.
RECURSOS = [
    {
        'slug': 'inteligencia-artificial',
        'nome': 'Inteligência artificial',
        'titulo': 'Prontuário com inteligência artificial para neurologia | NeuroDoc',
        'descricao': 'IA no prontuário neurológico: resumo do atendimento, relatório do paciente, '
                     'apoio diagnóstico e chat do caso, desidentificados e revisados pelo médico.',
        'h1': 'Inteligência artificial no prontuário de neurologia',
        'chamada': 'A IA escreve o rascunho; você decide. Resumo, relatório, hipóteses e '
                   'conversa sobre o caso — em segundos, e sempre com a sua revisão.',
        'intro': [
            'No plano Completo, a inteligência artificial resume o atendimento, redige o '
            'relatório para o paciente, levanta hipóteses no apoio diagnóstico e conversa '
            'sobre o caso com o prontuário à mão. Sem paciente aberto, o mesmo chat responde '
            'como usar o sistema, pelo manual.',
            'O texto sai desidentificado — sem nome nem documento —, e o envio é recusado '
            'quando não satisfaz a política de privacidade. Nada entra no prontuário sem você '
            'aceitar, e a clínica pode usar o próprio provedor e a própria chave.',
        ],
        'destaques': [
            ('Resumo do atendimento', 'O caso condensado, aprovado por você antes de valer.'),
            ('Relatório do paciente', 'A IA redige; você revisa e assina.'),
            ('Apoio diagnóstico', 'Hipóteses para o médico avaliar, sem decidir por ele.'),
            ('Chat do caso', 'Perguntas sobre o paciente, com o prontuário como fonte.'),
        ],
        'perguntas': [
            ('A IA dá diagnóstico?',
             'Não. Ela redige, resume e organiza; o médico aceita, edita ou rejeita, e sugestão não aceita não entra no prontuário.'),
            ('Em qual plano está a IA?',
             'No Completo e no Personalizado. Dá para testar o Completo por 7 dias, sem cartão.'),
            ('Os dados do paciente vão para a IA?',
             'O texto passa por desidentificação antes de sair, sem nome nem documento. A clínica também pode usar o próprio provedor e a própria chave.'),
        ],
    },
    {
        'slug': 'portal-do-paciente',
        'nome': 'Portal do paciente',
        'titulo': 'Portal do paciente: pedido de receita sem ligar | NeuroDoc',
        'descricao': 'O paciente pede receita, relatório ou pedido de exame e envia laudos em PDF '
                     'sem criar conta. Menos telefone, menos WhatsApp, recepção livre.',
        'h1': 'Portal do paciente: receita, relatório e exames sem ligar para a recepção',
        'chamada': 'Tire a renovação de receita do telefone e do WhatsApp. O paciente pede '
                   'pelo portal, e o pedido chega pronto para você decidir.',
        'intro': [
            'O paciente pede receita, relatório ou pedido de exame pelo portal, sem criar '
            'conta. O pedido entra numa fila que só o médico revisa — a receita pelo mesmo '
            'bloco da tela de emissão, o relatório pela IA —, e quem decide o que é emitido '
            'continua sendo você. Recusar exige um motivo.',
            'Pelo mesmo portal, o paciente envia em PDF os laudos dos exames que já fez: eles '
            'entram direto no prontuário, e o médico é avisado até marcar que viu. A clínica '
            'pode exigir consulta recente, no prazo de 180 dias da norma do CFM.',
        ],
        'destaques': [
            ('Sem conta para o paciente', 'Ele se identifica e pede; nada de senha nova.'),
            ('Laudos direto no prontuário', 'PDF enviado pelo paciente, com aviso ao médico.'),
            ('Fila do médico', 'Pedido pronto para emitir pelo caminho de sempre.'),
            ('Regra dos 180 dias', 'A clínica escolhe exigir consulta recente.'),
        ],
        'perguntas': [
            ('O paciente precisa criar conta?',
             'Não. Ele se identifica no portal da clínica e faz o pedido; a resposta chega pelo documento entregue por link com código de acesso.'),
            ('O sistema emite a receita sozinho?',
             'Não. Todo pedido passa pela revisão do médico, que emite, edita ou recusa com motivo.'),
        ],
    },
    {
        'slug': 'whatsapp-da-recepcao',
        'nome': 'WhatsApp da recepção',
        'titulo': 'Lembrete de consulta por WhatsApp em um clique | NeuroDoc',
        'descricao': 'Botão de WhatsApp na agenda e no balcão: a mensagem de lembrete já vem '
                     'escrita, com data, horário e endereço. Em todos os planos, sem custo extra.',
        'h1': 'Lembrete de consulta pelo WhatsApp da clínica, em um clique',
        'chamada': 'Chega de digitar a mesma mensagem cinquenta vezes por dia. Um clique na '
                   'agenda e o WhatsApp da clínica abre com o lembrete pronto.',
        'intro': [
            'Na agenda e no balcão, o botão WhatsApp abre a conversa com o paciente no '
            'WhatsApp da própria clínica, com o lembrete já escrito: nome, data, horário, '
            'médico e endereço. A secretária confere e envia. É a mensagem que a clínica '
            'escreve uma vez, em Integrações, com os campos que ela escolher.',
            'O botão não envia nada sozinho, de propósito: a conversa sai do número que o '
            'paciente já conhece. O envio automático, quando a clínica quiser, é a integração '
            'com a conta Twilio dela. E o portal do paciente tira do WhatsApp o pedido de '
            'renovação de receita — a recepção respira.',
        ],
        'destaques': [
            ('Mensagem pronta', 'Data, horário, médico e endereço preenchidos.'),
            ('Do número da clínica', 'O paciente reconhece quem escreve.'),
            ('Em todos os planos', 'Inclusive no Gratuito, sem custo por mensagem.'),
            ('Portal desafoga o WhatsApp', 'Pedido de receita sai do chat e vai para a fila.'),
        ],
        'perguntas': [
            ('O NeuroDoc envia WhatsApp automaticamente?',
             'Este botão não: ele abre a conversa no WhatsApp da clínica com a mensagem pronta, e quem envia é a recepção. O envio automático é outra integração, em liberação, pela conta Twilio da própria clínica.'),
            ('Posso mudar o texto do lembrete?',
             'Sim. A clínica escreve o texto em Integrações, com os campos de uma lista fechada, e vê a prévia antes de salvar.'),
        ],
    },
    {
        'slug': 'receita-controlada-sncr',
        'nome': 'Receita controlada eletrônica',
        'titulo': 'Receita controlada eletrônica no SNCR da Anvisa | NeuroDoc',
        'descricao': 'Receita de Controle Especial e Notificação de Receita A, B e B2 eletrônicas, '
                     'com numeração do SNCR e assinatura com o seu certificado digital. Portaria 344 conferida na hora.',
        'h1': 'Receita controlada eletrônica com a numeração do SNCR',
        'chamada': 'Sem talonário, sem caneta, sem fila no cartório da Vigilância. A receita '
                   'controlada sai eletrônica, numerada e assinada.',
        'intro': [
            'Integrado ao SNCR (RDC 1.000/2025), o NeuroDoc pede os números do médico com o '
            'Gov.br e emite a Receita de Controle Especial, a de Retenção e a Notificação de '
            'Receita A, B e B2 eletrônicas, no modelo oficial, uma folha por medicamento, com '
            'assinatura com o seu certificado digital.',
            'A lista da Portaria 344/98 é conferida na hora: o medicamento é classificado '
            'sozinho e o tipo de receita certo é apontado. As Notificações de retinoide e de '
            'talidomida não são emitidas pelo NeuroDoc.',
        ],
        'destaques': [
            ('Numeração da Anvisa', 'Os números do médico, pedidos pelo Gov.br.'),
            ('Notificação A, B e B2', 'Eletrônicas, com a cota liberada pela Vigilância.'),
            ('Portaria 344 conferida', 'O medicamento classificado pela lista oficial.'),
            ('Assinatura digital', 'Uma folha e um número por medicamento.'),
        ],
        'perguntas': [
            ('Preciso de certificado digital?',
             'Sim, o seu certificado digital, cadastrado no sistema, assina a receita eletrônica.'),
            ('Funciona em todas as clínicas em que atendo?',
             'Sim. O bloco de números é do médico e vale em todas as clínicas dele.'),
        ],
    },
    {
        'slug': 'faturamento-tiss',
        'nome': 'Faturamento TISS',
        'titulo': 'Faturamento TISS para clínica de neurologia | NeuroDoc',
        'descricao': 'Guias de Consulta e SP/SADT preenchidas com o que o sistema já sabe e lotes '
                     'em XML validados no padrão da ANS, da versão 3.04 à 4.03. No plano Completo.',
        'h1': 'Faturamento de convênio no padrão TISS, sem redigitar nada',
        'chamada': 'A guia nasce com o convênio, a carteira e os profissionais que o sistema '
                   'já conhece. O lote sai em XML, validado antes de você enviar.',
        'intro': [
            'No plano Completo, as guias de Consulta e de SP/SADT são preenchidas com o que o '
            'NeuroDoc já sabe, e a consulta cobrada no check-in entra sem cobrança duplicada. '
            'Pendências aparecem antes de fechar, e a guia fechada vira o retrato do que foi '
            'faturado.',
            'O lote sai em XML na versão que cada operadora aceita — da 3.04 à 4.03 —, '
            'conferido contra o esquema oficial da ANS, com o hash certo. Você envia pelo '
            'portal da operadora e registra o protocolo no lote.',
        ],
        'destaques': [
            ('Guias pré-preenchidas', 'Convênio, carteira e profissionais vindos do cadastro.'),
            ('Sete versões do padrão', 'Da 3.04.00 à 4.03.00, validadas no XSD da ANS.'),
            ('Sem cobrança duplicada', 'A consulta do check-in vinculada à guia.'),
            ('Agenda de exames junto', 'EEG, ENMG e polissonografia no mesmo plano.'),
        ],
        'perguntas': [
            ('O NeuroDoc envia o lote direto à operadora?',
             'Ainda não. Ele gera o XML conferido contra o padrão oficial; você envia pelo portal da operadora e registra o protocolo.'),
            ('Em qual plano está o TISS?',
             'No Completo e no Personalizado. Contratar o Completo libera o TISS sozinho.'),
        ],
    },
    {
        'slug': 'escalas-neurologicas',
        'nome': 'Escalas neurológicas',
        'titulo': '14 escalas neurológicas com cálculo automático | NeuroDoc',
        'descricao': 'NIHSS, Glasgow, Rankin, Hoehn e Yahr, MEEM, ALSFRS-R, SARA, Epworth e mais: '
                     'escore calculado no prontuário e evolução em gráfico.',
        'h1': 'Catorze escalas neurológicas com cálculo automático',
        'chamada': 'O escore e a interpretação saem calculados, e a série do paciente vira '
                   'gráfico. Sem calculadora, sem planilha, sem procurar número em texto antigo.',
        'intro': [
            'Glasgow, FOUR, RASS, MEEM, Epworth, Barthel, Rankin modificada, NIHSS, SARA, '
            'ALSFRS-R, MG-ADL, Pfeffer, Ashworth modificada e Hoehn e Yahr — aplicadas dentro '
            'do atendimento, com o escore e a faixa de interpretação calculados.',
            'Funcionam no prontuário estruturado e no de texto livre, e cada aplicação entra '
            'na mesma série. A tela de evolução desenha a curva com o tempo na escala certa, '
            'e a aplicação incompleta fica fora da linha.',
        ],
        'destaques': [
            ('Catorze escalas', 'Do pronto atendimento ao ambulatório de subespecialidade.'),
            ('Escore automático', 'Pontuação e interpretação sem conta de cabeça.'),
            ('Gráfico de evolução', 'A série do paciente em curva, na data real.'),
            ('Estruturado ou texto livre', 'As escalas valem nos dois tipos de atendimento.'),
        ],
        'perguntas': [
            ('Quais escalas o NeuroDoc tem?',
             'Glasgow, FOUR, RASS, MEEM, Epworth, Barthel, Rankin modificada, NIHSS, SARA, ALSFRS-R, MG-ADL, Pfeffer, Ashworth modificada e Hoehn e Yahr.'),
            ('Preciso usar o prontuário estruturado para ter as escalas?',
             'Não. Elas funcionam também no atendimento em texto livre.'),
        ],
    },
    {
        'slug': 'exame-neurologico-estruturado',
        'nome': 'Exame neurológico estruturado',
        'titulo': 'Exame neurológico estruturado ou texto livre | NeuroDoc',
        'descricao': 'Roteiro de exame neurológico com 387 itens por eixo, ou texto livre com a '
                     'consulta anterior ao lado: o prontuário do jeito que você já escreve.',
        'h1': 'Exame neurológico estruturado ou texto livre — você escolhe',
        'chamada': 'Gosta de estrutura? 387 itens por eixo, com "tudo normal" por grupo. '
                   'Prefere escrever? Folha em branco com a consulta anterior ao lado.',
        'intro': [
            'O roteiro de exame neurológico tem 387 itens organizados por eixo — pares '
            'cranianos, motor, sensibilidade, coordenação, marcha —, com "tudo normal" por '
            'grupo para o que veio sem alteração. O achado anormal fica destacado no '
            'registro, em vez de se diluir num parágrafo.',
            'Quem prefere escrever usa o atendimento em texto livre: a folha em branco com a '
            'consulta anterior ao lado para revisar. São três tipos — primeira consulta, '
            'seguimento e texto livre —, com o tipo sugerido pela agenda do dia. As escalas '
            'funcionam em todos.',
        ],
        'destaques': [
            ('387 itens por eixo', 'Com "tudo normal" por grupo e o achado destacado.'),
            ('Texto livre de verdade', 'Folha em branco, com a última consulta ao lado.'),
            ('Primeira consulta e seguimento', 'Queixa e história, ou evolução — no mesmo editor.'),
            ('Consulta anterior em um clique', 'Revise e aceite item a item o que continua valendo.'),
        ],
        'perguntas': [
            ('Sou obrigado a usar o roteiro estruturado?',
             'Não. O atendimento em texto livre é um dos três tipos, e você escolhe a cada consulta.'),
            ('Posso trocar o tipo do atendimento depois de começar?',
             'Enquanto está aberto, sim, desde que nada do que já foi escrito fique escondido.'),
        ],
    },
    {
        'slug': 'assinatura-digital',
        'nome': 'Assinatura digital',
        'titulo': 'Receita e laudo com assinatura digital e QR | NeuroDoc',
        'descricao': 'Receita, laudo, relatório e pedido de exame assinados em PAdES com o seu '
                     'certificado, com QR de verificação pública que a farmácia confere.',
        'h1': 'Receita e laudo com assinatura digital e verificação por QR',
        'chamada': 'Documento assinado com o seu certificado, conferível por qualquer '
                   'farmácia num QR. Adeus impressão, caneta e carimbo.',
        'intro': [
            'Receita, laudo, relatório, pedido de exame e encaminhamento são assinados no '
            'padrão PAdES com o certificado digital do próprio médico. Cada documento sai com '
            'um código e um QR de verificação pública: a farmácia confere tipo, número, CRM e '
            'data sem ter conta no sistema.',
            'O documento chega ao paciente por link com código de acesso, por e-mail e, nos '
            'planos pagos, por SMS. Controle especial sai em duas vias, com o quadro da '
            'Portaria 344/98.',
        ],
        'destaques': [
            ('PAdES com o seu certificado', 'A assinatura que o documento eletrônico pede.'),
            ('Verificação por QR', 'A farmácia confere sem ter conta.'),
            ('Entrega por link', 'Com código de acesso, por e-mail ou SMS.'),
            ('Sessão de assinatura', 'Assine vários documentos sem digitar a senha a cada um.'),
        ],
        'perguntas': [
            ('Qualquer pessoa consegue conferir o documento?',
             'Sim. Em /verificar/ ou pelo QR, sem conta, aparecem tipo, número, médico, CRM e data.'),
            ('Preciso de certificado digital?',
             'Para assinar, sim: o seu certificado A1, cadastrado no sistema.'),
        ],
    },
    {
        'slug': 'agenda-de-exames',
        'nome': 'Agenda de exames',
        'titulo': 'Agenda de EEG, ENMG e polissonografia | NeuroDoc',
        'descricao': 'Agenda por equipamento para EEG, ENMG e polissonografia: sem sobreposição, '
                     'noite inteira num exame só, lembrete na véspera e guia TISS do exame.',
        'h1': 'Agenda de exames para EEG, ENMG e polissonografia',
        'chamada': 'O aparelho tem a agenda dele. Nunca dois pacientes no mesmo horário, e a '
                   'polissonografia da noite inteira é um exame só.',
        'intro': [
            'No plano Completo, cada equipamento tem a sua agenda, separada da dos médicos e '
            'sem ocupar vaga de médico. A sobreposição é recusada pelo próprio banco, mesmo '
            'com duas pessoas marcando ao mesmo tempo.',
            'A janela pode atravessar a meia-noite, o paciente recebe lembrete na véspera, e o '
            'exame realizado vira cobrança quando há honorário cadastrado para ele — e a guia '
            'SP/SADT sai da reserva.',
        ],
        'destaques': [
            ('Uma agenda por aparelho', 'EEG, ENMG e polissonografia, cada um no seu.'),
            ('Sem sobreposição', 'Recusada pelo banco, não só pela tela.'),
            ('Noite inteira', 'A polissonografia das 21h às 7h, num exame só.'),
            ('Cobrança e guia', 'O exame realizado vira recebível e guia SP/SADT.'),
        ],
        'perguntas': [
            ('A agenda de exames ocupa a agenda dos médicos?',
             'Não. É uma agenda por equipamento, à parte.'),
            ('Em qual plano está?',
             'No Completo e no Personalizado, junto com o faturamento TISS.'),
        ],
    },
    {
        'slug': 'lme-medicamento-alto-custo',
        'nome': 'LME do medicamento de alto custo',
        'titulo': 'LME de alto custo preenchida no prontuário | NeuroDoc',
        'descricao': 'A LME do CEAF no formulário oficial do Ministério da Saúde, já com os dados do '
                     'paciente e os medicamentos, para imprimir, assinar e carimbar.',
        'h1': 'LME do medicamento de alto custo, no formulário do Ministério e já preenchida',
        'chamada': 'Chega de preencher à mão o mesmo laudo a cada três meses. A LME sai do '
                   'prontuário com o que o sistema já sabe, e a renovação parte da anterior.',
        'intro': [
            'O NeuroDoc preenche o próprio formulário do Ministério da Saúde: nome, mãe, peso, '
            'altura e documento do paciente, até seis medicamentos com a quantidade de seis '
            'meses, CID-10, anamnese, tratamento prévio e, se o paciente for incapaz, o '
            'responsável. O médico completa o que é dele, na Conduta ou na ficha.',
            'A LME sai para imprimir, assinar à mão e carimbar, com número e data. A lista de '
            'medicamentos do formulário aparece como sugestão, e o médico escreve o que '
            'precisar; "Nova LME a partir desta" refaz a renovação em segundos.',
        ],
        'destaques': [
            ('Formulário oficial', 'O modelo do Ministério da Saúde, não um parecido.'),
            ('Dados do paciente prontos', 'Cadastro, peso e altura já no lugar.'),
            ('Seis meses por medicamento', 'Até seis medicamentos, mês a mês.'),
            ('Renovação rápida', 'A nova LME parte da anterior.'),
        ],
        'perguntas': [
            ('A LME é assinada digitalmente?',
             'Não. Ela sai para imprimir, assinar à mão e carimbar, que é o que toda farmácia de alto custo aceita.'),
            ('Posso prescrever um medicamento que não está na lista do formulário?',
             'Pode. A lista do Ministério aparece só como sugestão, e o médico escreve o medicamento como quiser.'),
        ],
    },
    {
        'slug': 'whatsapp-automatico',
        'nome': 'WhatsApp automático',
        'titulo': 'WhatsApp automático pela conta Twilio da clínica | NeuroDoc',
        'descricao': 'Lembrete, aviso de horário e documento disponível por WhatsApp, pela conta '
                     'Twilio e pelo número da própria clínica, com modelos aprovados pela Meta.',
        'h1': 'WhatsApp automático pela conta Twilio da própria clínica',
        'chamada': 'Os avisos que hoje saem por SMS e e-mail, também pelo WhatsApp oficial da '
                   'clínica — sem a secretária digitar nada e sem dado clínico na mensagem.',
        'intro': [
            'Em liberação: a clínica abre a própria conta na Twilio, liga o número de WhatsApp '
            'dela e informa as credenciais ao NeuroDoc, que confere a conta antes de ativar. '
            'Lembrete, horário marcado, remarcado ou cancelado e documento disponível saem por '
            'modelos aprovados pela Meta, só para quem deu o aceite de WhatsApp.',
            'A mensagem leva o nome da clínica, a data e o horário, ou o link seguro do '
            'documento — nunca diagnóstico, exame ou receita. A clínica paga as mensagens '
            'direto à Twilio, pode suspender a qualquer momento, e o passo a passo está no '
            'manual.',
        ],
        'destaques': [
            ('Número da clínica', 'O paciente reconhece quem escreve.'),
            ('Modelos aprovados pela Meta', 'Sem texto livre, sem surpresa.'),
            ('Sem dado clínico', 'Só data, horário ou link seguro.'),
            ('Custo direto na Twilio', 'Sem intermediário na conta da mensagem.'),
        ],
        'perguntas': [
            ('Quanto custa?',
             'A clínica paga as mensagens direto à Twilio e à Meta, na conta dela. O NeuroDoc não cobra pela integração.'),
            ('Posso usar o número que já está no WhatsApp Business do celular?',
             'A Twilio pede que o número não esteja registrado em outro WhatsApp; o manual explica as opções e recomenda um número só para os avisos.'),
        ],
    },
]


def area(slug):
    return next((p for p in AREAS if p['slug'] == slug), None)


def recurso(slug):
    return next((p for p in RECURSOS if p['slug'] == slug), None)

"""Artigo da central de ajuda sobre a LME (medicamento de alto custo).

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc): o texto recebe
o nome do produto, e `help_content.py` de cada lado o inclui. Mudou um passo
aqui, copie o arquivo inteiro para o outro repositório.

Decisões e fontes em `docs/governance/lme.md`. Sem captura de tela: a tela
é conferida por `checks/check_lme.py`, e o formulário é o do Ministério.
"""

FONTE = 'https://www.gov.br/saude/pt-br/composicao/sectics/daf/ceaf'


def artigo(produto):
    """O artigo `lme`, no formato de `help_content.ARTICLES`."""
    passos = [
        ('**O que é.** A LME (Laudo de Solicitação, Avaliação e Autorização de '
         'Medicamento) é o formulário com que o paciente pede, na farmácia do Estado, o '
         'medicamento do Componente Especializado da Assistência Farmacêutica — o "alto '
         f'custo". O {{p}} preenche o **próprio formulário do Ministério da Saúde** '
         f'([CEAF]({FONTE})), e não um parecido.'),
        ('**Onde fica.** No atendimento, na **Conduta**, o botão **LME (alto custo)**, ao '
         'lado de "Emitir documento". Também na ficha do paciente (para renovar sem abrir '
         'atendimento) e na tela **Emitir documento**. Só o médico emite.'),
        ('**O que já vem preenchido.** Nome, nome da mãe e CPF do cadastro; peso e altura '
         'da ficha (a altura em centímetros); telefones e e-mail do contato do paciente; o '
         'seu CNS e o CNES da sua última LME nesta clínica; e o CID-10 da primeira hipótese '
         'do atendimento. Confira tudo: o que vier errado, corrija na tela.'),
        ('**Medicamentos.** Até seis, com a quantidade de cada um dos seis meses '
         '(comprimidos, frascos, ampolas…). Ao digitar, aparece a lista do formulário do '
         'Ministério, só como sugestão: escreva o medicamento como quiser. Nome comprido '
         'vai em duas linhas com a letra menor; o que não couber nem assim é recusado, para '
         'a farmácia não receber um nome cortado.'),
        ('**O que é do médico.** CID-10 (a LME não aceita CID-11), diagnóstico, anamnese, '
         'se houve tratamento prévio (com o relato) e o **atestado de capacidade** (item '
         '13): se o paciente é considerado incapaz, indique o responsável, que poderá fazer '
         'a solicitação do medicamento. Raça/cor e o CNS do paciente ficam só na LME e '
         'voltam preenchidos na próxima.'),
        ('**Sempre impressa.** A LME **não é assinada digitalmente**: gere o rascunho, '
         'revise e use **Emitir para assinar e carimbar**. Ela ganha número e data, e você '
         'imprime, assina à mão e carimba no campo 17. Não há envio por link ao paciente — '
         'entregue o papel.'),
        ('**Renovar.** Na página de uma LME, **Nova LME a partir desta** abre o formulário '
         'com o conteúdo dela (só do mesmo paciente): ajuste as quantidades e emita de novo.'),
        ('**Quando o Ministério mudar o formulário**, a equipe do {p} troca o modelo numa '
         'versão nova do sistema; cada LME guarda em qual modelo saiu.'),
    ]
    return {
        'slug': 'lme',
        'title': 'LME — medicamento de alto custo',
        'summary': 'O laudo do CEAF no formulário do Ministério da Saúde, já preenchido, '
                   'para imprimir e assinar.',
        'audience': 'Médico',
        'steps': [(texto.replace('{p}', produto), '', '') for texto in passos],
    }

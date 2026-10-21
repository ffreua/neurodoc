"""Assinatura e quadro da farmacia no pe da folha, em todo documento.

Pedido de 2026-10-08: cabecalho no alto, corpo no meio, e a assinatura do
medico -- com o QR, e no controle especial o quadro do comprador e do
fornecedor -- sempre no RODAPE, ocupando a folha inteira como o
receituario em papel. Antes o rodape vinha logo depois do corpo, e a
receita de uma linha deixava meia folha em branco abaixo da assinatura.

O que este roteiro tenta quebrar, medindo ONDE o texto cai na pagina (e
nao so se ele existe -- um roteiro que procurasse o texto passaria com a
assinatura no meio da folha):

1. receita curta: a assinatura no quarto de baixo da folha, numa pagina so;
2. controle especial curto: duas vias, duas paginas, e em cada uma a
   assinatura e o quadro no pe -- o quadro abaixo da assinatura;
3. corpo que enche a folha: o rodape vai INTEIRO para a pagina seguinte,
   no pe dela, e nunca se parte (assinatura, QR e quadro na mesma folha);
4. relatorio de mais de uma pagina: o rodape no pe da ultima;
5. nenhuma folha so com o rodape quando ele cabia na anterior;
6. (2026-10-20) TODA folha com cabecalho e rodape de pagina -- o timbre
   saia uma vez, no comeco da via, e o documento de duas folhas tinha o
   cabecalho numa e o rodape na outra. A assinatura continua so na ultima
   folha de cada via; o rodape de pagina diz o documento, o paciente e
   "Pagina N de M", contado por via.
"""
import io
import secrets

from django.utils import timezone
from pypdf import PdfReader

from documents.models import MedicalDocument
from documents.pdf import render_medical_document_pdf
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Tenant

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
    user__physician_profile__isnull=False,
).first()
paciente = Patient.objects.filter(tenant=tenant).first()


def gerar(kind, conteudo):
    """PDF de um documento emitido, sem gravar nada: so o desenho importa."""
    doc = MedicalDocument(
        tenant=tenant, patient=paciente, physician=medico, kind=kind,
        content_snapshot=conteudo, status='issued', issued_at=timezone.now(),
        document_number='ROTEIRO-RODAPE', validation_token=secrets.token_hex(16),
        signature_metadata={'content_sha256': 'a' * 64},
    )
    return PdfReader(io.BytesIO(render_medical_document_pdf(doc)))


def posicoes(pagina):
    """[(texto, y relativo de 0 = pe a 1 = topo)] de cada trecho da pagina.

    O ReportLab desenha cada bloco depois de deslocar a origem, entao a
    altura real e a da matriz de texto composta com a de transformacao.
    """
    altura = float(pagina.mediabox.height)
    trechos = []

    def visitor(texto, cm, tm, *_):
        if texto.strip():
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            trechos.append((texto.strip(), y / altura))

    pagina.extract_text(visitor_text=visitor)
    return trechos


def y_de(pagina, trecho):
    achados = [y for texto, y in posicoes(pagina) if trecho in texto]
    return min(achados) if achados else None


def y_do_corpo(pagina, trecho):
    achados = [y for texto, y in posicoes(pagina) if trecho in texto]
    return max(achados) if achados else None


ASSINATURA = 'Assinado digitalmente'
QR = 'Confira este documento'
QUADRO = 'IDENTIFICAÇÃO DO COMPRADOR'

print('=== 1. receita curta: uma pagina, assinatura no pe ===')
pdf = gerar('prescription', {'prescription_format': 'simple',
                             'prescription_text': '1. Topiramato 25 mg — 1 cp à noite.'})
confere(len(pdf.pages) == 1, 'uma pagina so', str(len(pdf.pages)))
y = y_de(pdf.pages[0], ASSINATURA)
confere(y is not None and y < 0.25, 'a assinatura no quarto de baixo da folha', f'y={y}')
corpo = y_do_corpo(pdf.pages[0], 'Topiramato')
confere(corpo is not None and y is not None and corpo - y > 0.3,
        'ha espaco entre o corpo e a assinatura (a folha inteira e usada)', f'{corpo} {y}')

print('=== 2. controle especial curto: duas vias, rodape no pe de cada uma ===')
pdf = gerar('prescription', {'prescription_format': 'special_control',
                             'prescription_text': '1. Clonazepam 2 mg — 1 cp à noite.'})
confere(len(pdf.pages) == 2, 'duas paginas, uma por via', str(len(pdf.pages)))
for i, pagina in enumerate(pdf.pages[:2], start=1):
    ya, yq = y_de(pagina, ASSINATURA), y_de(pagina, QUADRO)
    confere(yq is not None and yq < 0.2, f'via {i}: o quadro da farmacia no pe', f'y={yq}')
    confere(ya is not None and yq is not None and ya > yq,
            f'via {i}: o quadro abaixo da assinatura (como no Anexo XVII)', f'{ya} {yq}')

print('=== 3. corpo que enche a folha: o rodape inteiro na seguinte, sem partir ===')
longo = '\n'.join(f'{i}. Medicamento {i} 50 mg — 1 cp ao dia, por 30 dias.' for i in range(1, 31))
pdf = gerar('prescription', {'prescription_format': 'special_control', 'prescription_text': longo})
confere(len(pdf.pages) == 4, 'duas paginas por via', str(len(pdf.pages)))
for pagina_n in range(len(pdf.pages)):
    pagina = pdf.pages[pagina_n]
    tem = {nome: y_de(pagina, t) is not None
           for nome, t in [('assinatura', ASSINATURA), ('qr', QR), ('quadro', QUADRO)]}
    if any(tem.values()):
        confere(all(tem.values()), f'pagina {pagina_n + 1}: assinatura, QR e quadro juntos', str(tem))
        confere(y_de(pagina, QUADRO) < 0.2, f'pagina {pagina_n + 1}: no pe da folha')

print('=== 4. relatorio de mais de uma pagina: rodape no pe da ultima ===')
texto = '\n\n'.join('Paciente em acompanhamento, quadro estável. ' * 12 for _ in range(8))
pdf = gerar('report', {'report_text': texto})
ultima = pdf.pages[-1]
y = y_de(ultima, ASSINATURA)
confere(len(pdf.pages) >= 2, 'o relatorio passou de uma pagina', str(len(pdf.pages)))
confere(y is not None and y < 0.25, 'a assinatura no pe da ultima pagina', f'y={y}')
confere(all(y_de(p, ASSINATURA) is None for p in pdf.pages[:-1]),
        'e so na ultima')

print('=== 5. nenhuma folha so com rodape quando ele cabia ===')
for kind, conteudo, esperado in [
    ('request', {'requested_procedure': 'Ressonância de crânio', 'justification': 'Cefaleia.'}, 1),
    ('referral', {'referral_specialty': 'Neurocirurgia', 'reason': 'Avaliação.'}, 1),
]:
    pdf = gerar(kind, conteudo)
    confere(len(pdf.pages) == esperado, f'{kind}: {esperado} pagina', str(len(pdf.pages)))
    y = y_de(pdf.pages[0], ASSINATURA)
    confere(y is not None and y < 0.25, f'{kind}: assinatura no pe', f'y={y}')

print('=== 6. toda folha com cabecalho e rodape de pagina ===')
CLINICA = tenant.trade_name or tenant.legal_name
for nome, kind, conteudo, vias in [
    ('relatorio longo', 'report', {'report_text': texto}, 1),
    ('controle longo', 'prescription', {'prescription_format': 'special_control',
                                        'prescription_text': longo}, 2),
    ('receita curta', 'prescription', {'prescription_format': 'simple',
                                       'prescription_text': '1. Topiramato 25 mg.'}, 1),
]:
    pdf = gerar(kind, conteudo)
    total = len(pdf.pages)
    por_via = total // vias
    for n, pagina in enumerate(pdf.pages, start=1):
        cab = y_do_corpo(pagina, CLINICA)
        confere(cab is not None and cab > 0.85, f'{nome}, folha {n}: o timbre no alto', f'y={cab}')
        esperado = f'Página {(n - 1) % por_via + 1} de {por_via}'
        yr = y_de(pagina, esperado)
        confere(yr is not None and yr < 0.05, f'{nome}, folha {n}: "{esperado}" no pe', f'y={yr}')
        confere(y_de(pagina, paciente.full_name) is not None and
                y_de(pagina, paciente.full_name) < 0.05,
                f'{nome}, folha {n}: o paciente no rodape de pagina')
        ultima_da_via = n % por_via == 0
        tem_assinatura = y_de(pagina, ASSINATURA) is not None
        confere(tem_assinatura == ultima_da_via,
                f'{nome}, folha {n}: assinatura {"presente" if ultima_da_via else "ausente"}'
                ' (so na ultima da via)', str(tem_assinatura))
    if vias == 2:
        # O rotulo inteiro, e nao "1ª via": o corpo da receita de controle
        # diz "A 1ª via fica retida na farmacia" -- inclusive na 2ª via.
        rotulos = [('1ª VIA — RETENÇÃO' in (p.extract_text() or '').upper(),
                    '2ª VIA — ORIENTAÇÃO' in (p.extract_text() or '').upper()) for p in pdf.pages]
        confere(all(r == (True, False) for r in rotulos[:por_via]) and
                all(r == (False, True) for r in rotulos[por_via:]),
                f'{nome}: cada folha diz a sua via, inclusive a segunda folha de cada uma',
                str(rotulos))

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: a assinatura mora no rodape, e o rodape nunca se parte.')

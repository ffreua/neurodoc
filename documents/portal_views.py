"""Telas do portal público de solicitações.

Sem conta e sem sessão prévia. Duas etapas: identificar o paciente e
descrever o pedido. A segunda só abre depois da primeira, e a primeira
expira em trinta minutos.
"""

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from . import portal
from .models import DocumentRequestKind

#: Finalidades de relatório, herdadas do portal em uso. A lista existe
#: porque "relatório para quê" muda o texto inteiro, e deixar isso em
#: campo livre produz pedido que o médico devolve pedindo esclarecimento.
REPORT_PURPOSES = [
    'Fisioterapia', 'Fonoaudiologia', 'Terapia ocupacional', 'Reabilitação',
    'Convênio / plano de saúde', 'INSS / benefício / perícia',
    'Trabalho / afastamento / adaptação', 'Escola / universidade',
    'Medicação / tratamento', 'Outro',
]


class PortalBaseView(View):
    """Resolve a clínica pelo slug e recusa quando o portal não está publicado."""

    def dispatch(self, request, slug, *args, **kwargs):
        self.tenant, self.clinic = portal.clinic_or_none(slug)
        if self.tenant is None:
            raise Http404
        self.slug = slug
        return super().dispatch(request, slug, *args, **kwargs)

    def base_context(self, **extra):
        context = {
            'slug': self.slug,
            'clinic_name': self.tenant.trade_name or self.tenant.legal_name,
            'notice': self.clinic.patient_portal_notice,
            'privacy_version': portal.PRIVACY_NOTICE_VERSION,
        }
        context.update(extra)
        return context


class PortalIdentifyView(PortalBaseView):
    """Etapa 1 — quem é o paciente."""

    template_name = 'documents/portal_identify.html'

    def get(self, request, slug):
        if portal.verified_patient(request, self.tenant) is not None:
            return redirect('portal:request', slug=slug)
        return render(request, self.template_name, self.base_context())

    def post(self, request, slug):
        from datetime import date

        if request.POST.get('privacy_ack') != '1':
            return render(request, self.template_name, self.base_context(
                error='Para prosseguir, confirme a ciência sobre o uso dos dados.',
            ), status=400)

        try:
            nascimento = date.fromisoformat(request.POST.get('birth_date', ''))
        except ValueError:
            nascimento = None

        try:
            patient = portal.identify(
                request, self.tenant, request.POST.get('cpf', ''), nascimento,
            )
        except portal.TooManyAttempts as exc:
            return render(request, self.template_name, self.base_context(error=str(exc)),
                          status=429)

        if patient is None:
            # Mensagem única para CPF inválido, data errada e paciente
            # inexistente. Distinguir os casos diria a quem tenta se aquele
            # CPF é de paciente da clínica — que é exatamente o que não
            # pode ser dito.
            return render(request, self.template_name, self.base_context(
                error='Não encontramos um cadastro ativo com esses dados. '
                      'Confira o CPF e a data de nascimento.',
            ), status=404)
        return redirect('portal:request', slug=slug)


class PortalRequestView(PortalBaseView):
    """Etapa 2 — o que o paciente precisa."""

    template_name = 'documents/portal_request.html'

    def get(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)
        return render(request, self.template_name, self.base_context(
            patient=patient, kinds=DocumentRequestKind.choices, purposes=REPORT_PURPOSES,
        ))

    def post(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)

        kind = request.POST.get('kind', '')
        if kind not in DocumentRequestKind.values:
            return self._invalid(request, patient, 'Escolha o tipo de solicitação.')

        proprio = request.POST.get('requester') != 'other'
        nome = (patient.full_name if proprio
                else (request.POST.get('requester_name') or '').strip())
        if not nome:
            return self._invalid(request, patient, 'Informe o nome de quem está solicitando.')

        payload, erro = self._payload(request, kind)
        if erro:
            return self._invalid(request, patient, erro)

        try:
            portal.submit(request, self.tenant, patient, kind, nome, proprio, payload)
        except portal.TooManyAttempts as exc:
            return self._invalid(request, patient, str(exc), status=429)

        messages.success(request, 'Pedido enviado.')
        return redirect('portal:done', slug=slug)

    def _invalid(self, request, patient, erro, status=400):
        return render(request, self.template_name, self.base_context(
            patient=patient, kinds=DocumentRequestKind.choices,
            purposes=REPORT_PURPOSES, error=erro,
        ), status=status)

    def _payload(self, request, kind):
        """Monta o conteúdo do pedido conforme o tipo, e valida o mínimo.

        Devolve `(payload, erro)`. O que se valida aqui é presença, não
        conteúdo clínico: quem julga se a medicação pedida faz sentido é o
        médico, na revisão — e um portal que recusasse o texto do paciente
        por conteúdo estaria praticando medicina.
        """
        if kind in (DocumentRequestKind.PRESCRIPTION_SIMPLE,
                    DocumentRequestKind.PRESCRIPTION_SPECIAL):
            nomes = request.POST.getlist('med_name')
            doses = request.POST.getlist('med_dose')
            usos = request.POST.getlist('med_usage')
            medicacoes = []
            for nome, dose, uso in zip(nomes, doses, usos):
                nome, dose, uso = nome.strip(), dose.strip(), uso.strip()
                if not any([nome, dose, uso]):
                    continue
                if not nome or not dose or not uso:
                    return None, ('Em cada medicação, informe o nome, a dose e como '
                                  'você utiliza.')
                medicacoes.append({'nome': nome[:120], 'dose': dose[:80], 'uso': uso[:180]})
            if not medicacoes:
                return None, 'Adicione ao menos uma medicação.'
            return {'medicacoes': medicacoes}, None

        if kind == DocumentRequestKind.REPORT:
            finalidade = (request.POST.get('purpose') or '').strip()
            conteudo = (request.POST.get('content') or '').strip()
            if not finalidade or not conteudo:
                return None, 'Informe a finalidade do relatório e o que precisa constar.'
            return {'finalidade': finalidade[:120], 'conteudo': conteudo[:4000]}, None

        exames = (request.POST.get('exams') or '').strip()
        if not exames:
            return None, 'Informe quais exames você precisa.'
        return {
            'exames': exames[:4000],
            'observacao': (request.POST.get('exam_note') or '').strip()[:2000],
        }, None


class PortalDoneView(PortalBaseView):
    template_name = 'documents/portal_done.html'

    def get(self, request, slug):
        return render(request, self.template_name, self.base_context())


class PortalMedicationSearchView(PortalBaseView):
    """Autocomplete de medicamento no portal público.

    Público porque o formulário é público — e o que ele devolve é a lista
    de preços da CMED, que a Anvisa publica na internet aberta. Não há
    nada aqui do paciente, da clínica nem do sistema.

    Herda de `PortalBaseView` de propósito: assim o endereço só responde
    para clínica cujo portal está **publicado**, exatamente como o
    formulário. Uma clínica que desligou o portal não passa a ter um
    endpoint aberto por esquecimento.
    """

    def get(self, request, slug):
        from catalogs.selectors import search_medications

        return JsonResponse({'results': search_medications(request.GET.get('q', ''))})

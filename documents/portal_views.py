"""Telas do portal público de solicitações.

Sem conta e sem sessão prévia. Duas etapas: identificar o paciente e
descrever o pedido. A segunda só abre depois da primeira, e a primeira
expira em trinta minutos.
"""

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from audit.services import record_audit_event

from . import portal, portal_retorno
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

    def _bloqueado(self, request, impedimento, patient):
        """A tela da janela de retorno, com a porta do envio de exames.

        Mesma tela e mesmo 403 nas três portas do pedido. O que ela ganhou
        foi o caminho para mandar laudo, que a janela não barra.
        """
        return render(request, 'documents/portal_retorno.html', self.base_context(
            bloqueio=impedimento, patient_first_name=patient.full_name.split(' ')[0],
            pode_enviar_exames=True,
        ), status=403)

    def base_context(self, **extra):
        context = {
            'slug': self.slug,
            'clinic_name': self.tenant.trade_name or self.tenant.legal_name,
            'notice': self.clinic.patient_portal_notice,
            # O encarregado vai em toda tela do portal, e não só na
            # primeira: quem chega aqui pelo link de um documento não
            # passa pela identificação, e o contato tem de estar onde a
            # pessoa estiver. LGPD art. 41, §1º.
            'dpo': {
                'nome': self.clinic.dpo_name,
                'email': self.clinic.dpo_email,
                'telefone': self.clinic.dpo_phone,
            },
            'privacy_version': portal.PRIVACY_NOTICE_VERSION,
            # Telefone e e-mail da clínica: a tela que recusa um pedido
            # precisa dizer como marcar a consulta que destrava o pedido.
            # Recusar sem oferecer o caminho seguinte joga o paciente de
            # volta na busca do Google.
            'clinic_phone': self.clinic.phone,
            'clinic_email': self.clinic.email,
        }
        context.update(extra)
        return context


class PortalIdentifyView(PortalBaseView):
    """Etapa 1 — quem é o paciente."""

    template_name = 'documents/portal_identify.html'

    def get(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        # Quem a janela de retorno barrou continua identificado (para
        # poder mandar exame), e por isso volta ao formulário, e não ao
        # pedido: senão a mãe que identificou um filho barrado ficaria
        # trinta minutos sem conseguir identificar o outro.
        if patient is not None and portal_retorno.bloqueio(self.clinic, patient) is None:
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

        # A janela de retorno, conferida aqui e não na tela seguinte:
        # descobrir a recusa depois de descrever cinco medicamentos é pior
        # do que descobrir antes de começar.
        #
        # A sessão **continua** (até 2026-10-18 era descartada aqui), porque
        # a janela barra pedido de ato médico e não o envio de laudo de
        # exame -- ver `documents.portal_exames`. `/solicitar/` não fica
        # aberto por isso: ele confere a janela de novo a cada GET e POST.
        impedimento = portal_retorno.bloqueio(self.clinic, patient)
        if impedimento is not None:
            record_audit_event(
                None, self.tenant.id, 'documents.portal_request_window_closed',
                object_type='patient', object_id=patient.id, outcome='denied',
                integrity_metadata={'dias': impedimento.dias},
            )
            return self._bloqueado(request, impedimento, patient)
        return redirect('portal:request', slug=slug)


class PortalRequestView(PortalBaseView):
    """Etapa 2 — o que o paciente precisa."""

    template_name = 'documents/portal_request.html'

    def get(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)
        impedimento = portal_retorno.bloqueio(self.clinic, patient)
        if impedimento is not None:
            return self._bloqueado(request, impedimento, patient)
        return render(request, self.template_name, self.base_context(
            patient=patient, kinds=DocumentRequestKind.choices, purposes=REPORT_PURPOSES,
            identidade=portal.identity_token(request),
        ))

    def post(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)

        # De novo, e não só na identificação: entre abrir a sessão e
        # enviar cabe o médico apertar a janela, e uma sessão aberta
        # antes não pode valer como autorização depois.
        impedimento = portal_retorno.bloqueio(self.clinic, patient)
        if impedimento is not None:
            return self._bloqueado(request, impedimento, patient)

        if not portal.token_confere(request, request.POST.get('identidade')):
            # 409, e o formulário de novo **para quem está identificado
            # agora**, com o nome à vista: a pessoa vê de quem é a ficha e
            # escreve o pedido certo. Gravar o texto na ficha errada era o
            # que acontecia.
            return self._invalid(
                request, patient,
                f'Outra pessoa foi identificada neste navegador depois que este formulário '
                f'foi aberto. Confira: o pedido agora será feito para '
                f'{patient.full_name.split(" ")[0]}. Escreva-o de novo e envie.',
                status=409,
            )

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
            purposes=REPORT_PURPOSES, error=erro, identidade=portal.identity_token(request),
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


class PortalExamUploadView(PortalBaseView):
    """Envio de laudos de exame pelo paciente. Ver `documents.portal_exames`.

    Exige a mesma identificação dos pedidos, e só ela: a janela de retorno
    não se aplica (ver o módulo).
    """

    template_name = 'documents/portal_exames.html'

    def get(self, request, slug):
        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)
        return render(request, self.template_name, self._context(request, patient))

    def post(self, request, slug):
        from . import portal_exames

        patient = portal.verified_patient(request, self.tenant)
        if patient is None:
            return redirect('portal:identify', slug=slug)

        if not portal.token_confere(request, request.POST.get('identidade')):
            return self._invalid(
                request, patient,
                f'Outra pessoa foi identificada neste navegador depois que esta página '
                f'foi aberta. Confira: os exames agora serão enviados para '
                f'{patient.full_name.split(" ")[0]}. Escolha os arquivos de novo e envie.',
                status=409,
            )

        proprio = request.POST.get('requester') != 'other'
        nome = (patient.full_name if proprio
                else (request.POST.get('requester_name') or '').strip())
        if not nome:
            return self._invalid(request, patient, 'Informe o nome de quem está enviando.')

        if portal_exames.limite_excedido(request):
            return self._invalid(
                request, patient,
                'Muitos envios a partir deste endereço. Aguarde e tente novamente.',
                status=429,
            )

        try:
            linhas = portal_exames.ler_formulario(request.POST, request.FILES)
            portal_exames.receber(request, self.tenant, patient, linhas, nome, proprio)
        except portal_exames.EnvioRecusado as exc:
            return self._invalid(request, patient, str(exc))

        request.session['portal_exames_enviados'] = len(linhas)
        return redirect('portal:exams-done', slug=slug)

    def _context(self, request, patient, **extra):
        from . import portal_exames
        from .models import PortalExamType

        return self.base_context(
            patient=patient, identidade=portal.identity_token(request),
            tipos=PortalExamType.choices, linhas=range(1, portal_exames.MAX_ARQUIVOS + 1),
            max_arquivos=portal_exames.MAX_ARQUIVOS,
            max_mb=portal_exames.MAX_BYTES // (1024 * 1024),
            max_bytes=portal_exames.MAX_BYTES,
            hoje=timezone.localdate().isoformat(),
            **extra,
        )

    def _invalid(self, request, patient, erro, status=400):
        # Os arquivos não voltam no formulário -- o navegador não deixa
        # repreencher um campo de arquivo --, e a mensagem diz qual linha.
        return render(request, self.template_name,
                      self._context(request, patient, error=erro), status=status)


class PortalLeaveView(PortalBaseView):
    """Encerra a identificação sem enviar nada.

    A identificação já se encerrava ao concluir um pedido ou um envio de
    exames, e expirava em trinta minutos. Faltava a saída de quem desiste
    no meio, ou termina e quer deixar o computador -- o caso da recepção,
    da lan house e do celular emprestado. Só POST: um link de GET que
    encerra sessão pode ser disparado por qualquer página.
    """

    def post(self, request, slug):
        portal.clear(request)
        request.session.pop('portal_exames_enviados', None)
        messages.info(request, 'Identificação encerrada.')
        return redirect('portal:identify', slug=slug)


class PortalExamDoneView(PortalBaseView):
    template_name = 'documents/portal_exames_enviados.html'

    def get(self, request, slug):
        quantos = request.session.pop('portal_exames_enviados', None)
        return render(request, self.template_name, self.base_context(quantos=quantos))


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

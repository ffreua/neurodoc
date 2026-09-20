from django.conf import settings
from django.contrib.auth import login as auth_login
from django.shortcuts import redirect, render
from django.views import View

from accounts.services import send_email_verification
from audit.services import record_audit_event
from tenancy.invitations import peek_invitation
from tenancy.models import InvitationPurpose
from tenancy.services import EmailAlreadyRegistered, InvalidInvitation, accept_platform_invitation

from .content import FAQ, RECURSOS
from .help_content import ARTICLES as HELP_ARTICLES
from .forms import InvitationCodeForm, LeadForm, OrganizationSignupForm
from base.net import client_ip


class LandingView(View):
    """A pagina de vendas, em `/`.

    Faz tres coisas que antes estavam em telas diferentes ou em lugar
    nenhum: apresenta o produto, mostra os planos com os limites reais
    lidos de `tenancy.plans`, e recebe pedido de contato.

    Os limites vem do catalogo, e nao escritos no template, para a pagina
    publica e o que o sistema cumpre nao poderem divergir: anunciar "ate
    500 pacientes" enquanto o servidor corta em 400 seria descoberto pelo
    cliente, no dia em que ele batesse o limite.

    O campo do convite continua aqui, embaixo: quem ja fechou negocio
    chega com um codigo, e mandar essa pessoa procurar outra tela seria
    trabalho para o cliente que ja pagou.
    """

    def _context(self, **overrides):
        from tenancy.plans import DESCONTO_PROMOCIONAL, public_plans

        context = {
            'form': InvitationCodeForm(),
            'lead_form': LeadForm(),
            'plans': public_plans(),
            # O percentual da promocao vai separado dos cartoes porque a
            # pagina o anuncia uma vez, em prosa, acima deles. Zero
            # apaga a frase e os valores riscados de uma vez so.
            'desconto_promocional': DESCONTO_PROMOCIONAL,
            'recursos': RECURSOS,
            'faq': FAQ,
            # Quatro artigos do manual, para a pagina mostrar que ele existe
            # sem virar um indice dentro da pagina de vendas.
            'manual_destaques': HELP_ARTICLES[1:5],
            'leads_email': settings.LEADS_EMAIL,
            'enviado': False,
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'onboarding/landing.html', self._context())

    def post(self, request):
        # Duas acoes na mesma pagina, distinguidas por um campo oculto.
        # Sem ele, o formulario de contato e o do convite disputariam o
        # mesmo POST, e o erro de um apareceria no outro.
        if request.POST.get('action') == 'lead':
            return self._contato(request)

        form = InvitationCodeForm(request.POST)
        if not form.is_valid():
            return render(request, 'onboarding/landing.html', self._context(form=form))
        code = form.cleaned_data['code'].strip()
        invitation = peek_invitation(code)
        if invitation is None or invitation.purpose != InvitationPurpose.PLATFORM:
            form.add_error('code', 'Convite invalido, expirado ou ja utilizado.')
            return render(request, 'onboarding/landing.html', self._context(form=form))
        return redirect('onboarding:signup', token=code)

    def _contato(self, request):
        from tenancy import leads as leads_service
        from tenancy.models import Lead

        lead_form = LeadForm(request.POST)
        if leads_service.rate_limited(request):
            lead_form.add_error(
                None,
                'Recebemos varios pedidos deste endereco nos ultimos minutos. '
                f'Se for urgente, escreva direto para {settings.LEADS_EMAIL}.',
            )
            return render(request, 'onboarding/landing.html',
                          self._context(lead_form=lead_form), status=429)
        if not lead_form.is_valid():
            return render(request, 'onboarding/landing.html',
                          self._context(lead_form=lead_form), status=400)

        dados = lead_form.cleaned_data
        # Grava primeiro, avisa depois. Com o envio antes, o SMTP fora
        # significaria lead perdido -- e e a unica falha desta tela que
        # ninguem percebe, porque quem preencheu ve a mesma mensagem de
        # sucesso de sempre.
        lead = Lead.objects.create(
            name=dados['name'], email=dados['email'].lower(),
            phone=leads_service.normalize_phone(dados.get('phone')),
            clinic_name=(dados.get('clinic_name') or '').strip(),
            plan=dados.get('plan') or '',
            message=(dados.get('message') or '').strip(),
            source_ip=client_ip(request) or None,
            privacy_notice_version=leads_service.PRIVACY_NOTICE_VERSION,
        )
        record_audit_event(
            None, None, 'tenancy.lead_received', object_type='lead',
            object_id=lead.id, outcome='success',
            integrity_metadata={'plan': lead.plan},
        )
        leads_service.notify(lead)
        # Sucesso mesmo quando o aviso falha: do ponto de vista de quem
        # preencheu, o pedido **foi** recebido -- esta no banco. Dizer
        # "erro, tente de novo" faria a pessoa reenviar o que ja chegou.
        return render(request, 'onboarding/landing.html',
                      self._context(enviado=True, lead_nome=lead.name))


class OrganizationSignupView(View):
    def _invitation_or_none(self, token):
        invitation = peek_invitation(token)
        if invitation is None or invitation.purpose != InvitationPurpose.PLATFORM:
            return None
        return invitation

    def get(self, request, token):
        if self._invitation_or_none(token) is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        return render(request, 'onboarding/signup.html', {'form': OrganizationSignupForm()})

    def post(self, request, token):
        if self._invitation_or_none(token) is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        form = OrganizationSignupForm(request.POST)
        if not form.is_valid():
            return render(request, 'onboarding/signup.html', {'form': form})
        try:
            user, tenant, membership = accept_platform_invitation(
                token,
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                legal_name=form.cleaned_data['legal_name'],
                trade_name=form.cleaned_data['trade_name'],
                cnpj=form.cleaned_data['cnpj'],
            )
        except InvalidInvitation:
            form.add_error(None, 'Convite inválido, expirado ou já utilizado.')
            return render(request, 'onboarding/signup.html', {'form': form})
        except EmailAlreadyRegistered:
            form.add_error('email', 'Este e-mail já possui conta. Faça login para vincular uma organização.')
            return render(request, 'onboarding/signup.html', {'form': form})
        record_audit_event(
            user, tenant, 'tenancy.organization_created',
            object_type='tenant', object_id=tenant.id, outcome='success',
        )
        auth_login(request, user)
        send_email_verification(user, request)
        return render(request, 'accounts/email_verification_sent.html')

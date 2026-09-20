from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.shortcuts import redirect, render
from django.urls import reverse
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


class StartFreePlanView(View):
    """Plano Gratuito sem passar por ninguém.

    O caminho antigo era o mesmo dos planos pagos: preencher o formulário,
    esperar alguém ler, receber um código de convite por e-mail. Para quem
    vai pagar, essa conversa faz sentido e é onde o negócio acontece. Para
    quem quer experimentar cinquenta pacientes de graça, ela é só uma
    porta entre a vontade de testar e o teste — e quem desiste ali desiste
    em silêncio, sem nunca aparecer como lead.

    Aqui o convite é emitido na hora e a pessoa cai direto na tela de
    criação da clínica. O convite é o mesmo objeto de sempre
    (`tenancy.invitations`), com o mesmo consumo atômico e o mesmo plano
    gravado: nada neste caminho cria organização por fora das regras.

    **POST, e não link.** Um `GET` que cria convite é acionado por
    qualquer imagem apontada para cá numa página de terceiro, e cada
    visitante daquela página emitiria um. Com POST e CSRF, o pedido tem de
    nascer de um formulário desta página.
    """

    #: Convites por IP na janela. Três é generoso para quem legitimamente
    #: recomeça (fechou a aba, errou o e-mail, quis outra clínica) e curto
    #: para quem automatiza.
    LIMITE_POR_IP = 3
    JANELA_SEGUNDOS = 3600

    #: Dois dias. O convite existe para atravessar a distância entre o
    #: clique e o cadastro, não para ficar guardado: quem clicou está
    #: olhando a tela agora, e um token de semanas é um token que vaza de
    #: um histórico de navegador.
    TTL_DIAS = 2

    def get(self, request):
        """Sem POST não há convite — mas também não há erro na cara.

        Alguém chega aqui pelo histórico do navegador ou por um link
        colado. Mandar de volta para os planos é o que essa pessoa queria.
        """
        return redirect(f"{reverse('onboarding:landing')}#planos")

    def post(self, request):
        from tenancy.invitations import issue_invitation
        from tenancy.models import InvitationPurpose
        from tenancy.plans import PlanCode

        # Campo-armadilha, o mesmo do formulário de contato: invisível na
        # tela, preenchido por robô que preenche tudo. Quem cai nele volta
        # para a página sem convite e sem saber que foi barrado.
        if (request.POST.get('website') or '').strip():
            return redirect(f"{reverse('onboarding:landing')}#planos")

        if self._excedeu_o_limite(request):
            # Para o formulário de contato, e não para uma página de erro:
            # quem estourou o limite pode ser uma clínica inteira atrás do
            # mesmo IP, e essa pessoa precisa de um caminho — não de um
            # "tente mais tarde".
            messages.info(
                request,
                'Já emitimos alguns acessos a partir desta conexão agora há pouco. '
                'Deixe seu contato que devolvemos o código do plano Gratuito.',
            )
            return redirect(f"{reverse('onboarding:landing')}#contato")

        invitation, raw_token = issue_invitation(
            purpose=InvitationPurpose.PLATFORM,
            plan=PlanCode.FREE,
            ttl_days=self.TTL_DIAS,
        )
        # `issued_by` fica nulo de propósito: não houve pessoa emitindo.
        # A trilha registra a origem, que é o que distingue este convite
        # de um emitido no console pelo superadministrador.
        record_audit_event(
            None, None, 'tenancy.free_plan_invitation_issued',
            object_type='invitation', object_id=invitation.id, outcome='success',
            origin_ip=client_ip(request),
            integrity_metadata={'plan': PlanCode.FREE, 'origem': 'landing'},
        )
        return redirect('onboarding:signup', token=raw_token)

    def _excedeu_o_limite(self, request):
        """Conta convites por IP. Falha **fechada**, ao contrário do lead.

        O formulário de contato falha aberto de propósito: com o Redis
        fora, o pior caso é um lead de robô no banco, e fechar ali
        transformaria uma indisponibilidade em página de vendas que não
        recebe contato.

        Aqui o pior caso é outro. Este botão cria organização, e sem
        contagem não há nada entre um script e um banco cheio de clínicas
        vazias. Então, quando não dá para contar, este caminho fecha e a
        pessoa vai para o formulário — que continua funcionando.
        """
        from django.core.cache import cache

        chave = f'plano-gratis:{client_ip(request)}'
        try:
            cache.get_or_set(chave, 0, self.JANELA_SEGUNDOS)
            return cache.incr(chave) > self.LIMITE_POR_IP
        except Exception:                                   # noqa: BLE001
            return True


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

    def _plano_do_convite(self, invitation):
        """O que esta clínica vai ser, dito antes de ela existir.

        Passou a importar quando o cartão do plano Gratuito virou um botão
        que traz direto para cá: quem clicou escolheu um plano na tela
        anterior e precisa reconhecer a escolha aqui, ou a sensação é de
        ter sido levado para outro lugar. Vale igual para quem chega com
        um código combinado por telefone — ver o plano escrito é a
        confirmação de que o código é o certo.
        """
        from tenancy.limits import describe_limit
        from tenancy.plans import max_doctors, max_patients, plan_label

        return {
            'rotulo': plan_label(invitation.plan),
            'pacientes': describe_limit(max_patients(invitation.plan)),
            'medicos': describe_limit(max_doctors(invitation.plan)),
        }

    def get(self, request, token):
        invitation = self._invitation_or_none(token)
        if invitation is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        return render(request, 'onboarding/signup.html', {
            'form': OrganizationSignupForm(),
            'plano': self._plano_do_convite(invitation),
        })

    def post(self, request, token):
        if self._invitation_or_none(token) is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        form = OrganizationSignupForm(request.POST)
        if not form.is_valid():
            return render(request, 'onboarding/signup.html', {
                'form': form,
                'plano': self._plano_do_convite(self._invitation_or_none(token)),
            })
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
            convite = self._invitation_or_none(token)
            return render(request, 'onboarding/signup.html', {
                'form': form,
                'plano': self._plano_do_convite(convite) if convite else None,
            })
        record_audit_event(
            user, tenant, 'tenancy.organization_created',
            object_type='tenant', object_id=tenant.id, outcome='success',
        )
        auth_login(request, user)
        send_email_verification(user, request)
        return render(request, 'accounts/email_verification_sent.html')

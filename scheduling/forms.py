from datetime import date, timedelta

from django.utils import timezone
from django import forms

from base.widgets import HTML5DateInput, HTML5DateTimeInput, HTML5TimeInput

from .models import (
    DEFAULT_TYPE_MINUTES, AppointmentType, AvailabilityRule, HolidayScope,
)
from .publishing import WEEKDAY_LABELS


def _doctor_queryset(tenant_id):
    from tenancy.models import Membership, MembershipStatus, Role

    if tenant_id is None:
        return Membership.objects.none()
    return Membership.objects.filter(
        tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('user', 'user__physician_profile')


def _doctor_label(membership):
    return membership.user.get_full_name() or membership.user.email


class DoctorChoiceForm(forms.Form):
    """Seletor de médico do painel da secretaria.

    A agenda é sempre de **um** médico por vez: horário livre só quer dizer
    algo dentro da agenda de quem vai atender, e uma grade com todos os
    médicos empilhados não responde "que horário posso oferecer".
    """

    physician_membership = forms.ModelChoiceField(
        queryset=None, label='Médico', empty_label=None,
    )

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician_membership'].queryset = _doctor_queryset(tenant_id)
        self.fields['physician_membership'].label_from_instance = _doctor_label


class TypeDurationForm(forms.Form):
    """Duração de cada tipo de atendimento, por médico (RF-06.02).

    Um campo por tipo, gerado do próprio enum: tipo novo aparece na tela sem
    mexer no formulário.
    """

    def __init__(self, *args, initial_minutes=None, **kwargs):
        super().__init__(*args, **kwargs)
        initial_minutes = initial_minutes or {}
        for value, label in AppointmentType.choices:
            self.fields[f'minutes_{value}'] = forms.IntegerField(
                label=label, min_value=5, max_value=480,
                initial=initial_minutes.get(value, DEFAULT_TYPE_MINUTES[value]),
                help_text='minutos',
                widget=forms.NumberInput(attrs={'step': '5', 'inputmode': 'numeric'}),
            )

    @property
    def minutes_by_type(self):
        return {
            value: self.cleaned_data.get(f'minutes_{value}')
            for value, _ in AppointmentType.choices
        }

    def clean(self):
        cleaned = super().clean()
        values = [v for v in (
            cleaned.get(f'minutes_{value}') for value, _ in AppointmentType.choices
        ) if v]
        if values:
            from math import gcd

            step = values[0]
            for value in values[1:]:
                step = gcd(step, value)
            self.suggested_slot = max(step, 5)
        return cleaned


#: Escolhas de vigência da agenda. É a resposta a "pelo período de tempo que
#: eu quiser": em vez de obrigar a calcular a data, os prazos que se usam de
#: fato estão prontos, e "outra data" continua disponível.
HORIZON_CHOICES = (
    ('90', '3 meses'),
    ('180', '6 meses'),
    ('365', '1 ano'),
    ('730', '2 anos'),
    ('', 'Sem prazo (até eu mudar)'),
    ('custom', 'Escolher a data final'),
)


class WeeklyScheduleForm(forms.Form):
    """Grade semanal do médico, para vários dias de uma vez.

    Um formulário por dia da semana obrigaria a repetir cinco vezes o mesmo
    horário — e é assim que se descreve a própria agenda: "segunda e terça
    das 8 às 18, quinta das 8 às 14". Marcar os dias e informar a janela uma
    vez gera uma regra por dia marcado.
    """

    weekdays = forms.MultipleChoiceField(
        label='Dias da semana', choices=WEEKDAY_LABELS,
        widget=forms.CheckboxSelectMultiple,
    )
    local_start = forms.TimeField(label='Início do atendimento', widget=HTML5TimeInput())
    local_end = forms.TimeField(label='Fim do atendimento', widget=HTML5TimeInput())
    slot_minutes = forms.IntegerField(
        label='Célula da agenda', min_value=5, max_value=240, initial=40,
        help_text='Em minutos. É o menor bloco da grade; um atendimento mais longo '
                  'ocupa várias células.',
        widget=forms.NumberInput(attrs={'step': '5', 'inputmode': 'numeric'}),
    )
    buffer_minutes = forms.IntegerField(
        label='Intervalo entre atendimentos', min_value=0, max_value=120, initial=0,
        required=False, help_text='Em minutos. Fica reservado depois de cada consulta.',
        widget=forms.NumberInput(attrs={'step': '5', 'inputmode': 'numeric'}),
    )
    starts_on = forms.DateField(
        label='Vale a partir de', widget=HTML5DateInput(), initial=date.today,
    )
    horizon = forms.ChoiceField(label='Por quanto tempo', choices=HORIZON_CHOICES, initial='365')
    ends_on = forms.DateField(
        label='Data final', required=False, widget=HTML5DateInput(),
        help_text='Só quando "Escolher a data final" estiver selecionado.',
    )
    replace_existing = forms.BooleanField(
        label='Substituir o que já existe nesses dias', required=False, initial=True,
        help_text='Desmarque para acrescentar uma segunda janela no mesmo dia '
                  '(por exemplo, manhã e tarde com durações diferentes).',
    )

    # ------------------------------------------------ intervalos pontuais
    #
    # Coisa diferente de `buffer_minutes`, e vale dizer por quê: aquele
    # reserva minutos **depois de cada** atendimento, para a consulta que
    # estourou não empurrar a seguinte. Isto é a pausa de relógio — o
    # almoço, o café —, que cai num horário fixo e em horário diferente a
    # cada dia da semana.
    #
    # Três pares, e não uma lista que cresce: duas pausas num dia (café e
    # almoço) cobrem o consultório; a terceira é folga. Uma lista
    # dinâmica pediria JavaScript para acrescentar linha, e o ganho não
    # paga — quem precisar de uma quarta manda num segundo envio, com os
    # mesmos dias e sem substituir.
    pausa_1_inicio = forms.TimeField(label='Intervalo 1 — início', required=False, widget=HTML5TimeInput())
    pausa_1_fim = forms.TimeField(label='Intervalo 1 — fim', required=False, widget=HTML5TimeInput())
    pausa_1_motivo = forms.CharField(
        label='Intervalo 1 — motivo', required=False, max_length=80,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Almoço'}),
    )
    pausa_2_inicio = forms.TimeField(label='Intervalo 2 — início', required=False, widget=HTML5TimeInput())
    pausa_2_fim = forms.TimeField(label='Intervalo 2 — fim', required=False, widget=HTML5TimeInput())
    pausa_2_motivo = forms.CharField(
        label='Intervalo 2 — motivo', required=False, max_length=80,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Café'}),
    )
    pausa_3_inicio = forms.TimeField(label='Intervalo 3 — início', required=False, widget=HTML5TimeInput())
    pausa_3_fim = forms.TimeField(label='Intervalo 3 — fim', required=False, widget=HTML5TimeInput())
    pausa_3_motivo = forms.CharField(
        label='Intervalo 3 — motivo', required=False, max_length=80,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Reunião'}),
    )

    #: Quantos pares de intervalo a tela desenha. Lido pelo template e
    #: pelo `clean`, para acrescentar o quarto ser mudar um número só.
    PAUSAS = (1, 2, 3)

    def pausas_declaradas(self):
        """Os intervalos preenchidos, já validados, em ordem de início.

        Devolve `[]` quando nenhum foi informado — que é o caso comum, e
        é por isso que os campos não são obrigatórios.
        """
        encontrados = []
        for indice in self.PAUSAS:
            inicio = self.cleaned_data.get(f'pausa_{indice}_inicio')
            fim = self.cleaned_data.get(f'pausa_{indice}_fim')
            if inicio and fim:
                encontrados.append({
                    'inicio': inicio, 'fim': fim,
                    'motivo': (self.cleaned_data.get(f'pausa_{indice}_motivo') or '').strip(),
                })
        return sorted(encontrados, key=lambda p: p['inicio'])

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('local_start')
        end = cleaned.get('local_end')
        if start and end and start >= end:
            self.add_error('local_end', 'O fim do atendimento tem de ser depois do início.')

        starts_on = cleaned.get('starts_on')
        horizon = cleaned.get('horizon')
        ends_on = cleaned.get('ends_on')
        if horizon == 'custom':
            if not ends_on:
                self.add_error('ends_on', 'Informe a data final ou escolha um prazo.')
        elif horizon:
            cleaned['ends_on'] = (starts_on or timezone.localdate()) + timedelta(days=int(horizon))
        else:
            cleaned['ends_on'] = None

        resolved_end = cleaned.get('ends_on')
        if starts_on and resolved_end and resolved_end < starts_on:
            self.add_error('ends_on', 'A data final não pode ser anterior ao início da vigência.')

        slot = cleaned.get('slot_minutes')
        if start and end and slot:
            window = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            if window < slot:
                self.add_error(
                    'slot_minutes',
                    f'A célula ({slot} min) não cabe na janela de atendimento ({window} min).',
                )

        # ------------------------------------------- intervalos pontuais
        #
        # Três erros possíveis, e cada um tem mensagem própria porque cada
        # um se corrige de um jeito diferente. Um "intervalo inválido"
        # genérico manda a pessoa adivinhar qual dos três é.
        informados = []
        for indice in self.PAUSAS:
            inicio = cleaned.get(f'pausa_{indice}_inicio')
            fim = cleaned.get(f'pausa_{indice}_fim')
            if not inicio and not fim:
                continue
            if not inicio or not fim:
                faltando = f'pausa_{indice}_inicio' if not inicio else f'pausa_{indice}_fim'
                self.add_error(faltando, 'Informe o início e o fim do intervalo.')
                continue
            if inicio >= fim:
                self.add_error(f'pausa_{indice}_fim', 'O fim do intervalo tem de ser depois do início.')
                continue
            # Fora da janela de atendimento o intervalo não recorta nada,
            # e ficaria gravado sem efeito nenhum — pior que recusar,
            # porque a pessoa sai achando que configurou.
            if start and end and not (start <= inicio and fim <= end):
                self.add_error(
                    f'pausa_{indice}_inicio',
                    f'O intervalo tem de ficar dentro do atendimento '
                    f'({start.strftime("%H:%M")}–{end.strftime("%H:%M")}).',
                )
                continue
            informados.append((indice, inicio, fim))

        # Dois intervalos que se sobrepõem são quase sempre engano de
        # digitação, e gravá-los daria o mesmo resultado de um só — com a
        # tela mostrando dois.
        for i in range(len(informados)):
            for j in range(i + 1, len(informados)):
                _, inicio_a, fim_a = informados[i]
                indice_b, inicio_b, fim_b = informados[j]
                if inicio_a < fim_b and inicio_b < fim_a:
                    self.add_error(
                        f'pausa_{indice_b}_inicio',
                        'Este intervalo se sobrepõe a outro informado acima.',
                    )
        return cleaned


class ScheduleBlockForm(forms.Form):
    """Bloqueio, férias ou atendimento extra numa data."""

    from .models import ScheduleBlockKind

    kind = forms.ChoiceField(
        label='Tipo', initial=ScheduleBlockKind.BLOCK,
        choices=[
            (ScheduleBlockKind.BLOCK, 'Bloqueio'),
            (ScheduleBlockKind.VACATION, 'Férias'),
            (ScheduleBlockKind.EXTRA_AVAILABILITY, 'Atendimento extra'),
        ],
    )
    start_at = forms.DateTimeField(label='Início', widget=HTML5DateTimeInput())
    end_at = forms.DateTimeField(label='Fim', widget=HTML5DateTimeInput())
    reason = forms.CharField(
        label='Motivo', max_length=255, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: congresso, cirurgia, férias'}),
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_at')
        end = cleaned.get('end_at')
        if start and end and start >= end:
            self.add_error('end_at', 'O fim tem de ser depois do início.')
        return cleaned


class ExtraHoursForm(forms.Form):
    """Incluir horário extra num dia, a partir da agenda.

    Quantidade de horários em vez de hora de fim: o fim sai da célula do
    dia (ver `services.include_extra_hours`).
    """

    date = forms.DateField(label='Dia', widget=HTML5DateInput())
    start_time = forms.TimeField(label='Início', widget=HTML5TimeInput())
    cells = forms.IntegerField(label='Quantidade de horários', min_value=1, max_value=24, initial=1)
    reason = forms.CharField(label='Motivo', max_length=255, required=False)


class RemoveFreeSlotForm(forms.Form):
    """Excluir o horário livre clicado; o servidor confere na grade se ele
    ainda está livre (ver `services.remove_free_slot`)."""

    starts_at = forms.DateTimeField(widget=forms.HiddenInput)


class LocalHolidayForm(forms.Form):
    """Feriado estadual ou municipal, cadastrado pela clínica.

    Não é calculável: varia por lei local. `recurring` cobre o caso comum
    (data fixa), então cadastrar uma vez vale para todos os anos.
    """

    name = forms.CharField(
        label='Feriado', max_length=120,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Aniversário da cidade'}),
    )
    date = forms.DateField(label='Data', widget=HTML5DateInput())
    scope = forms.ChoiceField(
        label='Abrangência',
        choices=[(HolidayScope.STATE, 'Estadual'), (HolidayScope.MUNICIPAL, 'Municipal')],
        initial=HolidayScope.MUNICIPAL,
    )
    state = forms.CharField(label='UF', max_length=2, required=False)
    city = forms.CharField(label='Município', max_length=120, required=False)
    recurring = forms.BooleanField(
        label='Repete na mesma data todos os anos', required=False, initial=True,
    )

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        if scope == HolidayScope.STATE and not (cleaned.get('state') or '').strip():
            self.add_error('state', 'Informe a UF do feriado estadual.')
        if scope == HolidayScope.MUNICIPAL and not (cleaned.get('city') or '').strip():
            self.add_error('city', 'Informe o município do feriado municipal.')
        return cleaned


class QuickBookingForm(forms.Form):
    """Marcar no horário clicado, com paciente existente ou pré-cadastro.

    O pré-cadastro é o ponto: ao telefone a secretária tem nome e telefone.
    Exigir CPF, endereço e forma de pagamento naquele momento significa
    perder o agendamento ou inventar dado para passar da tela. O cadastro
    completo aparece no check-in, quando o paciente está na recepção com os
    documentos.
    """

    starts_at = forms.DateTimeField(widget=forms.HiddenInput)
    appointment_type = forms.ChoiceField(
        label='Tipo de atendimento', choices=AppointmentType.choices,
        initial=AppointmentType.FIRST_VISIT,
    )
    patient_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    patient_search = forms.CharField(
        label='Paciente já cadastrado', required=False, max_length=200,
        widget=forms.TextInput(attrs={
            'placeholder': 'Digite o nome para buscar', 'autocomplete': 'off',
            'data-nd-patient-search': '1',
        }),
    )
    new_name = forms.CharField(
        label='Nome do paciente', required=False, max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Nome completo, como ele falou'}),
    )
    new_phone = forms.CharField(
        label='Telefone', required=False, max_length=16,
        widget=forms.TextInput(attrs={
            'placeholder': 'Ex.: (11) 98888-7777', 'inputmode': 'tel',
        }),
    )
    new_email = forms.EmailField(
        label='E-mail', required=False, max_length=254,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Ex.: paciente@email.com', 'inputmode': 'email',
            'autocomplete': 'off',
        }),
    )
    #: Nasce marcada, como no cadastro completo (`patients/forms.py`), e pela
    #: mesma razao: mensagem transacional e execucao do que a pessoa pediu --
    #: confirmar o horario que ela acabou de marcar --, e quem deu o telefone
    #: na ligacao deu para ser chamado. Divulgacao e outra coisa, exige
    #: consentimento especifico e destacado (LGPD art. 11, I) e nao se decide
    #: aqui: `marketing_opt_in_at` continua nulo.
    #:
    #: Marcada e nao implicita: a secretaria esta ao telefone com a pessoa e
    #: pode desmarcar quando ela pedir para nao ser contatada. Deduzir o
    #: consentimento sem oferecer a recusa e o que transforma um aceite em
    #: presuncao.
    contact_accepts_messages = forms.BooleanField(
        label='Pode receber confirmação e lembrete', required=False, initial=True,
    )
    note = forms.CharField(
        label='Observação para a recepção', required=False, max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: primeira vez, indicado pela Dra. Ana'}),
    )
    is_overbook = forms.BooleanField(label='Encaixe fora da grade', required=False)
    override_reason = forms.CharField(
        label='Justificativa do encaixe', required=False, max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Por que este encaixe'}),
    )

    def clean(self):
        cleaned = super().clean()
        has_existing = bool(cleaned.get('patient_id'))
        name = (cleaned.get('new_name') or '').strip()
        if not has_existing and not name:
            self.add_error(
                'new_name',
                'Escolha um paciente já cadastrado ou informe o nome para o pré-cadastro.',
            )
        if not has_existing and name:
            tem_telefone = bool((cleaned.get('new_phone') or '').strip())
            tem_email = bool((cleaned.get('new_email') or '').strip())
            # Um dos dois basta, e nao mais o telefone obrigatoriamente.
            # O que a regra protege e o mesmo de antes: um pre-cadastro sem
            # contato nenhum e um horario que ninguem consegue confirmar
            # depois. O e-mail cumpre esse papel tao bem quanto -- e para
            # quem nao atende numero desconhecido, melhor.
            if not tem_telefone and not tem_email:
                self.add_error(
                    'new_phone',
                    'Informe telefone ou e-mail — é por onde a confirmação sai.',
                )
        if cleaned.get('is_overbook') and not (cleaned.get('override_reason') or '').strip():
            self.add_error('override_reason', 'Encaixe exige justificativa.')
        return cleaned


class RescheduleAppointmentForm(forms.Form):
    starts_at = forms.DateTimeField(label='Novo início', widget=HTML5DateTimeInput())
    ends_at = forms.DateTimeField(label='Novo fim', widget=HTML5DateTimeInput())
    row_version = forms.IntegerField(widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('starts_at')
        end = cleaned.get('ends_at')
        if start and end and start >= end:
            self.add_error('ends_at', 'O fim tem de ser depois do início.')
        return cleaned


class ChangePatientForm(forms.Form):
    """Troca o paciente de um horário já marcado.

    Existe porque acontece: a secretária marca no nome errado, ou o
    pré-cadastro precisa ser ligado ao paciente que já existia no sistema.
    Remarcar e cancelar não resolvem isso — o horário é o mesmo.
    """

    patient_id = forms.UUIDField(widget=forms.HiddenInput)
    patient_search = forms.CharField(
        label='Novo paciente', max_length=200,
        widget=forms.TextInput(attrs={
            'placeholder': 'Digite o nome para buscar', 'autocomplete': 'off',
            'data-nd-patient-search': '1',
        }),
    )
    reason = forms.CharField(
        label='Motivo da troca', max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: horário marcado no nome errado'}),
    )


class ReserveAppointmentForm(forms.Form):
    """Reserva pelo formulário completo, com médico e horário digitados.

    Continua existindo para o caso em que se sabe o horário e não se quer
    navegar até a célula — por exemplo vindo do CRM. O caminho normal é
    clicar no horário livre da grade.
    """

    patient_id = forms.UUIDField(widget=forms.HiddenInput)
    physician_membership = forms.ModelChoiceField(
        queryset=None, label='Médico', empty_label='Selecione o médico',
    )
    starts_at = forms.DateTimeField(label='Início', widget=HTML5DateTimeInput())
    appointment_type = forms.ChoiceField(
        label='Tipo de atendimento', choices=AppointmentType.choices,
        initial=AppointmentType.FIRST_VISIT,
    )
    is_overbook = forms.BooleanField(label='Encaixe (fora da grade)', required=False)
    override_reason = forms.CharField(label='Justificativa do encaixe', max_length=255, required=False)

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician_membership'].queryset = _doctor_queryset(tenant_id)
        self.fields['physician_membership'].label_from_instance = _doctor_label

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('is_overbook') and not (cleaned.get('override_reason') or '').strip():
            self.add_error('override_reason', 'Encaixe exige justificativa.')
        return cleaned


class AvailabilityRuleForm(forms.ModelForm):
    """Edição de uma regra existente, item por item."""

    class Meta:
        model = AvailabilityRule
        fields = [
            'weekday', 'local_start', 'local_end', 'starts_on', 'ends_on',
            'slot_minutes', 'buffer_minutes',
        ]
        labels = {
            'weekday': 'Dia da semana',
            'local_start': 'Início',
            'local_end': 'Fim',
            'starts_on': 'Vale a partir de',
            'ends_on': 'Vale até',
            'slot_minutes': 'Célula (min)',
            'buffer_minutes': 'Intervalo (min)',
        }
        widgets = {
            'weekday': forms.Select(choices=WEEKDAY_LABELS),
            'local_start': HTML5TimeInput(),
            'local_end': HTML5TimeInput(),
            'starts_on': HTML5DateInput(),
            'ends_on': HTML5DateInput(),
        }

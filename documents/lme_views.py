"""A tela da LME: do atendimento ou da ficha do paciente.

Cria o **rascunho** pelo caminho de todo documento (`issuance.create_draft`)
e leva à tela do documento, onde se revisa e se emite para assinar e
carimbar — a LME nunca é assinada digitalmente (`documents/lme.py`).

"Nova LME a partir desta" (`?a_partir_de=<id>`) abre o formulário com o
conteúdo de outra LME **do mesmo paciente e da mesma clínica**: é a
renovação, que repete medicamento, CID e anamnese e muda as quantidades. A
de outro paciente é ignorada, e não aberta: copiar o laudo de um paciente
para outro é o erro que esta regra impede.
"""

import uuid

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import PhysicianProfile
from patients.models import Patient

from . import issuance, lme
from .lme_forms import LmeForm
from .models import MedicalDocument, MedicalDocumentKind
from .views import ClinicalDocumentView, _encounter_or_404, _own_doctor_membership_or_403

TEMPLATE = 'documents/lme_form.html'


def _tenant(request):
    from tenancy.models import Tenant

    return Tenant.objects.get(id=request.access_context.tenant_id)


def _lme_de_base(request, patient):
    """A LME de onde se parte, só se for deste paciente e desta clínica."""
    valor = request.GET.get('a_partir_de') or ''
    if not valor:
        return None
    try:
        uuid.UUID(valor)
    except ValueError:
        return None
    return MedicalDocument.objects.filter(
        tenant_id=request.access_context.tenant_id, patient=patient, kind=MedicalDocumentKind.LME, id=valor,
    ).first()


class _LmeBase(ClinicalDocumentView):
    def _contexto(self, request, patient, encounter, form, base=None):
        return {
            'form': form, 'patient': patient, 'encounter': encounter, 'base': base,
            'sem_atendimento': encounter is None,
            'medicamentos_sugeridos': lme.medicamentos_do_modelo(),
            'versao_modelo': lme.VERSAO_MODELO,
        }

    def _get(self, request, patient, encounter):
        membro = _own_doctor_membership_or_403(request)
        if membro is None:
            return HttpResponseForbidden('Só um vínculo de médico pode emitir a LME.')
        base = _lme_de_base(request, patient)
        if not PhysicianProfile.objects.filter(user_id=membro.user_id).exists():
            # Sem CRM no perfil a criação recusa (`MissingPhysicianProfile`);
            # a tela abre com o mínimo e mostra a recusa no envio.
            inicial = {'paciente': patient.full_name, 'mae': patient.mother_name}
        else:
            inicial = lme.valores_iniciais(_tenant(request), patient, membro, encounter=encounter, base=base)
        return render(request, TEMPLATE, self._contexto(request, patient, encounter, LmeForm(initial=inicial), base))

    def _post(self, request, patient, encounter):
        membro = _own_doctor_membership_or_403(request)
        if membro is None:
            return HttpResponseForbidden('Só um vínculo de médico pode emitir a LME.')
        form = LmeForm(request.POST)
        if not form.is_valid():
            return render(request, TEMPLATE, self._contexto(request, patient, encounter, form))
        try:
            documento = issuance.create_draft(
                _tenant(request), patient, encounter, membro, request.user.id,
                MedicalDocumentKind.LME, form.conteudo(),
            )
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            form.add_error(None, str(exc))
            return render(request, TEMPLATE, self._contexto(request, patient, encounter, form))
        return redirect('documents:medical-detail', document_id=documento.id)


class LmeCreateView(_LmeBase):
    def get(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        return self._get(request, encounter.patient, encounter)

    def post(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        return self._post(request, encounter.patient, encounter)


class PatientLmeCreateView(_LmeBase):
    """A LME pela ficha, sem atendimento — a renovação que não pede consulta."""

    def _paciente(self, request, patient_id):
        return get_object_or_404(
            Patient.objects.filter(tenant_id=request.access_context.tenant_id), id=patient_id,
        )

    def get(self, request, patient_id):
        return self._get(request, self._paciente(request, patient_id), None)

    def post(self, request, patient_id):
        return self._post(request, self._paciente(request, patient_id), None)

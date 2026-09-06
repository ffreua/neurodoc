from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from tenancy.selectors import scope_to_tenant

from . import services
from .context import AIAuthorizationDenied
from .models import AIArtifact, AIJob, AIJobKind
from .review import AlreadyReviewed, ArtifactStale, accept_artifact, reject_artifact


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class EncounterSummaryRequestView(TenantScopedView):
    """Manual trigger for RF-11.01/02 -- a physician explicitly asks for an
    AI-drafted summary of one encounter. Runs the same authorization/
    privacy-policy path as the automatic post-finalization job.
    """

    def post(self, request, encounter_id):
        from clinical.models import Encounter
        from .tasks import run_ai_job

        encounter = get_object_or_404(
            scope_to_tenant(Encounter.objects.all(), request.access_context), id=encounter_id,
        )
        try:
            job = services.create_job(
                request.access_context, AIJobKind.ENCOUNTER_SUMMARY,
                purpose='Resumo solicitado manualmente', patient_id=encounter.patient_id, encounter_id=encounter.id,
            )
        except AIAuthorizationDenied as exc:
            return HttpResponseForbidden(str(exc))
        if job.status == 'queued':
            run_ai_job.delay(str(job.id))
        return redirect('ai:job-detail', job_id=job.id)


class AIJobDetailView(TenantScopedView):
    def get(self, request, job_id):
        job = get_object_or_404(scope_to_tenant(AIJob.objects.all(), request.access_context), id=job_id)
        artifacts = job.artifacts.order_by('-created_at')
        return render(request, 'ai/job_detail.html', {'job': job, 'artifacts': artifacts})


class ArtifactAcceptView(TenantScopedView):
    def post(self, request, artifact_id):
        from tenancy.models import Membership

        artifact = get_object_or_404(scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id)
        reviewer = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            accept_artifact(artifact, reviewer)
        except (ArtifactStale, AlreadyReviewed) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:job-detail', job_id=artifact.job_id)


class ArtifactRejectView(TenantScopedView):
    def post(self, request, artifact_id):
        from tenancy.models import Membership

        artifact = get_object_or_404(scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id)
        reviewer = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            reject_artifact(artifact, reviewer, request.POST.get('reason', ''))
        except (ArtifactStale, AlreadyReviewed) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:job-detail', job_id=artifact.job_id)

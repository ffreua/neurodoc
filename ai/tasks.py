from celery import shared_task

from .models import AIJob, AIJobStatus
from .services import JobNotRunnable, run_job


@shared_task(name='ai.tasks.run_ai_job', expires=600)
def run_ai_job(job_id):
    try:
        artifact = run_job(job_id)
    except JobNotRunnable:
        return {'status': 'skipped'}
    if artifact is None:
        job = AIJob.objects.filter(id=job_id).first()
        return {'status': job.status if job else 'unknown'}
    return {'status': AIJobStatus.SUCCEEDED, 'artifact_id': str(artifact.id)}

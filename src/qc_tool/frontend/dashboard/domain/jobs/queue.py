"""Worker queue claim for persisted QC jobs."""

from django.utils import timezone

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING

from .job import Job


def pull_job(worker_url):
    """Claim the oldest waiting job using the existing guarded update."""

    jobs = Job.objects.filter(job_status=JOB_WAITING).order_by("date_created")[:1]
    if len(jobs) != 1:
        return None
    job = jobs.get()
    affected = Job.objects.filter(
        job_status=JOB_WAITING,
        job_uuid=job.job_uuid,
    ).update(
        job_status=JOB_RUNNING,
        date_started=timezone.now(),
        worker_url=worker_url,
    )
    if affected != 1:
        return None
    return Job.objects.get(job_uuid=job.job_uuid)

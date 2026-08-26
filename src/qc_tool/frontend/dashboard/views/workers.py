"""Internal worker endpoints."""

from django.http import HttpResponseBadRequest
from django.http import JsonResponse
import qc_tool.frontend.dashboard.models as models
from qc_tool.common import CONFIG
from qc_tool.common import WORKER_PORT
from qc_tool.worker_auth import InvalidWorkerUrl
from qc_tool.worker_auth import worker_origin_from_remote_address


def pull_job(request):
    worker_port = CONFIG.get("worker_port", WORKER_PORT)
    try:
        worker_url = worker_origin_from_remote_address(
            request.META.get("REMOTE_ADDR"),
            worker_port,
        )
    except InvalidWorkerUrl:
        return HttpResponseBadRequest("The worker peer address is invalid.")
    job = models.pull_job(worker_url)
    if job is None:
        response = None
    else:
        response = {"job_uuid": job.job_uuid,
                    "product_ident": job.product_ident,
                    "username": job.delivery.user.username,
                    "filename": job.delivery.filename,
                    "skip_steps": job.skip_steps}
        if job.delivery.s3:
            response.update({
                 "s3_host": job.delivery.s3.host,
                 "s3_access_key": job.delivery.s3.access_key,
                 "s3_secret_key": job.delivery.s3.secret_key,
                 "s3_bucketname": job.delivery.s3.bucketname,
                 "s3_key_prefix": job.delivery.s3.key_prefix
            })
    return JsonResponse(response, safe=False)

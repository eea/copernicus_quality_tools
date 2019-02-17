import qc_tool.common as common


# WPS STATUSES
WPS_ACCEPTED = "accepted"
WPS_FAILED = "error"
WPS_STARTED = "started"
WPS_SUCCEEDED = "finished"

# JOB STATUSES
JOB_WAITING = "waiting"
JOB_RUNNING = "running"
JOB_PARTIAL = common.JOB_PARTIAL
JOB_FAILED = common.JOB_FAILED
JOB_ERROR = common.JOB_ERROR
JOB_OK = common.JOB_OK
JOB_DELIVERY_NOT_FOUND = "file_not_found"
JOB_EXPIRED = "expired"

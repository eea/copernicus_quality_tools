"""Allowed delivery-list sort and filter columns."""


COLUMN_LOOKUP = {
    "id": "d.id",
    "name": "d.id",
    "type": "d.s3_id",
    "filename": "d.filename",
    "date_uploaded": "d.date_uploaded",
    "size_bytes": "d.size_bytes",
    "product_ident": "d.product_ident",
    "product_description": "d.product_description",
    "product_unit_code": "d.product_unit_code",
    "submitted_product_unit_code": "d.submitted_product_unit_code",
    "content_sha256": "d.content_sha256",
    "date_submitted": "d.date_submitted",
    "is_deleted": "d.is_deleted",
    "date_created": "j.date_created",
    "date_started": "j.date_started",
    "date_finished": "j.date_finished",
    "last_job_status": "j.job_status",
    "last_job_uuid": "j.job_uuid",
    "username": "u.username",
    "user": "u.username",
}

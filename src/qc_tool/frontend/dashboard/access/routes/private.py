"""Private dashboard routes.

Groups do not appear here. They are reusable bundles of Django permissions;
the same permissions may also be granted directly to a user.
"""

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.access.routes.policies import (
    private_api_key,
    private_session_data,
    private_session_page,
    private_worker,
)


VIEW = AccountPermission.VIEW_DELIVERIES
MANAGE_CONFIGURATION = AccountPermission.MANAGE_CONFIGURATION


SESSION_PRIVATE_ROUTE_POLICIES = {
    # Navigable pages and downloads redirect an anonymous browser to login.
    "dashboard_home": private_session_page(VIEW, "GET"),
    "deliveries": private_session_page(VIEW, "GET"),
    "products": private_session_page(VIEW, "GET"),
    "product_upload": private_session_page(MANAGE_CONFIGURATION, "GET", "POST"),
    "product_remove": private_session_page(MANAGE_CONFIGURATION, "GET", "POST"),
    "product_plan_edit": private_session_page(MANAGE_CONFIGURATION, "GET", "POST"),
    "product_finalize": private_session_page(VIEW, "POST"),
    "submission_queue": private_session_page(VIEW, "GET"),
    "submission_bulk_approve": private_session_page(VIEW, "POST"),
    "submission_queue_slash": private_session_page(VIEW, "GET"),
    "legacy_submission_queue": private_session_page(VIEW, "GET"),
    "submission_review": private_session_page(VIEW, "GET", "POST"),
    "submission_file": private_session_page(VIEW, "GET"),
    "product_detail": private_session_page(VIEW, "GET"),
    "export_deliveries_excel": private_session_page(VIEW, "GET"),
    "download_delivery_file": private_session_page(VIEW, "GET"),
    "job_report_pdf": private_session_page(VIEW, "GET"),
    "job_combined_log": private_session_page(VIEW, "GET"),
    "file_upload": private_session_page(AccountPermission.UPLOAD_DELIVERY, "GET"),
    "legacy_file_upload": private_session_page(
        AccountPermission.UPLOAD_DELIVERY,
        "GET",
    ),
    "job_history": private_session_page(VIEW, "GET"),
    "legacy_job_history": private_session_page(VIEW, "GET"),
    "legacy_delivery_job_history": private_session_page(VIEW, "GET"),
    "boundaries": private_session_page(VIEW, "GET"),
    "boundaries_upload": private_session_page(MANAGE_CONFIGURATION, "GET"),
    "legacy_boundaries_upload": private_session_page(
        MANAGE_CONFIGURATION,
        "GET",
    ),
    "setup_job": private_session_page(AccountPermission.RUN_QC, "GET"),
    "legacy_setup_job": private_session_page(AccountPermission.RUN_QC, "GET"),
    "show_result": private_session_page(VIEW, "GET"),
    "legacy_show_result": private_session_page(VIEW, "GET"),
    "legacy_delivery_show_result": private_session_page(VIEW, "GET"),
    "get_attachment": private_session_page(VIEW, "GET"),
    "announcement": private_session_page(VIEW, "GET"),
    "announcement_update": private_session_page(
        MANAGE_CONFIGURATION,
        "POST",
    ),

    # Session-backed data endpoints return structured 401/403 responses.
    "table_export": private_session_data(VIEW, "POST"),
    "deliveries_json": private_session_data(VIEW, "GET"),
    "job_history_json": private_session_data(VIEW, "GET"),
    "delivery_delete": private_session_data(
        AccountPermission.DELETE_DELIVERY,
        "POST",
    ),
    "delivery_submit": private_session_data(
        AccountPermission.SUBMIT_DELIVERY,
        "POST",
    ),
    "delivery_submit_batch": private_session_data(
        AccountPermission.SUBMIT_DELIVERY,
        "POST",
    ),
    "job_info_json": private_session_data(VIEW, "GET"),
    "product_definition_json": private_session_data(VIEW, "GET"),
    "product_list_json": private_session_data(VIEW, "GET"),
    "legacy_product_list_json": private_session_data(VIEW, "GET"),
    "product_descriptions_dropdown": private_session_data(VIEW, "GET"),
    "job_report_json": private_session_data(VIEW, "GET"),
    "resumable_upload": private_session_data(
        AccountPermission.UPLOAD_DELIVERY,
        "GET",
        "POST",
    ),
    "delivery_upload_check": private_session_data(
        AccountPermission.UPLOAD_DELIVERY,
        "POST",
    ),
    "update_job": private_session_data(VIEW, "POST"),
    "boundaries_json": private_session_data(VIEW, "GET"),
    "boundaries_upload_data": private_session_data(
        MANAGE_CONFIGURATION,
        "POST",
    ),
    "create_job": private_session_data(AccountPermission.RUN_QC, "POST"),
}


MACHINE_PRIVATE_ROUTE_POLICIES = {
    "api_register_delivery": private_api_key(
        AccountPermission.UPLOAD_DELIVERY,
        "POST",
    ),
    "api_register_delivery_s3": private_api_key(
        AccountPermission.UPLOAD_DELIVERY,
        "POST",
    ),
    "api_delivery_list": private_api_key(VIEW, "GET"),
    "api_product_list": private_api_key(VIEW, "GET"),
    "api_product_info": private_api_key(VIEW, "GET"),
    "api_create_job": private_api_key(AccountPermission.RUN_QC, "POST"),
    "api_job_result": private_api_key(VIEW, "GET"),
    "api_job_result_pdf": private_api_key(VIEW, "GET"),
    "api_job_history": private_api_key(VIEW, "GET"),
    "api_submit_delivery_to_eea": private_api_key(
        AccountPermission.SUBMIT_DELIVERY,
        "POST",
    ),
    "pull_job": private_worker("POST"),
}


_duplicates = set(SESSION_PRIVATE_ROUTE_POLICIES) & set(
    MACHINE_PRIVATE_ROUTE_POLICIES
)
if _duplicates:
    raise RuntimeError(f"Duplicate private route policies: {sorted(_duplicates)}")

PRIVATE_ROUTE_POLICIES = {
    **SESSION_PRIVATE_ROUTE_POLICIES,
    **MACHINE_PRIVATE_ROUTE_POLICIES,
}

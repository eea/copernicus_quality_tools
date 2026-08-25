from enum import Enum

from qc_tool.frontend.accounts.authorization.roles import Role


class AccountPermission(str, Enum):
    """Stable application vocabulary backed by native Django permissions."""

    VIEW_DELIVERIES = "view_deliveries"
    UPLOAD_DELIVERY = "upload_delivery"
    RUN_QC = "run_qc"
    DELETE_DELIVERY = "delete_delivery"
    SUBMIT_DELIVERY = "submit_delivery"
    CHANGE_PASSWORD = "change_password"
    MANAGE_OWN_ACCOUNT = "manage_own_account"
    MANAGE_API_CREDENTIAL = "manage_api_credential"
    MANAGE_CONFIGURATION = "manage_configuration"
    VIEW_REGION_DELIVERIES = "view_region_deliveries"
    VIEW_PRODUCT_DELIVERIES = "view_product_deliveries"
    VIEW_REGION_AGGREGATE_REPORT = "view_region_aggregate_report"
    VIEW_PRODUCT_AGGREGATE_REPORT = "view_product_aggregate_report"

    @property
    def django_name(self):
        return f"accounts.{self.value}"


DEFAULT_PERMISSIONS = frozenset(
    {
        AccountPermission.VIEW_DELIVERIES,
        AccountPermission.UPLOAD_DELIVERY,
        AccountPermission.RUN_QC,
        AccountPermission.DELETE_DELIVERY,
        AccountPermission.SUBMIT_DELIVERY,
        AccountPermission.CHANGE_PASSWORD,
        AccountPermission.MANAGE_OWN_ACCOUNT,
        AccountPermission.MANAGE_API_CREDENTIAL,
    }
)

PRODUCT_MANAGER_PERMISSIONS = frozenset(
    {
        AccountPermission.VIEW_PRODUCT_DELIVERIES,
        AccountPermission.VIEW_PRODUCT_AGGREGATE_REPORT,
    }
)

ROLE_PERMISSION_GRANTS = {
    Role.DEFAULT: DEFAULT_PERMISSIONS,
    Role.PRODUCT_MANAGER: PRODUCT_MANAGER_PERMISSIONS,
    Role.ADMIN: frozenset(AccountPermission),
}


def permissions_for(user):
    """Resolve effective capabilities through Django's auth backends."""

    if not (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    ):
        return frozenset()

    return frozenset(
        permission
        for permission in AccountPermission
        if user.has_perm(permission.django_name)
    )

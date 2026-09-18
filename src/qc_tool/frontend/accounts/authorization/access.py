from dataclasses import dataclass
from functools import cached_property
from typing import FrozenSet
from typing import Optional

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import permissions_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.authorization.roles import roles_for
from qc_tool.product_security import normalize_product_ident


@dataclass(frozen=True)
class AccountAccess:
    """Immutable account facts used by views and templates for one request."""

    user_id: Optional[int]
    is_authenticated: bool
    is_administrator: bool
    roles: FrozenSet[Role]
    permissions: FrozenSet[AccountPermission]
    region_codes: FrozenSet[str] = frozenset()
    product_idents: FrozenSet[str] = frozenset()

    @classmethod
    def anonymous(cls):
        return cls(None, False, False, frozenset(), frozenset())

    @classmethod
    def from_user(cls, user):
        is_authenticated = bool(
            getattr(user, "is_authenticated", False)
            and getattr(user, "is_active", False)
        )
        if not is_authenticated:
            return cls.anonymous()

        roles = roles_for(user)
        is_administrator = bool(
            user.is_superuser or Role.ADMIN in roles
        )
        region_codes = frozenset(
            user.region_grants.exclude(region_code="").values_list(
                "region_code",
                flat=True,
            )
        )
        product_idents = frozenset(
            normalized
            for product_ident in user.product_grants.exclude(
                product_ident=""
            ).values_list("product_ident", flat=True)
            if (
                normalized := normalize_product_ident(product_ident)
            ) is not None
        )
        return cls(
            user_id=user.pk,
            is_authenticated=True,
            is_administrator=is_administrator,
            roles=roles,
            permissions=permissions_for(user),
            region_codes=region_codes,
            product_idents=product_idents,
        )

    @property
    def is_default_user(self):
        return Role.DEFAULT in self.roles

    @property
    def is_product_manager(self):
        return Role.PRODUCT_MANAGER in self.roles

    def allows(self, permission):
        return AccountPermission(permission) in self.permissions

    @property
    def can_view_deliveries(self):
        return self.allows(AccountPermission.VIEW_DELIVERIES)

    @property
    def can_upload(self):
        return self.allows(AccountPermission.UPLOAD_DELIVERY)

    @property
    def can_run_qc(self):
        return self.allows(AccountPermission.RUN_QC)

    @property
    def can_delete(self):
        return self.allows(AccountPermission.DELETE_DELIVERY)

    @property
    def can_change_password(self):
        return self.allows(AccountPermission.CHANGE_PASSWORD)

    @property
    def can_manage_own_account(self):
        return self.allows(AccountPermission.MANAGE_OWN_ACCOUNT)

    @property
    def can_manage_api_credential(self):
        return self.allows(AccountPermission.MANAGE_API_CREDENTIAL)

    @property
    def can_access_account_settings(self):
        return bool(
            self.can_manage_own_account or self.can_manage_api_credential
        )

    @property
    def can_submit(self):
        return self.allows(AccountPermission.SUBMIT_DELIVERY)

    @property
    def can_manage_configuration(self):
        return self.allows(AccountPermission.MANAGE_CONFIGURATION)

    @property
    def can_manage_product_catalog(self):
        """Specification uploads, delivery plans and stopping are admin tasks."""

        return self.is_authenticated and self.is_administrator

    @property
    def can_access_django_admin(self):
        return self.is_authenticated and (
            self.is_administrator or self.is_product_manager
        )

    @property
    def can_view_submission_queue(self):
        """Reviewers use the queue; uploaders track reviews in Deliveries."""

        return self.is_authenticated and (
            self.is_administrator or self.is_product_manager
        )

    @property
    def show_boundaries_navigation(self):
        """Keep package navigation in the management workspace."""

        return self.is_authenticated and (
            self.is_administrator or self.is_product_manager
            or self.can_manage_configuration
        )

    @property
    def can_view_region_deliveries(self):
        return bool(
            self.allows(AccountPermission.VIEW_REGION_DELIVERIES)
            and self.region_codes
        )

    @property
    def can_view_product_deliveries(self):
        return bool(
            self.allows(AccountPermission.VIEW_PRODUCT_DELIVERIES)
            and self.product_idents
        )

    @property
    def can_view_region_aggregate_report(self):
        return bool(
            self.allows(AccountPermission.VIEW_REGION_AGGREGATE_REPORT)
            and self.region_codes
        )

    @property
    def can_view_product_aggregate_report(self):
        return bool(
            self.allows(AccountPermission.VIEW_PRODUCT_AGGREGATE_REPORT)
            and self.product_idents
        )

    def can_view_product_report(self, product_ident):
        """Return whether aggregate facts for this exact product are visible."""

        if not self.is_authenticated or not isinstance(product_ident, str):
            return False
        normalized = normalize_product_ident(product_ident)
        if normalized is None:
            return False
        return bool(
            self.is_administrator
            or (
                self.allows(AccountPermission.VIEW_PRODUCT_AGGREGATE_REPORT)
                and normalized in self.reportable_product_idents
            )
        )

    def can_review_product_submission(self, product_ident):
        """Review decisions belong to admins and explicitly assigned managers."""

        ident = normalize_product_ident(product_ident)
        return bool(
            self.is_authenticated and ident is not None
            and (self.is_administrator or (
                self.is_product_manager and ident in self.reviewable_product_idents
            ))
        )

    def can_browse_product(self, product_ident):
        """Browse assigned products and the parent metadata of assigned recipes."""

        ident = normalize_product_ident(product_ident)
        return bool(self.is_authenticated and ident is not None and (
            self.is_administrator or ident in self.browsable_product_idents
        ))

    def can_access_product(self, product_ident):
        """Allow an assigned product or its unambiguously associated QC recipe."""

        ident = normalize_product_ident(product_ident)
        return bool(
            self.is_authenticated and ident is not None and (
                self.is_administrator or ident in self.operable_product_idents
            )
        )

    def can_access_product_snapshot(self, product_ident, catalog_product_ident=None):
        """Check recorded product identities without deriving a new association.

        Jobs and submissions retain the release selected when QC ran. A later
        catalog change must not authorize their artifacts under another product.
        """

        identities = {
            normalize_product_ident(product_ident),
            normalize_product_ident(catalog_product_ident),
        } - {None}
        return bool(self.is_authenticated and identities and (
            self.is_administrator or self.product_idents.intersection(identities)
        ))

    @property
    def has_product_assignments(self):
        """Whether the account may begin a delivery before identifying its product."""

        return bool(self.is_authenticated and (self.is_administrator or self.product_idents))

    @cached_property
    def operable_product_idents(self):
        from qc_tool.frontend.accounts.services.products import operable_product_scope

        return operable_product_scope(self.product_idents)

    @cached_property
    def _catalog_product_scope(self):
        from qc_tool.frontend.accounts.services.products import catalog_product_scope

        return catalog_product_scope(self.product_idents)

    @property
    def browsable_product_idents(self):
        return self._catalog_product_scope[0]

    @property
    def reportable_product_idents(self):
        return self._catalog_product_scope[1]

    @property
    def reviewable_product_idents(self):
        return self._catalog_product_scope[2] if self.is_product_manager else frozenset()

    @property
    def can_view_other_users_deliveries(self):
        return bool(
            self.is_administrator
            or self.can_view_region_deliveries
            or self.can_view_product_deliveries
        )

    @property
    def delivery_list_heading(self):
        if self.is_administrator:
            return "All Deliveries"
        if self.can_view_other_users_deliveries:
            return "Managed Deliveries"
        return "My Deliveries"

    def can_manage_user(self, owner_id):
        """Return whether this principal may mutate an owner's resources."""

        return bool(
            self.is_authenticated
            and (
                self.is_administrator
                or (self.user_id is not None and self.user_id == owner_id)
            )
        )

    def restricted_to_snapshot(
        self,
        *,
        permissions,
        roles,
        region_codes,
        product_idents,
        is_administrator,
    ):
        """Intersect live access with a fail-closed token access snapshot.

        Revoking a user's current permission or scope narrows every token
        immediately. Later grants do not silently broaden tokens that were
        issued before those grants existed.
        """

        snapshot_permissions = _known_enum_values(
            permissions,
            AccountPermission,
        )
        snapshot_roles = _known_enum_values(roles, Role)
        snapshot_regions = _bounded_strings(region_codes, maximum_length=100)
        snapshot_products = _bounded_strings(
            product_idents,
            maximum_length=64,
        )
        return AccountAccess(
            user_id=self.user_id,
            is_authenticated=self.is_authenticated,
            is_administrator=bool(
                is_administrator is True and self.is_administrator
            ),
            roles=self.roles.intersection(snapshot_roles),
            permissions=self.permissions.intersection(snapshot_permissions),
            region_codes=self.region_codes.intersection(snapshot_regions),
            product_idents=self.product_idents.intersection(snapshot_products),
        )


def _known_enum_values(values, enum_type):
    """Parse one bounded JSON list into known enum members or fail closed."""

    if not isinstance(values, list) or len(values) > 100:
        return frozenset()
    parsed = set()
    try:
        for value in values:
            if not isinstance(value, str):
                return frozenset()
            parsed.add(enum_type(value))
    except ValueError:
        return frozenset()
    return frozenset(parsed)


def _bounded_strings(values, *, maximum_length):
    """Validate bounded scope snapshots before they reach access policy."""

    if not isinstance(values, list) or len(values) > 1_000:
        return frozenset()
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > maximum_length
        for value in values
    ):
        return frozenset()
    return frozenset(values)


def access_for(user):
    return AccountAccess.from_user(user)


def access_for_request(request):
    """Resolve and cache account policy once for the current request."""

    attribute = "_qc_tool_account_access"
    access = getattr(request, attribute, None)
    if access is None:
        access = access_for(getattr(request, "user", None))
        setattr(request, attribute, access)
    return access

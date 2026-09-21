"""Prepare legacy identities without granting access inferred from history.

This deliberately does not save anything. The whole-import transaction owns
insertion, role bootstrap, permission resolution and sequence repair.
"""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher, is_password_usable

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.product_security import normalize_product_ident

from .values import boolean, bounded_text, integer, timestamp


@dataclass(repr=False)
class PreparedAccounts:
    # A default dataclass repr would reveal password hashes and personal data.
    users: list
    role_names: dict
    product_grants: list
    permissions: dict
    omitted: dict
    warnings: list


def _indexed_rows(dump, table):
    result = {}
    for row in dump.tables.get(table, ()):
        pk = integer(row.get("id"), f"{table}.id")
        if pk in result:
            raise ValueError(f"{table}: duplicate primary key {pk}.")
        result[pk] = row
    return result


def _reference(value, rows, location):
    pk = integer(value, location)
    if pk not in rows:
        raise ValueError(f"{location}: referenced row {pk} is missing.")
    return pk


def _string_list(value, location, *, maximum_length):
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected a list.")
    result = []
    for item in value:
        item = bounded_text(item, location, maximum_length)
        if not item or item != item.strip() or any(ord(char) < 32 for char in item):
            raise ValueError(f"{location}: expected nonempty, unpadded identifiers.")
        if item in result:
            raise ValueError(f"{location}: duplicate identifiers.")
        result.append(item)
    return result


def _access_overrides(access_map, user_ids):
    if access_map is None:
        return {}
    if not isinstance(access_map, dict) or set(access_map) - {"users"}:
        raise ValueError("Access map must be an object containing only 'users'.")
    users = access_map.get("users", {})
    if not isinstance(users, dict):
        raise ValueError("Access map users must be an object keyed by source user ID.")
    result = {}
    for source_id, values in users.items():
        if not isinstance(source_id, str) or not source_id.isascii() or not source_id.isdecimal():
            raise ValueError("Access map user keys must be decimal source user IDs.")
        pk = integer(source_id, "access map user ID")
        if str(pk) != source_id or pk not in user_ids:
            raise ValueError("Access map contains an unknown or noncanonical user ID.")
        if isinstance(values, dict) and "regions" in values:
            raise ValueError(f"Access map user {pk}: regions are no longer supported; assign products instead.")
        if not isinstance(values, dict) or set(values) - {"roles", "products"}:
            raise ValueError(f"Access map user {pk}: only roles and products are supported.")
        roles = _string_list(values.get("roles", []), f"Access map user {pk} roles", maximum_length=150)
        if not set(roles).issubset(Role.values()):
            raise ValueError(f"Access map user {pk}: unknown role.")
        products = _string_list(values.get("products", []), f"Access map user {pk} products", maximum_length=64)
        if any(normalize_product_ident(product) != product for product in products):
            raise ValueError(f"Access map user {pk}: product identifiers must be canonical.")
        result[pk] = {"roles": roles, "products": products}
    return result


def prepare_accounts(dump, *, access_map=None):
    """Convert identities and explicit grants; never write or consult a database.

    Existing password hashes are copied directly, preserving Django's password
    upgrade-on-login behavior. Obsolete profiles, arbitrary groups and their
    memberships are omitted; no retired access rules enter the current schema.
    Explicit product grants can name historical products absent from the empty
    catalog. An administrator must still upload their original specifications.
    """

    source_users = _indexed_rows(dump, "auth_user")
    source_profiles = dump.tables.get("dashboard_userprofile", ())
    source_groups = _indexed_rows(dump, "auth_group")
    source_permissions = _indexed_rows(dump, "auth_permission")
    source_content_types = _indexed_rows(dump, "django_content_type")
    overrides = _access_overrides(access_map, source_users)
    role_names = {pk: {Role.DEFAULT.value} for pk in source_users}
    obsolete_group_count = 0
    names = set()
    for pk, row in source_groups.items():
        name = bounded_text(row.get("name"), "auth_group.name", 150)
        if not name or name in names:
            raise ValueError("auth_group: empty or duplicate group name.")
        names.add(name)
        if name not in Role.values():
            obsolete_group_count += 1
    obsolete_membership_count = 0
    membership_keys = set()
    for row in _indexed_rows(dump, "auth_user_groups").values():
        user_id = _reference(row.get("user_id"), source_users, "auth_user_groups.user_id")
        group_id = _reference(row.get("group_id"), source_groups, "auth_user_groups.group_id")
        membership = (user_id, group_id)
        if membership in membership_keys:
            raise ValueError("auth_user_groups: duplicate user/group membership.")
        membership_keys.add(membership)
        name = source_groups[group_id]["name"]
        if name in Role.values():
            role_names[user_id].add(name)
        else:
            obsolete_membership_count += 1

    users = []
    product_grants = []
    usernames = set()
    user_model = get_user_model()
    staff_without_role = 0
    unsupported_passwords = 0
    for pk, row in source_users.items():
        location = f"auth_user row {pk}"
        fields = {
            name: bounded_text(row.get(name), f"{location}.{name}", length)
            for name, length in (
                ("password", 128), ("username", 150), ("first_name", 150),
                ("last_name", 150), ("email", 254),
            )
        }
        username_key = fields["username"].casefold()
        if not username_key or username_key in usernames:
            raise ValueError("auth_user: empty or case-insensitively duplicated username.")
        usernames.add(username_key)
        if is_password_usable(fields["password"]):
            try:
                identify_hasher(fields["password"])
            except ValueError:
                unsupported_passwords += 1
        fields.update({
            name: boolean(row.get(name), f"{location}.{name}")
            for name in ("is_active", "is_superuser", "is_staff")
        })
        fields["last_login"] = timestamp(row.get("last_login"), f"{location}.last_login", nullable=True)
        fields["date_joined"] = timestamp(row.get("date_joined"), f"{location}.date_joined")
        if fields["is_superuser"]:
            role_names[pk].add(Role.ADMIN.value)
        override = overrides.get(pk, {})
        role_names[pk].update(override.get("roles", ()))
        if role_names[pk].intersection({Role.ADMIN.value, Role.PRODUCT_MANAGER.value}):
            fields["is_staff"] = True
        elif fields["is_staff"]:
            staff_without_role += 1
        users.append(user_model(id=pk, **fields))
        product_grants.extend(
            UserProductGrant(user_id=pk, product_ident=ident)
            for ident in override.get("products", ())
        )

    natural_permissions = {}
    for pk, row in source_permissions.items():
        content_type_id = _reference(row.get("content_type_id"), source_content_types, "auth_permission.content_type_id")
        content_type = source_content_types[content_type_id]
        natural_permissions[pk] = (
            bounded_text(content_type.get("app_label"), "django_content_type.app_label", 100),
            bounded_text(content_type.get("model"), "django_content_type.model", 100),
            bounded_text(row.get("codename"), "auth_permission.codename", 100),
        )
    permissions = {}
    permission_keys = set()
    for row in _indexed_rows(dump, "auth_user_user_permissions").values():
        user_id = _reference(row.get("user_id"), source_users, "auth_user_user_permissions.user_id")
        permission_id = _reference(row.get("permission_id"), source_permissions, "auth_user_user_permissions.permission_id")
        key = (user_id, permission_id)
        if key in permission_keys:
            raise ValueError("auth_user_user_permissions: duplicate user permission.")
        permission_keys.add(key)
        permissions.setdefault(user_id, []).append(natural_permissions[permission_id])
    group_permissions = _indexed_rows(dump, "auth_group_permissions")
    for row in group_permissions.values():
        _reference(row.get("group_id"), source_groups, "auth_group_permissions.group_id")
        _reference(row.get("permission_id"), source_permissions, "auth_group_permissions.permission_id")

    warnings = []
    if staff_without_role:
        warnings.append(f"{staff_without_role} legacy staff accounts retain their staff flag but have no management role; review access explicitly.")
    if obsolete_group_count:
        warnings.append(f"{obsolete_group_count} obsolete groups and {obsolete_membership_count} memberships are omitted; source group permissions are not copied.")
    if source_profiles:
        warnings.append(f"{len(source_profiles)} obsolete profiles are omitted; countries and product-family labels remain only in the source dump.")
    if unsupported_passwords:
        warnings.append(f"{unsupported_passwords} users retain unsupported password hashes and require password resets before password login.")
    return PreparedAccounts(
        users=users, role_names=role_names, product_grants=product_grants,
        permissions=permissions, warnings=warnings,
        omitted={
            "legacy_profiles": len(source_profiles),
            "legacy_profile_country_values": sum(bool(row.get("country")) for row in source_profiles),
            "legacy_profile_product_family_values": sum(bool(row.get("product_family")) for row in source_profiles),
            "obsolete_groups": obsolete_group_count,
            "obsolete_group_memberships": obsolete_membership_count,
            "source_group_permissions": len(group_permissions),
        },
    )

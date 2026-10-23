"""Explicit table policies, independent of SQL supplied by a browser.

New tables have no implicit editor or disclosure policy. Framework joins are
inspected as records but edited through their owning user/group forms.
"""

from dataclasses import dataclass

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers.records import RESOURCE_FIELDS
from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant


@dataclass(frozen=True)
class Resource:
    model: type
    label: str
    category: str
    description: str
    columns: tuple
    fields: tuple
    search: tuple = ()
    editor: str = ""
    create: bool = False
    delete: str = ""
    owner: str = ""
    detail: bool = True

    @property
    def table(self):
        return self.model._meta.db_table


HISTORY = "Retained history. Its identity and connected records cannot be edited or deleted here."
CATALOG = "Versioned catalog evidence. Existing revisions and original specifications are preserved."


def resources():
    User = get_user_model()
    result = [
        Resource(User, "Users", "Accounts & access",
                 "Create accounts, edit profiles and access, or deactivate users. Existing usernames and history are protected.",
                 ("id", "username", "email", "is_active"),
                 ("id", "username", "first_name", "last_name", "email", "is_active", "is_staff", "is_superuser", "date_joined", "last_login"),
                 ("username", "email", "first_name", "last_name"), "Edit user", True),
        Resource(Group, "Role groups", "Accounts & access",
                 "Manage custom groups and permissions. QC Tool's built-in roles are protected.",
                 ("id", "name"), ("id", "name"), ("name",), "Edit group", True, "Delete custom group"),
        Resource(UserProductGrant, "Product access", "Accounts & access",
                 "Assign or remove a user's product scope. The owner and creator of existing grants are protected.",
                 ("id", "user_id", "product_ident", "created_at"),
                 ("id", "user_id", "product_ident", "created_at", "created_by_id"),
                 ("user__username", "product_ident"), "Edit access", True, "Remove access"),
        Resource(PersonalAccessToken, "API tokens", "Accounts & access",
                 "Inspect token metadata or revoke a token. Secrets and captured access cannot be edited; owners issue credentials through their account.",
                 ("id", "user_id", "name", "token_hint", "last_used_at"),
                 ("id", "user_id", "name", "token_hint", "created_at", "last_used_at", "permission_snapshot", "role_snapshot", "product_idents_snapshot", "is_administrator_snapshot"),
                 ("user__username", "name"), delete="Revoke token"),
        Resource(User.groups.through, "User roles", "Accounts & access",
                 "Role membership is changed in the user's editor, so staff access and role policies stay synchronized.",
                 ("id", "user_id", "group_id"), ("id", "user_id", "group_id"),
                 ("user__username", "group__name"), owner="user"),
        Resource(User.user_permissions.through, "User permissions", "Accounts & access",
                 "Additional permissions are changed in the user's editor.",
                 ("id", "user_id", "permission_id"), ("id", "user_id", "permission_id"),
                 ("user__username", "permission__name", "permission__codename"), owner="user"),
        Resource(Group.permissions.through, "Group permissions", "Accounts & access",
                 "Permissions are changed in the group's editor. Built-in role permissions are managed by QC Tool.",
                 ("id", "group_id", "permission_id"), ("id", "group_id", "permission_id"),
                 ("group__name", "permission__name", "permission__codename"), owner="group"),
        Resource(Permission, "Permission definitions", "System & audit",
                 "Application-owned permission definitions. Assign them through users and groups.",
                 ("id", "name", "codename", "content_type_id"), ("id", "name", "codename", "content_type_id"),
                 ("name", "codename")),
        Resource(ContentType, "Model identities", "System & audit",
                 "Framework model identities used by permissions and audit records. Managed by QC Tool.",
                 ("id", "app_label", "model"), ("id", "app_label", "model"), ("app_label", "model")),
        Resource(LogEntry, "Admin activity", "System & audit",
                 "The retained audit trail of administration changes.",
                 ("id", "action_time", "user_id", "object_repr", "action_flag"),
                 ("id", "action_time", "user_id", "content_type_id", "object_id", "object_repr", "action_flag", "change_message"),
                 ("user__username", "object_repr")),
        Resource(Session, "Sessions", "System & audit",
                 "Session references and expiry only. Session keys and signed payloads are hidden.",
                 ("session_reference", "expire_date"), ("expire_date",), detail=False),
        Resource(TransferReceipt, "Import receipts", "System & audit",
                 "Committed import and provenance evidence. Editing or deleting it would break recovery and duplicate detection.",
                 ("id", "profile", "actor_name", "created_at"),
                 ("id", "package_id", "operation_id", "profile", "actor_id", "actor_name", "created_at", "package_sha256", "plan_sha256"),
                 ("actor_name", "profile")),
    ]
    domain = {
        "products": ("Products", "Catalog", "Edit display names and descriptions. Product identity, activation, readiness and specifications stay protected.",
                     ("id", "ident", "name", "is_active"), ("ident", "name", "description"), "Edit metadata"),
        "definitions": ("QC definitions", "Catalog", CATALOG,
                        ("id", "product_ident", "description", "imported_at"), ("product_ident", "description", "digest"), ""),
        "releases": ("Product releases", "Catalog", CATALOG,
                     ("id", "product_id", "release_key", "revision", "is_current"), ("release_key", "product__ident"), ""),
        "release_definitions": ("Release definitions", "Catalog", CATALOG,
                                ("id", "product_release_id", "qc_definition_id", "is_primary"), ("product_release__release_key", "qc_definition__product_ident"), ""),
        "units": ("Product units", "Catalog", CATALOG,
                  ("id", "product_unit_code", "product_release_id"), ("product_unit_code", "product_release__release_key"), ""),
        "remote_sources": ("Remote storage", "Deliveries & jobs", "Location metadata only. Credentials stay in private storage; deleting a location could cascade into deliveries.",
                           ("id", "host", "bucketname", "key_prefix"), ("host", "bucketname", "key_prefix"), ""),
        "deliveries": ("Deliveries", "Deliveries & jobs", "Inspect delivery ownership and linked jobs. Uploads, file identities and retained history require their validated workflows.",
                       ("id", "filename", "user_id", "product_ident", "is_deleted"), ("filename", "user__username", "product_ident", "product_unit_code"), ""),
        "jobs": ("QC jobs", "Deliveries & jobs", HISTORY,
                 ("job_uuid", "delivery_id", "job_status", "date_created"), ("job_uuid", "delivery__filename", "product_ident"), ""),
        "submissions": ("Submissions", "Publication & history", HISTORY,
                        ("submission_uuid", "delivery_id", "publication_state", "review_state", "requested_at"), ("submission_uuid", "delivery__filename", "product_unit_code"), ""),
        "conflicts": ("Submission conflicts", "Publication & history", HISTORY,
                      ("id", "product_unit_id", "state", "version"), ("product_unit__product_unit_code", "state"), ""),
        "conflict_events": ("Conflict history", "Publication & history", HISTORY,
                            ("id", "conflict_id", "event_type", "actor_username", "created_at"), ("actor_username", "event_type"), ""),
        "review_events": ("Review history", "Publication & history", HISTORY,
                          ("id", "submission_id", "decision", "actor_username", "created_at"), ("actor_username", "decision"), ""),
    }
    for name, (model, fields) in RESOURCE_FIELDS.items():
        label, category, description, columns, search, editor = domain[name]
        result.append(Resource(model, label, category, description, columns, fields, search, editor))
    return tuple(sorted(result, key=lambda row: (row.category, row.label)))


def resource_for(table):
    return next((resource for resource in resources() if resource.table == table), None)

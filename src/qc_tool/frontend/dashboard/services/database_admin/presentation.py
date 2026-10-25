"""Bounded presentation of allowlisted ORM records and their dependencies."""

import hashlib
import json
from urllib.parse import urlencode

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from django.utils import formats, timezone

from .resources import resources


def table_url(resource, **query):
    url = reverse("admin_database_records", args=[resource.table])
    return url + "?" + urlencode(query) if query else url


def record_url(resource, pk):
    if resource.detail:
        return reverse("admin_database_record", args=[resource.table, str(pk)])
    return ""


def model_field(resource, name):
    return next((field for field in resource.model._meta.concrete_fields
                 if name in {field.name, field.attname}), None)


def field_label(resource, name):
    field = model_field(resource, name)
    return str(field.verbose_name).capitalize() if field else "Session reference"


def query_records(resource, params):
    """No uploaded table, lookup, field or SQL expression selects query code."""
    fields = [field.attname for field in resource.model._meta.concrete_fields
              if field.attname in resource.fields]
    queryset = resource.model._default_manager.only(*fields).order_by(resource.model._meta.pk.name)
    query = (params.get("q") or "").strip()[:150]
    if query and resource.search:
        condition = Q()
        for field in resource.search:
            condition |= Q(**{field + "__icontains": query})
        queryset = queryset.filter(condition)
    relation = params.get("related_field")
    value = params.get("related_value")
    if relation or value:
        field = model_field(resource, relation)
        if not field or not field.is_relation or field.attname not in resource.fields or value is None:
            raise ValidationError("Choose a linked record from its details page.")
        value = field.target_field.to_python(value)
        queryset = queryset.filter(**{field.attname: value})
    return queryset, query


def display_value(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    elif hasattr(value, "tzinfo"):
        value = formats.date_format(timezone.localtime(value) if timezone.is_aware(value) else value,
                                    "DATETIME_FORMAT")
    else:
        value = str(value)
    if len(value) > 8000:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"{value[:8000]}\n… Preview limited to 8,000 characters ({len(value):,} total; SHA-256 {digest})."
    return value


def cell(resource, obj, name):
    if name == "session_reference":
        return {"value": hashlib.sha256(obj.pk.encode("utf-8")).hexdigest()[:12], "url": ""}
    field = model_field(resource, name)
    value = getattr(obj, field.attname)
    url = ""
    if field.is_relation and value is not None:
        related = next((item for item in resources() if item.model is field.related_model), None)
        if related:
            url = record_url(related, value)
    return {"value": display_value(value), "url": url, "label": field_label(resource, name)}


def record_heading(resource, obj):
    """Use an already-allowlisted label, without reading related or secret data."""
    for name in ("username", "name", "filename", "product_unit_code", "release_key", "product_ident", "object_repr"):
        if name in resource.fields:
            value = getattr(obj, name, None)
            if value:
                return str(value)[:180]
    return f"Record {obj.pk}"


def record_field_groups(resource, fields):
    """Keep relationships and ordinary metadata visible; tuck raw evidence away."""
    technical, ordinary = [], []
    raw_fields = {"document", "provenance", "source_path", "change_message", "skip_steps",
                  "permission_snapshot", "role_snapshot", "product_idents_snapshot", "ready_scope_digest"}
    for name, item in zip(resource.fields, fields):
        field = model_field(resource, name)
        is_raw = (name in raw_fields or "sha256" in name or "digest" in name or
                  (field and field.get_internal_type() == "JSONField") or len(item["value"]) > 400)
        (technical if is_raw else ordinary).append(item)
    return ordinary, technical


def record_rows(resource, objects):
    return [{"url": record_url(resource, obj.pk),
             "cells": [cell(resource, obj, field) for field in resource.columns]}
            for obj in objects]


def editor_actions(resource, request, obj=None):
    registered = admin.site._registry.get(resource.model)
    model = resource.model
    target = obj
    if resource.owner and obj is not None:
        field = model._meta.get_field(resource.owner)
        model = field.related_model
        target = getattr(obj, resource.owner)
        registered = admin.site._registry.get(model)
    actions = []
    if registered:
        prefix = f"admin:{model._meta.app_label}_{model._meta.model_name}_"
        if obj is None and resource.create and registered.has_add_permission(request):
            actions.append({"label": "Create record", "url": reverse(prefix + "add"), "kind": "primary"})
        if obj is not None and (resource.editor or resource.owner) and registered.has_change_permission(request, target):
            actions.append({"label": resource.editor or "Edit assignments", "url": reverse(prefix + "change", args=[target.pk]), "kind": "primary"})
        if obj is not None and resource.delete and registered.has_delete_permission(request, obj):
            actions.append({"label": resource.delete, "url": reverse(prefix + "delete", args=[obj.pk]), "kind": "danger"})
    return actions


def dependencies(resource, obj):
    """Inspect every declared FK, including joins and hidden reverse relations."""
    result = []
    for related in resources():
        for field in related.model._meta.concrete_fields:
            if not field.is_relation or field.related_model is not resource.model:
                continue
            count = related.model._default_manager.filter(**{field.attname: obj.pk}).count()
            if count:
                result.append({"label": related.label, "field": str(field.verbose_name), "count": count,
                               "url": table_url(related, related_field=field.attname, related_value=obj.pk)})
    return result

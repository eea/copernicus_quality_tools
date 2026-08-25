"""Build the public, server-rendered API reference from its OpenAPI source."""

from .documentation_examples import curl_example
from .documentation_examples import parameter_context
from .documentation_examples import request_body_context
from .documentation_examples import resolve_reference
from .documentation_examples import response_contexts
from .openapi_contract import openapi_document


HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def api_documentation_context(api_url):
    """Return grouped operations for the accessible HTML reference page.

    The generated examples use a visible token placeholder. This service never
    receives or stores an actual personal access token.
    """

    document = openapi_document(api_url)
    server_url = document["servers"][0]["url"]
    groups, groups_by_name = _declared_groups(document)

    for path, path_item in document["paths"].items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tag_name = _operation_tag(operation)
            group = groups_by_name.get(tag_name)
            if group is None:
                group = _group(tag_name)
                groups.append(group)
                groups_by_name[tag_name] = group
            group["operations"].append(
                _operation_context(
                    document,
                    server_url=server_url,
                    path=path,
                    method=method,
                    operation=operation,
                )
            )

    return {
        "api_title": document["info"].get("title", "QC Tool API"),
        "api_version": document["info"].get("version", ""),
        "api_description": document["info"].get("description", ""),
        "api_url": server_url,
        "api_groups": groups,
        "api_operation_count": sum(len(group["operations"]) for group in groups),
    }


def _declared_groups(document):
    groups = []
    groups_by_name = {}
    for tag in document.get("tags", []):
        name = tag.get("name")
        if not isinstance(name, str) or not name:
            continue
        group = _group(name, description=tag.get("description", ""))
        groups.append(group)
        groups_by_name[name] = group
    return groups, groups_by_name


def _group(name, *, description=""):
    return {
        "name": name,
        "description": description,
        "anchor": _anchor(name),
        "operations": [],
    }


def _operation_context(document, *, server_url, path, method, operation):
    request_body = request_body_context(document, operation.get("requestBody"))
    parameters = [
        resolve_reference(document, parameter)
        for parameter in operation.get("parameters", [])
        if isinstance(parameter, dict)
    ]
    return {
        "id": _anchor(operation.get("operationId") or f"{method}-{path}"),
        "method": method.upper(),
        "path": path,
        "summary": operation.get("summary", "API operation"),
        "description": operation.get("description", ""),
        "permission": operation.get(
            "x-required-permission-label",
            "Authenticated account",
        ),
        "parameters": [
            parameter_context(document, parameter) for parameter in parameters
        ],
        "request_body": request_body,
        "responses": response_contexts(
            document,
            operation.get("responses", {}),
        ),
        "curl_example": curl_example(
            server_url=server_url,
            path=path,
            method=method,
            parameters=parameters,
            request_body=request_body,
        ),
        "search_text": _operation_search_text(
            method,
            path,
            operation,
            parameters,
        ),
    }


def _operation_search_text(method, path, operation, parameters):
    parts = [
        method,
        path,
        str(operation.get("summary", "")),
        str(operation.get("description", "")),
        str(operation.get("x-required-permission-label", "")),
        " ".join(str(tag) for tag in operation.get("tags", [])),
    ]
    parts.extend(
        " ".join(
            (
                str(parameter.get("name", "")),
                str(parameter.get("description", "")),
            )
        )
        for parameter in parameters
    )
    return " ".join(parts).casefold()


def _operation_tag(operation):
    tags = operation.get("tags", [])
    return tags[0] if tags and isinstance(tags[0], str) else "Other"


def _anchor(value):
    normalized = "".join(
        character.casefold() if character.isalnum() else "-"
        for character in str(value)
    )
    return "-".join(part for part in normalized.split("-") if part)

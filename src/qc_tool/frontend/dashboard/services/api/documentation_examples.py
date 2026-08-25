"""Template-friendly fields, examples, and responses derived from OpenAPI."""

import json
import shlex


TOKEN_PLACEHOLDER = "<personal-access-token>"


def parameter_context(document, parameter):
    parameter = resolve_reference(document, parameter)
    schema = resolve_reference(document, parameter.get("schema", {}))
    return {
        "name": parameter.get("name", ""),
        "location": parameter.get("in", ""),
        "required": bool(parameter.get("required")),
        "description": parameter.get("description", ""),
        "type": _schema_label(schema),
        "default": schema.get("default"),
        "has_default": "default" in schema,
        "example": _display_value(
            parameter.get("example", schema.get("example"))
        ),
    }


def request_body_context(document, request_body):
    if not isinstance(request_body, dict):
        return None
    request_body = resolve_reference(document, request_body)
    content = request_body.get("content", {})
    media_type = (
        "application/json"
        if "application/json" in content
        else next(iter(content), "")
    )
    media = content.get(media_type, {})
    schema = resolve_reference(document, media.get("schema", {}))
    example = media.get("example")
    if example is None:
        example = _example_for_schema(document, schema)
    required_names = set(schema.get("required", []))
    properties = [
        _property_context(document, name, property_schema, required_names)
        for name, property_schema in schema.get("properties", {}).items()
    ]
    return {
        "description": request_body.get("description", ""),
        "required": bool(request_body.get("required")),
        "media_type": media_type,
        "properties": properties,
        "example": json.dumps(example, indent=2, ensure_ascii=True),
    }


def response_contexts(document, responses):
    result = []
    for status_code, response in responses.items():
        if not isinstance(response, dict):
            continue
        response = resolve_reference(document, response)
        result.append(
            {
                "status": status_code,
                "description": response.get("description", ""),
                "content_types": ", ".join(
                    response.get("content", {}).keys()
                ),
            }
        )
    return result


def curl_example(*, server_url, path, method, parameters, request_body):
    rendered_path = path
    query_parts = []
    for parameter in parameters:
        location = parameter.get("in")
        name = parameter.get("name", "value")
        schema = parameter.get("schema", {})
        example = parameter.get(
            "example",
            schema.get("example", schema.get("default")),
        )
        if example is None:
            example = "value"
        if location == "path":
            rendered_path = rendered_path.replace(
                "{" + name + "}",
                str(example),
            )
        elif location == "query" and (
            parameter.get("required") or "example" in parameter
        ):
            query_parts.append(f"{name}={example}")

    url = server_url + rendered_path
    if query_parts:
        url += "?" + "&".join(query_parts)
    lines = [
        f"curl --request {method.upper()} \\",
        f"  --url {shlex.quote(url)} \\",
        "  --header 'Accept: application/json' \\",
        f"  --header 'Authorization: Bearer {TOKEN_PLACEHOLDER}'",
    ]
    if request_body is not None:
        lines[-1] += " \\"
        lines.append("  --header 'Content-Type: application/json' \\")
        compact_body = " ".join(request_body["example"].split())
        lines.append(f"  --data {shlex.quote(compact_body)}")
    return "\n".join(lines)


def resolve_reference(document, value):
    """Resolve one local JSON pointer while failing closed on malformed refs."""

    if not isinstance(value, dict):
        return {}
    reference = value.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return value
    current = document
    for part in reference[2:].split("/"):
        if not isinstance(current, dict) or part not in current:
            return value
        current = current[part]
    return current if isinstance(current, dict) else value


def _property_context(document, name, property_schema, required_names):
    resolved = resolve_reference(document, property_schema)
    return {
        "name": name,
        "type": _schema_label(resolved),
        "required": name in required_names,
        "description": resolved.get("description", ""),
        "example": _display_value(resolved.get("example")),
    }


def _example_for_schema(document, schema):
    schema = resolve_reference(document, schema)
    if "example" in schema:
        return schema["example"]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        return {
            name: _example_for_schema(document, property_schema)
            for name, property_schema in schema.get("properties", {}).items()
        }
    if schema_type == "array":
        return [_example_for_schema(document, schema.get("items", {}))]
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    if schema.get("format") == "uuid":
        return "00000000-0000-0000-0000-000000000001"
    return "string"


def _schema_label(schema):
    label = schema.get("type", "value")
    schema_format = schema.get("format")
    if schema_format:
        label = f"{label} ({schema_format})"
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        label += ": " + " | ".join(str(value) for value in enum)
    return label


def _display_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)

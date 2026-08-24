"""Security invariants applied before product configuration is executed."""

import re


_ENUM_CHECK = "qc_tool.vector.enum"
_NAME_INFO_REFERENCE = re.compile(
    r"name_info\[(?P<quote>['\"])(?P<key>[A-Za-z0-9_]+)(?P=quote)\]\Z"
)


class UnsafeProductDefinition(ValueError):
    pass


def validate_executable_product_configuration(definition):
    """Reject code-like dynamic values before a QC check can evaluate them.

    This guard intentionally lives outside raster/vector implementations.  It
    preserves their existing runtime contract while ensuring product JSON is
    treated as data rather than a general-purpose Python program.
    """

    if not isinstance(definition, dict):
        raise UnsafeProductDefinition("product definition must be an object")
    steps = definition.get("steps")
    if not isinstance(steps, list):
        raise UnsafeProductDefinition("product steps must be a list")
    for step in steps:
        if not isinstance(step, dict):
            raise UnsafeProductDefinition("product step must be an object")
        if step.get("check_ident") != _ENUM_CHECK:
            continue
        parameters = step.get("parameters", {})
        if not isinstance(parameters, dict):
            raise UnsafeProductDefinition("enum parameters must be an object")
        column_definitions = parameters.get("column_defs", ())
        if not isinstance(column_definitions, (list, tuple)):
            raise UnsafeProductDefinition("enum columns must be a list")
        for column_definition in column_definitions:
            _validate_enum_column(column_definition)
    return definition


def _validate_enum_column(column_definition):
    if (
        not isinstance(column_definition, (list, tuple))
        or len(column_definition) != 2
        or not isinstance(column_definition[1], (list, tuple))
        or not column_definition[1]
    ):
        raise UnsafeProductDefinition("enum column definition is invalid")
    first_value = column_definition[1][0]
    if (
        isinstance(first_value, str)
        and "name_info" in first_value
        and _NAME_INFO_REFERENCE.fullmatch(first_value) is None
    ):
        raise UnsafeProductDefinition("dynamic enum expression is unsafe")

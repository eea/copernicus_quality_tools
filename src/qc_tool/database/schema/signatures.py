"""Normalize declared indexes and CHECK rules while retaining their semantics."""

import re
from qc_tool.database.predicates import predicate_signature

def index_signature(sql):
    """Normalize current simple/LOWER indexes across SQLite and PostgreSQL."""
    sql = "".join(part if position % 2 else part.casefold().replace('"', '')
                  for position, part in enumerate(re.split(r"('(?:''|[^'])*')", sql)))
    sql = re.sub(r"::(?:text|character\s+varying|varchar)(?:\(\d+\))?", "", sql)
    sql = re.sub(r"\busing\s+btree\b", "", sql)
    match = re.search(r"\bon\s+(?:\w+\.)?\w+\s+(.*)", sql)
    if not match:
        return None
    expression, separator, condition = match.group(1).partition(" where ")
    expression = re.sub(r"[\s()]", "", expression)
    return expression, predicate_signature(condition) if separator else None

def index_matches(definition, expected):
    if not definition or expected is None:
        return False
    try:
        expected_signature = index_signature(str(expected))
        return expected_signature is not None and index_signature(definition) == expected_signature
    except ValueError:
        return False

def check_signature(expression):
    """Django predicates plus its narrowly defined SQLite JSON validity check."""
    try:
        return predicate_signature(expression)
    except ValueError:
        value = re.sub(r'[\s"()]', '', expression).casefold()
        match = re.fullmatch(r"json_valid([a-z_][a-z_0-9]*)or([a-z_][a-z_0-9]*)isnull", value)
        if match and match[1] == match[2]:
            return ("sqlite-json-valid-or-null", match[1])
        raise


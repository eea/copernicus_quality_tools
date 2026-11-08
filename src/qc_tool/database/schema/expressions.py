"""Compare Django-compiled defaults and generated expressions without evaluation."""

import re
import sqlparse
from qc_tool.database.predicates import predicate_signature

def expression_signature(sql):
    """Compare compiled declarations without evaluating defaults or functions.

    Reuse predicate normalization for literals/casts. For other expressions,
    retain operator precedence and string bytes while normalizing formatting.
    Unsupported backend rewrites fail closed rather than executing source SQL.
    """
    try:
        return ("predicate", predicate_signature(sql))
    except ValueError:
        tokens = []
        for kind, value in sqlparse.lexer.tokenize(sql):
            if kind in sqlparse.tokens.Whitespace:
                continue
            if kind in sqlparse.tokens.Literal.String.Single:
                tokens.append(value)
            elif value.startswith('"') and value.endswith('"'):
                identifier = value[1:-1].replace('""', '"')
                tokens.append(identifier if re.fullmatch(r"[a-z_][a-z_0-9]*", identifier) else value)
            else:
                tokens.append(value.casefold())
        while tokens and tokens[0] == "(" and tokens[-1] == ")":
            depth = 0
            for position, token in enumerate(tokens):
                depth += (token == "(") - (token == ")")
                if depth == 0:
                    break
            if position != len(tokens) - 1:
                break
            tokens = tokens[1:-1]
        return ("sql", tuple(tokens))

def declared_expression(field, editor, *, generated=False):
    sql, params = (field.generated_sql(editor.connection) if generated else editor.db_default_sql(field))
    return sql % tuple(editor.quote_value(value) for value in params) if params else sql

def declared_expression_matches(field, actual, editor, *, generated=False):
    if actual is None:
        return False
    try:
        expected = declared_expression(field, editor, generated=generated)
        return expression_signature(actual) == expression_signature(expected)
    except (ValueError, TypeError):
        return False


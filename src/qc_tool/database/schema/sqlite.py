"""Parse SQLite's stored table declarations without executing their expressions."""

import re
import sqlparse

def column_sql(table_sql, name):
    """Read one declared column and its generated expression without SQL writes."""
    depth, started, pieces = 0, False, []
    for _kind, token in sqlparse.lexer.tokenize(table_sql):
        if not started:
            started = token == "("
            continue
        if token == "(":
            depth += 1
        elif token == ")" and depth:
            depth -= 1
        elif token in {",", ")"} and depth == 0:
            definition = "".join(pieces).strip()
            match = re.match(r'^(?:"((?:""|[^"])+)"|([a-zA-Z_][a-zA-Z_0-9]*))', definition)
            if match and (match[1].replace('""', '"') if match[1] else match[2]) == name:
                return definition
            pieces = []
            continue
        pieces.append(token)
    return ""

def generated_expression(column_sql):
    match = re.search(r"\bGENERATED\s+ALWAYS\s+AS\s*\(", column_sql, re.I)
    if match is None:
        return None
    # Django emits the full GENERATED ALWAYS clause. Use its explicit stored or
    # virtual suffix to delimit the expression; nested expression groups remain.
    expression = re.fullmatch(r"(.*)\)\s+(?:STORED|VIRTUAL)(?:\s+.*)?", column_sql[match.end():], re.I | re.S)
    return expression[1] if expression else None

def checks(sql):
    """Extract CHECK bodies without changing quoted values or nested syntax."""
    result = []
    for match in re.finditer(r"\bCHECK\s*\(", sql, re.I):
        start, position, depth, quote = match.end(), match.end(), 1, None
        while position < len(sql):
            char = sql[position]
            if quote:
                if char == quote:
                    if position + 1 < len(sql) and sql[position + 1] == quote:
                        position += 1
                    else:
                        quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    result.append(sql[start:position])
                    break
            position += 1
    return result


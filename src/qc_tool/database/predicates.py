"""Normalize the boolean SQL predicates used by the current Django models."""

import re

_TOKEN = re.compile(r"\s*(?:('(?:''|[^'])*')|\"((?:\"\"|[^\"])+)\"|(-?\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z_0-9$]*)|(>=|<=|<>|!=|=|>|<)|([(),\[\]]))")
_CAST = re.compile(r"::(?:character\s+varying|text|varchar|integer|bigint|smallint|boolean|numeric|double\s+precision)(?:\(\d+(?:,\s*\d+)?\))?(?:\[\])?", re.I)


def _canonical(node):
    kind = node[0]
    if kind in {"and", "or"}:
        children = []
        for child in node[1:]:
            child = _canonical(child)
            children.extend(child[1:] if child[0] == kind else [child])
        return (kind, *sorted(children, key=repr))
    if kind == "not":
        child = _canonical(node[1])
        inverses = {"=": "!=", "!=": "=", ">": "<=", "<": ">=", ">=": "<", "<=": ">", "in": "notin", "notin": "in", "isnull": "isnotnull", "isnotnull": "isnull"}
        if child[0] == "not":
            return child[1]
        if child[0] in inverses:
            return (inverses[child[0]], *child[1:])
        return ("not", child)
    return node


class _Predicate:
    def __init__(self, sql):
        # PostgreSQL casts may decorate fields and ARRAY literals. Preserve
        # quoted string values, including text that happens to resemble a cast.
        sql = "".join(part if position % 2 else _CAST.sub("", part)
                      for position, part in enumerate(
                          re.split(r"('(?:''|[^'])*')", sql.strip())))
        if sql.upper().startswith("CHECK"):
            sql = sql[5:].strip()
        self.tokens = []
        position = 0
        while position < len(sql):
            match = _TOKEN.match(sql, position)
            if not match:
                if not sql[position:].strip():
                    break
                raise ValueError("Unsupported model predicate syntax.")
            quoted, identifier, number, word, operator, punctuation = match.groups()
            if quoted is not None:
                self.tokens.append(("string", quoted[1:-1].replace("''", "'")))
            elif identifier is not None:
                self.tokens.append(("word", identifier.replace('""', '"').casefold()))
            elif number is not None:
                self.tokens.append(("number", number))
            else:
                self.tokens.append(("word", word.casefold()) if word else ("symbol", operator or punctuation))
            position = match.end()
        self.position = 0

    def peek(self, value):
        return self.position < len(self.tokens) and self.tokens[self.position][1] == value

    def take(self, value):
        if not self.peek(value):
            raise ValueError("Unsupported model predicate syntax.")
        self.position += 1

    def boolean(self, operator="or"):
        next_parser = (lambda: self.boolean("and")) if operator == "or" else self.negation
        children = [next_parser()]
        while self.peek(operator):
            self.take(operator)
            children.append(next_parser())
        return (operator, *children) if len(children) > 1 else children[0]

    def negation(self):
        if self.peek("not"):
            self.take("not")
            return ("not", self.negation())
        left = self.atom()
        if self.peek("is"):
            self.take("is")
            negative = self.peek("not")
            if negative:
                self.take("not")
            self.take("null")
            return ("isnotnull" if negative else "isnull", left)
        if self.peek("in") or self.peek("not"):
            negative = self.peek("not")
            if negative:
                self.take("not")
            self.take("in")
            return ("notin" if negative else "in", left, self.values("(", ")"))
        if self.position < len(self.tokens) and self.tokens[self.position][1] in {"=", "!=", "<>", ">", "<", ">=", "<="}:
            operator = self.tokens[self.position][1]
            self.position += 1
            right = self.atom()
            if operator == "=" and right[0] == "any":
                return ("in", left, right[1])
            if operator in {"<>", "!="} and right[0] == "all":
                return ("notin", left, right[1])
            return ("!=" if operator == "<>" else operator, left, right)
        return left

    def values(self, start, end):
        self.take(start)
        values = [self.atom()]
        while self.peek(","):
            self.take(",")
            values.append(self.atom())
        self.take(end)
        return tuple(values)

    def atom(self):
        if self.peek("("):
            self.take("(")
            value = self.boolean()
            self.take(")")
            return value
        if self.position == len(self.tokens):
            raise ValueError("Unsupported model predicate syntax.")
        kind, value = self.tokens[self.position]
        self.position += 1
        if kind == "word" and value in {"any", "all"}:
            self.take("(")
            wrappers = 0
            while self.peek("("):
                self.take("(")
                wrappers += 1
            self.take("array")
            values = self.values("[", "]")
            for _ in range(wrappers):
                self.take(")")
            self.take(")")
            return (value, values)
        if kind == "word":
            return ("literal", value) if value in {"true", "false", "null"} else ("field", value)
        if kind in {"string", "number"}:
            return (kind, value)
        raise ValueError("Unsupported model predicate syntax.")


def predicate_signature(sql):
    parser = _Predicate(sql)
    result = parser.boolean()
    if parser.position != len(parser.tokens):
        raise ValueError("Unsupported model predicate syntax.")
    return _canonical(result)


def named_sqlite_check(table_sql, name):
    quoted = r'(?:"' + re.escape(name) + r'"|' + re.escape(name) + r')'
    match = re.search(r"\bCONSTRAINT\s+" + quoted + r"\s+CHECK\s*\(", table_sql, re.I)
    if not match:
        return None
    position = match.end()
    beginning = position
    depth = 1
    quote = None
    while position < len(table_sql):
        char = table_sql[position]
        if quote:
            if char == quote:
                if position + 1 < len(table_sql) and table_sql[position + 1] == quote:
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
                return table_sql[beginning:position]
        position += 1
    return None

"""Reference implementation of slice A: SQL text -> Select syntax tree.

See seeds/minisql/SPEC.md sections 3 and 4.
"""
from __future__ import annotations

import re

from .types import Condition, OrderKey, ParseError, Select

_KEYWORDS = frozenset(
    (
        "SELECT",
        "FROM",
        "WHERE",
        "AND",
        "ORDER",
        "BY",
        "ASC",
        "DESC",
        "LIMIT",
        "NULL",
        "IS",
        "NOT",
    )
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INT_RE = re.compile(r"[+-]?[0-9]+")
_TWO_CHAR_OPS = ("<=", ">=", "!=", "<>")


def _tokenize(sql):
    """Return a list of (kind, text, position) tokens."""
    tokens = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if char == "'":
            start = index
            index += 1
            chunk = []
            while True:
                if index >= length:
                    raise ParseError("unterminated string literal", start)
                if sql[index] == "'":
                    if index + 1 < length and sql[index + 1] == "'":
                        chunk.append("'")
                        index += 2
                        continue
                    index += 1
                    break
                chunk.append(sql[index])
                index += 1
            tokens.append(("str", "".join(chunk), start))
            continue
        if char in ",*;":
            tokens.append(("punct", char, index))
            index += 1
            continue
        match = _IDENT_RE.match(sql, index)
        if match:
            tokens.append(("ident", match.group(0), index))
            index = match.end()
            continue
        match = _INT_RE.match(sql, index)
        if match:
            tokens.append(("int", match.group(0), index))
            index = match.end()
            continue
        if sql[index : index + 2] in _TWO_CHAR_OPS:
            tokens.append(("op", sql[index : index + 2], index))
            index += 2
            continue
        if char in "=<>":
            tokens.append(("op", char, index))
            index += 1
            continue
        raise ParseError("unexpected character %r" % (char,), index)
    return tokens


class _Parser:
    def __init__(self, sql):
        self.sql = sql
        self.tokens = _tokenize(sql)
        self.index = 0

    def peek(self):
        if self.index < len(self.tokens):
            return self.tokens[self.index]
        return None

    def advance(self):
        token = self.tokens[self.index]
        self.index += 1
        return token

    def error(self, message, token=None):
        if token is None:
            token = self.peek()
        position = token[2] if token is not None else len(self.sql)
        return ParseError(message, position)

    def at_keyword(self, *words):
        token = self.peek()
        return token is not None and token[0] == "ident" and token[1].upper() in words

    def expect_keyword(self, word):
        if not self.at_keyword(word):
            raise self.error("expected %s" % word)
        self.advance()

    def parse_name(self, where):
        token = self.peek()
        if token is None or token[0] != "ident" or token[1].upper() in _KEYWORDS:
            raise self.error("expected a name in %s" % where)
        self.advance()
        return token[1]

    def at_punct(self, char):
        token = self.peek()
        return token is not None and token[0] == "punct" and token[1] == char

    def parse_condition(self):
        column = self.parse_name("WHERE")
        token = self.peek()
        if token is None:
            raise self.error("expected a comparison operator")
        if token[0] == "ident" and token[1].upper() in ("IS", "NOT"):
            if token[1].upper() == "NOT":
                raise self.error("expected a comparison operator")
            self.advance()
            token = self.peek()
            if token is None or token[0] != "ident" or token[1].upper() not in ("NULL", "NOT"):
                raise self.error("expected NULL or NOT after IS")
            if token[1].upper() == "NULL":
                self.advance()
                return Condition(column, "IS NULL", None)
            self.advance()
            token = self.peek()
            if token is None or token[0] != "ident" or token[1].upper() != "NULL":
                raise self.error("expected NULL after IS NOT")
            self.advance()
            return Condition(column, "IS NOT NULL", None)
        if token[0] != "op":
            raise self.error("expected a comparison operator", token)
        operator = "!=" if token[1] == "<>" else token[1]
        self.advance()
        token = self.peek()
        if token is None:
            raise self.error("expected a value")
        if token[0] == "int":
            value = int(token[1])
        elif token[0] == "str":
            value = token[1]
        elif token[0] == "ident" and token[1].upper() == "NULL":
            raise self.error("use IS NULL instead of comparing with NULL", token)
        else:
            raise self.error("expected a value", token)
        self.advance()
        return Condition(column, operator, value)

    def parse_statement(self):
        self.expect_keyword("SELECT")
        if self.at_punct("*"):
            self.advance()
            columns = ("*",)
        else:
            names = [self.parse_name("the column list")]
            while self.at_punct(","):
                self.advance()
                names.append(self.parse_name("the column list"))
            columns = tuple(names)

        self.expect_keyword("FROM")
        table = self.parse_name("FROM")

        where = []
        if self.at_keyword("WHERE"):
            self.advance()
            while True:
                where.append(self.parse_condition())
                if self.at_keyword("AND"):
                    self.advance()
                    continue
                break

        order_by = []
        if self.at_keyword("ORDER"):
            self.advance()
            self.expect_keyword("BY")
            while True:
                column = self.parse_name("ORDER BY")
                descending = False
                if self.at_keyword("ASC", "DESC"):
                    descending = self.advance()[1].upper() == "DESC"
                order_by.append(OrderKey(column, descending))
                if self.at_punct(","):
                    self.advance()
                    continue
                break

        limit = None
        if self.at_keyword("LIMIT"):
            self.advance()
            token = self.peek()
            if token is None or token[0] != "int":
                raise self.error("expected a non-negative integer after LIMIT")
            if int(token[1]) < 0:
                raise self.error("LIMIT must not be negative", token)
            limit = int(token[1])
            self.advance()

        if self.at_punct(";"):
            self.advance()
        token = self.peek()
        if token is not None:
            raise self.error("unexpected token %r" % (token[1],), token)

        return Select(
            columns=columns,
            table=table,
            where=tuple(where),
            order_by=tuple(order_by),
            limit=limit,
        )


def parse(sql):
    """Parse one statement into a frozen Select (SPEC.md 4)."""
    if not isinstance(sql, str):
        raise TypeError("parse expects a string, got %r" % (type(sql).__name__,))
    parser = _Parser(sql)
    if not parser.tokens:
        raise ParseError("empty statement", 0)
    return parser.parse_statement()

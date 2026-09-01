"""Small, non-executing reader for DCS data-table literals, not a Lua runtime.

Symbols and arithmetic are preserved, never evaluated. Unknown calls, duplicate
keys and unsupported syntax fail explicitly. No dofile/require or Lua code runs.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


class LuaDataError(ValueError):
    pass


class Symbol(str):
    pass


class Expression(str):
    pass


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    kind: str


_NUMBER = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_LONG = re.compile(r"\[(=*)\[")


def tokenize(source: str) -> list[Token]:
    tokens, i = [], 0
    while i < len(source):
        start = i
        if source[i].isspace():
            i += 1
            continue
        comment = source.startswith("--", i)
        if comment:
            i += 2
        long = _LONG.match(source, i)
        if long:
            close = "]" + long[1] + "]"
            end = source.find(close, long.end())
            if end < 0:
                raise LuaDataError("Unterminated long string/comment")
            i = end + len(close)
            if not comment:
                tokens.append(Token(source[start:i], start, i, "long_string"))
            continue
        if comment:
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
            continue
        if source[i] in "\"'":
            quote = source[i]
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            if i >= len(source):
                raise LuaDataError("Unterminated quoted string")
            i += 1
            kind = "string"
        elif match := _NUMBER.match(source, i):
            i, kind = match.end(), "number"
        elif match := _NAME.match(source, i):
            i, kind = match.end(), "name"
        else:
            i, kind = i + 1, "punctuation"
        tokens.append(Token(source[start:i], start, i, kind))
    return tokens


def _string(token: Token) -> str:
    if token.kind == "long_string":
        match = _LONG.match(token.text)
        value = token.text[match.end():-(len(match[1]) + 2)]
        return value[1:] if value.startswith("\n") else value
    value, i, body = [], 0, token.text[1:-1]
    escapes = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
               "\\": "\\", "'": "'", '"': '"'}
    while i < len(body):
        if body[i] != "\\":
            value.append(body[i])
            i += 1
            continue
        i += 1
        if i >= len(body):
            raise LuaDataError("Incomplete string escape")
        if body[i].isdigit():
            match = re.match(r"\d{1,3}", body[i:])
            number = int(match[0])
            if number > 255:
                raise LuaDataError("Invalid decimal string escape")
            value.append(chr(number))
            i += len(match[0])
        elif body[i] in escapes:
            value.append(escapes[body[i]])
            i += 1
        else:
            raise LuaDataError(f"Unsupported string escape: {body[i]}")
    return "".join(value)


class Reader:
    def __init__(self, source: str):
        self.source, self.tokens = source, tokenize(source)
        self.i = 0
        self.table_spans: dict[int, tuple[int, int]] = {}

    def peek(self, offset: int = 0) -> str:
        return self.tokens[self.i + offset].text if self.i + offset < len(self.tokens) else ""

    def take(self, text: str | None = None) -> Token:
        if self.i >= len(self.tokens) or (text is not None and self.peek() != text):
            raise LuaDataError(f"Expected {text or 'value'}, got {self.peek() or 'end of file'}")
        token = self.tokens[self.i]
        self.i += 1
        return token

    def assignment(self, name: str, *, terminal: bool = False) -> Any:
        indexes = [i for i, token in enumerate(self.tokens[:-1])
                   if token.kind == "name" and token.text == name and self.tokens[i + 1].text == "="
                   and (i == 0 or self.tokens[i - 1].text not in {".", ":"})]
        if len(indexes) != 1:
            raise LuaDataError(f"Expected exactly one {name} assignment, found {len(indexes)}")
        self.i = indexes[0] + 2
        result = self.value()
        if terminal:
            while self.peek() == ";":
                self.take()
            if self.peek():
                raise LuaDataError(f"Unsupported code after {name} table")
        return result

    def value(self, depth: int = 0) -> Any:
        if depth > 40:
            raise LuaDataError("Data table nesting exceeds 40 levels")
        start = self.i
        result = self.atom(depth)
        while self.peek() and self.peek() in {"+", "-", "*", "/", "%", "^"}:
            self.take()
            self.atom(depth)
            result = Expression(self.source[self.tokens[start].start:self.tokens[self.i - 1].end])
        return result

    def atom(self, depth: int) -> Any:
        if self.peek() == "{":
            return self.table(depth + 1)
        if self.peek() in {"-", "+"}:
            sign = self.take().text
            number = self.take()
            if number.kind != "number":
                raise LuaDataError("Unary sign requires a number")
            return self.number(sign + number.text)
        token = self.take()
        if token.kind in {"string", "long_string"}:
            return _string(token)
        if token.kind == "number":
            return self.number(token.text)
        if token.text in {"true", "false", "nil"}:
            return {"true": True, "false": False, "nil": None}[token.text]
        if token.kind != "name":
            raise LuaDataError(f"Unsupported data expression: {token.text}")
        name = token.text
        while self.peek() == ".":
            self.take()
            part = self.take()
            if part.kind != "name":
                raise LuaDataError("Expected a symbol after '.'")
            name += "." + part.text
        if self.peek() == "(":
            if name not in {"_", "math.pow"}:
                raise LuaDataError(f"Unsupported function call: {name}")
            self.take()
            first = self.value(depth + 1)
            if name == "_":
                if type(first) is not str:
                    raise LuaDataError("Translation wrapper requires a string literal")
                self.take(")")
                return first
            self.take(",")
            self.value(depth + 1)
            end = self.take(")")
            return Expression(self.source[token.start:end.end])
        return Symbol(name)

    @staticmethod
    def number(text: str) -> int | float:
        result = float(text) if any(c in text.lower() for c in ".e") else int(text)
        if abs(result) > 1.7976931348623157e308 or not math.isfinite(result):
            raise LuaDataError("Non-finite numeric literal")
        return result

    def table(self, depth: int) -> dict[Any, Any]:
        start = self.take("{").start
        result: dict[Any, Any] = {}
        array_index = 1
        while self.peek() != "}":
            if self.peek() == "[":
                self.take()
                key = self.value(depth)
                self.take("]")
                self.take("=")
            elif self.peek(1) == "=" and self.tokens[self.i].kind == "name":
                key = self.take().text
                self.take("=")
            else:
                key, array_index = array_index, array_index + 1
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                raise LuaDataError("Unsupported table key")
            if key in result:
                raise LuaDataError(f"Duplicate table key: {key}")
            result[key] = self.value(depth)
            if self.peek() in {",", ";"}:
                self.take()
            elif self.peek() != "}":
                raise LuaDataError("Expected a table separator")
        end = self.take("}").end
        self.table_spans[id(result)] = (start, end)
        return result


def json_value(value: Any) -> Any:
    if isinstance(value, Expression):
        return {"lua_expression": str(value)}
    if isinstance(value, Symbol):
        return {"lua_symbol": str(value)}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    return value

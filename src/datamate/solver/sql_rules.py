"""Static SQL checks before execution (SPEC §7.7.3). Owner: M3."""

from __future__ import annotations

import re

import duckdb

from datamate.contracts import codes

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_IDENT_LITERAL = re.compile(r'"(?:[^"]|"")*"')
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def check_sql(sql: str) -> tuple[str | None, str | None]:
    """Return (error_code, detail) or (None, None) if the SQL may be executed."""
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        return codes.E_SQL_EXEC, f"{type(exc).__name__}: {exc}"
    if len(statements) != 1:
        return codes.E_SQL_NOT_SELECT, f"expected exactly one statement, got {len(statements)}"
    if statements[0].type != duckdb.StatementType.SELECT:
        return codes.E_SQL_NOT_SELECT, f"statement type {statements[0].type.name} is not SELECT"
    bare = _COMMENT.sub(" ", _IDENT_LITERAL.sub('""', _STRING_LITERAL.sub("''", sql))).upper()
    if re.search(r"\bLIMIT\b", bare) and not re.search(r"\bORDER\s+BY\b", bare):
        return codes.E_SQL_NONDETERMINISTIC, "LIMIT requires ORDER BY"
    return None, None

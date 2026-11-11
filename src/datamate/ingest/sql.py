"""Syntactic table references without expanding installed views into underlying tables."""

from __future__ import annotations

import duckdb


def referenced_tables(sql: str, *, qualified: bool = False) -> set[str]:
    with duckdb.connect(
        ":memory:",
        config={
            "threads": 1,
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    ) as parser:
        return parser.get_table_names(sql, qualified=qualified)

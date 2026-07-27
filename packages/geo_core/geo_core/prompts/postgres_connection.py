"""Shared PostgreSQL cursor helpers for Prompt persistence adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from geo_core.prompts.ports import PromptProgramPersistenceError


class PromptPostgresConnectionMixin:
    _connection: Any

    def _advisory_lock(self, key: str) -> None:
        self._execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))

    def _execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(query, parameters)

    def _optional(
        self, query: str, parameters: tuple[object, ...]
    ) -> Mapping[str, Any] | None:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return cast(Mapping[str, Any] | None, cursor.fetchone())
        except psycopg.Error as error:
            raise self._database_error("read Prompt Program state", error) from error

    def _many(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return tuple(cast(list[Mapping[str, Any]], cursor.fetchall()))
        except psycopg.Error as error:
            raise self._database_error("list Prompt Program state", error) from error

    @staticmethod
    def _database_error(
        operation: str, error: psycopg.Error
    ) -> PromptProgramPersistenceError:
        del error
        return PromptProgramPersistenceError(f"PostgreSQL could not {operation}")


__all__ = ["PromptPostgresConnectionMixin"]

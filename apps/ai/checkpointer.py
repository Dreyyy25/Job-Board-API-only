"""LangGraph Postgres checkpointer — chat history storage.

Deliberately NOT a Django model: LangGraph owns the schema, creates it via
`manage.py ai_checkpointer_setup`, and migrates it on its own cadence.

Runs on psycopg v3 with its own connection pool, entirely separate from
Django's psycopg2 connections. Nothing here participates in a Django
transaction — see `delete_conversation` in services.py for what that means.
"""
from urllib.parse import quote

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

_checkpointer = None
_pool = None


def build_conn_string() -> str:
    """libpq URI from the same credentials Django uses. No new env keys.

    quote(..., safe='') on user and password: a password containing '@', '/'
    or ':' would otherwise be parsed as URI structure and silently connect
    somewhere else. quote, not quote_plus — the latter encodes a space as '+',
    which is a literal '+' in URI userinfo, not a space.
    """
    return (
        f"postgresql://{quote(DB_USER, safe='')}:{quote(DB_PASSWORD, safe='')}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


def get_checkpointer():
    """Process-wide PostgresSaver. Built once — a pool per request exhausts Postgres."""
    global _checkpointer, _pool
    if _checkpointer is None:
        _pool = ConnectionPool(
            conninfo=build_conn_string(),
            min_size=1,
            max_size=5,
            # Explicit: psycopg_pool's implicit default is deprecated and is
            # slated to become False, which would break every chat turn with
            # "the pool is not open yet" on a routine dependency bump.
            open=True,
            # autocommit: the saver issues its own statements and must not sit
            # inside an open transaction. dict_row: it reads columns by name.
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        # allowed_msgpack_modules=None is the STRICT allowlist. The default
        # JsonPlusSerializer() uses True, which is fully permissive and will
        # reconstruct arbitrary Python types out of checkpoint rows. The
        # LANGGRAPH_STRICT_MSGPACK env var cannot be relied on here: langgraph
        # reads it into a module constant at import time, before this module
        # ever runs.
        _checkpointer = PostgresSaver(
            _pool, serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    return _checkpointer


def reset_checkpointer():
    """Drop the singleton. Tests only — production never tears the pool down."""
    global _checkpointer, _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:  # pragma: no cover - best effort teardown
            pass
    _checkpointer = None
    _pool = None

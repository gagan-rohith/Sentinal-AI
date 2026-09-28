"""Checkpoint persistence for paused runs.

LangGraph deserializes checkpoints with msgpack. Newer versions only rebuild
classes on an explicit allowlist, so we register our own state types instead of
allowing arbitrary classes to be reconstructed from the database.
"""

import inspect
from enum import Enum
from types import ModuleType

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

import agents.evidence
import agents.schemas
import core.enums
import core.models
import retrieval.models
import tools.common
import tools.deployments
import tools.logs
import tools.metrics
import tools.tool_registry

STATE_MODULES: tuple[ModuleType, ...] = (
    agents.evidence,
    agents.schemas,
    core.enums,
    core.models,
    retrieval.models,
    tools.common,
    tools.deployments,
    tools.logs,
    tools.metrics,
    tools.tool_registry,
)


def allowed_types() -> set[tuple[str, str]]:
    allowed = set()
    for module in STATE_MODULES:
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module.__name__ and issubclass(obj, (BaseModel, Enum)):
                allowed.add((module.__name__, name))
    return allowed


def serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=allowed_types())


async def open_checkpointer(conn: aiosqlite.Connection) -> AsyncSqliteSaver:
    """Checkpointer on the application's shared connection (see storage.db.Database).

    The connection belongs to the Database; closing the Database closes the checkpointer.
    """
    saver = AsyncSqliteSaver(conn, serde=serializer())
    await saver.setup()
    return saver

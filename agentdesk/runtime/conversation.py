"""SQLite-backed, PII-minimized conversation state."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from agentdesk.schemas.agents import ConversationState


class ConversationStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, state: ConversationState) -> None:
        updated = state.model_copy(update={"updated_at": datetime.now(UTC)})
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO conversation_state (conversation_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(updated.conversation_id),
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                ),
            )

    def load(self, conversation_id: UUID) -> ConversationState | None:
        row = self.connection.execute(
            "SELECT state_json FROM conversation_state WHERE conversation_id = ?",
            (str(conversation_id),),
        ).fetchone()
        return (
            ConversationState.model_validate_json(row["state_json"])
            if row is not None
            else None
        )

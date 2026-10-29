"""SQLite persistence."""

from agentdesk.db.connection import connect, initialize_database

__all__ = ["connect", "initialize_database"]

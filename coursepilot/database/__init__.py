"""SQLite persistence bootstrap."""

from coursepilot.database.schema import connect_database, initialize_database

__all__ = ["connect_database", "initialize_database"]

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import CursorResult, Engine, Result, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from ..models.config import DatabaseConfig

SessionFactory = sessionmaker[Session]


def affected_rows(result: Result[Any]) -> int:
    """Rows an UPDATE or DELETE touched. Session.execute is typed to return a plain Result for any statement."""
    assert isinstance(result, CursorResult)
    return result.rowcount


_ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def resolve_database_url(url: str, data_dir: Path | None) -> str:
    """Rebase a relative SQLite file path under *data_dir*.

    Without this, the default ``sqlite:///carapace.db`` would land in the process
    working directory instead of beside the configured data tree. Absolute paths,
    ``:memory:``, and non-SQLite URLs are returned unchanged.
    """
    if data_dir is None or not _is_sqlite(url):
        return url
    parsed = make_url(url)
    database = parsed.database
    if not database or database == ":memory:" or Path(database).is_absolute():
        return url
    return str(parsed.set(database=str((data_dir / database).resolve())))


def create_engine_and_factory(db_config: DatabaseConfig, data_dir: Path | None = None) -> tuple[Engine, SessionFactory]:
    """Build a sync SQLAlchemy engine + session factory for the configured URL.

    A relative SQLite path is resolved under *data_dir* when given.
    """
    url = resolve_database_url(db_config.url, data_dir)
    kwargs: dict[str, Any] = {"echo": db_config.echo, "future": True}

    if _is_sqlite(url):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = db_config.pool_size
        kwargs["max_overflow"] = db_config.max_overflow
        kwargs["pool_pre_ping"] = True

    engine = create_engine(url, **kwargs)

    if _is_sqlite(url):
        _install_sqlite_pragmas(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def _install_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
        # foreign_keys cannot be set mid-transaction; toggle autocommit (Python 3.12+ sqlite3).
        previous_autocommit = getattr(dbapi_conn, "autocommit", None)
        try:
            if previous_autocommit is not None:
                dbapi_conn.autocommit = True
        except Exception:  # pragma: no cover - driver without autocommit attr
            previous_autocommit = None
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            if previous_autocommit is not None:
                dbapi_conn.autocommit = previous_autocommit


def _alembic_config(url: str) -> Any:
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def run_migrations(engine: Engine) -> None:
    """Upgrade the database to the latest Alembic revision, reusing the app engine."""
    from alembic import command

    cfg = _alembic_config(str(engine.url))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

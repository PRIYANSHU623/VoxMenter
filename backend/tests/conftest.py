"""Shared test setup.

Nothing here touches the real database, Redis or any paid API:

* every test gets its own in-memory SQLite database
* real network connections are blocked, so a test that forgets to mock a
  provider fails loudly instead of spending search credits or AI tokens
* connecting to the real application database is refused
"""

import socket
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registers every table on Base)
from app.db.session import Base
from app.db.session import engine as real_engine


@pytest.fixture(scope="session", autouse=True)
def forbid_real_database():
    def refuse(dialect, conn_rec, cargs, cparams):
        raise RuntimeError(
            "Tests must not use the real database. "
            "Use the db or session_factory fixtures instead."
        )

    event.listen(real_engine, "do_connect", refuse)
    yield
    event.remove(real_engine, "do_connect", refuse)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError(
            "Network access is blocked in tests. Use a fake provider or a mock transport."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture()
def engine():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def now():
    """A fixed 'current time' so day-based logic is deterministic."""
    return datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
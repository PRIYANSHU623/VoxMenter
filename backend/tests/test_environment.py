import socket

import pytest
from sqlalchemy import inspect

from app.models import Question


def test_real_network_connections_are_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Network access is blocked"):
            sock.connect(("example.com", 80))
    finally:
        sock.close()


def test_tests_use_an_empty_in_memory_database(db, engine):
    assert str(engine.url) == "sqlite://"

    tables = set(inspect(engine).get_table_names())
    assert {
        "questions",
        "question_sources",
        "question_generation_runs",
        "category_cooldowns",
    } <= tables

    assert db.query(Question).count() == 0
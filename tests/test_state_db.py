"""
Boundary tests for src/harness/state/db.py
"""
import sqlite3

import pytest

from harness.state import db
from harness._constants import LIMIT_MAX


@pytest.fixture(autouse=True)
def reset_connection():
    """Reset the module-level connection singleton before/after each test."""
    db._connection = None
    yield
    if db._connection is not None:
        db._connection.close()
    db._connection = None


class TestInitDb:
    def test_init_db_creates_tables(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        expected = {"dispatches", "fallbacks", "observer_cycles", "status_writes", "routing_changes"}
        assert expected.issubset(tables)

    def test_init_db_idempotent(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        db.insert_dispatch(project="proj", packet_path="p", backend="kimi")
        db.init_db(db_path=str(db_path))
        rows = db.query_active_dispatches(project="proj")
        assert len(rows) == 1  # data preserved, no error

    def test_init_db_default_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "STATE_DIR", tmp_path)
        db.init_db()
        assert (tmp_path / "history.db").exists()
        # Should be usable
        assert db.get_connection() is not None

    def test_get_connection_lazily_initialises(self, tmp_path, monkeypatch):
        """get_connection auto-calls init_db at default STATE_DIR when needed."""
        monkeypatch.setattr(db, "STATE_DIR", tmp_path)
        # Force un-initialised state for this test
        monkeypatch.setattr(db, "_connection", None)
        conn = db.get_connection()
        assert conn is not None
        assert (tmp_path / "history.db").exists()


class TestDispatchInsertQuery:
    def test_insert_and_query_active_dispatches(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        did = db.insert_dispatch(
            project="test-proj",
            packet_path="/some/packet.md",
            backend="kimi",
            model="kimi-latest",
        )
        assert len(did) == 32  # UUID hex
        rows = db.query_active_dispatches(project="test-proj")
        assert len(rows) == 1
        assert rows[0]["id"] == did
        assert rows[0]["project"] == "test-proj"
        assert rows[0]["packet_path"] == "/some/packet.md"
        assert rows[0]["backend"] == "kimi"
        assert rows[0]["model"] == "kimi-latest"
        assert rows[0]["status"] == "dispatched"

    def test_query_active_dispatches_no_project_filter(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        db.insert_dispatch(project="proj-a", packet_path="p1", backend="kimi")
        db.insert_dispatch(project="proj-b", packet_path="p2", backend="deepseek")
        rows = db.query_active_dispatches(limit=10)
        assert len(rows) == 2

    def test_update_dispatch_status(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        did = db.insert_dispatch(project="proj", packet_path="p", backend="kimi")
        db.update_dispatch_status(did, status="completed", latency_ms=123, fallback_to="deepseek")
        rows = db.query_active_dispatches(project="proj")
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert rows[0]["latency_ms"] == 123
        assert rows[0]["fallback_to"] == "deepseek"


class TestFallback:
    def test_insert_and_query_fallback_chain(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        did = db.insert_dispatch(project="proj", packet_path="p", backend="kimi")
        rid = db.insert_fallback(did, from_backend="kimi", to_backend="deepseek", reason="timeout")
        assert rid == 1
        rows = db.query_fallback_chain(did)
        assert len(rows) == 1
        assert rows[0]["dispatch_id"] == did
        assert rows[0]["from_backend"] == "kimi"
        assert rows[0]["to_backend"] == "deepseek"
        assert rows[0]["reason"] == "timeout"


class TestObserverCycle:
    def test_insert_observer_cycle(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        rid = db.insert_observer_cycle(project="proj", flags=["stale", "dirty"], status_count=5)
        assert rid == 1
        rows = db.query_recent_events(limit=10)
        assert any(r["_table"] == "observer" and r["project"] == "proj" for r in rows)


class TestStatusWrite:
    def test_insert_status_write(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        rid = db.insert_status_write(project="proj", backend_type="kimi", summary="all good")
        assert rid == 1
        # smoke: query_recent_events still works
        rows = db.query_recent_events(limit=10)
        assert isinstance(rows, list)


class TestValidation:
    def test_invalid_project_name_on_insert_dispatch(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        with pytest.raises(ValueError, match="Invalid project name"):
            db.insert_dispatch(project="Bad Project!", packet_path="p", backend="kimi")

    def test_invalid_project_name_on_query(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        with pytest.raises(ValueError, match="Invalid project name"):
            db.query_active_dispatches(project="!!!")

    def test_invalid_source_raises(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        with pytest.raises(ValueError, match="Invalid source"):
            db.insert_routing_change(source="unknown", action="lock", engine="kimi")

    def test_invalid_action_raises(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        with pytest.raises(ValueError, match="Invalid action"):
            db.insert_routing_change(source="cli", action="unknown", engine="kimi")


class TestLimitCoercion:
    def test_string_limit_coerced(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        # query_active_dispatches with a string limit should not raise
        rows = db.query_active_dispatches(limit="50")  # type: ignore[arg-type]
        assert isinstance(rows, list)

    def test_zero_limit_clamped_to_one(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        assert db._clamp_limit(0) == 1

    def test_huge_limit_clamped_to_max(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        assert db._clamp_limit(999_999) == LIMIT_MAX

    def test_non_numeric_limit_raises(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        with pytest.raises(ValueError, match="limit must be an integer"):
            db._clamp_limit("abc")


class TestRoutingChangeInsert:
    def test_records_lock(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        rid = db.insert_routing_change(
            source="cli",
            action="lock",
            engine="kimi",
            old_value="unlocked",
            new_value="locked",
        )
        assert rid == 1
        rows = db.query_routing_history(engine="kimi")
        assert len(rows) == 1
        assert rows[0]["source"] == "cli"
        assert rows[0]["action"] == "lock"
        assert rows[0]["engine"] == "kimi"
        assert rows[0]["old_value"] == "unlocked"
        assert rows[0]["new_value"] == "locked"

    def test_records_burst_start(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        rid = db.insert_routing_change(source="ws", action="burst_start", engine="deepseek")
        assert rid == 1
        rows = db.query_routing_history(engine="deepseek")
        assert len(rows) == 1
        assert rows[0]["action"] == "burst_start"

    def test_records_priority_change(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        rid = db.insert_routing_change(
            source="adapter",
            action="priority_change",
            engine="anthropic",
            old_value="5",
            new_value="1",
        )
        assert rid == 1
        rows = db.query_routing_history()
        assert len(rows) == 1
        assert rows[0]["action"] == "priority_change"

    def test_query_routing_history_no_engine_filter(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        db.insert_routing_change(source="cli", action="lock", engine="kimi")
        db.insert_routing_change(source="ws", action="burst_start", engine="deepseek")
        rows = db.query_routing_history(limit=10)
        assert len(rows) == 2


class TestConcurrentReadSafety:
    def test_two_connections_see_committed_data(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        db.insert_dispatch(project="concurrent-test", packet_path="p", backend="kimi")
        # Open a second raw connection to the same underlying file
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        cur = conn2.cursor()
        cur.execute("SELECT * FROM dispatches WHERE project = ?", ("concurrent-test",))
        rows = cur.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["backend"] == "kimi"
        conn2.close()


class TestQueryRecentEvents:
    def test_union_query_returns_all_types(self, tmp_path):
        db_path = tmp_path / "history.db"
        db.init_db(db_path=str(db_path))
        db.insert_dispatch(project="proj", packet_path="p", backend="kimi")
        db.insert_observer_cycle(project="proj", flags=[], status_count=0)
        db.insert_routing_change(source="cli", action="lock", engine="kimi")
        rows = db.query_recent_events(limit=10)
        tables = {r["_table"] for r in rows}
        assert "dispatch" in tables
        assert "observer" in tables
        assert "routing" in tables

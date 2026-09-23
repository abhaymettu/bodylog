from datetime import datetime, timedelta

import pytest

from bodylog.store import Store, parse_duration

T0 = datetime(2026, 9, 22, 18, 0).astimezone()


def test_log_defaults_to_last_exercise_and_unit(store):
    store.log_set("bench", 60, 8, "kg", at=T0)
    row = store.log_set(weight=62.5, reps=6, at=T0 + timedelta(minutes=3))[0]
    assert row["exercise"] == "Bench Press" and row["unit"] == "kg"
    assert len(store.sets(row["session_id"])) == 2


def test_count_logs_identical_sets(store):
    rows = store.log_set("seated cable row", 90, 10, "lb", count=3, at=T0)
    assert [r["reps"] for r in rows] == [10, 10, 10]


def test_edit_and_delete_last_set(store):
    store.log_set("bench", 60, 8, "kg", at=T0)
    store.log_set(weight=60, reps=8, at=T0 + timedelta(minutes=2))
    assert store.edit_last_set(reps=10, kind="failure")["reps"] == 10
    assert store.edit_last_set(exercise="incline bench")["exercise"] == "Incline Bench Press"
    store.edit_last_set(delete=True)
    assert len(store.sets(store.open_session()["id"])) == 1
    with pytest.raises(ValueError):
        store.edit_last_set(kind="giant")


def test_name_recent_names_unnamed_sets(store):
    store.log_set(weight=10.2, reps=15, unit="kg", at=T0)
    store.log_set(weight=10.2, reps=12, at=T0 + timedelta(minutes=2))
    rows = store.name_recent("tricep cable pushdowns btw")
    assert len(rows) == 2 and rows[0]["exercise"] == "Triceps Cable Pushdown"


def test_name_recent_only_moves_trailing_same_weight_defaulted_sets(store):
    store.log_set("incline db press", 55, 10, "lb", at=T0)
    store.log_set(weight=55, reps=9, at=T0 + timedelta(minutes=3))
    store.log_set(weight=12.5, reps=12, unit="kg", at=T0 + timedelta(minutes=9))
    moved = store.name_recent("triceps pushdown")
    assert [r["weight"] for r in moved] == [12.5]
    names = [r["exercise"] for r in store.sets(store.open_session()["id"])]
    assert names == ["Incline Dumbbell Press", "Incline Dumbbell Press", "Triceps Pushdown"]


def test_end_session_with_spoken_duration(store):
    store.log_set("bench", 60, 8, "kg", at=T0 + timedelta(minutes=5))
    s = store.end_session("1h 5m", at=T0 + timedelta(minutes=65))
    assert s["duration_s"] == 3900
    assert datetime.fromisoformat(s["started_at"]) == T0
    assert store.open_session() is None
    with pytest.raises(LookupError):
        store.end_session("10 min")


def test_stale_session_closes_before_a_new_one(store):
    store.log_set("bench", 60, 8, "kg", at=T0)
    store.log_set("bench", 60, 8, "kg", at=T0 + timedelta(days=1))
    rows = store.db.execute("SELECT * FROM sessions ORDER BY id").fetchall()
    assert len(rows) == 2 and rows[0]["ended_at"] is not None


def test_validation(store):
    with pytest.raises(ValueError):
        store.log_set("bench", 60, None)
    with pytest.raises(ValueError):
        store.log_set("bench", 60, 8, "stone")


@pytest.mark.parametrize("text,secs", [("1h 5m", 3900), ("65 min", 3900), ("1:05", 3900), (65, 3900),
                                       ("45", 2700), ("1 hour", 3600), ("90s", 90)])
def test_parse_duration(text, secs):
    assert parse_duration(text) == secs


def test_file_store_persists(tmp_path):
    path = tmp_path / "log.db"
    s = Store(path)
    s.log_set("bench", 60, 8, "kg", at=T0)
    s.close()
    assert Store(path).sets(1)[0]["exercise"] == "Bench Press"


def test_announced_exercise_carries_to_the_next_message(store):
    store.log_set("bench", 60, 8, "kg", at=T0)
    store.set_current("squats", at=T0 + timedelta(minutes=5))
    row = store.log_set(weight=100, reps=5, at=T0 + timedelta(minutes=7))[0]
    assert row["exercise"] == "Squat"


def test_repeat_keeps_the_previous_sets_exercise(store):
    store.log_set("bench", 60, 8, "kg", at=T0)
    store.set_current("squat", at=T0 + timedelta(minutes=1))
    assert store.repeat_last(at=T0 + timedelta(minutes=2))[0]["exercise"] == "Bench Press"


def test_sessions_order_by_instant_not_string(store):
    east = datetime.fromisoformat("2026-03-01T22:00:00-05:00")  # 03:00 UTC
    west = datetime.fromisoformat("2026-03-01T20:00:00-08:00")  # 04:00 UTC, later despite the smaller string
    store.log_set("bench", 100, 5, "kg", at=east)
    store.end_session(at=east + timedelta(minutes=30))
    store.log_set("bench", 120, 5, "kg", at=west + timedelta(minutes=31))
    s = store.end_session(at=west + timedelta(hours=1))
    assert store.last_session()["id"] == s["id"]
    from bodylog import stats
    assert {p["type"] for p in stats.session_prs(store, s)} >= {"weight"}


def test_end_with_duration_on_a_stale_session_ends_at_its_last_set(store):
    store.log_set("bench", 60, 8, "kg", at=T0 - timedelta(days=30))
    s = store.end_session("1h")
    assert s["ended_at"] == (T0 - timedelta(days=30)).isoformat()

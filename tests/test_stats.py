from datetime import datetime, timedelta

from bodylog import stats

T0 = datetime(2026, 9, 8, 18, 0).astimezone()


def _session(store, day, sets, duration="1h"):
    at = T0 + timedelta(days=day)
    for i, (ex, w, u, r) in enumerate(sets):
        store.log_set(ex, w, r, u, at=at + timedelta(minutes=3 * i))
    return store.end_session(duration, at=at + timedelta(hours=1))["id"]


def test_first_session_sets_no_prs(store):
    sid = _session(store, 0, [("bench", 60, "kg", 8)])
    assert stats.summary(store, sid)["prs"] == []


def test_pr_types(store):
    _session(store, 0, [("bench", 60, "kg", 8), ("bench", 62.5, "kg", 6)])
    sid = _session(store, 2, [("bench", 60, "kg", 10), ("bench", 65, "kg", 3)])
    prs = {p["type"]: p for p in stats.summary(store, sid)["prs"]}
    assert prs["weight"]["set"] == "65 kg x 3"
    assert prs["e1rm"]["set"] == "60 kg x 10"  # 80 kg beats 62.5 x 6 = 75 kg
    assert prs["reps"]["set"] == "60 kg x 10" and prs["reps"]["previous"] == 8
    assert prs["volume"]["set"] == "60 kg x 10" and prs["volume"]["previous_kg"] == 480  # 600 beats 60 x 8


def test_prs_compare_across_units(store):
    _session(store, 0, [("curl", 11.34, "kg", 10)])
    sid = _session(store, 2, [("curl", 25, "lb", 10)])  # 25 lb = 11.34 kg: same weight, no PR
    assert stats.summary(store, sid)["prs"] == []
    sid = _session(store, 4, [("curl", 27.5, "lb", 10)])
    assert {p["type"] for p in stats.summary(store, sid)["prs"]} == {"weight", "e1rm", "volume"}


def test_warmups_do_not_count(store):
    _session(store, 0, [("bench", 60, "kg", 8)])
    store.log_set("bench", 100, 1, "kg", kind="warmup", at=T0 + timedelta(days=2))
    store.log_set("bench", 60, 8, "kg", at=T0 + timedelta(days=2, minutes=3))
    sid = store.end_session("30 min", at=T0 + timedelta(days=2, hours=1))["id"]
    s = stats.summary(store, sid)
    assert s["prs"] == [] and s["sets"] == 1 and s["volume"] == 480


def test_summary_totals_and_week(imported):
    store, ids = imported
    s = stats.summary(store, ids[-1])
    assert s["title"] == "Push Day" and s["duration"] == "1h 3m" and s["unit"] == "kg"
    assert s["sets"] == 11 and s["volume"] == 2639.5
    assert [e["name"] for e in s["exercises"]] == ["Bench Press", "Incline Dumbbell Press", "Triceps Cable Pushdown", "Lateral Raise"]
    assert s["exercises"][0]["best"] == "60 kg x 10"
    assert s["week"]["workouts"] == 2 and s["week"]["change_pct"] == -14


def test_history_prs_and_weekly_volume(imported):
    store, ids = imported
    h = stats.exercise_history(store, "bench")
    assert h["exercise"] == "Bench Press" and len(h["sessions"]) == 3
    assert h["sessions"][0]["best"] == "60 kg x 10" and h["sessions"][0]["date"] == "2026-09-17"
    bench = next(p for p in stats.current_prs(store) if p["exercise"] == "Bench Press")
    assert bench["heaviest"]["set"] == "67.5 kg x 4" and bench["best_1rm"]["value"] == "80 kg"
    weeks = stats.weekly_volume(store, 2, until=datetime(2026, 9, 20, 12).astimezone(), unit="kg")
    assert [w["workouts"] for w in weeks] == [2, 2]

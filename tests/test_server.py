import pytest

pytest.importorskip("mcp")


def test_tools_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("BODYLOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("BODYLOG_CARDS", str(tmp_path / "cards"))
    from bodylog import server

    assert server.log_set(exercise="bench", weight=60, reps=8, unit="kg")["logged"][0]["exercise"] == "Bench Press"
    assert server.log_set(weight=62.5, reps=6)["logged"][0]["unit"] == "kg"
    assert server.edit_last_set(reps=7)["set"]["reps"] == 7
    out = server.log_set(text="10.2 kg x 15 reps")
    assert out["logged"][0]["exercise"] == "Bench Press"
    server.edit_last_set(exercise="cable pushdown")
    text, image = server.end_session(duration="45 min", title="Push Day")
    assert text.startswith("**Push Day**") and "Cable Pushdown" in text
    assert image.path.exists()
    assert server.exercise_history("bench")["sessions"][0]["sets"] == 2
    assert server.prs()[0]["exercise"] == "Bench Press"
    assert server.weekly_volume(2)[-1]["workouts"] == 1
    server.log_set(text="squat 100kg x 5")
    text, image = server.log_set(text="done, 30 min")
    assert text.startswith("**") and "Squat" in text and image.path.exists()
    assert server.import_chat("[2026-09-01 18:00] me: squat 100kg x 5\n[2026-09-01 18:40] me: done 40 min")["sets"] == 1


def test_tools_are_registered():
    from bodylog import server

    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert {"log_set", "edit_last_set", "end_session", "session_card", "exercise_history", "prs", "log_food",
            "edit_food", "lookup_food", "food_day", "food_card", "set_goals", "streaks"} <= names


def test_food_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("BODYLOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("BODYLOG_CARDS", str(tmp_path / "cards"))
    from bodylog import server

    out = server.log_food(text="2 eggs and a handful of almonds")
    assert [r["status"] for r in out["logged"]] == ["ok", "needs_amount"]
    assert out["day_totals"]["kcal"] == 143
    fixed = server.edit_food(out["logged"][1]["id"], grams=28)["item"]
    assert fixed["status"] == "ok"
    assert server.set_goals(kcal=2000) == {"kcal": 2000}
    day = server.food_day()
    assert day["remaining"]["kcal"] == 2000 - 143 - fixed["kcal"]
    text, image = server.food_card(style="story")
    assert image.path.exists() and text.startswith("**")
    assert server.streaks()["logging_days"] == 1

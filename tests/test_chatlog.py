from bodylog import chatlog, import_chat, interpret
from tests.conftest import FIXTURE


def kinds(text):
    return [a.kind for a in interpret(text)]


def test_interpret_sets_and_units():
    a = interpret("10.2 kg x 15 reps")[0]
    assert (a.weight, a.unit, a.reps) == (10.2, "kg", 15)
    assert [(a.weight, a.unit, a.reps) for a in interpret("50lbs for 9")] == [(50, "lb", 9)]
    assert [(a.weight, a.reps) for a in interpret("8 reps at 60kg")] == [(60, 8)]
    a = interpret("seated cable row 3x10 @ 90lb")
    assert a[0].exercise == "seated cable row" and (a[1].count, a[1].reps, a[1].weight) == (3, 10, 90)
    assert [(x.weight, x.count) for x in interpret("60kg 3x8")] == [(60, 3)]


def test_interpret_flags_and_commands():
    assert interpret("bench 20kg x 10 warmup")[1].set_kind == "warmup"
    assert interpret("25 lb x 8 to failure")[0].set_kind == "failure"
    assert interpret("110lb x 9 rpe 9")[0].rpe == 9
    assert kinds("same") == kinds("one more") == ["repeat"]
    assert kinds("this is tricep cable pushdowns btw") == ["name"]
    assert kinds("push day") == ["title"]
    assert interpret("done, 1h 5m")[0].duration == "1h 5m"
    assert interpret("wrapped up, workout took 1h 3m")[0].kind == "end"
    assert kinds("done with bench") == ["current"]  # not the end of the workout
    assert kinds("ugh forearms are fried") == []


def test_import_fixture(store):
    r = import_chat(store, FIXTURE.read_text())
    assert len(r.sessions) == 4 and r.sets == 40
    assert r.skipped == ["line 25: ugh forearms are fried"]
    titles = [store.session(i)["title"] for i in r.sessions]
    assert titles == ["Push Day", "Pull Day", "Push Day", "Push Day"]
    assert [store.session(i)["duration_s"] for i in r.sessions] == [3900, 2700, 3300, 3780]
    first = store.sets(r.sessions[0])
    assert [s["exercise"] for s in first if s["weight"] == 10.2] == ["Triceps Cable Pushdown"] * 2
    assert {s["unit"] for s in first} == {"kg", "lb"}
    names = {row["name"] for row in store.db.execute("SELECT name FROM exercises")}
    assert names == {"Bench Press", "Incline Dumbbell Press", "Triceps Cable Pushdown", "Lateral Raise",
                     "Lat Pulldown", "Seated Cable Row", "Incline Dumbbell Curl"}


def test_import_is_idempotent(store):
    import_chat(store, FIXTURE.read_text())
    again = import_chat(store, FIXTURE.read_text())
    assert again.sessions == [] and again.duplicates == 4


def test_untimed_log_is_one_session(store):
    r = import_chat(store, "bench 60kg x 8\n62.5kg x 6\nnow squats 100kg x 5\ndone 40 min\n")
    assert len(r.sessions) == 1 and r.sets == 3


def test_log_text_live(store):
    assert chatlog.log_text(store, "10.2 kg x 15 reps") == ["unnamed exercise: 10.2 kg x 15"]
    assert chatlog.log_text(store, "this is tricep cable pushdowns btw") == ["named 1 set(s) Triceps Cable Pushdown"]
    assert chatlog.log_text(store, "same")[0] == "Triceps Cable Pushdown: 10.2 kg x 15"


def test_negated_done_does_not_end_the_workout():
    for text in ("not done yet, one more set", "still not done", "done warming up", "almost done"):
        assert "end" not in kinds(text), text


def test_bare_drop_is_not_a_drop_set():
    assert interpret("try not to drop this one 40kg x10")[-1].set_kind == "normal"


def test_clauses_split_exercises_and_flags():
    acts = interpret("bench press 60kg x8, now overhead press 40kg x8")
    assert [(a.kind, a.exercise) for a in acts if a.kind == "current"] == [("current", "bench press"), ("current", "overhead press")]
    acts = interpret("11.3kg x 12, then 9 kg x 15 drop set")
    assert [a.set_kind for a in acts] == ["normal", "drop"]
    assert interpret("62.5 x 8, rpe 9")[0].rpe == 9


def test_announcement_in_its_own_message(store):
    chatlog.log_text(store, "bench 60kg x 8")
    chatlog.log_text(store, "switching to squats")
    assert chatlog.log_text(store, "100kg x 5") == ["Squat: 100 kg x 5"]
    r = import_chat(store, "[2026-09-01 18:00] me: bench press\n[2026-09-01 18:02] me: 60kg x 8\n[2026-09-01 18:40] me: done 40 min")
    assert r.skipped == [] and r.sets == 1

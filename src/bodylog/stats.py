"""Volume, best sets, PRs against history, per-exercise history and weekly volume."""
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import muscles
from .store import LB, Store, to_kg, unit_of

EPS = 1e-6
PR_LABELS = {"weight": "Heaviest weight", "e1rm": "Best 1RM", "volume": "Best set volume", "reps": "Most reps"}


def e1rm(kg: float, reps: int) -> float:
    """Epley estimated one-rep max."""
    if reps <= 0 or kg <= 0:
        return 0.0
    return kg if reps == 1 else kg * (1 + reps / 30)


def kg(row) -> float:
    """Weight in kg, rounded once so 15 lb always compares equal to 15 lb."""
    return round(to_kg(row["weight"], row["unit"]), 3)


def in_unit(row, unit: str) -> float:
    """Weight in `unit`, converted exactly (no rounding), for sums like volume."""
    if row["unit"] == unit:
        return row["weight"]
    return row["weight"] * LB if unit == "kg" else row["weight"] / LB


def working(rows):
    return [r for r in rows if r["kind"] != "warmup" and r["exercise_id"] is not None]


def fmt_num(x: float) -> str:
    x = round(x, 1)
    return f"{x:,.0f}" if abs(x - round(x)) < EPS else f"{x:,.1f}"


def fmt_weight(value_kg: float, unit: str) -> str:
    return f"{fmt_num(value_kg / LB if unit == 'lb' else value_kg)} {unit}"


def fmt_set(row, times: str = " x ") -> str:
    if not row["weight"]:
        return f"{row['reps']} reps"
    return f"{fmt_num(row['weight'])} {row['unit']}{times}{row['reps']}"


def fmt_duration(secs: int | None) -> str:
    if not secs:
        return "0m"
    h, m = divmod(round(secs / 60), 60)
    return f"{h}h {m}m" if h else f"{m}m"


def majority_unit(rows, default: str = "kg") -> str:
    c = Counter(r["unit"] for r in rows)
    return c.most_common(1)[0][0] if c else default


def best_set(rows):
    """Heaviest-effort set: highest e1RM, or most reps for bodyweight work."""
    rows = working(rows)
    return max(rows, key=lambda r: (e1rm(kg(r), r["reps"]), r["reps"]), default=None)


def _history(store: Store, exercise_id: int, before: str, exclude_session: int):
    return store.db.execute(
        "SELECT st.* FROM sets st JOIN sessions se ON se.id = st.session_id "
        "WHERE st.exercise_id = ? AND st.kind != 'warmup' AND julianday(se.started_at) < julianday(?) AND se.id != ?",
        (exercise_id, before, exclude_session)).fetchall()


def records(rows) -> dict:
    rec = {"weight": 0.0, "e1rm": 0.0, "volume": 0.0, "reps": defaultdict(int)}
    for r in working(rows):
        w = kg(r)
        rec["weight"] = max(rec["weight"], w)
        rec["e1rm"] = max(rec["e1rm"], e1rm(w, r["reps"]))
        rec["volume"] = max(rec["volume"], w * r["reps"])
        rec["reps"][w] = max(rec["reps"][w], r["reps"])
    return rec


def session_prs(store: Store, session) -> list[dict]:
    """PRs set in this session, each against sessions that started earlier. A first-ever exercise sets no PRs."""
    out = []
    by_ex = defaultdict(list)
    for r in working(store.sets(session["id"])):
        by_ex[r["exercise_id"]].append(r)
    for ex_id, rows in by_ex.items():
        past = _history(store, ex_id, session["started_at"], session["id"])
        if not past:
            continue
        old, name = records(past), rows[0]["exercise"]
        heavy = max(rows, key=lambda r: (kg(r), r["reps"]))
        if kg(heavy) > old["weight"] + EPS:
            out.append({"exercise": name, "exercise_id": ex_id, "type": "weight", "set_id": heavy["id"], "set": fmt_set(heavy),
                        "unit": heavy["unit"], "value_kg": round(kg(heavy), 2), "previous_kg": old["weight"]})
        top = max(rows, key=lambda r: e1rm(kg(r), r["reps"]))
        if e1rm(kg(top), top["reps"]) > old["e1rm"] + EPS:
            out.append({"exercise": name, "exercise_id": ex_id, "type": "e1rm", "set_id": top["id"], "set": fmt_set(top),
                        "unit": top["unit"], "value_kg": round(e1rm(kg(top), top["reps"]), 1), "previous_kg": round(old["e1rm"], 1)})
        big = max(rows, key=lambda r: (kg(r) * r["reps"], kg(r)))
        if kg(big) * big["reps"] > old["volume"] + EPS:
            out.append({"exercise": name, "exercise_id": ex_id, "type": "volume", "set_id": big["id"], "set": fmt_set(big),
                        "unit": big["unit"], "value_kg": round(kg(big) * big["reps"], 1),
                        "previous_kg": round(old["volume"], 1)})
        # most reps at a weight done before; one per exercise, the biggest jump
        gains = [(r["reps"] - old["reps"][kg(r)], kg(r), r) for r in rows
                 if kg(r) in old["reps"] and r["reps"] > old["reps"][kg(r)]]
        if gains:
            _, _, r = max(gains, key=lambda g: g[:2])
            out.append({"exercise": name, "exercise_id": ex_id, "type": "reps", "set_id": r["id"], "set": fmt_set(r),
                        "unit": r["unit"], "value": r["reps"], "previous": old["reps"][kg(r)]})
    return out


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_volume(store: Store, weeks: int = 8, until=None, unit: str | None = None) -> list[dict]:
    """Volume per Monday-start week, oldest first. `until` caps the data (a card only counts what came before it)."""
    until = datetime.fromisoformat(until) if isinstance(until, str) else until or datetime.now().astimezone()
    last = week_start(until.date())
    first = last - timedelta(weeks=weeks - 1)
    unit = unit or store.default_unit()
    buckets = {first + timedelta(weeks=i): {"sessions": set(), "volume": 0.0, "sets": 0} for i in range(weeks)}
    rows = store.db.execute(
        "SELECT st.*, se.started_at FROM sets st JOIN sessions se ON se.id = st.session_id "
        "WHERE st.kind != 'warmup' AND julianday(se.started_at) <= julianday(?)", (until.isoformat(),)).fetchall()
    for r in rows:
        wk = week_start(datetime.fromisoformat(r["started_at"]).date())
        if wk in buckets:
            b = buckets[wk]
            b["sessions"].add(r["session_id"])
            b["volume"] += in_unit(r, unit) * r["reps"]
            b["sets"] += 1
    return [{"week": wk.isoformat(), "workouts": len(b["sessions"]), "sets": b["sets"],
             "volume": round(b["volume"], 1), "unit": unit}
            for wk, b in sorted(buckets.items())]


MARKS = {"warmup": "W", "drop": "D", "failure": "F"}


def _set_rows(rows, prs) -> list[dict]:
    """Every set in logged order, in its logged unit. Normal sets are numbered 1..n; warm-up, drop and
    failure sets carry W / D / F instead of a number, as in the usual tracker convention."""
    on_set = defaultdict(list)
    for p in prs:
        on_set[p["set_id"]].append(p["type"])
    out, n = [], 0
    for r in rows:
        if r["kind"] in MARKS:
            label = MARKS[r["kind"]]
        else:
            n += 1
            label = str(n)
        out.append({"id": r["id"], "label": label, "kind": r["kind"], "weight": r["weight"], "unit": r["unit"],
                    "reps": r["reps"], "rpe": r["rpe"], "text": fmt_set(r), "prs": on_set[r["id"]]})
    return out


def _week_days(store: Store, started: datetime) -> list[int]:
    """Workouts per day, Monday to Sunday, of the week holding `started`, up to and including it."""
    first = week_start(started.date())
    days = [0] * 7
    for r in store.db.execute("SELECT started_at FROM sessions WHERE julianday(started_at) <= julianday(?)",
                              (started.isoformat(),)):
        d = datetime.fromisoformat(r["started_at"]).date()
        if first <= d < first + timedelta(days=7):
            days[d.weekday()] += 1
    return days


def summary(store: Store, session_id: int | None = None, unit: str | None = None) -> dict:
    """Everything a card needs, for one session (default: the open one, else the latest).
    Totals are in `unit`, else $BODYLOG_UNIT, else the session's most-logged unit; each set keeps its own."""
    s = store.session(session_id) if session_id else store.open_session() or store.last_session()
    if not s:
        raise LookupError("no sessions logged yet")
    rows = store.sets(s["id"])
    unit = unit_of(unit) or unit_of(os.environ.get("BODYLOG_UNIT") or None) or majority_unit(rows, store.default_unit())
    prs = session_prs(store, s)
    exercises, order = {}, []
    for r in rows:
        key = r["exercise_id"]
        if key not in exercises:
            exercises[key] = {"name": r["exercise"] or "Unnamed exercise", "sets": []}
            order.append(key)
        exercises[key]["sets"].append(r)
    ex_out, volume = [], 0.0  # summed per set in the target unit, so conversion never compounds rounding
    for key in order:
        ex_rows = exercises[key]["sets"]
        best = best_set(ex_rows)
        vol_kg = sum(in_unit(r, "kg") * r["reps"] for r in working(ex_rows))
        vol = sum(in_unit(r, unit) * r["reps"] for r in working(ex_rows))
        volume += vol
        ex_out.append({
            "name": exercises[key]["name"],
            "muscle": muscles.muscle(exercises[key]["name"] if key is not None else None),
            "sets": _set_rows(ex_rows, prs),
            "working_sets": len(working(ex_rows)),
            "best": fmt_set(best) if best else None,
            "volume_kg": round(vol_kg, 1),
            "volume": round(vol, 1),
            "prs": [p["type"] for p in prs if p["exercise_id"] == key],
        })
    per_muscle = Counter()
    for e in ex_out:
        per_muscle[e["muscle"]] += e["working_sets"] or len(e["sets"])
    started = datetime.fromisoformat(s["started_at"])
    duration = s["duration_s"]
    if duration is None and rows:
        duration = int((datetime.fromisoformat(rows[-1]["logged_at"]) - started).total_seconds())
    weeks = weekly_volume(store, 8, until=started, unit=unit)
    this = weeks[-1]
    # compare with last week up to the same weekday and time, so a Monday session is not "down 90%"
    same_point = weekly_volume(store, 1, until=started - timedelta(weeks=1), unit=unit)[0]["volume"]
    change = round((this["volume"] - same_point) / same_point * 100) if same_point else None
    hour = started.hour
    part = "Morning" if 4 <= hour < 12 else "Afternoon" if hour < 17 else "Evening" if hour < 22 else "Night"
    return {
        "id": s["id"],
        "title": s["title"] or f"{part} Workout",
        "started_at": s["started_at"],
        "ended_at": s["ended_at"],
        "open": s["ended_at"] is None,
        "duration_s": duration,
        "duration": fmt_duration(duration),
        "unit": unit,
        "volume": round(volume, 1),
        "volume_text": f"{fmt_num(volume)} {unit}",
        "sets": sum(e["working_sets"] for e in ex_out),
        "number": store.db.execute("SELECT COUNT(*) FROM sessions WHERE julianday(started_at) <= julianday(?)",
                                   (s["started_at"],)).fetchone()[0],
        "exercises": ex_out,
        "muscles": muscles.split(per_muscle),
        "prs": prs,
        "week": {"workouts": this["workouts"], "volume": this["volume"], "previous_to_date": same_point,
                 "change_pct": change, "bars": [w["volume"] for w in weeks], "unit": unit,
                 "days": _week_days(store, started), "today": started.weekday()},
    }


def exercise_history(store: Store, exercise: str, limit: int = 20, unit: str | None = None) -> dict:
    ex = store.find_exercise(exercise)
    if not ex:
        raise LookupError(f"no exercise matching {exercise!r}")
    rows = store.db.execute(
        "SELECT st.*, se.started_at FROM sets st JOIN sessions se ON se.id = st.session_id "
        "WHERE st.exercise_id = ? ORDER BY julianday(se.started_at) DESC, julianday(st.logged_at)", (ex["id"],)).fetchall()
    unit = unit or majority_unit(rows, store.default_unit())
    sessions = defaultdict(list)
    for r in rows:
        sessions[(r["started_at"], r["session_id"])].append(r)
    out = []
    for (started, sid), srows in list(sessions.items())[:limit]:
        best = best_set(srows)
        work = working(srows)
        out.append({
            "session_id": sid, "date": started[:10], "sets": len(work),
            "best": fmt_set(best) if best else None,
            "top_weight": fmt_weight(max((kg(r) for r in work), default=0), unit),
            "e1rm": fmt_weight(max((e1rm(kg(r), r["reps"]) for r in work), default=0), unit),
            "volume": fmt_weight(sum(in_unit(r, "kg") * r["reps"] for r in work), unit),
        })
    return {"exercise": ex["name"], "unit": unit, "sessions": out}


def current_prs(store: Store, exercise: str | None = None) -> list[dict]:
    """All-time records per exercise: heaviest weight, best estimated 1RM, most reps in one set."""
    if exercise:
        ex = store.find_exercise(exercise)
        if not ex:
            raise LookupError(f"no exercise matching {exercise!r}")
        ids = [ex["id"]]
    else:
        ids = [r["id"] for r in store.db.execute("SELECT id FROM exercises ORDER BY name")]
    out = []
    for ex_id in ids:
        rows = store.db.execute(
            "SELECT st.*, e.name AS exercise, se.started_at FROM sets st JOIN exercises e ON e.id = st.exercise_id "
            "JOIN sessions se ON se.id = st.session_id WHERE st.exercise_id = ? AND st.kind != 'warmup'", (ex_id,)).fetchall()
        if not rows:
            continue
        unit = majority_unit(rows)
        heavy = max(rows, key=lambda r: (kg(r), r["reps"]))
        top = max(rows, key=lambda r: e1rm(kg(r), r["reps"]))
        most = max(rows, key=lambda r: (r["reps"], kg(r)))
        out.append({
            "exercise": rows[0]["exercise"],
            "heaviest": {"set": fmt_set(heavy), "date": heavy["started_at"][:10]},
            "best_1rm": {"value": fmt_weight(e1rm(kg(top), top["reps"]), unit), "set": fmt_set(top), "date": top["started_at"][:10]},
            "most_reps": {"set": fmt_set(most), "date": most["started_at"][:10]},
        })
    return out

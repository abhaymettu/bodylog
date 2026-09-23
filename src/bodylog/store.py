"""SQLite store (workouts and food in one file) and the chat-shaped workout API (log a set, fix the last one,
end with a duration). Food logging lives in food.py on the same connection."""
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import APP, names

LB = 0.45359237
KINDS = ("normal", "warmup", "drop", "failure")
STALE = timedelta(hours=6)  # an open session idle this long is closed before a new set starts a new one
# Timestamps are ISO strings with a UTC offset; compare them with julianday() so DST or travel cannot reorder them.

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (id INTEGER PRIMARY KEY, name TEXT NOT NULL, key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, exercise_id INTEGER NOT NULL REFERENCES exercises(id));
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY, title TEXT, started_at TEXT NOT NULL, ended_at TEXT, duration_s INTEGER, notes TEXT,
  current_exercise_id INTEGER REFERENCES exercises(id));
CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  exercise_id INTEGER REFERENCES exercises(id), explicit INTEGER NOT NULL DEFAULT 1,
  weight REAL NOT NULL DEFAULT 0, unit TEXT NOT NULL DEFAULT 'kg' CHECK (unit IN ('kg', 'lb')),
  reps INTEGER NOT NULL CHECK (reps >= 0), rpe REAL, kind TEXT NOT NULL DEFAULT 'normal', notes TEXT,
  logged_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sets_by_exercise ON sets(exercise_id);
CREATE INDEX IF NOT EXISTS sets_by_session ON sets(session_id);
-- food: foods is a cache of source records (per 100 g); food_log is what was eaten
CREATE TABLE IF NOT EXISTS foods (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL, brand TEXT,
  kcal REAL, protein REAL, carbs REAL, fat REAL, portions TEXT NOT NULL DEFAULT '[]', count TEXT,
  fetched_at TEXT NOT NULL, UNIQUE (source, source_id));
CREATE TABLE IF NOT EXISTS food_lookups (query TEXT PRIMARY KEY, food_id INTEGER NOT NULL REFERENCES foods(id));
CREATE TABLE IF NOT EXISTS food_log (
  id INTEGER PRIMARY KEY, eaten_at TEXT NOT NULL, day TEXT NOT NULL, meal TEXT NOT NULL, said TEXT NOT NULL,
  name TEXT NOT NULL, amount REAL, unit TEXT, grams REAL, food_id INTEGER REFERENCES foods(id),
  kcal REAL, protein REAL, carbs REAL, fat REAL,
  status TEXT NOT NULL CHECK (status IN ('ok', 'manual', 'unknown', 'needs_amount')), note TEXT);
CREATE INDEX IF NOT EXISTS food_log_by_day ON food_log(day);
CREATE TABLE IF NOT EXISTS goals (key TEXT PRIMARY KEY, value REAL NOT NULL);
"""


def default_path() -> Path:
    return Path(os.environ.get(f"{APP.upper()}_DB") or Path.home() / f".{APP}" / "log.db")


def now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def ts(dt: datetime | str | None) -> str:
    if dt is None:
        return now().isoformat()
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.replace(microsecond=0).isoformat()


def to_kg(weight: float, unit: str) -> float:
    return weight * LB if unit == "lb" else weight


def unit_of(u: str | None) -> str | None:
    if not u:
        return None
    u = u.lower().strip().rstrip(".")
    if u in ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"):
        return "kg"
    if u in ("lb", "lbs", "pound", "pounds", "#"):
        return "lb"
    raise ValueError(f"unknown unit {u!r}, use kg or lb")


def parse_duration(value) -> int | None:
    """Seconds from 65, "65", "65 min", "1h 5m", "1:05", "1 hour 5 minutes". Bare numbers are minutes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(round(value * 60))
    s = str(value).strip().lower()
    if m := re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", s):
        h, mi, sec = int(m[1]), int(m[2]), int(m[3] or 0)
        return h * 3600 + mi * 60 + sec
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(round(float(s) * 60))
    total, found = 0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|seconds)\b", s):
        found = True
        total += float(num) * (3600 if unit.startswith("h") else 1 if unit.startswith("s") else 60)
    if not found:
        raise ValueError(f"cannot read duration {value!r}, try '1h 5m' or '65 min'")
    return int(round(total))


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # exercises

    def find_exercise(self, name: str) -> sqlite3.Row | None:
        k = names.key(name)
        if not k:
            return None
        row = self.db.execute(
            "SELECT e.* FROM aliases a JOIN exercises e ON e.id = a.exercise_id WHERE a.alias = ?", (k,)).fetchone()
        if row:
            return row
        keys = [r["key"] for r in self.db.execute("SELECT key FROM exercises")]
        match = names.close_match(k, keys)
        if match:
            row = self.db.execute("SELECT * FROM exercises WHERE key = ?", (match,)).fetchone()
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (k, row["id"]))
        return row

    def exercise(self, name: str) -> sqlite3.Row:
        """Resolve a spoken name to an exercise, creating it on first mention."""
        row = self.find_exercise(name)
        if row:
            return row
        k = names.key(name)
        if not k:
            raise ValueError(f"no exercise name in {name!r}")
        with self.db:
            cur = self.db.execute("INSERT INTO exercises (name, key) VALUES (?, ?)", (names.display(name), k))
            self.db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (k, cur.lastrowid))
        return self.db.execute("SELECT * FROM exercises WHERE id = ?", (cur.lastrowid,)).fetchone()

    def alias(self, alias: str, exercise: str) -> sqlite3.Row:
        """Teach a name: alias("skullcrushers", "EZ bar lying triceps extension")."""
        row = self.exercise(exercise)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?)", (names.key(alias), row["id"]))
        return row

    # sessions

    def session(self, session_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise LookupError(f"no session {session_id}")
        return row

    def open_session(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY julianday(started_at) DESC LIMIT 1").fetchone()

    def last_session(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM sessions ORDER BY julianday(started_at) DESC, id DESC LIMIT 1").fetchone()

    def start_session(self, title: str | None = None, at=None) -> sqlite3.Row:
        with self.db:
            cur = self.db.execute("INSERT INTO sessions (title, started_at) VALUES (?, ?)", (title, ts(at)))
        return self.session(cur.lastrowid)

    def _live_session(self, at) -> sqlite3.Row:
        s = self.open_session()
        if s:
            last = self._last_time(s)
            if datetime.fromisoformat(ts(at)) - last > STALE:
                self.end_session(session_id=s["id"], at=last)
                s = None
        return s or self.start_session(at=at)

    def end_session(self, duration=None, at=None, title: str | None = None, session_id: int | None = None) -> sqlite3.Row:
        """Close a session. With a duration ("1h 5m"), start = end - duration, as Hevy does."""
        s = self.session(session_id) if session_id else self.open_session()
        if not s:
            raise LookupError("no open session to end")
        secs = parse_duration(duration)
        if at is None:
            # "done, 1h 5m" said right after training ends now; an end call on a stale session ends at its last set
            last = self._last_time(s)
            end = now() if secs and now() - last < STALE else last
        else:
            end = datetime.fromisoformat(ts(at))
        start = datetime.fromisoformat(s["started_at"])
        if secs:
            start = min(start, end - timedelta(seconds=secs))
        else:
            secs = int((end - start).total_seconds())
        with self.db:
            self.db.execute(
                "UPDATE sessions SET started_at = ?, ended_at = ?, duration_s = ?, title = COALESCE(?, title) WHERE id = ?",
                (start.isoformat(), end.isoformat(), secs, title, s["id"]))
        return self.session(s["id"])

    def _last_time(self, s) -> datetime:
        rows = self.sets(s["id"])
        return datetime.fromisoformat(rows[-1]["logged_at"] if rows else s["started_at"])

    def set_current(self, exercise: str, session_id: int | None = None, at=None) -> sqlite3.Row:
        """"now squats": later sets without a name go to this exercise."""
        s = self.session(session_id) if session_id else self._live_session(at)
        ex = self.exercise(exercise)
        with self.db:
            self.db.execute("UPDATE sessions SET current_exercise_id = ? WHERE id = ?", (ex["id"], s["id"]))
        return ex

    def delete_session(self, session_id: int):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # sets

    def sets(self, session_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT s.*, e.name AS exercise FROM sets s LEFT JOIN exercises e ON e.id = s.exercise_id "
            "WHERE s.session_id = ? ORDER BY julianday(s.logged_at), s.id", (session_id,)).fetchall()

    def last_set(self, session_id: int | None = None) -> sqlite3.Row | None:
        if session_id is None:
            s = self.open_session()
            if not s:
                return None
            session_id = s["id"]
        rows = self.sets(session_id)
        return rows[-1] if rows else None

    def log_set(self, exercise: str | None = None, weight: float | None = None, reps: int | None = None,
                unit: str | None = None, rpe: float | None = None, kind: str = "normal", notes: str | None = None,
                at=None, count: int = 1, session_id: int | None = None, exercise_id: int | None = None) -> list[sqlite3.Row]:
        """Add set(s) to the open session, opening one if needed. No exercise means "same as last set"."""
        if reps is None or int(reps) < 0:
            raise ValueError("reps is required")
        kind = kind or "normal"
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        s = self.session(session_id) if session_id else self._live_session(at)
        prev = self.last_set(s["id"])
        if exercise:
            ex_id, explicit = self.exercise(exercise)["id"], 1
        else:
            ex_id, explicit = exercise_id or s["current_exercise_id"] or (prev["exercise_id"] if prev else None), 0
        unit = unit_of(unit) or (prev["unit"] if prev else self.default_unit())
        base = datetime.fromisoformat(ts(at))
        ids = []
        with self.db:
            for i in range(max(1, int(count))):
                cur = self.db.execute(
                    "INSERT INTO sets (session_id, exercise_id, explicit, weight, unit, reps, rpe, kind, notes, logged_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (s["id"], ex_id, explicit, float(weight or 0), unit, int(reps), rpe, kind, notes,
                     (base + timedelta(seconds=i)).isoformat()))
                ids.append(cur.lastrowid)
            self.db.execute("UPDATE sessions SET current_exercise_id = ? WHERE id = ?", (ex_id, s["id"]))
        return [r for r in self.sets(s["id"]) if r["id"] in ids]

    def repeat_last(self, count: int = 1, reps: int | None = None, weight: float | None = None, at=None,
                    session_id: int | None = None) -> list[sqlite3.Row]:
        prev = self.last_set(session_id)
        if not prev:
            raise LookupError("no previous set to repeat")
        kind = prev["kind"] if prev["kind"] == "warmup" else "normal"
        return self.log_set(None, prev["weight"] if weight is None else weight, prev["reps"] if reps is None else reps,
                            prev["unit"], kind=kind, at=at, count=count, session_id=prev["session_id"],
                            exercise_id=prev["exercise_id"])

    def edit_last_set(self, delete: bool = False, session_id: int | None = None, **fields) -> sqlite3.Row | None:
        """Fix the last set: edit_last_set(reps=12), edit_last_set(exercise="cable pushdown"), or delete=True."""
        last = self.last_set(session_id)
        if not last:
            raise LookupError("no set to edit")
        if delete:
            with self.db:
                self.db.execute("DELETE FROM sets WHERE id = ?", (last["id"],))
            return None
        updates = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k == "exercise":
                updates["exercise_id"], updates["explicit"] = self.exercise(v)["id"], 1
                with self.db:
                    self.db.execute("UPDATE sessions SET current_exercise_id = ? WHERE id = ?",
                                    (updates["exercise_id"], last["session_id"]))
            elif k == "unit":
                updates["unit"] = unit_of(v)
            elif k == "kind":
                if v not in KINDS:
                    raise ValueError(f"kind must be one of {', '.join(KINDS)}")
                updates["kind"] = v
            elif k in ("weight", "reps", "rpe", "notes"):
                updates[k] = v
            else:
                raise ValueError(f"cannot edit {k!r}")
        if updates:
            with self.db:
                self.db.execute(f"UPDATE sets SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
                                (*updates.values(), last["id"]))
        return next(r for r in self.sets(last["session_id"]) if r["id"] == last["id"])

    def name_recent(self, exercise: str, session_id: int | None = None) -> list[sqlite3.Row]:
        """"this is tricep cable pushdowns btw": name the sets just logged without a name.

        Takes unnamed sets if there are any, else the trailing run of defaulted sets at the last set's weight.
        """
        last = self.last_set(session_id)
        if not last:
            return []
        rows = self.sets(last["session_id"])
        unnamed = [r for r in rows if r["exercise_id"] is None]
        if not unnamed:
            for r in reversed(rows):
                if r["explicit"] or (r["weight"], r["unit"]) != (last["weight"], last["unit"]):
                    break
                unnamed.append(r)
        ex_id = self.exercise(exercise)["id"]
        with self.db:
            self.db.executemany("UPDATE sets SET exercise_id = ?, explicit = 1 WHERE id = ?", [(ex_id, r["id"]) for r in unnamed])
            self.db.execute("UPDATE sessions SET current_exercise_id = ? WHERE id = ?", (ex_id, last["session_id"]))
        ids = {r["id"] for r in unnamed}
        return [r for r in self.sets(last["session_id"]) if r["id"] in ids]

    def default_unit(self) -> str:
        row = self.db.execute("SELECT unit, COUNT(*) n FROM sets GROUP BY unit ORDER BY n DESC LIMIT 1").fetchone()
        return row["unit"] if row else "kg"

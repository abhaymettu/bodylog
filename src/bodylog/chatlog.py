"""Read workout chat ("60kg x 8", "this is tricep cable pushdowns btw", "done, 1h 5m") into store calls.

`interpret(line)` is pure: it turns one message into actions. `apply(store, actions)` runs them against the
live session (or a given one), and `import_chat(store, text)` backfills a whole pasted log.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import names
from .stats import fmt_set
from .store import Store, ts, unit_of

U = r"(?:kgs?|kilos?|kilograms?|lbs?|pounds?)"
W = r"\d+(?:\.\d+)?"
SET_PATTERNS = [
    # 3x10 @ 90lb, 3 sets of 10 at 60 kg
    rf"(?P<sets>\d+)\s*(?:x|×|sets?\s+of)\s*(?P<reps>\d+)\s*(?:reps?\s*)?(?:@|at|with)\s*(?P<w>{W})\s*(?P<u>{U})?",
    # 60kg 3x8
    rf"(?P<w>{W})\s*(?P<u>{U})\s+(?P<sets>\d+)\s*[x×]\s*(?P<reps>\d+)",
    # 60kg x 8, 60 kg for 8 reps, 60 x 8, 60kg x 8 x 3
    rf"(?P<w>{W})\s*(?P<u>{U})?\s*(?:[x×*]|(?<=[a-z])\s*for)\s*(?P<reps>\d+)(?:\s*reps?)?(?:\s*[x×]\s*(?P<sets>\d+)(?:\s*sets?)?)?",
    # 8 reps at 60kg
    rf"(?P<reps>\d+)\s*reps?\s*(?:@|at|with|of)\s*(?P<w>{W})\s*(?P<u>{U})",
    # 12 reps (bodyweight)
    r"(?P<reps>\d+)\s*reps?\b",
]
SET_RE = [re.compile(p, re.I) for p in SET_PATTERNS]

STAMP = re.compile(r"^\s*\[?(?P<date>\d{4}-\d{2}-\d{2})?[ T]?(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]m)?)?\]?\s*", re.I)
SPEAKER = re.compile(r"^(?P<who>[A-Za-z][\w .'-]{0,30}):\s+")
AGENTS = {"assistant", "agent", "bot", "claude", "ai", "hermes", "system", "coach"}
RETRO = re.compile(r"^(?:ok\s+|oh\s+|btw\s+)?(?:this|that|these|those)\s+(?:is|was|were|are)\s+(?:the\s+|my\s+)?(?P<name>.+?)[\s.!]*$", re.I)
NEXT = re.compile(r"^(?:now|next|then|moving\s+(?:on\s+)?to|starting|doing|onto|on\s+to|switching\s+to)\s+(?P<name>.+)$", re.I)
TITLE = re.compile(r"^(?:starting\s+|start\s+|doing\s+)?(?:a\s+|my\s+)?(?P<title>[a-z ]{2,20}?\s(?:day|workout|session))\b", re.I)
END = re.compile(r"\b(?:done|finished|wrapped up|that'?s it|all done|end(?:ed)?\s+(?:the\s+)?(?:workout|session)|workout took|session took)\b", re.I)
REPEAT = re.compile(r"^(?:same(?:\s+again)?|again|another(?:\s+(?:one|set))?|one\s+more(?:\s+set)?|repeat)(?:\s*(?:x|for|with)\s*(?P<reps>\d+)(?:\s*reps?)?)?[\s.!]*$", re.I)
FLAGS = {
    "warmup": re.compile(r"\bwarm[\s-]?ups?\b|\bwu\b", re.I),
    "drop": re.compile(r"\bdrop\s*sets?\b", re.I),
    "failure": re.compile(r"\b(?:to\s+)?failure\b", re.I),
}
NOT_END = re.compile(r"\b(?:not|never|almost|nearly|yet|warm(?:ing)?[\s-]?ups?|with)\b|n't\b", re.I)
CLAUSE = re.compile(r"[,;]|\s+(?:and\s+)?then\s+|\s+and\s+now\s+|\s+(?=now\s)", re.I)
RPE = re.compile(r"\brpe\s*(?P<rpe>\d+(?:\.\d)?)\b", re.I)
NOISE = re.compile(r"\b(?:then|and|btw|plus|also|same|x|for|at|reps?|sets?|ok|okay|did|just|lol|done|finished|with)\b|[,;:+&.!?()\-]", re.I)


@dataclass
class Action:
    kind: str  # set | name | current | repeat | end | title
    exercise: str | None = None
    weight: float = 0.0
    unit: str | None = None
    reps: int = 0
    count: int = 1
    set_kind: str = "normal"
    rpe: float | None = None
    duration: str | None = None
    title: str | None = None


def _sets(text: str) -> tuple[list[tuple[int, Action]], str]:
    found, rest = [], text
    for rx in SET_RE:
        for m in rx.finditer(rest):
            g = m.groupdict()
            found.append((m.start(), Action("set", weight=float(g.get("w") or 0), unit=unit_of(g.get("u")),
                                            reps=int(g["reps"]), count=int(g.get("sets") or 1))))
        rest = rx.sub(lambda m: " " * len(m.group()), rest)
    return sorted(found, key=lambda x: x[0]), rest


def interpret(line: str) -> list[Action]:
    """One chat message to actions. Unrecognized chatter returns []."""
    text = line.strip()
    if not text:
        return []
    if (END.search(text) and not NOT_END.search(text) and not _sets(text)[0]
            and not names.looks_like_exercise(NOISE.sub(" ", text))):
        dur = re.search(r"(\d+\s*h(?:ours?|rs?)?(?:\s*\d+\s*m(?:in(?:ute)?s?)?)?|\d+\s*m(?:in(?:ute)?s?)?\b|\d{1,2}:\d{2})", text, re.I)
        return [Action("end", duration=dur.group(1) if dur else None)]
    if m := REPEAT.match(text):
        return [Action("repeat", reps=int(m["reps"]) if m["reps"] else 0)]
    if m := re.match(r"^same\s+weight\s*(?:x|for|with)?\s*(?P<reps>\d+)", text, re.I):
        return [Action("repeat", reps=int(m["reps"]))]
    if m := RETRO.match(text):
        name = m["name"]
        if names.tokens(name):
            return [Action("name", exercise=name)]
    if (m := TITLE.match(text)) and not re.search(r"\d", text):
        return [Action("title", title=m["title"].strip().title())]

    # clause by clause, so "bench 60kg x 8, now ohp 40kg x 8" names two exercises and
    # "11.3kg x 12, then 9kg x 15 drop set" flags only the second set
    out, last_sets = [], []
    for clause in CLAUSE.split(text):
        flag = next((k for k, rx in FLAGS.items() if rx.search(clause)), None)
        rpe = RPE.search(clause)
        stripped = RPE.sub(" ", clause)
        for rx in FLAGS.values():
            stripped = rx.sub(" ", stripped)
        sets, rest = _sets(stripped)
        sets = [a for _, a in sets]
        for a in sets or last_sets:  # a bare "rpe 9" or "drop set" clause describes the sets before it
            a.set_kind = flag or a.set_kind
            a.rpe = float(rpe["rpe"]) if rpe else a.rpe
        rest = NOISE.sub(" ", rest)
        rest = " ".join(re.sub(r"\b\d+(?:\.\d+)?\b", " ", rest).split())
        announced = NEXT.match(rest)
        if announced:
            rest = announced["name"]
        if rest and (announced or names.looks_like_exercise(rest)):
            out.append(Action("current", exercise=rest))
        out += sets
        last_sets = sets or last_sets
    return out


def apply(store: Store, actions: list[Action], at=None, session_id: int | None = None) -> list[str]:
    """Run actions against the store. Returns a short note per action, for the agent to relay."""
    notes, current = [], None
    for a in actions:
        if a.kind == "current":
            current = store.set_current(a.exercise, session_id=session_id, at=at)["name"]
            notes.append(f"exercise: {current}")
        elif a.kind == "set":
            rows = store.log_set(current, a.weight, a.reps, a.unit, rpe=a.rpe, kind=a.set_kind, at=at, count=a.count,
                                 session_id=session_id)
            notes.append(f"{rows[0]['exercise'] or 'unnamed exercise'}: " + (f"{len(rows)} sets of " if len(rows) > 1 else "")
                         + fmt_set(rows[0]) + (f" ({a.set_kind})" if a.set_kind != "normal" else ""))
        elif a.kind == "repeat":
            rows = store.repeat_last(reps=a.reps or None, at=at, session_id=session_id)
            notes.append(f"{rows[0]['exercise'] or 'unnamed exercise'}: {fmt_set(rows[0])}")
        elif a.kind == "name":
            rows = store.name_recent(a.exercise, session_id=session_id)
            if rows:
                notes.append(f"named {len(rows)} set(s) {rows[0]['exercise']}")
            else:
                notes.append(f"exercise: {store.exercise(a.exercise)['name']}")
        elif a.kind == "title":
            s = store.session(session_id) if session_id else store.open_session() or store.start_session(at=at)
            with store.db:
                store.db.execute("UPDATE sessions SET title = ? WHERE id = ?", (a.title, s["id"]))
            notes.append(f"title: {a.title}")
        elif a.kind == "end":
            s = store.end_session(a.duration, at=at, session_id=session_id)
            notes.append(f"ended session {s['id']}")
    return notes


def log_text(store: Store, text: str, at=None) -> list[str]:
    """Live logging from one chat message. Raises ValueError when nothing in it looks like a set or command."""
    actions = interpret(text)
    if not actions:
        raise ValueError(f"no set, exercise or command found in {text!r}")
    return apply(store, actions, at=at)


@dataclass
class Message:
    at: datetime
    text: str
    line_no: int


@dataclass
class ImportResult:
    sessions: list[int] = field(default_factory=list)
    sets: int = 0
    skipped: list[str] = field(default_factory=list)
    duplicates: int = 0


def messages(text: str, start: datetime | None = None) -> list[Message]:
    """Split a pasted log into user messages with timestamps. Agent lines are dropped."""
    out, day, clock = [], None, None
    base = start or datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = STAMP.match(line)
        if m and (m["date"] or m["time"]):
            if m["date"]:
                day = datetime.fromisoformat(m["date"]).date()
            if m["time"]:
                t = m["time"].strip().lower()
                pm, am = t.endswith("pm"), t.endswith("am")
                hh, mm = (int(x) for x in t.rstrip("apm ").split(":")[:2])
                hh = hh % 12 + (12 if pm else 0) if (pm or am) else hh
                clock = (hh, mm)
            line = line[m.end():]
        if (s := SPEAKER.match(line)) and not names.looks_like_exercise(s["who"]):
            if s["who"].strip().lower() in AGENTS:
                continue
            line = line[s.end():]
        if not line.strip():
            continue
        d = day or base.date()
        hh, mm = clock or (base.hour, base.minute)
        at = datetime(d.year, d.month, d.day, hh, mm).astimezone()
        if out and at <= out[-1].at:
            at = out[-1].at + timedelta(seconds=30)  # untimed follow-ups keep their order
        out.append(Message(at, line.strip(), n))
    return out


def import_chat(store: Store, text: str, gap: timedelta = timedelta(hours=3), start: datetime | None = None) -> ImportResult:
    """Backfill sessions from a chat log. A new session starts after an "done" message or a long gap.

    Re-importing the same log is a no-op: a group whose time span already holds logged sets is skipped.
    """
    res = ImportResult()
    groups, cur = [], []
    for msg in messages(text, start):
        if cur and msg.at - cur[-1].at > gap:
            groups.append(cur)
            cur = []
        cur.append(msg)
        if any(a.kind == "end" for a in interpret(msg.text)):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    for group in groups:
        if store.db.execute("SELECT 1 FROM sets WHERE julianday(logged_at) BETWEEN julianday(?) AND julianday(?) LIMIT 1",
                            (ts(group[0].at), ts(group[-1].at))).fetchone():
            res.duplicates += 1
            continue
        s = store.start_session(at=group[0].at)
        ended = False
        for msg in group:
            actions = interpret(msg.text)
            if not actions:
                res.skipped.append(f"line {msg.line_no}: {msg.text}")
                continue
            try:
                apply(store, actions, at=msg.at, session_id=s["id"])
            except (ValueError, LookupError) as e:
                res.skipped.append(f"line {msg.line_no}: {msg.text} ({e})")
                continue
            ended = ended or any(a.kind == "end" for a in actions)
        if not store.sets(s["id"]):
            store.delete_session(s["id"])
            continue
        if not ended:
            store.end_session(at=store.sets(s["id"])[-1]["logged_at"], session_id=s["id"])
        unnamed = store.db.execute("SELECT COUNT(*) n FROM sets WHERE session_id = ? AND exercise_id IS NULL", (s["id"],)).fetchone()["n"]
        if unnamed:
            res.skipped.append(f"session {s['id']}: {unnamed} set(s) never got an exercise name")
        res.sessions.append(s["id"])
        res.sets += len(store.sets(s["id"]))
    return res

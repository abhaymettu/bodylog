"""Session summary card: a markdown fallback and phone-width PNG pages in dark or light.

Every exercise and every set is drawn; a session too long for one image is split across pages.
`layout()` is the render model (what goes on which page); `render_png()` draws it."""
import math
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import APP
from .muscles import MACRO
from .stats import PR_LABELS, fmt_num
from .store import LB

FONTS = Path(__file__).parent / "fonts"
WIDTH, PAD, S = 1080, 56, 2  # S: render at 2x and downsample for smooth edges
MAX_H = 3600  # page height cap (about two phone screens); longer sessions paginate
GAP = 20
IP = 36  # inner padding of surfaces
PR_SHORT = {"weight": "Weight", "e1rm": "1RM", "volume": "Volume", "reps": "Reps"}
KIND_NAMES = {"warmup": "warm-up", "drop": "drop set", "failure": "to failure"}

THEMES = {
    "dark": {"bg": "#0C0D0F", "surface": "#16181B", "stripe": "#1C1F23", "text": "#F4F5F7", "muted": "#8C929B",
             "faint": "#2A2E34", "accent": "#3D8BFF", "accent_bg": "#16243A", "gold": "#F6B93B", "gold_bg": "#33280F",
             "W": "#F5A142", "W_bg": "#382613", "D": "#B69CFF", "D_bg": "#29223F", "F": "#FF6A5C", "F_bg": "#3A1B18",
             "up": "#3CCB6C", "down": "#FF6A5C", "fat": "#A8C8FF"},
    "light": {"bg": "#F2F3F5", "surface": "#FFFFFF", "stripe": "#F6F7F9", "text": "#0E1013", "muted": "#646C76",
              "faint": "#DADDE2", "accent": "#1C69F0", "accent_bg": "#E4EDFE", "gold": "#9A6300", "gold_bg": "#FCEFD2",
              "W": "#B25E00", "W_bg": "#FDEBD6", "D": "#6B45D8", "D_bg": "#EDE7FD", "F": "#C8321F", "F_bg": "#FCE3DF",
              "up": "#16904A", "down": "#C8321F", "fat": "#79A6F2"},
}
# "clear": a sticker to lay over a gym photo. The dark card as one rounded panel with transparent corners,
# so no text ever sits on the photo itself.
THEMES["clear"] = {**THEMES["dark"], "bg": (0, 0, 0, 0), "panel": THEMES["dark"]["bg"]}

# block heights, in px at 1x; the draw code below uses the same numbers
HEAD_H, CONT_H, FOOT_H, WEEK_H = 432, 150, 96, 214
EX_HEAD, ROW, EX_FOOT = 150, 58, 18
MU_HEAD, MU_ROW, MU_FOOT, RADAR_H = 92, 50, 22, 280
REC_HEAD, REC_ROW, REC_FOOT = 92, 54, 18
LIST_HEAD, LIST_ROW, LIST_FOOT = 92, 62, 18
STORY_H = 1920  # the story style is at least one phone screen tall
RADAR_AXES = ("Chest", "Shoulders", "Arms", "Core", "Legs", "Back")  # clockwise from the top

# "That's like lifting ..." for the session volume: the heaviest thing it clears (kg, approximate)
LIKE = [(150_000, "a blue whale"), (40_000, "a humpback whale"), (12_000, "a school bus"), (8_000, "a T. rex"),
        (5_000, "an elephant"), (2_500, "a pickup truck"), (1_400, "a car"), (500, "a grand piano"), (250, "a motorbike")]


def _when(summary) -> str:
    d = datetime.fromisoformat(summary["started_at"])
    return f"{d:%A}, {d:%b} {d.day} · {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


def _delta(week) -> str | None:
    c = week["change_pct"]
    if c is None:
        return None
    return f"{'+' if c >= 0 else '−'}{abs(c)}% vs last week to date"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _like(summary) -> str | None:
    kg = summary["volume"] * (LB if summary["unit"] == "lb" else 1)
    thing = next((t for w, t in LIKE if kg >= w), None)
    return f"That's like lifting {thing}" if thing else None


def _raw(value_kg: float, unit: str) -> float:
    return value_kg / LB if unit == "lb" else value_kg


def _conv(value_kg: float, unit: str) -> str:
    return fmt_num(_raw(value_kg, unit))


def _record(pr) -> tuple[str, str, str]:
    """(what, before, now) for one PR, in the unit the set was logged in."""
    u = pr["unit"]
    if pr["type"] == "reps":
        at = pr["set"].split(" x ")[0]
        return f"Most reps at {at}" if not at.endswith("reps") else "Most reps", str(pr["previous"]), f"{pr['value']} reps"
    if pr["type"] == "volume":  # whole numbers: a set's volume to 0.1 is noise
        return PR_LABELS["volume"], fmt_num(round(_raw(pr["previous_kg"], u))), f"{fmt_num(round(_raw(pr['value_kg'], u)))} {u}"
    return PR_LABELS[pr["type"]], _conv(pr["previous_kg"], u), f"{_conv(pr['value_kg'], u)} {u}"


def render_text(summary: dict) -> str:
    """Markdown card for chat surfaces that cannot show images: every exercise, every set."""
    s = summary
    lines = [f"**{s['title']}**" + (" (in progress)" if s["open"] else ""), _when(s),
             f"{s['duration']} · {fmt_num(round(s['volume']))} {s['unit']} · {_plural(s['sets'], 'set')} · "
             f"{_plural(len(s['prs']), 'PR')}"]
    if s["muscles"]:
        lines.append("Muscles: " + ", ".join(f"{m['group']} {m['pct']}%" for m in s["muscles"]))
    lines.append("")
    for e in s["exercises"]:
        head = f"**{e['name']}** · {e['muscle']} · {_plural(e['working_sets'], 'set')}"
        if e["best"]:
            head += f" · best {e['best']}"
        if e["prs"]:
            head += " · PR: " + ", ".join(PR_LABELS[p] for p in e["prs"])
        lines.append(head)
        for st in e["sets"]:
            t = f"  {st['label']}. {st['text']}"
            if st["rpe"]:
                t += f" @ RPE {fmt_num(st['rpe'])}"
            if st["kind"] in KIND_NAMES:
                t += f" ({KIND_NAMES[st['kind']]})"
            if st["prs"]:
                t += " 🏆 " + ", ".join(PR_LABELS[p] for p in st["prs"])
            lines.append(t)
    w = s["week"]
    tail = f"This week: {_plural(w['workouts'], 'workout')}, {fmt_num(round(w['volume']))} {w['unit']}"
    lines += ["", tail + (f" ({_delta(w)})" if _delta(w) else "")]
    return "\n".join(lines)


# ---- render model ---------------------------------------------------------------------------------

def _ex_h(n: int) -> int:
    return EX_HEAD + ROW * n + EX_FOOT


def _mu_h(s) -> int:
    return MU_HEAD + max(MU_ROW * len(s["muscles"]), RADAR_H) + MU_FOOT


def _rec_h(s) -> int:
    return REC_HEAD + REC_ROW * len(s["prs"]) + REC_FOOT


def _list_h(s) -> int:
    return LIST_HEAD + LIST_ROW * len(s["exercises"]) + LIST_FOOT


def layout(summary: dict, max_h: int = MAX_H, style: str = "full") -> list[list[dict]]:
    """Pages of blocks. Exercise blocks carry a set range [start, end); an exercise that does not fit
    the rest of a page continues on the next one, so no set is ever dropped.
    style "story" is one page with an exercise list (one line per exercise) instead of set tables."""
    s = summary
    if style == "story":
        return [[{"kind": "head"}] + ([{"kind": "muscles"}] if s["muscles"] else []) +
                [{"kind": "list"}, {"kind": "week"}, {"kind": "foot"}]]
    if style != "full":
        raise ValueError("style must be full or story")
    pages = [[{"kind": "head"}]]
    y = HEAD_H
    budget = max_h - FOOT_H - GAP  # every block is followed by GAP

    def new_page():
        nonlocal y
        pages.append([{"kind": "cont"}])
        y = CONT_H

    def place(block, h):
        nonlocal y
        if y + h > budget and len(pages[-1]) > 1:
            new_page()
        pages[-1].append(block)
        y += h + GAP

    if s["muscles"]:
        place({"kind": "muscles"}, _mu_h(s))
    if s["prs"]:
        place({"kind": "records"}, _rec_h(s))
    for i, e in enumerate(s["exercises"]):
        start, n = 0, len(e["sets"])
        while start < n:
            room = (budget - y - EX_HEAD - EX_FOOT) // ROW
            left = n - start
            # keep at least 3 rows together (or the whole exercise if shorter) unless the page is empty
            if room < min(3, left) and len(pages[-1]) > 1:
                new_page()
                continue
            take = max(1, min(left, room))
            pages[-1].append({"kind": "exercise", "index": i, "start": start, "end": start + take})
            y += _ex_h(take) + GAP
            start += take
    place({"kind": "week"}, WEEK_H)
    for p in pages:
        p.append({"kind": "foot"})
    return pages


def page_height(page: list[dict], summary: dict) -> int:
    h = 0
    for b in page:
        k = b["kind"]
        if k == "exercise":
            h += _ex_h(b["end"] - b["start"]) + GAP
        else:
            h += {"head": HEAD_H, "cont": CONT_H, "foot": FOOT_H, "week": WEEK_H + GAP,
                  "muscles": _mu_h(summary) + GAP, "records": _rec_h(summary) + GAP,
                  "list": _list_h(summary) + GAP}[k]
    return h


# ---- drawing --------------------------------------------------------------------------------------

class _Pen:
    def __init__(self, theme: str, height: int):
        if theme not in THEMES:
            raise ValueError(f"theme must be one of {', '.join(THEMES)}")
        self.c = THEMES[theme]
        self.img = Image.new("RGBA" if theme == "clear" else "RGB", (WIDTH * S, height * S), self.c["bg"])
        self.d = ImageDraw.Draw(self.img)
        self._fonts = {}
        if "panel" in self.c:
            self.rect(0, 0, WIDTH, height, "panel", 44)

    def col(self, c):
        return self.c.get(c, c)

    def font(self, size: int, weight: str = "regular"):
        k = (size, weight)
        if k not in self._fonts:
            file = {"regular": "Inter-Regular.ttf", "semibold": "Inter-SemiBold.ttf", "bold": "InterDisplay-Bold.ttf"}[weight]
            self._fonts[k] = ImageFont.truetype(str(FONTS / file), size * S)
        return self._fonts[k]

    def width(self, text, size, weight="regular") -> float:
        return self.font(size, weight).getlength(text) / S

    def text(self, x, y, text, size, color, weight="regular", anchor="ls"):
        self.d.text((x * S, y * S), text, fill=self.col(color), font=self.font(size, weight), anchor=anchor)
        return self.width(text, size, weight)

    def caps(self, x, y, text, size, color, track=1.2, anchor="l"):
        """Small caps label with letter spacing; anchor l or r."""
        w = sum(self.width(ch, size, "semibold") for ch in text) + track * (len(text) - 1)
        if anchor == "r":
            x -= w
        for ch in text:
            x += self.text(x, y, ch, size, color, "semibold") + track
        return w

    def rect(self, x0, y0, x1, y1, color, r=0, outline=None, width=0):
        self.d.rounded_rectangle((x0 * S, y0 * S, x1 * S, y1 * S), radius=r * S, fill=self.col(color) if color else None,
                                 outline=self.col(outline) if outline else None, width=round(width * S))

    def circle(self, cx, cy, r, color=None, outline=None, width=0):
        self.d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=self.col(color) if color else None,
                       outline=self.col(outline) if outline else None, width=round(width * S))

    def line(self, pts, color, width):
        self.d.line([(x * S, y * S) for x, y in pts], fill=self.col(color), width=round(width * S), joint="curve")

    def poly(self, pts, color):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=self.col(color))

    def fit(self, text, size, weight, max_w) -> str:
        if self.width(text, size, weight) <= max_w:
            return text
        while text and self.width(text + "…", size, weight) > max_w:
            text = text[:-1]
        return text.rstrip() + "…"

    def value(self, x, y, text, size, color="text"):
        """Big digits, smaller units: "1h 3m" draws 1 and 3 large, h and m small."""
        for part in re.findall(r"[\d,.]+|[^\d,.]+", text):
            big = part[0].isdigit()
            if not big:
                part = part.strip()
                x += 3
            x += self.text(x, y, part, size if big else round(size * 0.5), color if big else "muted", "bold" if big else "semibold")
            x += 0 if big else 12
        return x

    # icons, drawn in a size x size box whose top-left is (x, y)
    def icon(self, name, x, y, size, color):
        u = size / 24
        P = lambda a, b: (x + a * u, y + b * u)  # noqa: E731
        if name == "clock":
            self.circle(x + 12 * u, y + 12 * u, 9.5 * u, outline=color, width=2.2 * u)
            self.line([P(12, 7), P(12, 12.5), P(15.5, 14.5)], color, 2.2 * u)
        elif name == "weight":  # dumbbell: two tall plates each side and a bar
            self.rect(*P(1, 8), *P(4, 16), color, 1.2 * u)
            self.rect(*P(4.8, 4), *P(8.6, 20), color, 1.6 * u)
            self.rect(*P(15.4, 4), *P(19.2, 20), color, 1.6 * u)
            self.rect(*P(20, 8), *P(23, 16), color, 1.2 * u)
            self.rect(*P(8.6, 10.6), *P(15.4, 13.4), color)
        elif name == "sets":  # stacked rows
            for top in (4.5, 10.5, 16.5):
                self.rect(*P(4, top), *P(20, top + 3.4), color, 1.7 * u)
        elif name == "trophy":
            self.d.chord((P(5, -1)[0] * S, P(5, -1)[1] * S, P(19, 15)[0] * S, P(19, 15)[1] * S), 0, 180, fill=self.col(color))
            self.rect(*P(5, 3.5), *P(19, 7.2), color)
            for cx in (5, 19):
                self.circle(*P(cx, 8), 3.1 * u, outline=color, width=1.9 * u)
            self.rect(*P(10.8, 14), *P(13.2, 18.5), color)
            self.rect(*P(7.5, 18.5), *P(16.5, 21.5), color, 1 * u)
        elif name == "flame":
            self.poly([P(12, 1.5), P(15.5, 6.5), P(18.5, 10.5), P(19.5, 15), P(18, 19), P(15, 21.8), P(12, 22.5),
                       P(9, 21.8), P(6, 19), P(4.5, 15), P(5.5, 10.5), P(8.3, 13.5), P(9, 9), P(10.8, 5)], color)
        elif name == "check":
            self.line([P(6.5, 12.5), P(10.5, 16.5), P(17.5, 8.5)], color, 2.6 * u)


def _head(p: _Pen, s, y):
    p.text(PAD, y + 72, f"{_when(s)} · {_ordinal(s['number'])} workout", 26, "muted", "semibold")
    title = p.fit(s["title"], 68, "bold", WIDTH - 2 * PAD - (190 if s["open"] else 0))
    p.text(PAD, y + 150, title, 68, "text", "bold")
    if s["open"]:
        w = p.width("In progress", 22, "semibold") + 32
        p.rect(WIDTH - PAD - w, y + 114, WIDTH - PAD, y + 154, "accent_bg", 20)
        p.text(WIDTH - PAD - w / 2, y + 134, "In progress", 22, "accent", "semibold", anchor="mm")
    top = y + 188
    p.rect(PAD, top, WIDTH - PAD, top + 160, "surface", 28)
    cells = [("clock", "Duration", s["duration"], "text"),
             ("weight", "Volume", f"{fmt_num(round(s['volume']))} {s['unit']}", "text"),
             ("sets", "Sets", str(s["sets"]), "text"),
             ("trophy", "Records", str(len(s["prs"])), "gold" if s["prs"] else "text")]
    cw = (WIDTH - 2 * PAD - 2 * IP) / 4
    for i, (icon, label, val, color) in enumerate(cells):
        x = PAD + IP + i * cw
        if i:
            p.rect(x - 18, top + 36, x - 16, top + 124, "faint")
        p.icon(icon, x, top + 38, 24, "gold" if icon == "trophy" and s["prs"] else "muted")
        p.text(x + 34, top + 58, label, 22, "muted", "semibold")
        p.value(x, top + 118, val, 46, color)
    like = _like(s)
    if like:
        p.text(WIDTH / 2, top + 212, like, 24, "muted", "semibold", anchor="ms")


def _cont(p: _Pen, s, y, page, pages):
    p.text(PAD, y + 66, _when(s), 22, "muted", "semibold")
    p.text(PAD, y + 120, p.fit(s["title"], 46, "bold", WIDTH - 2 * PAD - 180), 46, "text", "bold")
    p.caps(WIDTH - PAD, y + 116, f"PAGE {page} OF {pages}", 20, "muted", anchor="r")


def _radar(p: _Pen, s, cx, cy, r):
    share = dict.fromkeys(RADAR_AXES, 0)
    for m in s["muscles"]:
        if m["group"] in MACRO:
            share[MACRO[m["group"]]] += m["sets"]
    peak = max(share.values()) or 1
    ang = [math.radians(-90 + 60 * i) for i in range(6)]
    pt = lambda k, rr: (cx + rr * math.cos(ang[k]), cy + rr * math.sin(ang[k]))  # noqa: E731
    for ring in (1, 2 / 3, 1 / 3):
        p.line([pt(k % 6, r * ring) for k in range(7)], "faint", 2)
    for k in range(6):
        p.line([(cx, cy), pt(k, r)], "faint", 2)
    shape = [pt(k, r * max(0.06, share[a] / peak)) for k, a in enumerate(RADAR_AXES)]
    p.poly(shape, "accent_bg")
    p.line(shape + [shape[0]], "accent", 3)
    for k, a in enumerate(RADAR_AXES):
        if share[a]:
            p.circle(*shape[k], 5, "accent")
        lx, ly = pt(k, r + 24)
        anchor = "ms" if k == 0 else "mt" if k == 3 else "lm" if k < 3 else "rm"
        p.text(lx, ly + (-2 if k == 0 else 2 if k == 3 else 0), a, 19, "text" if share[a] else "muted", "semibold",
               anchor=anchor)


def _muscles(p: _Pen, s, y):
    rows = s["muscles"]
    h = _mu_h(s)
    p.rect(PAD, y, WIDTH - PAD, y + h, "surface", 28)
    p.text(PAD + IP, y + 56, "Muscle split", 30, "text", "semibold")
    p.text(WIDTH - PAD - IP, y + 56, "share of sets", 22, "muted", anchor="rs")
    body = y + MU_HEAD
    span = max(MU_ROW * len(rows), RADAR_H)
    _radar(p, s, PAD + IP + 150, body + span / 2 - 2, 88)
    lx = PAD + IP + 400
    p.rect(lx - 32, body + 8, lx - 30, body + span - 8, "faint")
    x0, x1 = lx + 150, WIDTH - PAD - IP - 76
    top = max(r["pct"] for r in rows)
    cy = body + (span - MU_ROW * len(rows)) / 2
    for r in rows:
        p.text(lx, cy + 20, r["group"], 22, "text", "semibold")
        p.rect(x0, cy + 4, x1, cy + 20, "faint", 8)
        p.rect(x0, cy + 4, x0 + max(16, (x1 - x0) * r["pct"] / top), cy + 20, "accent", 8)
        p.text(WIDTH - PAD - IP, cy + 21, f"{r['pct']}%", 22, "text", "semibold", anchor="rs")
        cy += MU_ROW


def _records(p: _Pen, s, y):
    h = _rec_h(s)
    x0, x1 = PAD, WIDTH - PAD
    p.rect(x0, y, x1, y + h, "surface", 28)
    p.icon("trophy", x0 + IP, y + 32, 28, "gold")
    p.text(x0 + IP + 40, y + 56, "Records", 30, "text", "semibold")
    p.text(x1 - IP, y + 56, "previous best → today", 22, "muted", anchor="rs")
    cy = y + REC_HEAD
    group, prev = -1, None
    name_w = max(p.width(pr["exercise"], 24, "semibold") for pr in s["prs"])
    col = x0 + IP + min(name_w + 20, 420)  # where the record type starts, shared by all rows
    for pr in s["prs"]:
        mid = cy + REC_ROW / 2
        first = pr["exercise_id"] != prev
        if first:
            group, prev = group + 1, pr["exercise_id"]
            n = sum(q["exercise_id"] == prev for q in s["prs"])
            if group % 2 == 0:
                p.rect(x0 + 12, cy + 3, x1 - 12, cy + REC_ROW * n - 3, "stripe", 14)
            p.text(x0 + IP, mid + 1, p.fit(pr["exercise"], 24, "semibold", col - x0 - IP - 16), 24, "text", "semibold",
                   anchor="lm")
        what, before, now = _record(pr)
        nw = p.width(now, 24, "semibold")
        bw = p.width(f"{before}  →  ", 22)
        p.text(col, mid + 1, p.fit(what, 22, "regular", x1 - IP - nw - bw - 16 - col), 22, "muted", anchor="lm")
        p.text(x1 - IP, mid + 1, now, 24, "gold", "semibold", anchor="rm")
        p.text(x1 - IP - nw, mid + 1, f"{before}  →  ", 22, "muted", anchor="rm")
        cy += REC_ROW


def _badge(p: _Pen, x, cy, st):
    if st["kind"] != "normal":
        k = st["label"]  # W, D or F
        p.rect(x, cy - 18, x + 44, cy + 18, f"{k}_bg", 10)
        p.text(x + 22, cy, k, 22, k, "bold", anchor="mm")
    else:
        p.text(x + 22, cy, st["label"], 24, "muted", "semibold", anchor="mm")


def _pr_pill(p: _Pen, xr, cy, t):
    label = PR_SHORT[t]
    w = 16 + 22 + 8 + p.width(label, 20, "semibold") + 16
    p.rect(xr - w, cy - 18, xr, cy + 18, "gold_bg", 18)
    p.icon("trophy", xr - w + 14, cy - 11, 22, "gold")
    p.text(xr - 16, cy + 1, label, 20, "gold", "semibold", anchor="rm")
    return w


def _exercise(p: _Pen, s, y, b):
    e = s["exercises"][b["index"]]
    sets = e["sets"][b["start"]:b["end"]]
    x0, x1 = PAD, WIDTH - PAD
    h = _ex_h(len(sets))
    p.rect(x0, y, x1, y + h, "surface", 28)
    cont = b["start"] > 0
    right = f"{_plural(e['working_sets'], 'set')}"
    rw = p.width(right, 22, "semibold")
    name = e["name"] + (" (cont.)" if cont else "")
    p.text(x0 + IP, y + 56, p.fit(name, 34, "semibold", x1 - x0 - 2 * IP - rw - 24), 34, "text", "semibold")
    p.text(x1 - IP, y + 56, right, 22, "muted", "semibold", anchor="rs")
    # muscle chip, then volume and best set
    cx = x0 + IP
    chip = e["muscle"]
    cw = p.width(chip, 20, "semibold") + 24
    p.rect(cx, y + 74, cx + cw, y + 104, "accent_bg", 15)
    p.text(cx + cw / 2, y + 89, chip, 20, "accent", "semibold", anchor="mm")
    info = []
    if e["volume"]:
        info.append(f"{fmt_num(round(e['volume']))} {s['unit']}")
    if e["best"]:
        info.append(f"best {e['best'].replace(' x ', ' × ')}")
    if info:
        p.text(cx + cw + 14, y + 97, "  ·  ".join(info), 22, "muted")
    # table: SET | WEIGHT | REPS | RPE | records
    bx = x0 + IP - 4
    wr = bx + 44 + 150  # right edge of the weight number
    ux = wr + 8        # unit
    rx = wr + 108      # reps
    px = rx + 110      # rpe
    hy = y + EX_HEAD - 14
    p.caps(bx + 22 - p.width("SET", 18, "semibold") / 2 - 1, hy, "SET", 18, "muted")
    p.caps(wr + 36, hy, "WEIGHT", 18, "muted", anchor="r")
    p.caps(rx, hy, "REPS", 18, "muted")
    if any(st["rpe"] for st in e["sets"]):
        p.caps(px, hy, "RPE", 18, "muted")
    cy = y + EX_HEAD
    for j, st in enumerate(sets):
        mid = cy + ROW / 2
        if j % 2 == 0:
            p.rect(x0 + 12, cy + 3, x1 - 12, cy + ROW - 3, "stripe", 14)
        _badge(p, bx, mid, st)
        dim = "muted" if st["kind"] == "warmup" else "text"
        if st["weight"]:
            p.text(wr, mid + 1, fmt_num(st["weight"]), 30, dim, "semibold", anchor="rm")
            p.text(ux, mid + 1, st["unit"], 22, "muted", "semibold", anchor="lm")
        else:
            p.text(wr, mid + 1, "BW", 26, "muted", "semibold", anchor="rm")
        p.text(rx - 18, mid + 1, "×", 24, "muted", anchor="mm")
        p.text(rx, mid + 1, str(st["reps"]), 30, dim, "semibold", anchor="lm")
        if st["rpe"]:
            p.text(px, mid + 1, fmt_num(st["rpe"]), 26, "muted", "semibold", anchor="lm")
        xr = x1 - IP + 8
        for t in reversed(st["prs"]):
            xr -= _pr_pill(p, xr, mid, t) + 8
        cy += ROW


def _list(p: _Pen, s, y):
    """One line per exercise: sets, name, best set, and a trophy count when it set records."""
    x0, x1 = PAD, WIDTH - PAD
    p.rect(x0, y, x1, y + _list_h(s), "surface", 28)
    p.text(x0 + IP, y + 56, "Workout", 30, "text", "semibold")
    p.text(x1 - IP, y + 56, _plural(len(s["exercises"]), "exercise"), 22, "muted", anchor="rs")
    cy = y + LIST_HEAD
    for j, e in enumerate(s["exercises"]):
        mid = cy + LIST_ROW / 2
        if j % 2 == 0:
            p.rect(x0 + 12, cy + 3, x1 - 12, cy + LIST_ROW - 3, "stripe", 14)
        n = e["working_sets"]
        p.text(x0 + IP + 30, mid + 1, str(n), 28, "text", "bold", anchor="rm")
        p.text(x0 + IP + 38, mid + 1, "sets" if n != 1 else "set", 20, "muted", "semibold", anchor="lm")
        xr = x1 - IP
        if e["prs"]:
            label = str(len(e["prs"]))
            w = 14 + 22 + 6 + p.width(label, 20, "semibold") + 14
            p.rect(xr - w, mid - 18, xr, mid + 18, "gold_bg", 18)
            p.icon("trophy", xr - w + 12, mid - 11, 22, "gold")
            p.text(xr - 14, mid + 1, label, 20, "gold", "semibold", anchor="rm")
            xr -= w + 14
        best = e["best"].replace(" x ", " × ") if e["best"] else ""
        bw = p.width(best, 22)
        p.text(xr, mid + 1, best, 22, "muted", anchor="rm")
        nx = x0 + IP + 112
        p.text(nx, mid + 1, p.fit(e["name"], 26, "semibold", xr - bw - 24 - nx), 26, "text", "semibold", anchor="lm")
        cy += LIST_ROW


def _week(p: _Pen, s, y):
    w = s["week"]
    x0, x1 = PAD, WIDTH - PAD
    p.rect(x0, y, x1, y + WEEK_H, "surface", 28)
    p.text(x0 + IP, y + 56, "This week", 30, "text", "semibold")
    delta = _delta(w)
    if delta:
        up = w["change_pct"] >= 0
        p.text(x1 - IP, y + 56, ("▲ " if up else "▼ ") + delta, 22, "up" if up else "down", "semibold", anchor="rs")
    # day strip, Monday first
    r, gap = 24, 14
    cx = x0 + IP + r
    for i, (letter, n) in enumerate(zip("MTWTFSS", w["days"])):
        cy = y + 118
        if n:
            p.circle(cx, cy, r, "accent")
            p.icon("check", cx - 15, cy - 15, 30, "#FFFFFF")
        else:
            p.circle(cx, cy, r, "faint" if i < w["today"] else None, outline=None if i < w["today"] else "faint",
                     width=0 if i < w["today"] else 2.5)
        if i == w["today"]:
            p.circle(cx, cy, r + 6, outline="accent", width=2.5)
        p.text(cx, y + 176, letter, 20, "text" if i == w["today"] else "muted", "semibold", anchor="ms")
        cx += 2 * r + gap
    # volume per week for the last 8 weeks, this week last and in the accent
    bars = w["bars"]
    peak = max(bars) or 1
    bw, bg, bh = 12, 7, 64
    bx = cx - r + 44
    base = y + 146
    for i, v in enumerate(bars):
        hh = max(5, v / peak * bh)
        p.rect(bx, base - hh, bx + bw, base, "accent" if i == len(bars) - 1 else "faint", 4)
        bx += bw + bg
    p.text(cx - r + 44 + (len(bars) * (bw + bg) - bg) / 2, y + 176, f"{len(bars)} weeks", 20, "muted", "semibold",
           anchor="ms")
    # totals, right-aligned
    xr = x1 - IP
    vol = f"{fmt_num(round(w['volume']))}"
    unit_w = p.width(w["unit"], 22, "semibold")
    p.text(xr, y + 136, w["unit"], 22, "muted", "semibold", anchor="rs")
    p.text(xr - unit_w - 6, y + 136, vol, 44, "text", "bold", anchor="rs")
    p.text(xr, y + 176, f"{_plural(w['workouts'], 'workout')} · volume", 22, "muted", anchor="rs")


def _foot(p: _Pen, s, y, page, pages, story=False):
    fy = y + 52
    p.circle(PAD + 11, fy - 8, 11, "accent")
    p.icon("weight", PAD + 3, fy - 16, 16, "#FFFFFF")
    p.text(PAD + 32, fy, APP, 22, "muted", "semibold")
    right = "" if story else _plural(len(s["exercises"]), "exercise")
    if pages > 1:
        right = f"{page} of {pages}  ·  " + right
    p.text(WIDTH - PAD, fy, right, 22, "muted", anchor="rs")


def render_pages(summary: dict, theme: str = "dark", max_h: int = MAX_H, style: str = "full") -> list[Image.Image]:
    s = summary
    pages = layout(s, max_h, style)
    out = []
    for n, page in enumerate(pages, 1):
        h = page_height(page, s)
        full_h = max(h, STORY_H) if style == "story" else h
        p = _Pen(theme, full_h)
        y = (full_h - h) // 2  # a short story sits centred on its screen
        for b in page:
            k = b["kind"]
            if k == "head":
                _head(p, s, y)
                y += HEAD_H
            elif k == "cont":
                _cont(p, s, y, n, len(pages))
                y += CONT_H
            elif k == "muscles":
                _muscles(p, s, y)
                y += _mu_h(s) + GAP
            elif k == "records":
                _records(p, s, y)
                y += _rec_h(s) + GAP
            elif k == "exercise":
                _exercise(p, s, y, b)
                y += _ex_h(b["end"] - b["start"]) + GAP
            elif k == "week":
                _week(p, s, y)
                y += WEEK_H + GAP
            elif k == "list":
                _list(p, s, y)
                y += _list_h(s) + GAP
            elif k == "foot":
                _foot(p, s, full_h - FOOT_H - GAP, n, len(pages), style == "story")
        out.append(p.img.resize((WIDTH, full_h), Image.LANCZOS))
    return out


def render_png(summary: dict, path: str | Path, theme: str = "dark", max_h: int = MAX_H, style: str = "full") -> list[Path]:
    """Draw the card and save it; a long session becomes path, path-2, path-3... Returns every page's path.
    style "full" has every set; "story" is one 1080x1920 (or taller) image with one line per exercise."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for n, img in enumerate(render_pages(summary, theme, max_h, style), 1):
        dest = path if n == 1 else path.with_name(f"{path.stem}-{n}{path.suffix}")
        img.save(dest, optimize=True)
        out.append(dest)
    return out

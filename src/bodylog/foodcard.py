"""Food day card: a markdown fallback and a phone-width PNG in the workout card's visual language.

style "full" lists every item under its meal; "story" is one 1080x1920 screen with one line per meal.
Workouts logged the same day get a Training block, so the card doubles as a combined day card.
Colours: protein blue, carbs yellow, fat light blue, each always labelled, so no macro is told by hue alone."""
from datetime import date
from pathlib import Path

from PIL import Image

from . import APP
from .card import FOOT_H, GAP, IP, PAD, STORY_H, WIDTH, _Pen, _plural
from .food import COUNTED, fmt_item
from .stats import fmt_num

MACRO_COL = {"protein": "accent", "carbs": "gold", "fat": "fat"}
MACRO_NAME = {"protein": "Protein", "carbs": "Carbs", "fat": "Fat"}
HEAD_H, ENERGY_HEAD, BAR_H, MACRO_ROW, ENERGY_FOOT = 432, 92, 132, 52, 26
MEAL_HEAD, ITEM_ROW, MEAL_FOOT = 96, 60, 18
LIST_HEAD, LIST_ROW, LIST_FOOT = 92, 62, 18
TRAIN_HEAD, TRAIN_ROW, TRAIN_FOOT = 92, 62, 18
WEEK_H = 214


def _date(d) -> str:
    d = date.fromisoformat(d["date"])
    return f"{d:%A}, {d:%b} {d.day}"


def _g(x) -> str:
    return fmt_num(round(x or 0))


def render_text(d: dict) -> str:
    """Markdown day card for chat surfaces that cannot show images: every item, flagged ones marked."""
    t, goals = d["totals"], d["goals"]
    head = f"{_g(t['kcal'])} kcal · P {_g(t['protein'])} g · C {_g(t['carbs'])} g · F {_g(t['fat'])} g"
    lines = [f"**{_date(d)}**", head]
    if goals:
        left = d["remaining"]
        lines.append("Goals: " + ", ".join(f"{k} {_g(abs(left[k]))} {'kcal' if k == 'kcal' else 'g'} "
                                            f"{'left' if left[k] >= 0 else 'over'}" for k in goals))
    for m in d["meals"]:
        lines += ["", f"**{m['meal'].capitalize()}** · {_g(m['kcal'])} kcal"]
        lines += [f"  - {fmt_item(r)}" for r in m["items"]]
    for w in d["workouts"]:
        lines += ["", f"**Training:** {w['title']} · {w['duration']} · {fmt_num(round(w['volume']))} {w['unit']} · "
                      f"{_plural(w['sets'], 'set')}" + (f" · {_plural(w['prs'], 'PR')}" if w["prs"] else "")]
    s = d["streaks"]
    lines += ["", f"Logging streak: {_plural(s['logging_days'], 'day')} (best {s['logging_best']})"
                  + (f" · training {_plural(s['training_weeks'], 'week')} in a row" if s["training_weeks"] else "")]
    if d["flagged"]:
        lines.append(f"{_plural(len(d['flagged']), 'item')} not counted: " + ", ".join(r["name"] for r in d["flagged"]))
    return "\n".join(lines)


# ---- layout ---------------------------------------------------------------------------------------

def _energy_h(d) -> int:
    return ENERGY_HEAD + BAR_H + MACRO_ROW * 3 + ENERGY_FOOT


def _meal_h(m) -> int:
    return MEAL_HEAD + ITEM_ROW * len(m["items"]) + MEAL_FOOT


def blocks(d: dict, style: str = "full") -> list[tuple[str, object, int]]:
    """(kind, data, height) top to bottom, footer excluded."""
    if style not in ("full", "story"):
        raise ValueError("style must be full or story")
    out = [("head", None, HEAD_H), ("energy", None, _energy_h(d) + GAP)]
    if style == "full":
        out += [("meal", m, _meal_h(m) + GAP) for m in d["meals"]]
    elif d["meals"]:
        out.append(("list", None, LIST_HEAD + LIST_ROW * len(d["meals"]) + LIST_FOOT + GAP))
    if d["workouts"]:
        out.append(("training", None, TRAIN_HEAD + TRAIN_ROW * len(d["workouts"]) + TRAIN_FOOT + GAP))
    out.append(("week", None, WEEK_H + GAP))
    return out


# ---- drawing --------------------------------------------------------------------------------------

def _head(p: _Pen, d, y):
    s = d["streaks"]
    sub = [_plural(d["items"], "item")]
    if s["logging_days"] > 1:
        sub.append(f"{s['logging_days']}-day streak")
    p.text(PAD, y + 72, "Food log · " + " · ".join(sub), 26, "muted", "semibold")
    p.text(PAD, y + 150, p.fit(_date(d), 68, "bold", WIDTH - 2 * PAD), 68, "text", "bold")
    top = y + 188
    p.rect(PAD, top, WIDTH - PAD, top + 160, "surface", 28)
    t = d["totals"]
    cells = [("Calories", f"{_g(t['kcal'])} kcal", None)] + [(MACRO_NAME[k], f"{_g(t[k])} g", MACRO_COL[k])
                                                          for k in ("protein", "carbs", "fat")]
    cw = (WIDTH - 2 * PAD - 2 * IP) / 4
    for i, (label, val, col) in enumerate(cells):
        x = PAD + IP + i * cw
        if i:
            p.rect(x - 18, top + 36, x - 16, top + 124, "faint")
        if col:
            p.circle(x + 9, top + 50, 8, col)
        else:
            p.icon("flame", x - 1, top + 38, 24, "gold")
        p.text(x + 34, top + 58, label, 22, "muted", "semibold")
        p.value(x, top + 118, val, 46, "text")
    goal = d["goals"].get("kcal")
    if goal:
        left = d["remaining"]["kcal"]
        line = f"{_g(abs(left))} kcal {'left' if left >= 0 else 'over'} of a {_g(goal)} kcal goal"
    else:  # the Macros block below already shows the split
        line = f"{_plural(len(d['flagged']), 'item')} not counted yet" if d["flagged"] else ""
    if line:
        p.text(WIDTH / 2, top + 212, line, 24, "muted", "semibold", anchor="ms")


def _bar(p: _Pen, x0, x1, cy, h, parts):
    """Track with coloured segments: parts = [(fraction, colour)], drawn left to right."""
    p.rect(x0, cy - h / 2, x1, cy + h / 2, "faint", h / 2)
    x = x0
    for frac, col in parts:
        w = (x1 - x0) * frac
        if w >= 1:
            p.rect(x, cy - h / 2, x + w, cy + h / 2, col, min(h / 2, w / 2))
            x += w


def _energy(p: _Pen, d, y):
    x0, x1 = PAD, WIDTH - PAD
    h = _energy_h(d)
    p.rect(x0, y, x1, y + h, "surface", 28)
    p.text(x0 + IP, y + 56, "Macros", 30, "text", "semibold")
    t, goals = d["totals"], d["goals"]
    flagged = len(d["flagged"])
    note = f"{_plural(flagged, 'item')} not counted" if flagged else "share of calories"
    p.text(x1 - IP, y + 56, note, 22, "muted", anchor="rs")
    # calories: progress against the goal, or the energy split when there is none
    by = y + ENERGY_HEAD + 34
    energy = {"protein": t["protein"] * 4, "carbs": t["carbs"] * 4, "fat": t["fat"] * 9}
    total = sum(energy.values())
    if goals.get("kcal"):
        frac = t["kcal"] / goals["kcal"]
        scale = max(1.0, frac)  # over the goal: the whole bar is today, a tick marks the goal
        parts = [(min(t["kcal"], goals["kcal"]) / goals["kcal"] / scale, "accent")]
        if frac > 1:
            parts.append(((t["kcal"] - goals["kcal"]) / goals["kcal"] / scale, "gold"))
        _bar(p, x0 + IP, x1 - IP, by, 28, parts)
        if frac > 1:
            gx = x0 + IP + (x1 - x0 - 2 * IP) / scale
            p.rect(gx - 2, by - 22, gx + 2, by + 22, "text", 2)
        p.text(x0 + IP, by + 60, f"{_g(t['kcal'])} of {_g(goals['kcal'])} kcal", 24, "text", "semibold")
        left = d["remaining"]["kcal"]
        p.text(x1 - IP, by + 60, f"{_g(abs(left))} {'left' if left >= 0 else 'over'}", 24,
               "muted" if left >= 0 else "gold", "semibold", anchor="rs")
    else:
        _bar(p, x0 + IP, x1 - IP, by, 28, [(energy[k] / total if total else 0, MACRO_COL[k]) for k in energy])
        x = x0 + IP
        for k in energy:
            p.circle(x + 8, by + 52, 8, MACRO_COL[k])
            x += 24 + p.text(x + 24, by + 60, f"{MACRO_NAME[k]} {d['split'][k]}%", 22, "text", "semibold") + 28
        p.text(x1 - IP, by + 60, f"{_g(t['kcal'])} kcal", 24, "muted", "semibold", anchor="rs")
    # one row per macro: grams, against its goal when there is one
    cy = y + ENERGY_HEAD + BAR_H
    lx, bx0, bx1 = x0 + IP, x0 + IP + 170, x1 - IP - 190
    peak = max(t[k] for k in energy) or 1
    for k in energy:
        mid = cy + MACRO_ROW / 2
        p.circle(lx + 8, mid, 8, MACRO_COL[k])
        p.text(lx + 26, mid + 1, MACRO_NAME[k], 24, "text", "semibold", anchor="lm")
        goal = goals.get(k)
        frac = min(1.0, t[k] / goal) if goal else t[k] / peak
        _bar(p, bx0, bx1, mid, 14, [(frac, MACRO_COL[k])])
        right = f"{_g(t[k])} / {_g(goal)} g" if goal else f"{_g(t[k])} g"
        p.text(x1 - IP, mid + 1, right, 24, "text", "semibold", anchor="rm")
        cy += MACRO_ROW


def _amount(r) -> str:
    a = fmt_num(r["amount"]) if r["amount"] is not None else ""
    if r["unit"]:
        return f"{a} {r['unit']}"
    return f"{a}×" if a else ""


def _meal(p: _Pen, d, y, m):
    x0, x1 = PAD, WIDTH - PAD
    p.rect(x0, y, x1, y + _meal_h(m), "surface", 28)
    p.text(x0 + IP, y + 56, m["meal"].capitalize(), 34, "text", "semibold")
    kw = p.width("kcal", 22, "semibold")
    p.text(x1 - IP, y + 56, "kcal", 22, "muted", "semibold", anchor="rs")
    p.text(x1 - IP - kw - 8, y + 56, _g(m["kcal"]), 34, "text", "bold", anchor="rs")
    cy = y + MEAL_HEAD
    for j, r in enumerate(m["items"]):
        mid = cy + ITEM_ROW / 2
        if j % 2 == 0:
            p.rect(x0 + 12, cy + 3, x1 - 12, cy + ITEM_ROW - 3, "stripe", 14)
        ok = r["status"] in COUNTED
        amt = _amount(r)
        aw = p.text(x0 + IP, mid + 1, amt, 22, "muted", "semibold", anchor="lm") if amt else 0
        nx = x0 + IP + max(aw + 14, 96)
        xr = x1 - IP
        if ok:
            kcal = _g(r["kcal"])
            p.text(xr, mid + 1, kcal, 28, "text", "bold", anchor="rm")
            xr -= p.width(kcal, 28, "bold") + 20
            macro = f"P {_g(r['protein'])}  C {_g(r['carbs'])}  F {_g(r['fat'])}"
            p.text(xr, mid + 1, macro, 20, "muted", anchor="rm")
            xr -= p.width(macro, 20) + 20
        else:
            label = "needs amount" if r["status"] == "needs_amount" else "not found"
            w = p.width(label, 20, "semibold") + 28 + 30
            p.rect(xr - w, mid - 18, xr, mid + 18, None, 18, outline="muted", width=2)
            p.circle(xr - w + 24, mid, 10, "muted")
            p.text(xr - w + 24, mid + 1, "?", 16, "surface", "bold", anchor="mm")
            p.text(xr - 14, mid + 1, label, 20, "muted", "semibold", anchor="rm")
            xr -= w + 16
        name = r["name"][:1].upper() + r["name"][1:]
        p.text(nx, mid + 1, p.fit(name, 26, "semibold", xr - nx), 26, "text" if ok else "muted", "semibold",
               anchor="lm")
        cy += ITEM_ROW


def _list(p: _Pen, d, y):
    x0, x1 = PAD, WIDTH - PAD
    h = LIST_HEAD + LIST_ROW * len(d["meals"]) + LIST_FOOT
    p.rect(x0, y, x1, y + h, "surface", 28)
    p.text(x0 + IP, y + 56, "Meals", 30, "text", "semibold")
    p.text(x1 - IP, y + 56, _plural(d["items"], "item"), 22, "muted", anchor="rs")
    cy = y + LIST_HEAD
    for j, m in enumerate(d["meals"]):
        mid = cy + LIST_ROW / 2
        if j % 2 == 0:
            p.rect(x0 + 12, cy + 3, x1 - 12, cy + LIST_ROW - 3, "stripe", 14)
        p.text(x0 + IP, mid + 1, m["meal"].capitalize(), 26, "text", "semibold", anchor="lm")
        kw = p.width("kcal", 20, "semibold")
        p.text(x1 - IP, mid + 1, "kcal", 20, "muted", "semibold", anchor="rm")
        p.text(x1 - IP - kw - 6, mid + 1, _g(m["kcal"]), 28, "text", "bold", anchor="rm")
        names = ", ".join(r["name"] for r in m["items"])
        nx = x0 + IP + 190
        p.text(nx, mid + 1, p.fit(names, 22, "regular", x1 - IP - kw - 110 - nx), 22, "muted", anchor="lm")
        cy += LIST_ROW


def _training(p: _Pen, d, y):
    x0, x1 = PAD, WIDTH - PAD
    ws = d["workouts"]
    p.rect(x0, y, x1, y + TRAIN_HEAD + TRAIN_ROW * len(ws) + TRAIN_FOOT, "surface", 28)
    p.icon("weight", x0 + IP, y + 34, 26, "accent")
    p.text(x0 + IP + 40, y + 56, "Training", 30, "text", "semibold")
    p.text(x1 - IP, y + 56, _plural(len(ws), "workout"), 22, "muted", anchor="rs")
    cy = y + TRAIN_HEAD
    for j, w in enumerate(ws):
        mid = cy + TRAIN_ROW / 2
        if j % 2 == 0:
            p.rect(x0 + 12, cy + 3, x1 - 12, cy + TRAIN_ROW - 3, "stripe", 14)
        xr = x1 - IP
        if w["prs"]:
            label = str(w["prs"])
            pw = 14 + 22 + 6 + p.width(label, 20, "semibold") + 14
            p.rect(xr - pw, mid - 18, xr, mid + 18, "gold_bg", 18)
            p.icon("trophy", xr - pw + 12, mid - 11, 22, "gold")
            p.text(xr - 14, mid + 1, label, 20, "gold", "semibold", anchor="rm")
            xr -= pw + 14
        info = f"{w['duration']} · {fmt_num(round(w['volume']))} {w['unit']} · {_plural(w['sets'], 'set')}"
        p.text(xr, mid + 1, info, 22, "muted", anchor="rm")
        xr -= p.width(info, 22) + 20
        p.text(x0 + IP, mid + 1, p.fit(w["title"], 26, "semibold", xr - x0 - IP), 26, "text", "semibold", anchor="lm")
        cy += TRAIN_ROW


def _week(p: _Pen, d, y):
    x0, x1 = PAD, WIDTH - PAD
    s, w = d["streaks"], d["week"]
    p.rect(x0, y, x1, y + WEEK_H, "surface", 28)
    p.text(x0 + IP, y + 56, "This week", 30, "text", "semibold")
    if s["training_weeks"]:
        p.text(x1 - IP, y + 56, f"training {_plural(s['training_weeks'], 'week')} in a row", 22, "muted", anchor="rs")
    r, gap = 24, 14
    cx = x0 + IP + r
    for i, (letter, n) in enumerate(zip("MTWTFSS", w["days"])):
        cy = y + 118
        if n:
            p.circle(cx, cy, r, "accent")
            p.icon("check", cx - 15, cy - 15, 30, "#FFFFFF")
        else:
            past = i < w["today"]
            p.circle(cx, cy, r, "faint" if past else None, outline=None if past else "faint", width=0 if past else 2.5)
        if i == w["today"]:
            p.circle(cx, cy, r + 6, outline="accent", width=2.5)
        p.text(cx, y + 176, letter, 20, "text" if i == w["today"] else "muted", "semibold", anchor="ms")
        cx += 2 * r + gap
    xr = x1 - IP
    days = str(s["logging_days"])
    unit = "day streak"
    uw = p.width(unit, 22, "semibold")
    p.text(xr, y + 136, unit, 22, "muted", "semibold", anchor="rs")
    p.text(xr - uw - 8, y + 136, days, 44, "gold" if s["logging_days"] > 1 else "text", "bold", anchor="rs")
    fw = p.width(days, 44, "bold")
    p.icon("flame", xr - uw - 8 - fw - 34, y + 104, 26, "gold" if s["logging_days"] > 1 else "muted")
    p.text(xr, y + 176, f"logged in a row · best {s['logging_best']}", 22, "muted", anchor="rs")


def _foot(p: _Pen, d, y):
    fy = y + 52
    p.circle(PAD + 11, fy - 8, 11, "accent")
    p.icon("weight", PAD + 3, fy - 16, 16, "#FFFFFF")
    p.text(PAD + 32, fy, APP, 22, "muted", "semibold")
    p.text(WIDTH - PAD, fy, "USDA FoodData Central · Open Food Facts", 20, "muted", anchor="rs")


DRAW = {"head": _head, "energy": _energy, "list": _list, "training": _training, "week": _week}


def render_image(d: dict, theme: str = "dark", style: str = "full") -> Image.Image:
    bs = blocks(d, style)
    h = sum(b[2] for b in bs) + FOOT_H + GAP
    full_h = max(h, STORY_H) if style == "story" else h
    p = _Pen(theme, full_h)
    y = (full_h - h) // 2  # a short story sits centred on its screen
    for kind, data, bh in bs:
        if kind == "meal":
            _meal(p, d, y, data)
        else:
            DRAW[kind](p, d, y)
        y += bh
    _foot(p, d, full_h - FOOT_H - GAP)
    return p.img.resize((WIDTH, full_h), Image.LANCZOS)


def render_png(d: dict, path: str | Path, theme: str = "dark", style: str = "full") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    render_image(d, theme, style).save(path, optimize=True)
    return path

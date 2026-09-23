"""Food: read a meal from plain text, match each item to real food data, store it, total the day.

Matching order for a name: the bundled USDA table (works offline), then foods matched before (cached in
SQLite), then a USDA FoodData Central search, then an Open Food Facts search. A barcode goes straight to
Open Food Facts. A search result is only taken when its name holds every word that was said; otherwise
the item is stored as `unknown` with the closest candidates, so the agent can ask. An item whose amount
cannot be turned into grams is stored as `needs_amount`. Neither counts toward totals.
"""
import json
import re
from datetime import date, datetime, timedelta
from functools import cache
from importlib import resources

from . import sources
from .stats import fmt_num, week_start
from .store import Store, now, ts

MACROS = ("kcal", "protein", "carbs", "fat")
MEALS = ("breakfast", "lunch", "dinner", "snack")
COUNTED = ("ok", "manual")
MASS = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "kg": 1000, "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
        "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592}
VOLUME = {"ml": 1, "milliliter": 1, "milliliters": 1, "l": 1000, "liter": 1000, "liters": 1000, "litre": 1000,
          "litres": 1000, "fl oz": 29.5735}
HOUSEHOLD = {"cup": "cup", "cups": "cup", "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tsp": "tsp",
             "teaspoon": "tsp", "teaspoons": "tsp", "slice": "slice", "slices": "slice", "piece": "piece",
             "pieces": "piece", "scoop": "scoop", "scoops": "scoop", "can": "can", "cans": "can", "glass": "glass",
             "glasses": "glass", "bottle": "bottle", "bottles": "bottle", "serving": "serving", "servings": "serving",
             "large": "large", "medium": "medium", "small": "small", "fillet": "fillet", "fillets": "fillet",
             "handful": "handful", "handfuls": "handful", "bowl": "bowl", "bowls": "bowl", "plate": "plate"}
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "twelve": 12, "half": 0.5, "half a": 0.5, "half an": 0.5, "a half": 0.5,
         "a couple of": 2, "a couple": 2, "couple of": 2, "a dozen": 12, "dozen": 12}
# words that change how a food was cooked or cut, not what it is: "grilled chicken breast" is chicken breast
PREP = {"grilled", "baked", "boiled", "hard", "soft", "roasted", "roast", "fried", "scrambled", "poached", "raw",
        "fresh", "sliced", "cooked", "steamed", "plain", "whole", "big", "homemade", "cold", "hot", "warm", "toasted",
        "chopped", "diced", "mashed", "frozen", "leftover"}
STOP = {"the", "some", "my", "of", "and", "with", "a", "an"}

_UNIT = "|".join(sorted(map(re.escape, [*MASS, *VOLUME, *HOUSEHOLD]), key=len, reverse=True))
_WORD = "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True))
NUM = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?"
LEAD = re.compile(rf"^(?:(?P<n>{NUM})(?!\s*%)\s*|(?P<w>{_WORD})\s+)(?:x\s*)?(?:(?P<u>{_UNIT})\.?(?=\s|$)\s*)?(?:of\s+)?(?P<name>.*)$", re.I)
TRAIL = re.compile(rf"^(?P<name>.+?)[\s(,]+(?:x\s*(?P<x>\d+)|(?P<n>{NUM})(?:\s*(?P<u>{_UNIT})\.?)?)\)?$", re.I)
WEIGHED = re.compile(rf"^(?P<n>{NUM})\s*(?P<u>{'|'.join(sorted(map(re.escape, [*MASS, *VOLUME]), key=len, reverse=True))})\.?\s+(?:of\s+)?(?P<name>.+)$", re.I)
AMOUNT_ONLY = re.compile(rf"^(?:(?:{NUM})(?:\s*(?:{_UNIT})\.?)?|x\s*\d+)$", re.I)
SPLIT = re.compile(r"\s*(?:[,;\n+]|\band\b|&|\bwith\b|\bplus\b)\s*", re.I)
MEAL_WORD = r"(?P<meal>breakfast|brunch|lunch|dinner|supper|snacks?)"
MEAL_HEAD = re.compile(rf"^\s*(?:for\s+)?{MEAL_WORD}\s*(?::|-|was|i\s+had|had)?\s*", re.I)
MEAL_TAIL = re.compile(rf"\s+(?:for|at|as)\s+(?:a\s+|my\s+)?{MEAL_WORD}[\s.!]*$", re.I)
VERB = re.compile(r"^\s*(?:i\s+|just\s+|i\s+just\s+)?(?:had|ate|eaten|eating|drank|having|got)\s+", re.I)
BARCODE = re.compile(r"^\d{8,14}$")
SAME = {"slice": "piece", "piece": "slice"}  # USDA calls a slice of pizza a piece


def key(name: str) -> str:
    """Comparable form of a food name: lower case, singular, no filler ("2% Milk" -> "2% milk")."""
    out = []
    for w in re.findall(r"[a-z0-9%]+", name.lower()):
        if w in STOP:
            continue
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("oes"):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us")):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


# ---- the bundled table ----------------------------------------------------------------------------

@cache
def table() -> dict[str, dict]:
    """key -> food, for every name and alias in data/common_foods.json (USDA SR Legacy and FNDDS)."""
    data = json.loads(resources.files(__package__).joinpath("data/common_foods.json").read_text())
    out = {}
    for f in data["foods"]:
        food = {"source": "fdc", "source_id": str(f["fdc_id"]), "name": f["name"], "brand": None,
                "per_100g": f["per_100g"], "portions": f["portions"], "count": f["count"],
                "description": f["description"]}
        for n in [f["name"], *f["aliases"]]:
            out.setdefault(key(n), food)
    return out


def bundled(name: str) -> dict | None:
    k = key(name)
    if k in table():
        return table()[k]
    words = set(k.split())
    core = words - PREP
    if core != words and core:  # "grilled chicken breast" -> "chicken breast"
        return table().get(" ".join(w for w in k.split() if w in core))
    return None


# ---- parsing --------------------------------------------------------------------------------------

def _num(s: str) -> float:
    s = s.strip().lower()
    if s in WORDS:
        return WORDS[s]
    if m := re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", s):
        return int(m[1]) + int(m[2]) / int(m[3])
    if m := re.fullmatch(r"(\d+)/(\d+)", s):
        return int(m[1]) / int(m[2])
    return float(s)


def _unit(u: str | None) -> str | None:
    if not u:
        return None
    u = re.sub(r"\s+", " ", u.lower().rstrip("."))
    return u if u in MASS or u in VOLUME else HOUSEHOLD.get(u, u)


def parse_item(text: str) -> dict:
    """"200g chicken breast" -> {"name": "chicken breast", "amount": 200, "unit": "g"}. No amount: amount 1, unit None."""
    t = re.sub(r"\s+", " ", text.strip(" .!?")).strip()
    if m := LEAD.match(t):
        if m["name"].strip():
            amount, unit, name = _num(m["n"] or m["w"]), _unit(m["u"]), m["name"].strip(" ,")
            if unit is None and (inner := WEIGHED.match(name)):  # "3x 100g chicken": three 100 g portions
                amount, unit, name = amount * _num(inner["n"]), _unit(inner["u"]), inner["name"]
            return {"said": text.strip(), "name": name, "amount": amount, "unit": unit}
    if m := TRAIL.match(t):
        amount = float(m["x"]) if m["x"] else _num(m["n"])
        return {"said": text.strip(), "name": m["name"].strip(" ,"), "amount": amount, "unit": _unit(m["u"])}
    return {"said": text.strip(), "name": t, "amount": 1.0, "unit": None}


def parse_meal(text: str) -> tuple[str | None, list[dict]]:
    """"breakfast: 2 eggs, toast and a protein shake" -> ("breakfast", [items])."""
    meal = None
    t = text.strip()
    if m := MEAL_HEAD.match(t):
        meal, t = m["meal"].lower(), t[m.end():]
    if m := MEAL_TAIL.search(t):
        meal, t = meal or m["meal"].lower(), t[:m.start()]
    t = VERB.sub("", t)
    meal = {"brunch": "breakfast", "supper": "dinner", "snacks": "snack"}.get(meal, meal)
    parts = []
    for p in SPLIT.split(t):
        p = p.strip(" .!?")
        if parts and AMOUNT_ONLY.match(p):  # "chicken breast, 200 g": the amount belongs to the item before it
            parts[-1] += f" {p}"
        elif p:
            parts.append(p)
    return meal, [parse_item(p) for p in parts]


# ---- amounts --------------------------------------------------------------------------------------

def portion(food: dict, word: str | None) -> dict | None:
    """The food's portion called `word` ("slice", "large"); None -> its usual portion for a bare count."""
    ps = food.get("portions") or []
    if word is None:
        word = food.get("count")
        if word is None:
            return None
    word = word.lower()
    return (next((p for p in ps if p["label"] == word), None)
            or next((p for p in ps if p["label"].startswith(word)), None)
            or next((p for p in ps if word in re.findall(r"[a-z]+(?: oz)?", p["label"])), None))


def grams_for(food: dict, amount: float, unit: str | None) -> tuple[float | None, str | None]:
    """(grams, None), or (None, why not). Volumes need the food's own cup or fl oz weight; no density is assumed."""
    if unit in MASS:
        return amount * MASS[unit], None
    if unit in VOLUME:
        ml = amount * VOLUME[unit]
        for word, ml_per in (("fl oz", 29.5735), ("cup", 236.588), ("tbsp", 14.787), ("tsp", 4.929)):
            p = portion(food, word)
            if p:
                return ml * p["grams"] / ml_per, None
        return None, f"no volume weight for {food['name']}; give grams"
    p = portion(food, unit) or (portion(food, SAME[unit]) if unit in SAME else None)
    if p:
        return amount * p["grams"], None
    what = f"a {unit}" if unit else "one"
    known = ", ".join(sorted({p["label"].split(",")[0].split(" (")[0] for p in food.get("portions") or []})[:6])
    return None, f"no weight for {what} of {food['name']}; give grams" + (f" or one of: {known}" if known else "")


def macros(food: dict, grams: float) -> dict:
    out = {}
    for k in MACROS:
        v = food["per_100g"].get(k)
        out[k] = None if v is None else round(v * grams / 100, 0 if k == "kcal" else 1)
    return out


# ---- the food cache -------------------------------------------------------------------------------

def _save(store: Store, food: dict) -> int:
    per = food["per_100g"]
    with store.db:
        store.db.execute(
            "INSERT INTO foods (source, source_id, name, brand, kcal, protein, carbs, fat, portions, count, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (source, source_id) DO UPDATE SET name = excluded.name, "
            "brand = excluded.brand, kcal = excluded.kcal, protein = excluded.protein, carbs = excluded.carbs, "
            "fat = excluded.fat, portions = excluded.portions, count = excluded.count, fetched_at = excluded.fetched_at",
            (food["source"], food["source_id"], food["name"], food.get("brand"), per.get("kcal"), per.get("protein"),
             per.get("carbs"), per.get("fat"), json.dumps(food.get("portions") or []), food.get("count"), ts(None)))
    return store.db.execute("SELECT id FROM foods WHERE source = ? AND source_id = ?",
                            (food["source"], food["source_id"])).fetchone()["id"]


def _load(store: Store, food_id: int) -> dict | None:
    r = store.db.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "source": r["source"], "source_id": r["source_id"], "name": r["name"], "brand": r["brand"],
            "per_100g": {k: r[k] for k in MACROS}, "portions": json.loads(r["portions"]), "count": r["count"]}


def source_label(food: dict) -> str:
    return {"fdc": "USDA FoodData Central", "off": "Open Food Facts"}.get(food["source"], food["source"]) + f" {food['source_id']}"


def _fits(query: str, name: str) -> bool:
    """A search hit counts only if its name holds every word that was said (preparation words aside)."""
    want = set(key(query).split()) - PREP
    have = set(key(name).split())
    return bool(want) and want <= have


def lookup(store: Store, query: str | None = None, barcode: str | None = None, n: int = 5) -> dict:
    """Candidates for a food name or a barcode, without logging anything. Each candidate is cached and carries
    a `food_id` that log_food accepts. Returns {"foods": [...], "errors": [...]}."""
    found, errors = [], []
    if barcode:
        try:
            f = sources.off_product(barcode)
            found += [f] if f else []
        except sources.SourceError as e:
            errors.append(str(e))
    elif query:
        if f := bundled(query):
            found.append(f)
        for search in (sources.fdc_search, sources.off_search):
            try:
                found += search(query, n)
            except sources.SourceError as e:
                errors.append(str(e))
    out = []
    for f in found[: n + 1]:
        f = {**f, "id": _save(store, f)}
        out.append(_public(f))
    return {"foods": out, "errors": errors}


def _public(f: dict) -> dict:
    return {"food_id": f["id"], "name": f["name"], "brand": f.get("brand"), "source": source_label(f),
            "per_100g": f["per_100g"], "portions": f.get("portions") or [], "usual_portion": f.get("count")}


def resolve(store: Store, name: str) -> tuple[dict | None, list[dict], list[str]]:
    """(food or None, candidates when unmatched, lookup errors)."""
    k = key(name)
    if f := bundled(name):
        return {**f, "id": _save(store, f)}, [], []
    row = store.db.execute("SELECT food_id FROM food_lookups WHERE query = ?", (k,)).fetchone()
    if row and (f := _load(store, row["food_id"])):
        return f, [], []
    if BARCODE.match(name.strip()):
        try:
            f = sources.off_product(name)
        except sources.SourceError as e:
            return None, [], [str(e)]
        return ({**f, "id": _save(store, f)}, [], []) if f else (None, [], [f"Open Food Facts has no product {name.strip()}"])
    candidates, errors = [], []
    for search in (sources.fdc_search, sources.off_search):
        try:
            hits = search(name, 5)
        except sources.SourceError as e:
            errors.append(str(e))
            continue
        for h in hits:
            if _fits(name, h["name"]):
                f = {**h, "id": _save(store, h)}
                with store.db:
                    store.db.execute("INSERT OR REPLACE INTO food_lookups VALUES (?, ?)", (k, f["id"]))
                return f, [], errors
        candidates += hits[:3]
    return None, [_public({**c, "id": _save(store, c)}) for c in candidates[:5]], errors


# ---- logging --------------------------------------------------------------------------------------

def meal_at(at: datetime) -> str:
    h = at.hour
    return "breakfast" if 4 <= h < 11 else "lunch" if 11 <= h < 15 else "dinner" if 17 <= h < 22 else "snack"


def _item(store: Store, name: str, amount: float | None, unit: str | None, food_id: int | None, given: dict) -> dict:
    """Fields for one food_log row: matched and weighed, or flagged."""
    amount = 1.0 if amount is None else float(amount)
    if amount <= 0:
        raise ValueError(f"amount must be more than 0, got {amount:g}")
    if any((given.get(k) or 0) < 0 for k in MACROS):
        raise ValueError("kcal, protein, carbs and fat cannot be negative")
    unit = _unit(unit)
    grams = amount * MASS[unit] if unit in MASS else None
    if any(given.get(k) is not None for k in MACROS):  # the user or agent supplied the numbers (a label, a menu)
        return {"name": name, "amount": amount, "unit": unit, "grams": grams, "food_id": food_id,
                **{k: given.get(k) for k in MACROS}, "status": "manual", "note": "numbers given"}
    food, candidates, errors = (_load(store, food_id), [], []) if food_id else resolve(store, name)
    if food_id and not food:
        raise LookupError(f"no food {food_id}; use a food_id from lookup_food")
    if not food:
        note = "no match in USDA FoodData Central or Open Food Facts"
        if errors:
            note = "lookup failed (" + "; ".join(dict.fromkeys(errors)) + ")"
        return {"name": name, "amount": amount, "unit": unit, "grams": grams, "food_id": None,
                **dict.fromkeys(MACROS), "status": "unknown", "note": note, "candidates": candidates}
    grams, why = grams_for(food, amount, unit)
    if grams is None:
        return {"name": food["name"], "amount": amount, "unit": unit, "grams": None, "food_id": food["id"],
                **dict.fromkeys(MACROS), "status": "needs_amount", "note": why}
    return {"name": food["name"], "amount": amount, "unit": unit, "grams": round(grams, 1), "food_id": food["id"],
            **macros(food, grams), "status": "ok", "note": source_label(food)}


def _row(store: Store, item_id: int) -> dict:
    r = store.db.execute("SELECT * FROM food_log WHERE id = ?", (item_id,)).fetchone()
    if not r:
        raise LookupError(f"no food item {item_id}")
    return dict(r)


def _insert(store: Store, said: str, fields: dict, at: datetime, meal: str) -> dict:
    cols = ("eaten_at", "day", "meal", "said", "name", "amount", "unit", "grams", "food_id", *MACROS, "status", "note")
    vals = (at.isoformat(), at.date().isoformat(), meal, said, *(fields[c] for c in cols[4:]))
    with store.db:
        cur = store.db.execute(f"INSERT INTO food_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    out = _row(store, cur.lastrowid)
    if fields.get("candidates"):
        out["candidates"] = fields["candidates"]
    return out


def log_food(store: Store, text: str | None = None, *, name: str | None = None, amount: float | None = None,
             unit: str | None = None, grams: float | None = None, barcode: str | None = None, food_id: int | None = None,
             meal: str | None = None, at=None, kcal: float | None = None, protein: float | None = None,
             carbs: float | None = None, fat: float | None = None) -> list[dict]:
    """Log what was eaten. Either `text` ("2 eggs, toast and a protein shake"; split into items), or one item
    by `name`/`barcode`/`food_id` with an amount (`grams`, or `amount` + `unit`). Giving kcal/protein/carbs/fat
    stores those numbers as said. Returns the stored rows; check each `status`."""
    when = datetime.fromisoformat(ts(at))
    if meal and meal.lower() not in MEALS:
        raise ValueError(f"meal must be one of {', '.join(MEALS)}")
    if text:
        said_meal, items = parse_meal(text)
        meal = (meal or said_meal or meal_at(when)).lower()
        if not items:
            raise ValueError(f"no food in {text!r}")
        return [_insert(store, it["said"], _item(store, it["name"], it["amount"], it["unit"], None, {}), when, meal)
                for it in items]
    if not (name or barcode or food_id):
        raise ValueError("give text, name, barcode or food_id")
    meal = (meal or meal_at(when)).lower()
    if grams is not None:
        amount, unit = grams, "g"
    given = {"kcal": kcal, "protein": protein, "carbs": carbs, "fat": fat}
    said = name or barcode or f"food {food_id}"
    fields = _item(store, (barcode or name or "").strip(), amount, unit, food_id, given)
    if name and fields["status"] in ("manual", "unknown"):
        fields["name"] = name
    return [_insert(store, said, fields, when, meal)]


def edit_food(store: Store, item_id: int, delete: bool = False, **changes) -> dict | None:
    """Fix a logged item: new amount (grams, or amount + unit), another food (name or food_id), another meal,
    or the numbers themselves (kcal, protein, carbs, fat). delete=True removes it."""
    row = _row(store, item_id)
    if delete:
        with store.db:
            store.db.execute("DELETE FROM food_log WHERE id = ?", (item_id,))
        return None
    bad = set(changes) - {"name", "amount", "unit", "grams", "food_id", "meal", *MACROS}
    if bad:
        raise ValueError(f"cannot edit {', '.join(sorted(bad))}")
    c = {k: v for k, v in changes.items() if v is not None}
    if "meal" in c and c["meal"] not in MEALS:
        raise ValueError(f"meal must be one of {', '.join(MEALS)}")
    given = {k: c.get(k) for k in MACROS}
    if any(v is not None for v in given.values()) and row["status"] in COUNTED and row["food_id"]:
        given = {k: c.get(k, row[k]) for k in MACROS}  # override some numbers, keep the rest
    if "grams" in c:
        c["amount"], c["unit"] = c.pop("grams"), "g"
    if "unit" in c and "amount" not in c:
        raise ValueError("give the amount with the new unit (amount=2, unit='cup'), or grams")
    manual = row["status"] == "manual" and "food_id" not in c and all(v is None for v in given.values())
    if manual and "amount" not in c:  # a label item renamed or moved keeps its numbers
        given = {k: row[k] for k in MACROS}
    elif manual:
        # numbers came from a label: scale them to the new amount when the two amounts compare
        old, new = row["amount"] or 1, c["amount"]
        if (c.get("unit") or row["unit"]) != row["unit"]:
            if not (row["grams"] and _unit(c["unit"]) in MASS):
                raise ValueError("this item's numbers were given by hand; give the new numbers too")
            old, new = row["grams"], c["amount"] * MASS[_unit(c["unit"])]
        given = {k: None if row[k] is None else round(row[k] * new / old, 0 if k == "kcal" else 1) for k in MACROS}
    fields = None
    if {"name", "food_id", "amount", "unit"} & set(c) or any(v is not None for v in given.values()):
        amount = c.get("amount", row["amount"])
        unit = c["unit"] if "unit" in c else None if "amount" in c else row["unit"]  # "3" alone means 3 of the usual
        food_id = c.get("food_id") or (None if "name" in c else row["food_id"])
        fields = _item(store, c.get("name", row["name"]), amount, unit, food_id, given)
        if "name" in c and fields["status"] in ("manual", "unknown"):
            fields["name"] = c["name"]
    with store.db:
        if fields:
            fields.pop("candidates", None)
            store.db.execute(f"UPDATE food_log SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             (*fields.values(), item_id))
        if "meal" in c:
            store.db.execute("UPDATE food_log SET meal = ? WHERE id = ?", (c["meal"], item_id))
    return _row(store, item_id)


# ---- goals, streaks, the day ----------------------------------------------------------------------

def set_goals(store: Store, **goals) -> dict:
    """Daily targets: set_goals(kcal=2400, protein=160). 0 clears one; omitted ones stay."""
    bad = set(goals) - set(MACROS)
    if bad:
        raise ValueError(f"goals are {', '.join(MACROS)}")
    with store.db:
        for k, v in goals.items():
            if v is None:
                continue
            if v <= 0:
                store.db.execute("DELETE FROM goals WHERE key = ?", (k,))
            else:
                store.db.execute("INSERT OR REPLACE INTO goals VALUES (?, ?)", (k, float(v)))
    return get_goals(store)


def get_goals(store: Store) -> dict:
    return {r["key"]: r["value"] for r in store.db.execute("SELECT * FROM goals")}


def _day(d) -> date:
    if d is None:
        return now().date()
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def _run(days: set[date], end: date, step: timedelta) -> int:
    n = 0
    while end in days:
        n, end = n + 1, end - step
    return n


def streaks(store: Store, day=None) -> dict:
    """Logging streak in days and training streak in weeks (Monday start), as of `day` (default today).
    Today not logged yet does not break a streak; it just is not counted."""
    d = _day(day)
    food_days = {date.fromisoformat(r["day"]) for r in store.db.execute("SELECT DISTINCT day FROM food_log")}
    food_days = {x for x in food_days if x <= d}
    logging = _run(food_days, d if d in food_days else d - timedelta(days=1), timedelta(days=1))
    best = run = 0
    prev = None
    for x in sorted(food_days):
        run = run + 1 if prev == x - timedelta(days=1) else 1
        best, prev = max(best, run), x
    weeks = {week_start(datetime.fromisoformat(r["started_at"]).date())
             for r in store.db.execute("SELECT started_at FROM sessions")}
    weeks = {w for w in weeks if w <= d}
    this = week_start(d)
    training = _run(weeks, this if this in weeks else this - timedelta(weeks=1), timedelta(weeks=1))
    return {"logging_days": logging, "logging_best": best, "logged_today": d in food_days,
            "training_weeks": training}


def _workouts(store: Store, d: date) -> list[dict]:
    from .stats import summary  # stats imports store only; kept local so food stays importable on its own

    out = []
    for r in store.db.execute("SELECT id, started_at FROM sessions ORDER BY julianday(started_at)"):
        if datetime.fromisoformat(r["started_at"]).date() == d:
            s = summary(store, r["id"])
            out.append({"id": s["id"], "title": s["title"], "duration": s["duration"], "sets": s["sets"],
                        "volume": s["volume"], "unit": s["unit"], "prs": len(s["prs"]),
                        "exercises": len(s["exercises"])})
    return out


def day_summary(store: Store, day=None) -> dict:
    """Everything a food card needs for one day: items by meal, totals, goals, streaks, the week's logged
    days and any workouts that day. Totals count only matched or given items; flagged ones are listed."""
    d = _day(day)
    rows = [dict(r) for r in store.db.execute("SELECT * FROM food_log WHERE day = ? ORDER BY julianday(eaten_at), id",
                                               (d.isoformat(),))]
    counted = [r for r in rows if r["status"] in COUNTED]
    totals = {k: round(sum(r[k] or 0 for r in counted), 0 if k == "kcal" else 1) for k in MACROS}
    meals = []
    for m in MEALS:
        items = [r for r in rows if r["meal"] == m]
        if items:
            meals.append({"meal": m, "items": items,
                          "kcal": round(sum(r["kcal"] or 0 for r in items if r["status"] in COUNTED))})
    goals = get_goals(store)
    energy = {"protein": totals["protein"] * 4, "carbs": totals["carbs"] * 4, "fat": totals["fat"] * 9}
    e_sum = sum(energy.values())
    split = {k: round(v / e_sum * 100) for k, v in energy.items()} if e_sum else dict.fromkeys(energy, 0)
    first = week_start(d)
    logged = {r["day"] for r in store.db.execute("SELECT DISTINCT day FROM food_log WHERE day BETWEEN ? AND ?",
                                                  (first.isoformat(), (first + timedelta(days=6)).isoformat()))}
    return {
        "date": d.isoformat(),
        "items": len(rows),
        "meals": meals,
        "totals": totals,
        "goals": goals,
        "remaining": {k: round(goals[k] - totals[k], 0 if k == "kcal" else 1) for k in goals},
        "split": split,
        "flagged": [r for r in rows if r["status"] not in COUNTED],
        "streaks": streaks(store, d),
        "week": {"days": [int((first + timedelta(days=i)).isoformat() in logged) for i in range(7)],
                 "today": d.weekday()},
        "workouts": _workouts(store, d),
    }


def fmt_item(r: dict) -> str:
    amt = fmt_num(r["amount"]) if r["amount"] is not None else ""
    what = f"{amt} {r['unit']} {r['name']}" if r["unit"] else f"{amt} × {r['name']}" if amt and amt != "1" else r["name"]
    if r["status"] in COUNTED:
        g = f", {fmt_num(r['grams'])} g" if r["grams"] and r["unit"] not in ("g",) else ""
        return f"{what}{g}: {fmt_num(r['kcal'] or 0)} kcal, P {fmt_num(r['protein'] or 0)} C {fmt_num(r['carbs'] or 0)} F {fmt_num(r['fat'] or 0)}"
    return f"{what}: not counted ({r['note']})"


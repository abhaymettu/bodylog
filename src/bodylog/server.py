"""MCP server (stdio). Run `bodylog-mcp`; the log lives at $BODYLOG_DB or ~/.bodylog/log.db."""
import os
from contextlib import closing
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from . import APP, card, chatlog, food, foodcard, stats
from .store import Store

INSTRUCTIONS = """Workout and food log. While the user trains, call log_set for every set they mention
("60kg x 8" -> weight 60, unit kg, reps 8). Leave exercise empty when it is the same as the last set.
If they correct something, call edit_last_set. When they say they are done and give a time, call
end_session with that duration and show them the card it returns. Use exercise_history, prs and
weekly_volume to answer progress questions. Pass `text` to log_set when you would rather not parse.
When they say what they ate, call log_food(text=<their words>). Items come back with a status: ok and
manual count toward totals; unknown and needs_amount do not, so ask about those in one short line
(or pick a candidate's food_id / pass grams via edit_food). food_day and food_card show the day."""

mcp = MCPServer(APP, instructions=INSTRUCTIONS)


def _cards_dir() -> Path:
    return Path(os.environ.get(f"{APP.upper()}_CARDS") or Path.home() / f".{APP}" / "cards")


def _set(row) -> dict:
    return {k: row[k] for k in ("id", "session_id", "exercise", "weight", "unit", "reps", "rpe", "kind", "notes", "logged_at")}


def _card(store: Store, session_id: int | None, theme: str, unit: str | None = None, style: str = "full") -> list:
    s = stats.summary(store, session_id, unit)
    name = f"session-{s['id']}-{theme}" + ("-story" if style == "story" else "")
    paths = card.render_png(s, _cards_dir() / f"{name}.png", theme, style=style)
    where = "\n".join(f"Card image: {p}" for p in paths)
    return [card.render_text(s) + f"\n\n{where}", *(Image(path=p) for p in paths)]


@mcp.tool(structured_output=False)
def log_set(exercise: str | None = None, weight: float | None = None, reps: int | None = None, unit: str | None = None,
            rpe: float | None = None, kind: str = "normal", notes: str | None = None, count: int = 1,
            text: str | None = None) -> dict | list:
    """Log a set to the current workout, starting one if none is open.

    exercise: name as the user says it ("incline db curl"); omit to reuse the last set's exercise.
    weight/unit: 0 or omitted for bodyweight; unit is kg or lb (defaults to the last unit used).
    kind: normal, warmup, drop or failure. count: identical sets at once ("3x10").
    text: alternatively, the user's raw message ("62.5kg x 6", "same", "this is tricep pushdowns btw").
    Returns the logged sets and any PRs they set. A text that ends the workout ("done, 1h 5m") returns the card.
    """
    with closing(Store()) as store:
        if text:
            notes_out = chatlog.log_text(store, text)
            if any(a.kind == "end" for a in chatlog.interpret(text)):
                return _card(store, store.last_session()["id"], "dark")
            last = store.last_set()
            logged = [_set(last)] if last else []
        else:
            logged = [_set(r) for r in store.log_set(exercise, weight, reps, unit, rpe, kind, notes, count=count)]
            notes_out = []
        prs = []
        if logged:
            s = store.session(logged[0]["session_id"])
            ids = {r["id"] for r in logged}
            prs = [p for p in stats.session_prs(store, s) if p["set_id"] in ids]
        return {"logged": logged, "notes": notes_out, "prs": prs}


@mcp.tool(structured_output=False)
def edit_last_set(exercise: str | None = None, weight: float | None = None, reps: int | None = None,
                  unit: str | None = None, rpe: float | None = None, kind: str | None = None, notes: str | None = None,
                  delete: bool = False) -> dict:
    """Fix the most recent set in the open workout ("that was 10 reps", "that was cable pushdowns"), or delete it."""
    with closing(Store()) as store:
        row = store.edit_last_set(delete=delete, exercise=exercise, weight=weight, reps=reps, unit=unit, rpe=rpe,
                                  kind=kind, notes=notes)
        return {"deleted": True} if row is None else {"set": _set(row)}


@mcp.tool(structured_output=False)
def end_session(duration: str | None = None, title: str | None = None, theme: str = "dark", unit: str | None = None) -> list:
    """End the open workout. duration is what the user says ("1h 5m", "65 min", "1:05"); title is optional
    ("Push Day"). unit (kg or lb) sets the totals' unit. Returns the summary card as text and PNG images
    (one per page; long workouts span several) to show the user."""
    with closing(Store()) as store:
        s = store.end_session(duration, title=title)
        return _card(store, s["id"], theme, unit)


@mcp.tool(structured_output=False)
def session_card(session_id: int | None = None, theme: str = "dark", unit: str | None = None, style: str = "full") -> list:
    """Summary card (text + PNG pages) for a workout: the open one, else the latest. theme: dark, light, or
    clear (transparent background, a sticker for a photo); unit: kg or lb for totals (each set keeps the unit
    it was logged in); style: full (every set, may span pages) or story (one phone-screen image, one line
    per exercise)."""
    with closing(Store()) as store:
        return _card(store, session_id, theme, unit, style)


@mcp.tool(structured_output=False)
def exercise_history(exercise: str, limit: int = 10) -> dict:
    """Per-session history for one exercise, newest first: sets, best set, top weight, estimated 1RM, volume."""
    with closing(Store()) as store:
        return stats.exercise_history(store, exercise, limit)


@mcp.tool(structured_output=False)
def prs(exercise: str | None = None) -> list:
    """All-time records (heaviest weight, best estimated 1RM, most reps) for one exercise or all of them."""
    with closing(Store()) as store:
        return stats.current_prs(store, exercise)


@mcp.tool(structured_output=False)
def weekly_volume(weeks: int = 8) -> list:
    """Training volume, workouts and sets per week (Monday start), oldest first."""
    with closing(Store()) as store:
        return stats.weekly_volume(store, weeks)


@mcp.tool(structured_output=False)
def import_chat(text: str) -> dict:
    """Backfill workouts from a pasted chat log (lines like "[2026-09-08 18:07] me: 60kg x 8").
    Safe to repeat: time spans that already hold sets are skipped. Lists lines it could not read."""
    with closing(Store()) as store:
        r = chatlog.import_chat(store, text)
        return {"sessions": r.sessions, "sets": r.sets, "duplicates_skipped": r.duplicates, "unread_lines": r.skipped}


# ---- food ----------------------------------------------------------------------------------------

def _food_row(r: dict) -> dict:
    out = {k: r[k] for k in ("id", "meal", "said", "name", "amount", "unit", "grams", *food.MACROS, "status", "note")}
    if r.get("candidates"):
        out["candidates"] = r["candidates"]
    return out


@mcp.tool(structured_output=False)
def log_food(text: str | None = None, name: str | None = None, grams: float | None = None, amount: float | None = None,
             unit: str | None = None, barcode: str | None = None, food_id: int | None = None, meal: str | None = None,
             kcal: float | None = None, protein: float | None = None, carbs: float | None = None,
             fat: float | None = None) -> dict:
    """Log food. Usually pass the user's words as text ("2 eggs, toast and a protein shake", "lunch: 200g chicken,
    1 cup rice"); it is split into items and each is matched to USDA FoodData Central or Open Food Facts.
    For one item: name (or barcode, or a food_id from lookup_food) with grams, or amount + unit (cup, slice, tbsp,
    oz, ml...). Pass kcal/protein/carbs/fat when the user reads them off a label. meal: breakfast, lunch, dinner
    or snack (default from the words, else the time of day).
    Each item has a status: ok / manual count; unknown (no match; see candidates) and needs_amount do not count
    until fixed with edit_food. Returns the items and the day's totals so far."""
    with closing(Store()) as store:
        rows = food.log_food(store, text, name=name, grams=grams, amount=amount, unit=unit, barcode=barcode,
                             food_id=food_id, meal=meal, kcal=kcal, protein=protein, carbs=carbs, fat=fat)
        day = food.day_summary(store, rows[0]["day"])
        return {"logged": [_food_row(r) for r in rows], "day_totals": day["totals"], "goals": day["goals"],
                "remaining": day["remaining"]}


@mcp.tool(structured_output=False)
def edit_food(item_id: int, grams: float | None = None, amount: float | None = None, unit: str | None = None,
              name: str | None = None, food_id: int | None = None, meal: str | None = None, kcal: float | None = None,
              protein: float | None = None, carbs: float | None = None, fat: float | None = None,
              delete: bool = False) -> dict:
    """Fix a logged food item by id: a new amount (grams, or amount + unit), another food (name, or food_id from
    lookup_food or an item's candidates), another meal, or the numbers themselves. delete=True removes it."""
    with closing(Store()) as store:
        row = food.edit_food(store, item_id, delete=delete, grams=grams, amount=amount, unit=unit, name=name,
                             food_id=food_id, meal=meal, kcal=kcal, protein=protein, carbs=carbs, fat=fat)
        return {"deleted": True} if row is None else {"item": _food_row(row)}


@mcp.tool(structured_output=False)
def lookup_food(query: str | None = None, barcode: str | None = None) -> dict:
    """Search foods without logging: a name ("kimchi", "clif bar") or a product barcode. Returns candidates with
    per-100 g macros, portions and a food_id to pass to log_food or edit_food."""
    with closing(Store()) as store:
        return food.lookup(store, query=query, barcode=barcode)


@mcp.tool(structured_output=False)
def food_day(date: str | None = None) -> dict:
    """One day's food (default today, YYYY-MM-DD): items by meal, totals, goals and what is left, streaks,
    items not counted, and any workouts that day."""
    with closing(Store()) as store:
        d = food.day_summary(store, date)
        d["meals"] = [{**m, "items": [_food_row(r) for r in m["items"]]} for m in d["meals"]]
        d["flagged"] = [_food_row(r) for r in d["flagged"]]
        return d


@mcp.tool(structured_output=False)
def food_card(date: str | None = None, theme: str = "dark", style: str = "full") -> list:
    """Shareable card for a day of food (default today): text plus a PNG. theme: dark, light or clear; style:
    full (every item) or story (one phone screen). Workouts that day appear on it too."""
    with closing(Store()) as store:
        d = food.day_summary(store, date)
        path = foodcard.render_png(d, _cards_dir() / f"food-{d['date']}-{theme}{'-story' if style == 'story' else ''}.png",
                                   theme, style)
        return [foodcard.render_text(d) + f"\n\nCard image: {path}", Image(path=path)]


@mcp.tool(structured_output=False)
def set_goals(kcal: float | None = None, protein: float | None = None, carbs: float | None = None,
              fat: float | None = None) -> dict:
    """Daily targets (kcal, grams of protein/carbs/fat). Omitted ones stay as they are; 0 clears one."""
    with closing(Store()) as store:
        return food.set_goals(store, kcal=kcal, protein=protein, carbs=carbs, fat=fat)


@mcp.tool(structured_output=False)
def streaks() -> dict:
    """Current food-logging streak in days (and the best), and training streak in weeks with a workout."""
    with closing(Store()) as store:
        return food.streaks(store)


def main():
    mcp.run()


if __name__ == "__main__":
    main()

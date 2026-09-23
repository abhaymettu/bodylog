"""Regenerate examples/: the workout cards from the chat fixtures and the food cards from a sample day.

    uv run python scripts/render_examples.py

Offline on purpose: every food below is in the bundled USDA table, so the numbers are reproducible.
"""
import os
from pathlib import Path

from bodylog import Store, foodcard, import_chat, render_png, render_text, summary
from bodylog.food import day_summary, log_food, set_goals

ROOT = Path(__file__).resolve().parents[1]
OUT, FIX = ROOT / "examples", ROOT / "tests" / "fixtures"


def workouts():
    for name, unit in (("chat", None), ("long", None), ("mixed", "lb")):
        store = Store(":memory:")
        s = summary(store, import_chat(store, (FIX / f"{name}.txt").read_text()).sessions[-1], unit)
        out = "card" if name == "chat" else name
        for theme in ("dark", "light"):
            for old in OUT.glob(f"{out}-{theme}*.png"):
                old.unlink()
            render_png(s, OUT / f"{out}-{theme}.png", theme)
        (OUT / f"{out}.md").write_text(render_text(s) + "\n")
        render_png(s, OUT / f"{out}-story.png", "dark", style="story")
        if name == "chat":
            render_png(s, OUT / "card-clear.png", "clear")


def food_day(store: Store, day: str):
    at = lambda t: f"{day}T{t}:00-05:00"  # noqa: E731
    log_food(store, "3 scrambled eggs, 2 slices of whole wheat toast, 1 tbsp peanut butter and a coffee", at=at("07:40"))
    log_food(store, "a protein shake and a banana", at=at("10:30"))
    log_food(store, "chicken breast 180g, 1.5 cups rice, broccoli and 1 tbsp olive oil", at=at("12:45"))
    log_food(store, "greek yogurt with blueberries and a handful of almonds", at=at("16:00"))
    log_food(store, "salmon 170g, sweet potato and spinach", at=at("19:15"))


def food():
    store = Store(":memory:")
    for d in ("2026-09-11", "2026-09-12", "2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16"):
        log_food(store, "2 eggs, toast and a banana", at=f"{d}T08:00:00-05:00")
    food_day(store, "2026-09-17")
    set_goals(store, kcal=2600, protein=180, carbs=280, fat=80)
    d = day_summary(store, "2026-09-17")
    foodcard.render_png(d, OUT / "food-dark.png")
    foodcard.render_png(d, OUT / "food-light.png", "light")
    foodcard.render_png(d, OUT / "food-story.png", style="story")
    (OUT / "food.md").write_text(foodcard.render_text(d) + "\n")
    # the combined day: the same food plus the Push Day workout from the chat fixture (also Sep 17)
    import_chat(store, (FIX / "chat.txt").read_text())
    d = day_summary(store, "2026-09-17")
    foodcard.render_png(d, OUT / "day-dark.png")
    foodcard.render_png(d, OUT / "day-story.png", style="story")


if __name__ == "__main__":
    os.environ.setdefault("BODYLOG_OFFLINE", "1")
    workouts()
    food()
    print("\n".join(sorted(p.name for p in OUT.iterdir())))

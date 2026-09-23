import pytest
from PIL import Image

from bodylog import foodcard
from bodylog.food import day_summary, log_food, set_goals

AM = "2026-09-23T08:00:00-05:00"


@pytest.fixture
def day(store):
    log_food(store, "2 eggs, toast and a protein shake", at=AM)
    log_food(store, "chicken breast 150g, 1.5 cups rice and a handful of almonds", at="2026-09-23T13:00:00-05:00")
    return store


@pytest.mark.parametrize("theme", ["dark", "light", "clear"])
@pytest.mark.parametrize("style", ["full", "story"])
def test_renders(day, tmp_path, theme, style):
    d = day_summary(day, "2026-09-23")
    img = Image.open(foodcard.render_png(d, tmp_path / "c.png", theme, style))
    assert img.width == 1080
    assert img.height >= 1920 if style == "story" else img.height == sum(b[2] for b in foodcard.blocks(d)) + 116
    assert img.mode == ("RGBA" if theme == "clear" else "RGB")


def test_goals_and_over(day, tmp_path):
    set_goals(day, kcal=800, protein=150, carbs=200, fat=60)
    d = day_summary(day, "2026-09-23")
    assert d["remaining"]["kcal"] < 0
    foodcard.render_png(d, tmp_path / "over.png")
    text = foodcard.render_text(d)
    assert "kcal" in text and "over" in text and "1 item not counted: almonds" in text


def test_text_lists_every_item(day):
    text = foodcard.render_text(day_summary(day, "2026-09-23"))
    for word in ("**Breakfast**", "**Lunch**", "egg", "whey protein", "white rice", "not counted"):
        assert word in text


def test_empty_day_renders(store, tmp_path):
    foodcard.render_png(day_summary(store, "2026-09-23"), tmp_path / "empty.png", style="story")

import json
from datetime import date

import pytest

from bodylog import food
from bodylog.food import day_summary, edit_food, log_food, lookup, parse_meal, set_goals, streaks

AM = "2026-09-23T08:00:00-05:00"


def names(rows):
    return [(r["name"], r["status"]) for r in rows]


@pytest.mark.parametrize("text, meal, items", [
    ("2 eggs, toast and a protein shake", None, [("eggs", 2, None), ("toast", 1, None), ("protein shake", 1, None)]),
    ("breakfast: 200g greek yogurt with blueberries", "breakfast", [("greek yogurt", 200, "g"), ("blueberries", 1, None)]),
    ("chicken breast 150g, 1.5 cups rice", None, [("chicken breast", 150, "g"), ("rice", 1.5, "cup")]),
    ("half an avocado", None, [("avocado", 0.5, None)]),
    ("2% milk 250 ml", None, [("2% milk", 250, "ml")]),
    ("a slice of pizza", None, [("pizza", 1, "slice")]),
    ("kimchi x2", None, [("kimchi", 2, None)]),
    ("i had 3 scrambled eggs and a coffee for breakfast", "breakfast", [("scrambled eggs", 3, None), ("coffee", 1, None)]),
    ("2 slices of whole wheat toast with 1 tbsp peanut butter", None,
     [("whole wheat toast", 2, "slice"), ("peanut butter", 1, "tbsp")]),
    ("for dinner 1 1/2 cups pasta", "dinner", [("pasta", 1.5, "cup")]),
])
def test_parse_meal(text, meal, items):
    got_meal, got = parse_meal(text)
    assert got_meal == meal
    assert [(i["name"], i["amount"], i["unit"]) for i in got] == items


def test_bundled_table_cites_usda():
    data = json.loads((food.resources.files("bodylog") / "data/common_foods.json").read_text())
    assert len(data["foods"]) >= 50
    for f in data["foods"]:
        assert isinstance(f["fdc_id"], int) and f["dataset"] in ("SR Legacy", "FNDDS")
        assert food.portion({**f, "count": f["count"]}, None), f["name"]  # every bare count has a USDA weight


def test_brief_example_offline(store):
    rows = log_food(store, "2 eggs, toast and a protein shake", at=AM)
    assert names(rows) == [("egg", "ok"), ("toast", "ok"), ("whey protein", "ok")]
    egg = rows[0]
    assert egg["grams"] == 100 and egg["kcal"] == 143 and egg["protein"] == 12.6  # 2 large eggs, FDC 171287
    assert all(r["meal"] == "breakfast" for r in rows)  # 8 AM
    assert "USDA FoodData Central 171287" in egg["note"]


def test_units(store):
    by = {r["name"]: r for r in log_food(store, "150 g chicken breast, 1.5 cups rice, 2% milk 250 ml, 1 oz cheddar", at=AM)}
    assert by["chicken breast"]["kcal"] == round(165 * 1.5)
    assert by["white rice"]["grams"] == 237  # 1.5 x 158 g cup
    assert by["2% milk"]["grams"] == pytest.approx(250 * 244 / 236.588, abs=0.1)  # from USDA's cup weight
    assert by["cheddar"]["grams"] == pytest.approx(28.3, abs=0.1)
    assert log_food(store, "grilled chicken breast", at=AM)[0]["name"] == "chicken breast"


def test_unknown_is_kept_and_flagged_not_counted(store):
    rows = log_food(store, "toast and zzqxv bar", at=AM)
    assert names(rows) == [("toast", "ok"), ("zzqxv bar", "unknown")]
    assert rows[1]["kcal"] is None and "lookup failed" in rows[1]["note"]
    day = day_summary(store, "2026-09-23")
    assert day["totals"]["kcal"] == rows[0]["kcal"]
    assert [r["name"] for r in day["flagged"]] == ["zzqxv bar"]


def test_amount_without_weight_asks(store):
    (r,) = log_food(store, "a handful of almonds", at=AM)
    assert r["status"] == "needs_amount" and "give grams" in r["note"]
    r = edit_food(store, r["id"], grams=28)
    assert r["status"] == "ok" and r["unit"] == "g" and r["kcal"] == round(579 * 0.28)


def test_manual_numbers_and_edits(store):
    (r,) = log_food(store, name="clif bar", kcal=250, protein=10, carbs=44, fat=5, at=AM)
    assert r["status"] == "manual" and r["name"] == "clif bar"
    (e,) = log_food(store, "2 eggs", at=AM)
    e = edit_food(store, e["id"], amount=3)
    assert e["grams"] == 150
    e = edit_food(store, e["id"], name="egg white")
    assert e["name"] == "egg white" and e["kcal"] == round(52 * 99 / 100)
    e = edit_food(store, e["id"], meal="lunch")
    assert e["meal"] == "lunch"
    assert edit_food(store, e["id"], delete=True) is None
    with pytest.raises(ValueError):
        edit_food(store, r["id"], colour="red")


def test_fdc_lookup_is_cached(store, recorded):
    calls = recorded({("fdc", "kimchi"): "fdc_search_kimchi.json"})
    (r,) = log_food(store, "kimchi", at=AM)
    assert r["status"] == "ok" and r["name"] == "Kimchi" and r["grams"] == 30  # FNDDS "quantity not specified"
    assert r["kcal"] == round(15 * 0.3) and "USDA FoodData Central 2710077" in r["note"]
    (r,) = log_food(store, "1 cup kimchi", at=AM)
    assert r["grams"] == 150
    assert len(calls) == 1  # the second one came from the cache


def test_falls_back_to_open_food_facts(store, recorded):
    recorded({("fdc", "clif bar chocolate chip"): "fdc_search_empty.json",
              ("off", "clif bar chocolate chip"): "off_search_clif.json"})
    rows = log_food(store, name="clif bar chocolate chip", grams=68, at=AM)
    assert rows[0]["status"] == "ok" and rows[0]["kcal"] == round(368 * 0.68)
    assert "Open Food Facts 0722252068484" in rows[0]["note"]


def test_search_hit_must_hold_every_word(store, recorded):
    recorded({("fdc", "kimchi fried rice"): "fdc_search_kimchi.json", ("off", "kimchi fried rice"): "off_search_clif.json"})
    (r,) = log_food(store, "kimchi fried rice", at=AM)
    assert r["status"] == "unknown"
    assert r["candidates"] and r["candidates"][0]["name"] == "Kimchi"  # offered, never taken silently
    fixed = edit_food(store, r["id"], food_id=r["candidates"][0]["food_id"], grams=200)
    assert fixed["status"] == "ok" and fixed["kcal"] == 30


def test_barcode(store, recorded):
    recorded({("off", "3017624010701"): "off_product_3017624010701.json", ("off", "0000000000017"): "off_product_missing.json"})
    (r,) = log_food(store, barcode="3017624010701", grams=15, at=AM)
    assert r["name"] == "Nutella" and r["kcal"] == round(539 * 0.15) and r["fat"] == round(30.9 * 0.15, 1)
    (r,) = log_food(store, "3017624010701", at=AM)  # a barcode in text: found, but no serving weight on record
    assert r["status"] == "needs_amount"
    (r,) = log_food(store, barcode="0000000000017", grams=10, at=AM)
    assert r["status"] == "unknown"
    assert lookup(store, barcode="3017624010701")["foods"][0]["brand"] == "Ferrero"


def test_goals_and_day(store):
    set_goals(store, kcal=2000, protein=150)
    log_food(store, "3 eggs", at=AM)
    d = day_summary(store, "2026-09-23")
    assert d["remaining"] == {"kcal": 2000 - 214, "protein": 150 - 18.8}
    assert set_goals(store, protein=0) == {"kcal": 2000}
    assert d["week"]["days"] == [0, 0, 1, 0, 0, 0, 0]
    assert sum(d["split"].values()) in (99, 100, 101)


def test_streaks(store, imported):
    store, _ = imported
    for day in ("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-10"):
        log_food(store, "a banana", at=f"{day}T09:00:00-05:00")
    s = streaks(store, "2026-09-23")  # nothing yet today: the streak still stands
    assert s["logging_days"] == 3 and s["logging_best"] == 3 and not s["logged_today"]
    assert streaks(store, "2026-09-24")["logging_days"] == 0
    assert s["training_weeks"] >= 1


def test_workouts_show_on_the_day(imported):
    store, sessions = imported
    started = store.session(sessions[-1])["started_at"]
    log_food(store, "a banana", at=started)
    d = day_summary(store, date.fromisoformat(started[:10]))
    assert [w["id"] for w in d["workouts"]] == [sessions[-1]]


@pytest.mark.parametrize("text, items", [
    ("chicken breast, 200 g", [("chicken breast", 200, "g")]),
    ("salmon, 6 oz and rice, 1 cup", [("salmon", 6, "oz"), ("rice", 1, "cup")]),
    ("eggs, x2", [("eggs", 2, None)]),
    ("eggs, 2", [("eggs", 2, None)]),
    ("chicken breast, 2 eggs", [("chicken breast", 1, None), ("eggs", 2, None)]),
    ("3x 100g chicken breast", [("chicken breast", 300, "g")]),
])
def test_amount_after_a_comma_or_a_count(text, items):
    assert [(i["name"], i["amount"], i["unit"]) for i in parse_meal(text)[1]] == items


def test_rejects_nonsense_amounts(store):
    for bad in ({"grams": -200}, {"grams": 0}, {"kcal": -5}):
        with pytest.raises(ValueError):
            log_food(store, name="chicken breast", at=AM, **bad)
    (r,) = log_food(store, "200 g chicken breast", at=AM)
    with pytest.raises(ValueError):
        edit_food(store, r["id"], unit="cup")  # a unit alone would turn 200 g into 200 cups
    assert edit_food(store, r["id"], amount=1, unit="cup")["status"] in ("ok", "needs_amount")


def test_editing_a_label_item_keeps_its_numbers(store):
    (r,) = log_food(store, name="mystery shake", kcal=300, protein=30, carbs=20, fat=5, at=AM)
    r = edit_food(store, r["id"], amount=2)
    assert (r["status"], r["kcal"], r["protein"]) == ("manual", 600, 60)
    (g,) = log_food(store, name="bar", grams=50, kcal=200, protein=10, carbs=25, fat=8, at=AM)
    assert edit_food(store, g["id"], grams=75)["kcal"] == 300
    r = edit_food(store, r["id"], name="mystery shake (chocolate)")
    assert (r["status"], r["name"], r["kcal"]) == ("manual", "mystery shake (chocolate)", 600)

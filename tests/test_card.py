from pathlib import Path

import pytest
from PIL import Image

from bodylog import Store, import_chat, render_png, render_text, summary
from bodylog.card import MAX_H, layout, page_height
from bodylog.muscles import muscle, split

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name, unit=None):
    store = Store(":memory:")
    r = import_chat(store, (FIXTURES / f"{name}.txt").read_text())
    return summary(store, r.sessions[-1], unit)


def _covered(s, pages):
    """(exercise index, set index) pairs the render model draws, in draw order."""
    return [(b["index"], j) for page in pages for b in page if b["kind"] == "exercise" for j in range(b["start"], b["end"])]


def test_text_card(imported):
    store, ids = imported
    text = render_text(summary(store, ids[-1]))
    assert text.startswith("**Push Day**\nThursday, Sep 17 · 6:05 PM\n1h 3m · 2,640 kg · 11 sets · 12 PRs\n"
                           "Muscles: Chest 55%, Shoulders 27%, Triceps 18%")
    assert "**Bench Press** · Chest · 3 sets · best 60 kg x 10 · PR: Heaviest weight, Best 1RM, Best set volume, Most reps" in text
    assert "  W. 20 kg x 10 (warm-up)\n  1. 60 kg x 10 🏆 Best 1RM, Best set volume, Most reps\n  2. 67.5 kg x 4 🏆 Heaviest weight" in text
    assert "  3. 62.5 kg x 8 @ RPE 9" in text
    assert text.endswith("This week: 2 workouts, 4,687 kg (−14% vs last week to date)")
    assert "—" not in text


@pytest.mark.parametrize("name", ["chat", "long", "mixed"])
def test_every_set_is_in_the_render_model_and_the_text(name):
    s = _fixture(name)
    pages = layout(s)
    expected = [(i, j) for i, e in enumerate(s["exercises"]) for j in range(len(e["sets"]))]
    assert _covered(s, pages) == expected
    text = render_text(s)
    for e in s["exercises"]:
        assert f"**{e['name']}**" in text
        for st in e["sets"]:
            assert f"  {st['label']}. {st['text']}" in text


def test_set_labels_and_pr_on_the_exact_set():
    s = _fixture("long")
    squat, rdl, press = s["exercises"][:3]
    assert [st["label"] for st in squat["sets"]] == ["W", "W", "1", "2", "3"]
    assert [st["label"] for st in rdl["sets"]] == ["1", "2", "F"]
    assert [st["label"] for st in press["sets"]] == ["1", "2", "D"]
    assert squat["sets"][2]["prs"] == ["weight", "e1rm", "volume"] and not any(st["prs"] for st in squat["sets"][3:])


def test_huge_session_paginates_without_losing_sets(store):
    for i in range(12):
        for r in range(9):
            store.log_set(f"cable fly variation {i}", 20 + r, 12, "kg", kind="failure" if r == 8 else "normal")
    s = summary(store)
    pages = layout(s)
    assert len(pages) > 2
    assert _covered(s, pages) == [(i, j) for i in range(12) for j in range(9)]
    assert all(page_height(p, s) <= MAX_H for p in pages)
    assert pages[0][0]["kind"] == "head" and all(p[0]["kind"] == "cont" for p in pages[1:])
    assert all(p[-1]["kind"] == "foot" for p in pages) and pages[-1][-2]["kind"] == "week"


def test_one_exercise_longer_than_a_page_is_split(store, tmp_path):
    for r in range(80):
        store.log_set("bench press", 60, 5, "kg")
    s = summary(store)
    pages = layout(s)
    assert len(pages) >= 2 and _covered(s, pages) == [(0, j) for j in range(80)]
    paths = render_png(s, tmp_path / "c.png")
    assert [p.name for p in paths] == ["c.png"] + [f"c-{n}.png" for n in range(2, len(pages) + 1)]
    assert all(Image.open(p).height <= MAX_H for p in paths)


def test_mixed_units_convert_before_summing():
    s = _fixture("mixed", "lb")
    # 42.5 kg x 15 + 25 kg x 12 in lb, plus 65 lb x 20 + 30 lb x 18 + 50 lb x 12
    expected_lb = (42.5 * 15 + 25 * 12) / 0.45359237 + 65 * 20 + 30 * 18 + 50 * 12
    assert s["unit"] == "lb" and s["volume"] == round(expected_lb, 1)
    kg = _fixture("mixed", "kg")
    assert kg["unit"] == "kg" and abs(kg["volume"] - expected_lb * 0.45359237) < 0.1
    # each set keeps the unit it was logged in
    push = s["exercises"][3]
    assert [st["text"] for st in push["sets"]] == ["25 kg x 12", "50 lb x 12"]
    assert render_text(s).split("\n")[2] == f"45m · {round(expected_lb):,} lb · 8 sets · 6 PRs"


def test_preferred_unit_from_env(monkeypatch):
    monkeypatch.setenv("BODYLOG_UNIT", "lb")
    assert _fixture("chat")["unit"] == "lb"


@pytest.mark.parametrize("name", ["chat", "long", "mixed"])
def test_muscle_split_sums_to_100(name):
    s = _fixture(name)
    assert sum(m["pct"] for m in s["muscles"]) == 100
    assert sum(m["sets"] for m in s["muscles"]) == s["sets"]


def test_muscle_split_rounding_and_map():
    assert sum(m["pct"] for m in split({"Chest": 1, "Back": 1, "Abs": 1})) == 100
    assert sum(m["pct"] for m in split({"Chest": 7, "Back": 5, "Quads": 3, "Abs": 1, "Calves": 1})) == 100
    assert split({}) == []
    cases = {"Bench Press": "Chest", "close grip bench press": "Triceps", "lat pulldown": "Back",
             "romanian deadlift": "Hamstrings", "leg curl": "Hamstrings", "incline db curls": "Biceps",
             "glute kickback": "Glutes", "tricep kickbacks": "Triceps", "ohp": "Shoulders", "calf press": "Calves",
             "hip thrust": "Glutes", "hanging leg raise": "Abs", "something new": "Other", None: "Other"}
    assert {k: muscle(k) for k in cases} == cases


def test_png_cards_render(tmp_path):
    """The three fixtures as README-style cards (scripts/render_examples.py writes the real examples/)."""
    for name, unit in (("chat", None), ("long", None), ("mixed", "lb")):
        s = _fixture(name, unit)
        out = "card" if name == "chat" else name  # tonight's session keeps v1's file names
        for theme in ("dark", "light"):
            paths = render_png(s, tmp_path / f"{out}-{theme}.png", theme)
            assert len(paths) == len(layout(s))
            for path in paths:
                img = Image.open(path)
                assert img.width == 1080 and 600 < img.height <= MAX_H
                assert img.getpixel((5, 5)) == Image.new("RGB", (1, 1), {"dark": "#0C0D0F", "light": "#F2F3F5"}[theme]).getpixel((0, 0))
        assert render_text(s).startswith("**")
        story = Image.open(render_png(s, tmp_path / f"{out}-story.png", "dark", style="story")[0])
        assert story.size == (1080, 1920)
    # the sticker variant: transparent outside the surfaces
    clear = Image.open(render_png(_fixture("chat"), tmp_path / "card-clear.png", "clear")[0])
    assert clear.mode == "RGBA" and clear.getpixel((5, 5))[3] == 0 and clear.getpixel((540, 600))[3] == 255


def test_story_lists_every_exercise_and_grows_instead_of_cutting(store, tmp_path):
    for i in range(30):
        store.log_set(f"machine press variation {i}", 40, 10, "kg")
    s = summary(store)
    assert [b["kind"] for b in layout(s, style="story")[0]] == ["head", "muscles", "list", "week", "foot"]
    img = Image.open(render_png(s, tmp_path / "s.png", style="story")[0])
    assert img.height > 1920  # 30 rows do not fit a phone screen; the image grows rather than hiding any
    with pytest.raises(ValueError):
        layout(s, style="poster")


def test_png_handles_open_session_and_long_names(store, tmp_path):
    store.log_set("single arm cable crossover with a very long description that will not fit", 10, 12, "kg")
    s = summary(store)
    assert s["open"]
    img = Image.open(render_png(s, tmp_path / "c.png", "light")[0])
    assert img.width == 1080

"""Rebuild src/bodylog/data/common_foods.json from two USDA FoodData Central CSV downloads.

    curl -LO https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
    curl -LO https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_csv_2024-10-31.zip
    unzip '*.zip'
    python scripts/build_common_foods.py FoodData_Central_sr_legacy_food_csv_2018-04 \
        FoodData_Central_survey_food_csv_2024-10-31

SR Legacy for most foods; FNDDS (survey) where SR Legacy has no household portion (a scoop, a slice of
pizza, a glass of wine). Every number in the output comes from those datasets; each entry keeps its fdc_id so it can be checked at
https://fdc.nal.usda.gov/food-details/<fdc_id>/nutrients. `count` names the portion a bare count
("2 eggs") means.
"""
import csv
import json
import re
import sys
from pathlib import Path

# name, fdc_id, other names people say, the portion a bare count means
FOODS = [
    ("egg", 171287, ["eggs", "whole egg", "boiled egg", "fried egg", "scrambled eggs"], "large"),
    ("egg white", 172183, ["egg whites"], "large"),
    ("white bread", 174924, ["bread", "slice of bread"], "slice"),
    ("toast", 174925, ["white toast"], "slice"),
    ("whole wheat bread", 172688, ["wheat bread", "whole wheat toast", "brown bread", "wholemeal bread"], "slice"),
    ("bagel", 174899, ["plain bagel"], "bagel"),
    ("flour tortilla", 175037, ["tortilla", "wrap"], "tortilla"),
    ("chicken breast", 171477, ["chicken", "grilled chicken", "roast chicken"], "breast"),
    ("white rice", 168878, ["rice", "cooked rice"], "cup"),
    ("brown rice", 169704, [], "cup"),
    ("pasta", 169737, ["spaghetti", "penne", "noodles"], "cup"),
    ("oats", 173904, ["rolled oats", "dry oats"], "cup"),
    ("quinoa", 168917, [], "cup"),
    ("baked potato", 170093, ["potato", "potatoes"], "potato medium"),
    ("sweet potato", 168483, ["sweet potatoes"], "medium"),
    ("banana", 173944, ["bananas"], "medium"),
    ("apple", 171688, ["apples"], "medium"),
    ("orange", 169097, ["oranges"], "fruit"),
    ("strawberries", 167762, ["strawberry"], "cup"),
    ("blueberries", 171711, ["blueberry"], "cup"),
    ("grapes", 174683, ["grape"], "cup"),
    ("avocado", 2709223, ["avocados"], "fruit"),
    ("broccoli", 170379, [], "cup"),
    ("spinach", 168462, [], "cup"),
    ("carrot", 170393, ["carrots"], "medium"),
    ("tomato", 170457, ["tomatoes"], "medium"),
    ("cucumber", 168409, [], "cup"),
    ("romaine lettuce", 169247, ["lettuce", "salad greens"], "cup"),
    ("whole milk", 171265, ["milk"], "cup"),
    ("2% milk", 171267, ["reduced fat milk", "semi skimmed milk"], "cup"),
    ("greek yogurt", 170894, ["plain greek yogurt", "greek yoghurt"], "container"),
    ("cottage cheese", 172182, [], "cup"),
    ("cheddar", 173414, ["cheddar cheese", "cheese"], "slice"),
    ("mozzarella", 170845, ["mozzarella cheese"], "oz"),
    ("cream cheese", 173418, [], "tbsp"),
    ("butter", 173410, [], "pat"),
    ("olive oil", 171413, ["oil"], "tbsp"),
    ("peanut butter", 172470, ["pb"], "tbsp"),
    ("almonds", 170567, ["almond"], "almond"),
    ("hummus", 174289, [], "tbsp"),
    ("honey", 169640, [], "tbsp"),
    ("sugar", 169655, [], "tsp"),
    ("dark chocolate", 170273, [], "oz"),
    ("chocolate chip cookie", 172716, ["cookie", "cookies"], "cookie"),
    ("whey protein", 2710742, ["protein shake", "protein powder", "whey", "whey shake"], "scoop, nfs"),
    ("ground beef", 174033, ["beef patty", "burger patty"], "patty"),
    ("steak", 2705823, ["beef steak"], "regular"),
    ("salmon", 175168, ["salmon fillet"], "fillet"),
    ("tuna", 173709, ["canned tuna", "tuna can"], "can"),
    ("shrimp", 171971, ["prawns"], "large"),
    ("bacon", 168322, ["bacon strips"], "slice"),
    ("ham", 173864, ["sliced ham"], "slice"),
    ("tofu", 172475, ["firm tofu"], "cup"),
    ("black beans", 173735, ["beans"], "cup"),
    ("lentils", 172421, [], "cup"),
    ("coffee", 171890, ["black coffee"], "cup"),
    ("cola", 174852, ["coke", "soda"], "can"),
    ("orange juice", 169098, ["oj"], "cup"),
    ("beer", 168746, [], "can"),
    ("red wine", 2710688, ["wine"], "glass"),
    ("cheese pizza", 2708614, ["pizza", "slice of pizza"], "piece, medium pizza"),
    ("pancake", 167926, ["pancakes"], "pancake"),
]
# SR Legacy uses nutrient ids, FNDDS the older nutrient numbers
NUTRIENTS = {"1008": "kcal", "1003": "protein", "1005": "carbs", "1004": "fat",
             "208": "kcal", "203": "protein", "205": "carbs", "204": "fat"}
SHORT = {"tablespoon": "tbsp", "teaspoon": "tsp", "milliliter": "ml", "undetermined": ""}
DATASETS = {"sr_legacy_food": "SR Legacy", "survey_fndds_food": "FNDDS"}


def portion_label(p, units) -> str:
    """(label, amount): ("cup, chopped", 1), ("bottle", 0.5). SR Legacy keeps the unit in measure_unit or
    modifier and the count in amount; FNDDS writes it all in the description ("1/2 bottle") and codes modifier."""
    unit = units.get(p["measure_unit_id"], "")
    amount, desc = float(p["amount"] or 1), p["portion_description"]
    if m := re.match(r"(\d+)(?:/(\d+))?\s+(.*)", desc):
        amount, desc = int(m[1]) / int(m[2] or 1), m[3]
    modifier = "" if p["modifier"].isdigit() else p["modifier"]
    words = " ".join(x for x in (unit, modifier, desc) if x).lower().split()
    return " ".join(filter(None, (SHORT.get(w, w) for w in words))), amount


def main(*dirs: str):
    want = {str(f[1]) for f in FOODS}
    desc, dataset, nut, portions = {}, {}, {i: {} for i in want}, {i: [] for i in want}
    for d in map(Path, dirs):
        rows = lambda f: csv.DictReader(open(d / f, newline=""))  # noqa: E731
        units = {r["id"]: r["name"] for r in rows("measure_unit.csv")}
        for r in rows("food.csv"):
            if r["fdc_id"] in want:
                desc[r["fdc_id"]], dataset[r["fdc_id"]] = r["description"], DATASETS[r["data_type"]]
        for r in rows("food_nutrient.csv"):
            if r["fdc_id"] in want and r["nutrient_id"] in NUTRIENTS:
                nut[r["fdc_id"]][NUTRIENTS[r["nutrient_id"]]] = float(r["amount"])
        for r in rows("food_portion.csv"):
            if r["fdc_id"] in want and float(r["gram_weight"] or 0) > 0:
                label, amount = portion_label(r, units)
                portions[r["fdc_id"]].append({"label": label, "grams": round(float(r["gram_weight"]) / amount, 2)})
    out, bad = [], []
    for name, fdc_id, aliases, count in FOODS:
        i = str(fdc_id)
        missing = set(NUTRIENTS.values()) - set(nut[i])
        if missing:
            sys.exit(f"{name} ({fdc_id}) lacks {missing}")
        if not any(p["label"].startswith(count) for p in portions[i]):  # bodylog.food.portion() picks exact, then prefix
            bad.append(f"{name} ({fdc_id}) has no portion starting {count!r}: {[p['label'] for p in portions[i]]}")
        out.append({"name": name, "aliases": aliases, "fdc_id": fdc_id, "dataset": dataset[i], "description": desc[i],
                    "per_100g": {k: nut[i][k] for k in ("kcal", "protein", "carbs", "fat")},
                    "count": count, "portions": portions[i]})
    if bad:
        sys.exit("\n".join(bad))
    dest = Path(__file__).resolve().parents[1] / "src" / "bodylog" / "data" / "common_foods.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps({"source": "USDA FoodData Central: SR Legacy (2018-04) and FNDDS (2024-10-31)",
                                "url": "https://fdc.nal.usda.gov/", "foods": out}, indent=1) + "\n")
    print(f"wrote {len(out)} foods to {dest}")


if __name__ == "__main__":
    main(*sys.argv[1:])

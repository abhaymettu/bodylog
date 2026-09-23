"""Food data from public sources: Open Food Facts (barcodes and branded products, no key) and USDA
FoodData Central (generic foods; key from $FDC_API_KEY, else DEMO_KEY).

Every lookup returns foods in one shape:
    {"source": "off" | "fdc", "source_id": str, "name": str, "brand": str | None,
     "per_100g": {"kcal", "protein", "carbs", "fat"}, "portions": [{"label", "grams"}], "count": label | None}
`fetch` is the only function that touches the network; tests replace it."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import APP, __version__

UA = f"{APP}/{__version__} (+https://github.com/abhaymettu/{APP})"  # Open Food Facts asks for a named agent
OFF_PRODUCT = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_SEARCH = "https://search.openfoodfacts.org/search"
FDC_SEARCH = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFF_FIELDS = "code,product_name,brands,nutriments,serving_size,serving_quantity"
FDC_TYPES = ["Survey (FNDDS)", "SR Legacy", "Foundation"]  # FNDDS first: foods as eaten, with household portions
FDC_IDS = {"kcal": (1008, 2048, 2047), "protein": (1003,), "carbs": (1005,), "fat": (1004,)}


class SourceError(Exception):
    """A source could not be reached or answered with an error; the caller keeps the item and flags it."""


def offline() -> bool:
    return os.environ.get(f"{APP.upper()}_OFFLINE", "") not in ("", "0")


def fetch(url: str, params: dict | None = None, body: dict | None = None) -> dict:
    if offline():
        raise SourceError(f"{APP.upper()}_OFFLINE is set")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"User-Agent": UA, "Accept": "application/json",
                                             **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SourceError(f"{url.split('?')[0]}: HTTP {e.code}") from e
    except (OSError, ValueError) as e:
        raise SourceError(f"{url.split('?')[0]}: {e}") from e


# ---- Open Food Facts ------------------------------------------------------------------------------

def _off_food(p: dict) -> dict | None:
    n = p.get("nutriments") or {}
    kcal = n.get("energy-kcal_100g")
    if kcal is None and n.get("energy-kj_100g") is not None:
        kcal = n["energy-kj_100g"] / 4.184
    if kcal is None:
        return None  # a product without a nutrition table is no use for counting
    brands = p.get("brands")
    brand = ", ".join(brands) if isinstance(brands, list) else brands or None
    portions = []
    try:
        if float(p.get("serving_quantity") or 0) > 0:
            portions.append({"label": "serving" + (f" ({p['serving_size']})" if p.get("serving_size") else ""),
                             "grams": float(p["serving_quantity"])})
    except (TypeError, ValueError):
        pass
    return {"source": "off", "source_id": str(p.get("code")), "name": (p.get("product_name") or "").strip() or str(p.get("code")),
            "brand": brand, "per_100g": {"kcal": round(float(kcal), 1), "protein": n.get("proteins_100g"),
                                         "carbs": n.get("carbohydrates_100g"), "fat": n.get("fat_100g")},
            "portions": portions, "count": portions[0]["label"] if portions else None}


def off_product(barcode: str) -> dict | None:
    """A packaged product by EAN/UPC barcode; None when Open Food Facts does not know it."""
    code = re.sub(r"\D", "", barcode)
    d = fetch(OFF_PRODUCT.format(code=code), {"fields": OFF_FIELDS})
    if d.get("status") != 1 or not d.get("product"):
        return None
    return _off_food({"code": code, **d["product"]})


def off_search(query: str, n: int = 5) -> list[dict]:
    d = fetch(OFF_SEARCH, {"q": query, "page_size": n, "fields": OFF_FIELDS})
    return [f for f in map(_off_food, d.get("hits") or []) if f]


# ---- USDA FoodData Central ------------------------------------------------------------------------

def _fdc_food(f: dict) -> dict | None:
    got = {n.get("nutrientId"): n.get("value") for n in f.get("foodNutrients", [])}
    per = {k: next((got[i] for i in ids if got.get(i) is not None), None) for k, ids in FDC_IDS.items()}
    if per["kcal"] is None:
        return None
    portions = []
    for m in sorted(f.get("foodMeasures") or [], key=lambda m: m.get("rank") or 0):
        text, grams = (m.get("disseminationText") or "").lower(), m.get("gramWeight")
        if not grams:
            continue
        if text == "quantity not specified":  # USDA's own portion for a food named without an amount
            text = "usual portion"
        amount = 1.0
        if mm := re.match(r"(\d+)(?:/(\d+))?\s+(.*)", text):
            amount, text = int(mm[1]) / int(mm[2] or 1), mm[3]
        portions.append({"label": text, "grams": round(grams / amount, 2)})
    return {"source": "fdc", "source_id": str(f["fdcId"]), "name": f.get("description", ""), "brand": f.get("brandOwner"),
            "per_100g": per, "portions": portions,
            "count": next((p["label"] for p in portions if p["label"] == "usual portion"), None)}


def fdc_search(query: str, n: int = 5) -> list[dict]:
    key = os.environ.get("FDC_API_KEY") or "DEMO_KEY"
    d = fetch(f"{FDC_SEARCH}?api_key={urllib.parse.quote(key)}", body={"query": query, "dataType": FDC_TYPES, "pageSize": n})
    return [f for f in map(_fdc_food, d.get("foods") or []) if f]

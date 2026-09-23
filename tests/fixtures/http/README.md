Real responses recorded on 2026-09-23, trimmed to the fields bodylog reads. Tests serve them in place of
the network (see `recorded` in tests/conftest.py); a recording may be served for a different query to
stand in for "this source found nothing".

| File | Request |
| --- | --- |
| fdc_search_kimchi.json | GET https://api.nal.usda.gov/fdc/v1/foods/search?query=kimchi&dataType=Survey (FNDDS),SR Legacy,Foundation&pageSize=5&api_key=DEMO_KEY |
| fdc_search_empty.json | POST https://api.nal.usda.gov/fdc/v1/foods/search?api_key=DEMO_KEY `{"query": "chicken tikka masala", "dataType": ["Survey (FNDDS)", "SR Legacy"], "pageSize": 5, "requireAllWords": true}` (0 hits) |
| off_product_3017624010701.json | GET https://world.openfoodfacts.org/api/v2/product/3017624010701.json?fields=code,product_name,brands,nutriments,serving_size,serving_quantity |
| off_product_missing.json | GET https://world.openfoodfacts.org/api/v2/product/0000000000017.json?fields=... |
| off_search_clif.json | GET https://search.openfoodfacts.org/search?q=clif bar chocolate chip&page_size=5&fields=... |

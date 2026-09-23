# Spec 003: bodylog (workouts + food, one package)


## What

Rename workout-log to bodylog without rewriting it, and add a food tracker in the same package, the
same SQLite file and the same card style. Publish-ready, not published.

## Requirements

1. One name, changeable in one place in code (`bodylog.APP`) plus the packaging files.
2. Meals from plain text: split into items; amount and unit per item; kcal, protein, carbs, fat.
   Unknown items are stored and flagged, never dropped and never given invented numbers.
3. Data: a bundled table of common foods, each entry with its USDA FDC id; USDA FoodData Central search
   (`FDC_API_KEY`, else `DEMO_KEY`); Open Food Facts search and barcode lookup. Lookups cached in SQLite.
4. Daily totals against optional goals; logging streak (days) and training streak (weeks).
5. A day card (dark, light, clear; full and story) in the workout card's visual language, with the
   day's workouts on it.
6. MCP tools, CLI commands and skill text for all of the above.
7. pyproject, README marker, server.json, Claude plugin manifests; `uv build` and `twine check` pass.

## Acceptance

Tests run offline (recorded API responses, network blocked by an autouse fixture) and write only to
temp dirs. They cover the parser on the brief's examples, bundled-table citations, unit conversion,
flagged items staying out of totals, the search-hit word rule, cache reuse, the OFF fallback, barcodes,
edits, goals, streaks and card rendering in every theme and style.

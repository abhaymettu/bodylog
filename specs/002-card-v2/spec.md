# Spec 002: summary card v2 (Hevy parity)


## What

The v1 card left out information Hevy shows and did not look like Hevy's summary card. v2 matches
Hevy's summary and share card feature for feature, then
improves on it. The PNG is the product; the markdown text stays as the fallback.

## Requirements

1. Every exercise and every set is drawn. No truncation: the card grows, and a session taller than
   the page cap continues on further PNGs.
2. Each set row: set number, or W / D / F for warm-up, drop and failure sets; weight in the unit it was
   logged in; reps; RPE; a PR tag on the exact set that broke a record.
3. Muscle-group split as share of working sets, from an exercise-to-muscle map shipped in the package
   (unknown names count as Other). Percentages sum to exactly 100.
4. Header stats: duration, volume, sets, records. A week strip, restyled.
5. Totals in the user's preferred unit (argument, then `$WORKOUT_LOG_UNIT`, then the session's
   majority unit), converting every set exactly before summing.
6. Dark and light themes. Set types and PRs readable without color (letters, trophy plus text).
7. The text fallback lists every exercise and every set.
8. Examples rendered from three fixtures: tonight's push day, an 8-exercise session, a mixed-unit
   session.

## Acceptance

Tests cover: every (exercise, set) pair appears once in the render model and the text, pagination of
a huge session and of one exercise longer than a page, kg/lb conversion against a hand-computed
total, the preferred-unit override, and the muscle split summing to 100.

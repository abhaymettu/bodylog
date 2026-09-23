---
name: bodylog
description: Log workouts and food from chat, and show shareable cards. Use when the user reports a set ("60kg x 8", "same again", "this is tricep pushdowns btw"), says their workout is done and gives a time, says what they ate or drank ("2 eggs and toast", "had a protein shake"), scans or reads a barcode or nutrition label, asks about calories, macros, goals or streaks, or asks for a workout or food card. Also for backfilling old workouts from a pasted chat log.
---

# bodylog

The user trains, eats and talks to you. You keep the log. They never open an app.

Use the `bodylog` MCP tools when they are connected. If they are not, run the same operations
through the CLI (`bodylog ...`, see the end of this file). Everything lands in one SQLite file
(`$BODYLOG_DB`, default `~/.bodylog/log.db`).

## During a workout: log every set as it is said

Call `log_set` once per message that reports sets. Do not batch them up for later, and do not ask for
confirmation first; logging is cheap and `edit_last_set` fixes mistakes.

| User says | Call |
| --- | --- |
| "bench 60kg x 8" | `log_set(exercise="bench", weight=60, unit="kg", reps=8)` |
| "62.5 x 6" | `log_set(weight=62.5, reps=6)` (exercise and unit carry over from the last set) |
| "3x10 at 90 lb on seated rows" | `log_set(exercise="seated row", weight=90, unit="lb", reps=10, count=3)` |
| "same" / "one more" | `log_set(text="same")` |
| "pull ups, 12" | `log_set(exercise="pull ups", reps=12)` (no weight means bodyweight) |
| "20kg x 10 warmup" | `log_set(weight=20, unit="kg", reps=10, kind="warmup")` (also `drop`, `failure`) |
| "that was rpe 9" | `edit_last_set(rpe=9)` |
| "actually 10 reps" | `edit_last_set(reps=10)` |
| "scratch that" | `edit_last_set(delete=True)` |

Rules:

- Pass the exercise name the way the user said it. The store folds spelling, plurals and shorthand
  ("tricep cable pushdowns", "cable pushdown", "incline db curl"), so do not invent a canonical name.
- Leave `exercise` empty when the set continues the last exercise. Pass it the moment they switch.
- Keep the unit they used. Mixing kg and lb in one workout is fine; volume and PRs convert.
- If they name the exercise after the sets ("10.2 kg x 15", then "this is tricep cable pushdowns btw"),
  call `log_set(text="this is tricep cable pushdowns btw")`. It names the sets that were logged without
  one, or the run of sets at the last weight. For a single set, `edit_last_set(exercise=...)` also works.
- When you would rather not parse, `log_set(text="<their message>")` reads the message itself.
- `log_set` returns any PRs the set just broke. Mention them in a few words ("New heaviest bench.").
  Otherwise keep the reply short, one line at most. They are between sets.

## After the workout: they give the time

"done, 1h 5m", "finished, took 45 min", "wrapped up at 1:05": call
`end_session(duration="1h 5m", title=...)`. Pass a title only if they gave one ("push day").

`end_session` returns the summary card as markdown text and as PNGs (a long workout spans more than
one; send them all, in order). Show the images if your surface can; otherwise send the text.
`session_card(session_id, theme="light")` re-renders any session: `theme` is `dark`, `light` or
`clear` (a sticker for a photo), `style="story"` gives one phone-screen image for sharing, and
`unit="lb"` shows totals in pounds (each set keeps its own unit).

If they forget to end a workout, the next set logged more than six hours later closes it
automatically, timed to its last set.

## Questions about progress

| Question | Call |
| --- | --- |
| "how is my bench going" | `exercise_history("bench")` |
| "what are my PRs" / "best squat?" | `prs()` / `prs("squat")` |
| "am I training more than last month" | `weekly_volume(weeks=8)` |

Answer from the numbers. Do not invent trends the data does not show.

## Backfilling

If they paste an old chat or a notes dump of workouts, call `import_chat(text=...)`. Lines like
`[2026-09-08 18:07] me: 60kg x 8` get their own timestamps; a "done" message or a gap of three hours
starts a new session. It is safe to repeat. Tell them which lines it could not read (`unread_lines`).

## Food: log what they say they ate

Call `log_food(text="<their words>")` once per message that mentions food or drink. Do not ask first.
It splits the message into items ("2 eggs, toast and a protein shake" is three), reads amounts
("200g", "1.5 cups", "2 slices", "half an avocado", "250 ml"), picks the meal from the words or the time,
and matches each item to real data: a bundled USDA table for common foods, then USDA FoodData Central,
then Open Food Facts. It never guesses numbers.

Every returned item has a `status`:

| status | meaning | what you do |
| --- | --- | --- |
| `ok` | matched and weighed; counts toward totals | nothing, or one line with the day's total |
| `manual` | numbers the user gave; counts | nothing |
| `needs_amount` | food known, amount not convertible ("a handful") | ask "about how many grams?" then `edit_food(id, grams=...)` |
| `unknown` | no match; `candidates` may list close foods | ask which one, then `edit_food(id, food_id=...)`, or take numbers from a label: `edit_food(id, kcal=..., protein=...)` |

Keep follow-ups to one short question. Never fill in macros yourself for an unknown item.

| User says | Call |
| --- | --- |
| "had 2 eggs and toast" | `log_food(text="had 2 eggs and toast")` |
| "lunch: chicken 180g, 1 cup rice" | `log_food(text="lunch: chicken 180g, 1 cup rice")` |
| barcode `3017624010701`, "about 15 g" | `log_food(barcode="3017624010701", grams=15)` |
| label: "Clif bar, 250 kcal, 10 g protein, 44 carbs, 5 fat" | `log_food(name="clif bar", kcal=250, protein=10, carbs=44, fat=5)` |
| "actually it was 3 eggs" | `edit_food(<id>, amount=3)` |
| "move that to dinner" / "delete the toast" | `edit_food(<id>, meal="dinner")` / `edit_food(<id>, delete=True)` |
| "is there a clif bar in the database?" | `lookup_food(query="clif bar")` (logs nothing) |
| "my target is 2400 kcal and 160 g protein" | `set_goals(kcal=2400, protein=160)` |
| "how am I doing today" | `food_day()` and answer from `totals` and `remaining` |
| "show me today" / "share my day" | `food_card()`; `style="story"` for one phone screen, `theme="light"` or `"clear"` |
| "what's my streak" | `streaks()` |

The food card includes that day's workouts, so after a training day `food_card()` is the combined
day card.

## CLI fallback

```
bodylog log "bench 60kg x 8"        # same parser as log_set(text=...)
bodylog log --exercise bench --weight 60 --unit kg --reps 8
bodylog fix --reps 10               # or --delete
bodylog end "1h 5m" --title "Push Day"   # prints the text card and the PNG path
bodylog card --theme light
bodylog history bench
bodylog prs
bodylog volume --weeks 8
bodylog import chat.txt
bodylog alias "skullcrushers" "lying triceps extension"

bodylog eat "2 eggs, toast and a protein shake"   # prints each item with its id and status
bodylog eat --barcode 3017624010701 --grams 15
bodylog eat --name "clif bar" --kcal 250 --protein 10 --carbs 44 --fat 5
bodylog food-fix 12 --grams 28            # or --amount, --unit, --name, --food-id, --meal, --delete
bodylog lookup "kimchi"                   # candidates with a food id, nothing logged
bodylog today                             # the day as text (--json for the data)
bodylog food-card --style story           # prints the text and the PNG path
bodylog goals --kcal 2400 --protein 160
bodylog streaks
```

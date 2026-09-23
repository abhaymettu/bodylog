"""Command line: the same operations as the MCP server, for agents that shell out."""
import argparse
import json
import sys
from pathlib import Path

from . import APP, card, chatlog, food, foodcard, stats
from .store import Store


def _print(obj):
    print(json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj)


def _card(store, session_id, theme, out, unit=None, style="full"):
    s = stats.summary(store, session_id, unit)
    name = f"session-{s['id']}-{theme}" + ("-story" if style == "story" else "")
    paths = card.render_png(s, out or Path.home() / f".{APP}" / "cards" / f"{name}.png", theme, style=style)
    print(card.render_text(s))
    print("\n" + "\n".join(f"card: {p}" for p in paths))


def main(argv=None):
    ap = argparse.ArgumentParser(prog=APP, description="Log workouts and food from chat, render shareable cards, show trends.")
    ap.add_argument("--db", help=f"SQLite file (default ${APP.upper()}_DB or ~/.{APP}/log.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help='log from a chat message: bodylog log "bench 60kg x 8"')
    p.add_argument("text", nargs="?")
    p.add_argument("--exercise")
    p.add_argument("--weight", type=float)
    p.add_argument("--reps", type=int)
    p.add_argument("--unit")
    p.add_argument("--rpe", type=float)
    p.add_argument("--kind", default="normal", choices=["normal", "warmup", "drop", "failure"])
    p.add_argument("--count", type=int, default=1)

    p = sub.add_parser("fix", help="edit or delete the last set")
    for f in ("exercise", "unit", "kind", "notes"):
        p.add_argument(f"--{f}")
    p.add_argument("--weight", type=float)
    p.add_argument("--reps", type=int)
    p.add_argument("--rpe", type=float)
    p.add_argument("--delete", action="store_true")

    p = sub.add_parser("end", help='end the open workout: bodylog end "1h 5m"')
    p.add_argument("duration", nargs="?")
    p.add_argument("--title")
    p.add_argument("--theme", default="dark", choices=list(card.THEMES))
    p.add_argument("--unit", choices=["kg", "lb"], help="unit for totals (default $BODYLOG_UNIT, else the session's most-logged)")
    p.add_argument("--out")

    p = sub.add_parser("card", help="summary card for a session (default: open, else latest)")
    p.add_argument("--session", type=int)
    p.add_argument("--style", default="full", choices=["full", "story"],
                   help="full: every set, pages if long; story: one phone screen, one line per exercise")
    p.add_argument("--theme", default="dark", choices=list(card.THEMES))
    p.add_argument("--unit", choices=["kg", "lb"], help="unit for totals (default $BODYLOG_UNIT, else the session's most-logged)")
    p.add_argument("--out")

    p = sub.add_parser("history", help="per-session history for one exercise")
    p.add_argument("exercise")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("prs", help="all-time records")
    p.add_argument("exercise", nargs="?")

    p = sub.add_parser("volume", help="volume per week")
    p.add_argument("--weeks", type=int, default=8)

    p = sub.add_parser("import", help="backfill from a chat log file ('-' for stdin)")
    p.add_argument("file")

    p = sub.add_parser("alias", help='teach a name: bodylog alias "skullcrushers" "lying triceps extension"')
    p.add_argument("alias")
    p.add_argument("exercise")

    p = sub.add_parser("eat", help=f'log food: {APP} eat "2 eggs, toast and a protein shake"')
    p.add_argument("text", nargs="?")
    p.add_argument("--name")
    p.add_argument("--grams", type=float)
    p.add_argument("--amount", type=float)
    p.add_argument("--unit")
    p.add_argument("--barcode")
    p.add_argument("--food-id", type=int)
    p.add_argument("--meal", choices=list(food.MEALS))
    for m in food.MACROS:
        p.add_argument(f"--{m}", type=float)

    p = sub.add_parser("food-fix", help="fix or delete a logged food item by id")
    p.add_argument("id", type=int)
    p.add_argument("--name")
    p.add_argument("--grams", type=float)
    p.add_argument("--amount", type=float)
    p.add_argument("--unit")
    p.add_argument("--food-id", type=int)
    p.add_argument("--meal", choices=list(food.MEALS))
    for m in food.MACROS:
        p.add_argument(f"--{m}", type=float)
    p.add_argument("--delete", action="store_true")

    p = sub.add_parser("lookup", help="search foods without logging (a name, or --barcode)")
    p.add_argument("query", nargs="?")
    p.add_argument("--barcode")

    p = sub.add_parser("today", help="a day of food as text (default today)")
    p.add_argument("--date")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("food-card", help="shareable card for a day of food")
    p.add_argument("--date")
    p.add_argument("--style", default="full", choices=["full", "story"])
    p.add_argument("--theme", default="dark", choices=list(card.THEMES))
    p.add_argument("--out")

    p = sub.add_parser("goals", help="show or set daily goals: --kcal 2400 --protein 160 (0 clears)")
    for m in food.MACROS:
        p.add_argument(f"--{m}", type=float)

    sub.add_parser("streaks", help="logging streak (days) and training streak (weeks)")
    sub.add_parser("mcp", help="run the MCP server on stdio (same as bodylog-mcp)")

    a = ap.parse_args(argv)
    if a.cmd == "mcp":
        from . import server

        return server.main()
    store = Store(a.db)
    try:
        if a.cmd == "log":
            if a.text:
                _print("\n".join(chatlog.log_text(store, a.text)))
            else:
                rows = store.log_set(a.exercise, a.weight, a.reps, a.unit, a.rpe, a.kind, count=a.count)
                _print("\n".join(f"{r['exercise'] or 'unnamed'}: {stats.fmt_set(r)}" for r in rows))
        elif a.cmd == "fix":
            row = store.edit_last_set(delete=a.delete, exercise=a.exercise, weight=a.weight, reps=a.reps, unit=a.unit,
                                      rpe=a.rpe, kind=a.kind, notes=a.notes)
            _print("deleted last set" if row is None else f"{row['exercise'] or 'unnamed'}: {stats.fmt_set(row)}")
        elif a.cmd == "end":
            s = store.end_session(a.duration, title=a.title)
            _card(store, s["id"], a.theme, a.out, a.unit)
        elif a.cmd == "card":
            _card(store, a.session, a.theme, a.out, a.unit, a.style)
        elif a.cmd == "history":
            _print(stats.exercise_history(store, a.exercise, a.limit))
        elif a.cmd == "prs":
            _print(stats.current_prs(store, a.exercise))
        elif a.cmd == "volume":
            _print(stats.weekly_volume(store, a.weeks))
        elif a.cmd == "import":
            text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text()
            r = chatlog.import_chat(store, text)
            _print({"sessions": r.sessions, "sets": r.sets, "duplicates_skipped": r.duplicates, "unread_lines": r.skipped})
        elif a.cmd == "eat":
            macros = {m: getattr(a, m) for m in food.MACROS}
            rows = food.log_food(store, a.text, name=a.name, grams=a.grams, amount=a.amount, unit=a.unit,
                                 barcode=a.barcode, food_id=a.food_id, meal=a.meal, **macros)
            _print("\n".join(f"#{r['id']} {r['meal']}: {food.fmt_item(r)}" for r in rows))
        elif a.cmd == "food-fix":
            macros = {m: getattr(a, m) for m in food.MACROS}
            row = food.edit_food(store, a.id, delete=a.delete, name=a.name, grams=a.grams, amount=a.amount,
                                 unit=a.unit, food_id=a.food_id, meal=a.meal, **macros)
            _print("deleted" if row is None else f"#{row['id']} {row['meal']}: {food.fmt_item(row)}")
        elif a.cmd == "lookup":
            _print(food.lookup(store, a.query, a.barcode))
        elif a.cmd == "today":
            d = food.day_summary(store, a.date)
            _print(d if a.json else foodcard.render_text(d))
        elif a.cmd == "food-card":
            d = food.day_summary(store, a.date)
            name = f"food-{d['date']}-{a.theme}" + ("-story" if a.style == "story" else "")
            path = foodcard.render_png(d, a.out or Path.home() / f".{APP}" / "cards" / f"{name}.png", a.theme, a.style)
            print(foodcard.render_text(d) + f"\n\ncard: {path}")
        elif a.cmd == "goals":
            _print(food.set_goals(store, **{m: getattr(a, m) for m in food.MACROS}))
        elif a.cmd == "streaks":
            _print(food.streaks(store))
        elif a.cmd == "alias":
            _print(f"{a.alias} -> {store.alias(a.alias, a.exercise)['name']}")
    except (ValueError, LookupError) as e:
        print(f"{APP}: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

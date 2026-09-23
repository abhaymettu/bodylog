"""bodylog: workouts and food, logged from chat by an agent, with shareable cards and trends."""
APP = "bodylog"  # the one place the name lives in code: data dir, env var prefix, card footer, MCP server
__version__ = "0.1.0"

from .card import render_png, render_text  # noqa: E402
from .chatlog import import_chat, interpret, log_text  # noqa: E402
from .food import day_summary, log_food, lookup, set_goals, streaks  # noqa: E402
from .stats import current_prs, exercise_history, summary, weekly_volume  # noqa: E402
from .store import Store  # noqa: E402

__all__ = ["APP", "Store", "log_text", "interpret", "import_chat", "summary", "exercise_history", "current_prs",
           "weekly_volume", "render_text", "render_png", "log_food", "lookup", "day_summary", "set_goals", "streaks"]

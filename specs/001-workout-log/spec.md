# Spec 001: workout-log


## What

A small package any personal agent can install to turn workout chat ("60kg x 8", "this is tricep
cable pushdowns btw", "done, 1h 5m") into a stored log, a Hevy-style summary card, and trends.
Out of scope: social, plans, accounts, sync, any server beyond a local MCP stdio process.

## User stories

1. During a workout the agent logs each set as the user says it; the exercise defaults to the last one.
2. The user corrects a set ("that was 12 reps") and the agent fixes the last set.
3. After the workout the user gives the time; the agent ends the session and shows a card (PNG + text).
4. The user asks "how is my bench going" and the agent answers from history, weekly volume and PRs.
5. The agent backfills old workouts from a pasted chat log.

## Acceptance

- One SQLite file, path from `WORKOUT_LOG_DB` or `~/.workout-log/log.db`.
- "tricep cable pushdowns", "Triceps Cable Pushdown" and "cable pushdown" resolve to one exercise.
- Mixed kg/lb sets compare correctly for volume and PRs.
- PRs: heaviest weight, best estimated 1RM (Epley), most reps at a weight, each against earlier sessions.
- Card: date, duration, volume, sets and best set per exercise, PR flags, week-over-week line; dark and light; 1080 px wide.
- MCP tools: log_set, edit_last_set, end_session, session_card, exercise_history, prs (plus import_chat).
- SKILL.md teaches when to call each tool.

## Plan

Python 3.10+: stdlib sqlite3, Pillow for the PNG, the official `mcp` SDK (FastMCP) as an optional extra.
Modules: `names` (normalization), `store` (schema + logging API), `stats` (volume, PRs, trends),
`card` (text + PNG), `chatlog` (parser/import), `cli`, `server` (MCP).

## Tasks

1. names + store + tests
2. stats (PRs, history, weekly volume) + tests
3. card text + PNG, examples/ from the fixture + tests
4. chat-log parser + fixture + tests
5. CLI, MCP server, SKILL.md, README

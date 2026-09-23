"""Exercise name normalization: "tricep cable pushdowns" and "cable pushdown" share one key family."""
import re

# Whole-phrase shorthand, applied before tokenizing.
PHRASES = {
    "bench": "bench press",
    "ohp": "overhead press",
    "rdl": "romanian deadlift",
    "rdls": "romanian deadlift",
}

# Single-token spellings folded to one form.
TOKENS = {
    "db": "dumbbell", "dbs": "dumbbell", "dumbell": "dumbbell",
    "bb": "barbell", "kb": "kettlebell",
    "tricep": "triceps", "bicep": "biceps",
    "pullup": "pull up", "pullups": "pull up",
    "chinup": "chin up", "chinups": "chin up",
    "pushup": "push up", "pushups": "push up",
    "flye": "fly", "flyes": "fly", "flies": "fly",
    "presses": "press", "crunches": "crunch", "benches": "bench",
    "lats": "lat", "delts": "delt", "ups": "up", "calves": "calf",
}

FILLER = {"the", "a", "an", "btw", "on", "with", "using", "of", "my", "some", "exercise", "set", "sets", "reps"}

# Words that describe a muscle rather than the movement. Two names that differ only by these
# are the same exercise ("triceps cable pushdown" vs "cable pushdown").
DESCRIPTORS = {"triceps", "biceps", "chest", "pec", "delt", "shoulder", "lat", "quad", "hamstring", "glute", "calf", "ab", "core", "trap"}

# Movement words, used to tell an exercise mention from chat noise.
MOVEMENTS = {
    "press", "curl", "row", "squat", "deadlift", "pushdown", "pulldown", "pull", "push", "fly", "raise",
    "extension", "dip", "lunge", "shrug", "crunch", "plank", "thrust", "pullover", "kickback", "carry",
    "bench", "chin", "lat", "calf", "leg", "hip", "face", "skullcrusher", "rdl", "ohp", "clean",
    "snatch", "jerk", "swing", "step", "split", "hack", "sissy", "machine", "cable", "dumbbell", "barbell",
}

KEEP_S = {"triceps", "biceps", "abs", "press", "cross", "glutes"}


def _singular(tok: str) -> str:
    if tok in KEEP_S or len(tok) <= 3 or tok.endswith(("ss", "us")):
        return {"glutes": "glute", "abs": "ab"}.get(tok, tok)
    return tok[:-1] if tok.endswith("s") else tok


def tokens(name: str) -> list[str]:
    text = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("-", " ").replace("/", " "))
    text = " ".join(PHRASES.get(w, w) for w in text.split())
    out = []
    for w in text.split():
        for t in TOKENS.get(w, w).split():
            t = _singular(TOKENS.get(t, t))
            t = TOKENS.get(t, t)
            if t not in FILLER and t not in out:
                out.append(t)
    return out


def key(name: str) -> str:
    """Order-insensitive identity: "pushdown cable triceps" == "triceps cable pushdown"."""
    return " ".join(sorted(tokens(name)))


def display(name: str) -> str:
    return " ".join(t.upper() if t in {"ez", "rdl"} else t.capitalize() for t in tokens(name))


def close_match(new_key: str, keys: list[str]) -> str | None:
    """Existing key that differs from new_key only by muscle descriptors; None if absent or ambiguous."""
    a = set(new_key.split())
    best, best_diff, tie = None, 99, False
    for k in keys:
        b = set(k.split())
        diff = a ^ b
        if a & b - DESCRIPTORS and diff <= DESCRIPTORS and (a <= b or b <= a):
            if len(diff) < best_diff:
                best, best_diff, tie = k, len(diff), False
            elif len(diff) == best_diff:
                tie = True
    return None if tie else best


def looks_like_exercise(name: str) -> bool:
    toks = tokens(name)
    return 0 < len(toks) <= 6 and any(t in MOVEMENTS for t in toks)

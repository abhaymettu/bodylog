"""Exercise -> primary muscle group, from name tokens. First matching rule wins, so specific rules come first."""
from . import names

GROUPS = ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Forearms", "Abs",
          "Quads", "Hamstrings", "Glutes", "Calves", "Full Body", "Other")

# broad regions for the radar chart; Full Body and Other sit outside it
MACRO = {"Chest": "Chest", "Back": "Back", "Shoulders": "Shoulders", "Biceps": "Arms", "Triceps": "Arms",
         "Forearms": "Arms", "Abs": "Core", "Quads": "Legs", "Hamstrings": "Legs", "Glutes": "Legs", "Calves": "Legs"}

# (tokens that must all appear in the exercise name, group)
RULES = [
    ("calf", "Calves"),
    ("wrist curl", "Forearms"), ("reverse curl", "Forearms"), ("farmer", "Forearms"),
    ("leg curl", "Hamstrings"), ("hamstring curl", "Hamstrings"), ("nordic", "Hamstrings"),
    ("romanian deadlift", "Hamstrings"), ("stiff leg", "Hamstrings"), ("good morning", "Hamstrings"),
    ("close grip bench", "Triceps"), ("pushdown", "Triceps"), ("skullcrusher", "Triceps"), ("skull crusher", "Triceps"),
    ("triceps", "Triceps"), ("chest dip", "Chest"), ("dip", "Triceps"), ("jm press", "Triceps"),
    ("hip thrust", "Glutes"), ("glute", "Glutes"), ("bridge", "Glutes"), ("abduction", "Glutes"),
    ("kickback", "Triceps"),
    ("leg press", "Quads"), ("leg extension", "Quads"), ("squat", "Quads"), ("lunge", "Quads"), ("step up", "Quads"),
    ("sissy", "Quads"), ("adduction", "Quads"),
    ("overhead press", "Shoulders"), ("shoulder press", "Shoulders"), ("military", "Shoulders"), ("arnold", "Shoulders"),
    ("push press", "Shoulders"), ("lateral raise", "Shoulders"), ("front raise", "Shoulders"), ("rear delt", "Shoulders"),
    ("reverse fly", "Shoulders"), ("face pull", "Shoulders"), ("upright row", "Shoulders"), ("delt", "Shoulders"),
    ("shoulder", "Shoulders"),
    ("curl", "Biceps"), ("biceps", "Biceps"),
    ("pulldown", "Back"), ("pull up", "Back"), ("chin up", "Back"), ("row", "Back"), ("deadlift", "Back"),
    ("shrug", "Back"), ("pullover", "Back"), ("back extension", "Back"), ("hyperextension", "Back"), ("lat", "Back"),
    ("crunch", "Abs"), ("plank", "Abs"), ("sit up", "Abs"), ("leg raise", "Abs"), ("knee raise", "Abs"), ("ab", "Abs"),
    ("russian twist", "Abs"), ("pallof", "Abs"), ("wood chop", "Abs"), ("core", "Abs"),
    ("bench", "Chest"), ("fly", "Chest"), ("crossover", "Chest"), ("push up", "Chest"), ("pec", "Chest"),
    ("chest", "Chest"), ("incline press", "Chest"), ("decline press", "Chest"), ("press", "Chest"),
    ("clean", "Full Body"), ("snatch", "Full Body"), ("thruster", "Full Body"), ("burpee", "Full Body"),
    ("swing", "Full Body"), ("carry", "Forearms"),
]
_RULES = [(set(names.tokens(t)), g) for t, g in RULES]


def muscle(exercise: str | None) -> str:
    toks = set(names.tokens(exercise or ""))
    return next((g for need, g in _RULES if need <= toks), "Other")


def split(counts: dict[str, int]) -> list[dict]:
    """Share of sets per group, largest first. Percents are whole numbers that sum to exactly 100
    (largest remainder), so the card never shows 33 + 33 + 33."""
    total = sum(counts.values())
    if not total:
        return []
    raw = {g: n * 100 / total for g, n in counts.items() if n}
    pct = {g: int(v) for g, v in raw.items()}
    for g in sorted(raw, key=lambda g: raw[g] - pct[g], reverse=True)[:100 - sum(pct.values())]:
        pct[g] += 1
    order = sorted(raw, key=lambda g: (-counts[g], GROUPS.index(g)))
    return [{"group": g, "sets": counts[g], "pct": pct[g]} for g in order]

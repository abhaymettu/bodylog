from bodylog import names


def test_brief_examples_share_one_exercise(store):
    a = store.exercise("tricep cable pushdowns")
    assert store.exercise("Triceps Cable Pushdown")["id"] == a["id"]
    assert store.exercise("cable pushdown")["id"] == a["id"]
    assert store.exercise("triceps pushdowns on the cable")["id"] == a["id"]
    assert a["name"] == "Triceps Cable Pushdown"


def test_shorthand_and_plurals():
    assert names.key("incline db curl") == names.key("Incline Dumbbell Curls")
    assert names.key("bench") == names.key("Bench Press")
    assert names.key("RDLs") == names.key("romanian deadlift")
    assert names.key("pullups") == names.key("pull ups")
    assert names.display("incline db curl") == "Incline Dumbbell Curl"


def test_different_movements_stay_apart(store):
    assert store.exercise("triceps curl")["id"] != store.exercise("biceps curl")["id"]
    assert store.exercise("curl")["id"] != store.exercise("incline dumbbell curl")["id"]
    assert store.exercise("leg press")["id"] != store.exercise("bench press")["id"]


def test_alias_teaches_a_name(store):
    ex = store.alias("skullcrushers", "lying triceps extension")
    assert store.exercise("skull crushers")["id"] != ex["id"]  # different tokens, not auto-merged
    assert store.find_exercise("skullcrushers")["id"] == ex["id"]


def test_chat_noise_is_not_an_exercise():
    assert not names.looks_like_exercise("ugh forearms are fried")
    assert not names.looks_like_exercise("wrapped up workout took")
    assert names.looks_like_exercise("seated cable row")

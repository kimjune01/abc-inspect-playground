"""Small browser catalog of tasks defined in the pinned ABC release."""

ABC_REV = "d0832d12651d1b260a652861a14648dc5f3660c7"
SOURCE = f"https://github.com/amazon-far/abc/blob/{ABC_REV}/abc_sim"
FIXED_COUNTS = {
    "count_one_into_opaque_box": 1,
    "count_two_into_opaque_box": 2,
    "count_three_into_opaque_box": 3,
}


def entry(task_id: str, label: str, evaluator: str):
    return {
        "id": task_id,
        "label": label,
        "source_url": f"{SOURCE}/task_specs.py",
        "evaluator_url": f"{SOURCE}/task_eval/{evaluator}.py",
        "attribution": "ABC · Amazon FAR and collaborators",
    }


SCENES = [
    {
        "id": "opaque_box",
        "label": "Opaque box",
        "hint": "Any objects count. Drop them through the flap; extras fail. Physics pauses between moves.",
        "tasks": [
            entry("count_one_into_opaque_box", "One object", "count_box"),
            entry("count_two_into_opaque_box", "Two objects", "count_box"),
            entry("count_three_into_opaque_box", "Three objects", "count_box"),
        ],
    },
    {
        "id": "letter_blocks",
        "label": "Letter blocks",
        "hint": "Arrange the letters left to right in a tight row on the table, letter faces up. Other blocks don't count.",
        "tasks": [
            entry("spell_cat", "CAT", "spell"),
            entry("spell_dog", "DOG", "spell"),
            entry("spell_fish", "FISH", "spell"),
        ],
    },
]
TASKS = {
    task["id"]: {**task, "scene_id": scene["id"], "hint": scene["hint"]}
    for scene in SCENES
    for task in scene["tasks"]
}
SUPPORTED_TASKS = frozenset((*TASKS, "count_into_opaque_box", "put_plastic_bottles_in_bin"))


def task_details(task_id: str) -> dict:
    if task_id in TASKS:
        return TASKS[task_id]
    if task_id == "count_into_opaque_box":
        return {
            **entry(task_id, "Sampled goal", "count_box"),
            "scene_id": "opaque_box",
            "hint": "Follow the sampled directive. Drop objects through the flap.",
        }
    return {
        **entry(task_id, "Bottles", "bottles"),
        "scene_id": "bottles",
        "hint": "Put the bottles in the bin.",
    }

import json
import os
import sys
from functools import lru_cache


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


@lru_cache(maxsize=1)
def load_ai_responses() -> list:
    json_path = get_resource_path(os.path.join("assets", "ai.json"))
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

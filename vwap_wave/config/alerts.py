"""Load default alert selections from the current working directory's config.json."""

import json
from pathlib import Path

from ..alerts.conditions import ALERT_CONDITIONS, DEFAULT_CONDITIONS


CONFIG_PATH = Path("config.json")


def load_default_conditions(path=CONFIG_PATH):
    path = Path(path)
    try:
        with path.open() as source:
            config = json.load(source)
    except FileNotFoundError:
        return DEFAULT_CONDITIONS
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a JSON object")
    conditions = config.get("default_conditions", list(DEFAULT_CONDITIONS))
    if not isinstance(conditions, list) or any(not isinstance(name, str) for name in conditions):
        raise ValueError(f"default_conditions in {path} must be a list of condition names")
    unknown = set(conditions) - set(ALERT_CONDITIONS)
    if unknown:
        raise ValueError(f"Unknown alert conditions in {path}: {', '.join(sorted(unknown))}")
    return tuple(dict.fromkeys(conditions))

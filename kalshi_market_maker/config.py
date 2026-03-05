from typing import Dict, Any

import yaml


def load_config(config_file: str) -> Dict[str, Any]:
    with open(config_file, "r") as file:
        return yaml.safe_load(file)


def get_dynamic_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_config, dict) or "dynamic" not in raw_config:
        raise ValueError("Dynamic-only mode is supported. config.yaml must contain top-level 'dynamic'.")
    return raw_config["dynamic"]

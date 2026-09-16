"""配置加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from .runtime import config_dir, config_path

CONFIG_DIR = config_dir()


def load_settings() -> Dict:
    """加载全局配置。"""
    path = CONFIG_DIR / "settings.yaml"
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_traders() -> List[Dict]:
    """加载操盘手配置，按组注入 initial_capital。"""
    path = config_path("traders.yaml")
    if not path.exists():
        raise FileNotFoundError(f"操盘手配置不存在: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    settings = load_settings()
    cap_each = settings["simulation"]["capital_per_trader"]

    traders = data.get("traders", [])
    for t in traders:
        t["initial_capital"] = cap_each
    return traders


def load_screening_config() -> Dict:
    """加载漏斗筛选配置。"""
    path = CONFIG_DIR / "screening.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("screening", {})


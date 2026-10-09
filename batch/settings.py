"""設定ファイルと .env の読み込み。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "data" / "raw"
PUBLIC_DIR = ROOT / "public"
REPORTS_DIR = ROOT / "reports"


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config(name: str, config_dir: Path = CONFIG_DIR) -> dict:
    return load_json(config_dir / f"{name}.json")


def enabled_areas(areas_config: dict) -> list[dict]:
    return [a for a in areas_config["areas"] if a.get("enabled")]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """依存ライブラリなしで .env を読む（既に環境変数があれば上書きしない）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def get_api_key(env_name: str) -> str:
    load_dotenv()
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(
            f"APIキーが未設定です。.env.example を .env にコピーし、{env_name} に値を入れてください。"
        )
    return key

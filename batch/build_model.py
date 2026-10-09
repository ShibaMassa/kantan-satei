"""data/raw/ のキャッシュから model.json を作る（Phase 2 で実行）。

    python -m batch.build_model --out public/model.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cleanse import cleanse
from .model import build_model
from .settings import PUBLIC_DIR, RAW_DIR, enabled_areas, load_config


class FixtureLeakError(RuntimeError):
    pass


def load_raw_files(raw_dir: Path) -> list[dict]:
    files = []
    for p in sorted(raw_dir.glob("*/*.json")):
        files.append(json.loads(p.read_text(encoding="utf-8")))
    return files


def write_model(model: dict, out: Path, *, from_fixture: bool) -> None:
    """テスト用 fixture 由来のモデルを public/ 配下に書き出すことを禁止する（要件 12章）。"""
    out = out.resolve()
    if from_fixture and (out == PUBLIC_DIR.resolve() or PUBLIC_DIR.resolve() in out.parents):
        raise FixtureLeakError(f"fixture 由来のモデルは public/ に出力できません: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=PUBLIC_DIR / "model.json")
    args = ap.parse_args(argv)

    raw_files = load_raw_files(args.raw_dir)
    if not raw_files:
        raise SystemExit(f"{args.raw_dir} にデータがありません。先に python -m batch.fetch を実行してください。")
    from_fixture = any(f.get("_fixture") for f in raw_files)
    result = cleanse(raw_files, load_config("exclusion_rules"))
    model = build_model(result.records, enabled_areas(load_config("areas")), load_config("model_params"))
    write_model(model, args.out, from_fixture=from_fixture)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

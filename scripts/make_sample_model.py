"""UIプレビュー用のサンプルモデル public/sample/model.sample.json を作る。

- テスト用 fixture とは無関係に、意図的に「全市区で同じ値」の架空データを生成する（実在の相場と誤認されないように）。
- 町名も架空（「サンプルA町」など）。is_sample=true のとき画面上部に「サンプルデータ」バナーが出る。
- Phase 2 で本物の public/model.json ができたら、site-config.json の allow_sample_preview を false にする。

    python scripts/make_sample_model.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from batch.settings import enabled_areas, load_config  # noqa: E402

PLACEHOLDER_ALPHA = 13.0  # 架空：全市区共通（log 価格の切片）
PLACEHOLDER_COEF = {"log_land": 0.5, "log_floor": 0.5, "age10": -0.3, "age10_sq": 0.02, "time": 0.0}
PLACEHOLDER_CORRECTION = {"count": 99, "p10": 0.7, "p25": 0.85, "p50": 1.0, "p75": 1.15, "p90": 1.3}


def main() -> None:
    params = load_config("model_params")
    town = lambda alpha, count, area: {"alpha": alpha, "count": count,  # noqa: E731
                                       "default_land_area": area, "default_floor_area": area}
    cities = {}
    for area in enabled_areas(load_config("areas")):
        cities[area["code"]] = {
            "name": area["name"], "available": True, "alpha": PLACEHOLDER_ALPHA, "count": 99,
            "default_land_area": 100.0, "default_floor_area": 100.0,
            "correction_town": PLACEHOLDER_CORRECTION, "correction_city": PLACEHOLDER_CORRECTION,
            "towns": {
                "サンプルA町（町名データあり）": town(PLACEHOLDER_ALPHA, 99, 100.0),
                "サンプルB町（件数不足→市区で計算）": town(None, 1, None),
            },
        }
    cities["99999"] = {
        "name": "（サンプル）データ不足のエリア", "available": False, "alpha": None, "count": 1,
        "default_land_area": None, "default_floor_area": None,
        "correction_town": {"count": 0}, "correction_city": {"count": 0},
        "towns": {"サンプルC町": town(None, 1, None)},
    }
    model = {
        "schema_version": 2,
        "is_sample": True,
        "_notice": "UIプレビュー専用の架空データ。実在の相場ではない。本番表示・バックテストに使わないこと。",
        "generated_at": "sample",
        "data_period": {"from": "2021Q1", "to": "2021Q1"},
        "params": {
            "coef": PLACEHOLDER_COEF,
            "clamp": {"land_area": [30, 1000], "floor_area": [30, 500], "age": [0, 60]},
            "range_percentiles": params["range_percentiles"],
            "rounding_yen": params["rounding_yen"],
        },
        "cities": cities,
    }
    out = ROOT / "public" / "sample" / "model.sample.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

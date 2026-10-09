"""テスト用 fixture を生成する。**ここの数値はすべて架空。本番の model.json や画面表示に使わないこと。**

- 市区コードは実在しない 99901 / 99902、町名は「テスト町A」などを使う
- 生成物には "_fixture" マーカーを入れる（batch.build_model.write_model が public/ への出力を拒否する）

    python tests/fixtures/make_fixtures.py
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from batch.cleanse import cleanse  # noqa: E402
from batch.model import build_model, predict_log  # noqa: E402

MARK = "TEST ONLY - 架空のテストデータ。本番に使用禁止"
PARAMS = {
    "min_town_count": 10, "min_correction_count": 20, "new_build_max_age": 1,
    "input_clamp_percentiles": [1, 99],
    "range_percentiles": {"normal": [25, 75], "wide": [10, 90]},
    "rounding_yen": 100000,
}
AREAS = [{"code": "99901", "name": "テスト市", "enabled": True},
         {"code": "99902", "name": "テスト過疎市", "enabled": True}]


def rec(**kw):
    base = {"PriceCategory": "不動産取引価格情報", "Prefecture": "テスト県", "Remarks": ""}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def raw_files():
    rnd = random.Random(20261008)
    files = {}

    def add(city, q, pc, r):
        files.setdefault((city, q, pc), []).append(r)

    quarters = [(y, n) for y in (2023, 2024, 2025) for n in (1, 2, 3, 4)] + [(2026, 1), (2026, 2)]
    # 99901：土地取引（v1.1 のモデルでは使わないが、クレンジングとプロファイルのテストに使う）
    for i in range(12):
        y, n = quarters[i % len(quarters)]
        area = 100 + i
        add("99901", (y, n), "01", rec(Type="宅地(土地)", MunicipalityCode="99901", DistrictName="テスト町A",
                                       TradePrice=int(area * (80000 + i * 1000)), Area=area,
                                       Period=f"{y}年第{n}四半期"))
    for i in range(3):
        y, n = quarters[-1 - i]
        add("99901", (y, n), "02", rec(Type="宅地(土地)", MunicipalityCode="99901", DistrictName="テスト町B",
                                       TradePrice=120 * 78000, Area=120, Period=f"{y}年第{n}四半期",
                                       PriceCategory="成約価格情報"))
    for i in range(25):
        y, n = quarters[i % len(quarters)]
        town = "テスト町A" if i % 5 else "テスト町B"  # A=20件（町名の効果あり）、B=5件（市区にフォールバック）
        land, floor, by = 110 + i, 90 + (i % 5) * 5, 1995 + (i % 20)
        add("99901", (y, n), "01", rec(Type="宅地(土地と建物)", MunicipalityCode="99901", DistrictName=town,
                                       TradePrice=int(rnd.uniform(1800, 3200)) * 10000, Area=land,
                                       TotalFloorArea=floor, BuildingYear=f"{by}年", Period=f"{y}年第{n}四半期"))
    # 除外されるべきレコード（理由別）
    bad = [
        rec(Type="宅地(土地と建物)", MunicipalityCode="99901", DistrictName="テスト町A", TradePrice=20000000,
            Area=100, TotalFloorArea=90, BuildingYear="戦前", Period="2025年第1四半期"),
        rec(Type="宅地(土地)", MunicipalityCode="99901", DistrictName="テスト町A", TradePrice=900000000,
            Area="2000㎡以上", Period="2025年第1四半期"),
        rec(Type="宅地(土地)", MunicipalityCode="99901", DistrictName="テスト町A", TradePrice=5000000,
            Area=100, Period="2025年第1四半期", Remarks="関係者間取引"),
        rec(Type="中古マンション等", MunicipalityCode="99901", DistrictName="テスト町A", TradePrice=30000000,
            Area=70, Period="2025年第1四半期"),
        rec(Type="宅地(土地)", MunicipalityCode="99901", DistrictName="テスト町A", TradePrice="",
            Area=100, Period="2025年第1四半期"),
    ]
    for r in bad:
        add("99901", (2025, 1), "01", r)
    # 99902：件数不足（confidence=none になるべき）
    add("99902", (2026, 2), "01", rec(Type="宅地(土地)", MunicipalityCode="99902", DistrictName="テスト町Z",
                                      TradePrice=5000000, Area=100, Period="2026年第2四半期"))
    return [{"_fixture": MARK, "city": c, "quarter": f"{q[0]}Q{q[1]}", "price_classification": pc, "records": rs}
            for (c, q, pc), rs in sorted(files.items())]


def shared_cases():
    cases = []
    coef = {"log_land": 0.5, "log_floor": 0.4, "age10": -0.3, "age10_sq": 0.02, "time": 0.05}
    for alpha, land, floor, age, time in [(12.0, 120, 100, 0, 0), (12.0, 120, 100, 15, 0), (13.5, 90.5, 85.2, 29, -1.25),
                                          (11.0, 200, 120, 30, 0.5), (11.0, 200, 120, 60, 0), (12.5, 100, 100, 2, -3)]:
        cases.append({"alpha": alpha, "land_area": land, "floor_area": floor, "age": age, "time": time,
                      "expected_log": predict_log(alpha, coef, land, floor, age, time)})
    return {"_fixture": MARK, "coef": coef, "cases": cases}


def main():
    files = raw_files()
    (HERE / "fixture_raw.json").write_text(json.dumps(files, ensure_ascii=False, indent=1), encoding="utf-8")
    result = cleanse(files, {"remarks_keywords": [{"keyword": "関係者間", "reason": "関係者間取引"}],
                             "iqr_multiplier": 1.5})
    model = build_model(result.records, AREAS, PARAMS, generated_at="fixture")
    model["_fixture"] = MARK
    (HERE / "fixture_model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "fixture_shared_cases.json").write_text(json.dumps(shared_cases(), ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
    print("fixtures written")


if __name__ == "__main__":
    main()

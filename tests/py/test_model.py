import math
import random

import pytest

from batch.build_model import FixtureLeakError, write_model
from batch.cleanse import cleanse, normalize_record
from batch.model import build_model, fit_fixed_effects, is_new_build, predict_log, solve
from batch.settings import PUBLIC_DIR

AREAS = [{"code": "99901", "name": "テスト市", "enabled": True},
         {"code": "99902", "name": "テスト過疎市", "enabled": True}]
RULES = {"remarks_keywords": [{"keyword": "関係者間", "reason": "関係者間取引"}], "iqr_multiplier": 1.5}
PARAMS = {"min_town_count": 10, "min_correction_count": 20, "new_build_max_age": 1,
          "input_clamp_percentiles": [1, 99], "range_percentiles": {"normal": [25, 75], "wide": [10, 90]},
          "rounding_yen": 100000}


def test_solve():
    assert solve([[2, 1], [1, 3]], [3, 5]) == pytest.approx([0.8, 1.4])


def test_fixed_effects_recovers_known_slopes():
    # y = α_g + 2·x1 − 0.5·x2（ノイズなし）→ 傾きを正確に復元できる
    rnd = random.Random(1)
    alphas = {"g1": 10.0, "g2": 12.0, "g3": 9.0}
    xs, ys, gs = [], [], []
    for _ in range(60):
        g = rnd.choice(list(alphas))
        x = [rnd.uniform(0, 5), rnd.uniform(0, 5)]
        xs.append(x), gs.append(g), ys.append(alphas[g] + 2 * x[0] - 0.5 * x[1])
    assert fit_fixed_effects(xs, ys, gs) == pytest.approx([2, -0.5])


def test_shared_cases(shared_cases):
    for c in shared_cases["cases"]:
        got = predict_log(c["alpha"], shared_cases["coef"], c["land_area"], c["floor_area"], c["age"], c["time"])
        assert got == pytest.approx(c["expected_log"])


@pytest.fixture
def model(raw_files):
    return build_model(cleanse(raw_files, RULES).records, AREAS, PARAMS, generated_at="test")


def test_town_fallback_hierarchy(model):
    city = model["cities"]["99901"]
    assert city["available"] is True
    assert city["towns"]["テスト町A"]["count"] >= PARAMS["min_town_count"]
    assert city["towns"]["テスト町A"]["alpha"] is not None
    # 件数不足の町名は町名の効果を持たない（フロントで市区にフォールバックし confidence=low）
    assert 0 < city["towns"]["テスト町B"]["count"] < PARAMS["min_town_count"]
    assert city["towns"]["テスト町B"]["alpha"] is None


def test_insufficient_city_is_unavailable(model):
    assert model["cities"]["99902"]["available"] is False


def test_correction_percentiles_ordered(model):
    for key in ("correction_town", "correction_city"):
        c = model["cities"]["99901"][key]
        assert c["p10"] <= c["p25"] <= c["p50"] <= c["p75"] <= c["p90"]


def test_model_uses_only_used_houses(model, raw_files):
    # 土地取引・新築・対象外は学習に使わない
    assert model["cities"]["99901"]["count"] == 25


def test_model_contains_only_aggregates(model):
    text = str(model)
    for key in ("TradePrice", "Remarks", "records", "price"):
        assert key not in text


def test_fixture_model_cannot_be_written_to_public(model, tmp_path):
    with pytest.raises(FixtureLeakError):
        write_model(model, PUBLIC_DIR / "model.json", from_fixture=True)
    write_model(model, tmp_path / "model.json", from_fixture=True)  # public 外なら可
    assert (tmp_path / "model.json").exists()


def test_new_builds_are_excluded(raw_files):
    house = {"kind": "house", "quarter": [2025, 1], "build_year": 2024}
    assert is_new_build(house, PARAMS)
    assert not is_new_build({**house, "build_year": 2023}, PARAMS)
    assert not is_new_build(house, {})  # 設定が無ければ除外しない
    # 新築だけを足してもモデルの件数は変わらない
    recs = cleanse(raw_files, RULES).records
    new = [{**r, "build_year": r["quarter"][0]} for r in recs if r["kind"] == "house"]
    m = build_model(recs + new, AREAS, PARAMS, generated_at="test")
    assert m["cities"]["99901"]["count"] == 25


def test_remarks_rule_applies_to_kind():
    rules = {"remarks_keywords": [{"keyword": "私道", "reason": "私道を含む取引", "applies_to": ["land"]}]}
    land = {"Type": "宅地(土地)", "TradePrice": "10000000", "Area": "100", "Period": "2025年第1四半期",
            "Remarks": "私道を含む取引"}
    house = {**land, "Type": "宅地(土地と建物)", "TotalFloorArea": "90", "BuildingYear": "2000年"}
    assert normalize_record(land, "99901", "01", rules)[1] == "remarks:私道を含む取引"
    assert normalize_record(house, "99901", "01", rules)[0] is not None

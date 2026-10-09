from batch.cleanse import cleanse, normalize_type, parse_build_year, parse_number

RULES = {"remarks_keywords": [{"keyword": "関係者間", "reason": "関係者間取引"}], "iqr_multiplier": 1.5}


def test_parse_number():
    assert parse_number("85000000") == (85000000.0, None)
    assert parse_number("1,200") == (1200.0, None)
    assert parse_number("2000㎡以上") == (None, "bounded")
    assert parse_number("") == (None, "missing")
    assert parse_number(None) == (None, "missing")
    assert parse_number("abc") == (None, "non_numeric")
    assert parse_number("0") == (None, "non_numeric")


def test_parse_build_year():
    assert parse_build_year("1972年") == (1972, None)   # 公式マニュアルの出力例の形式
    assert parse_build_year("昭和47年") == (1972, None)
    assert parse_build_year("平成元年") == (1989, None)
    assert parse_build_year("戦前") == (None, "non_numeric")
    assert parse_build_year("") == (None, "missing")


def test_normalize_type_accepts_fullwidth_parens():
    assert normalize_type("宅地(土地と建物)") == "宅地(土地と建物)"
    assert normalize_type("宅地（土地）") == "宅地(土地)"
    assert normalize_type("中古マンション等") is None


def test_cleanse_counts_exclusions_by_reason(raw_files):
    result = cleanse(raw_files, RULES)
    ex = {why: n for (city, why), n in result.excluded.items() if city == "99901"}
    assert ex["build_year_non_numeric"] == 1   # 戦前
    assert ex["area_bounded"] == 1             # 2000㎡以上
    assert ex["remarks:関係者間取引"] == 1
    assert ex["type_not_target"] == 1
    assert ex["price_missing"] == 1
    kinds = {r["kind"] for r in result.records}
    assert kinds == {"land", "house"}
    assert all(r["unit_price"] > 0 for r in result.records)


def test_iqr_removes_outlier():
    def land(price):
        return {"Type": "宅地(土地)", "MunicipalityCode": "99901", "DistrictName": "テスト町A",
                "TradePrice": str(price), "Area": "100", "Period": "2025年第1四半期"}
    files = [{"city": "99901", "price_classification": "01",
              "records": [land(p) for p in (8_000_000, 8_100_000, 8_200_000, 8_300_000, 8_400_000, 90_000_000)]}]
    result = cleanse(files, RULES)
    assert len(result.records) == 5
    assert result.excluded[("99901", "iqr_outlier")] == 1


def test_iqr_on_log_scale_removes_extremely_cheap():
    def land(price):
        return {"Type": "宅地(土地)", "MunicipalityCode": "99901", "DistrictName": "テスト町A",
                "TradePrice": str(price), "Area": "100", "Period": "2025年第1四半期"}
    prices = [8_000_000, 9_000_000, 10_000_000, 12_000_000, 15_000_000, 20_000_000, 30_000_000, 200_000]
    result = cleanse([{"city": "99901", "price_classification": "01", "records": [land(p) for p in prices]}], RULES)
    assert 200_000 not in [r["price"] for r in result.records]  # 線形の IQR では下限が負になり残ってしまう

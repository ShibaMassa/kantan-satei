"""APIレコードの正規化とクレンジング（要件定義 6章）。

フィールド名は公式API操作説明の出力項目に合わせる：
Type, MunicipalityCode, DistrictName, TradePrice, Area, TotalFloorArea, BuildingYear, Period, Remarks, PriceCategory など。
API の値はすべて文字列型。
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from . import quarters as Q
from .stats import iqr_bounds

TYPE_HOUSE = "宅地(土地と建物)"
TYPE_LAND = "宅地(土地)"

_WAREKI = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", "")


def normalize_type(s: str | None) -> str | None:
    if not s:
        return None
    t = _norm(s)
    return t if t in (TYPE_HOUSE, TYPE_LAND) else None


def parse_number(s) -> tuple[float | None, str | None]:
    """数値に変換する。失敗時は (None, 理由)。理由: missing / bounded（「2000㎡以上」等の上限表記）/ non_numeric。"""
    if s is None:
        return None, "missing"
    if isinstance(s, (int, float)):
        return float(s), None
    t = _norm(str(s)).replace(",", "")
    if t == "":
        return None, "missing"
    if re.search(r"(以上|未満|以下|超)", t):
        return None, "bounded"
    t = t.replace("㎡", "").replace("m2", "")
    try:
        v = float(t)
    except ValueError:
        return None, "non_numeric"
    return (v, None) if v > 0 else (None, "non_numeric")


def parse_build_year(s) -> tuple[int | None, str | None]:
    """「1972年」（公式の出力例）を西暦整数に。和暦表記も念のため受け付ける。「戦前」等は除外理由を返す。"""
    if s is None:
        return None, "missing"
    t = _norm(str(s))
    if t == "":
        return None, "missing"
    m = re.fullmatch(r"(\d{4})年?", t)
    if m:
        return int(m.group(1)), None
    m = re.fullmatch(r"(明治|大正|昭和|平成|令和)(元|\d{1,2})年", t)
    if m:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        return _WAREKI[m.group(1)] + n, None
    return None, "non_numeric"


@dataclass
class CleanResult:
    records: list[dict] = field(default_factory=list)
    # (city, reason) -> 件数
    excluded: Counter = field(default_factory=Counter)


def normalize_record(raw: dict, city: str, price_classification: str, rules: dict) -> tuple[dict | None, str | None]:
    t = normalize_type(raw.get("Type"))
    if t is None:
        return None, "type_not_target"

    kind = "house" if t == TYPE_HOUSE else "land"
    remarks = raw.get("Remarks") or ""
    for rule in rules.get("remarks_keywords", []):
        # applies_to を省略したルールは土地・戸建ての両方に適用する
        if kind not in rule.get("applies_to", ["land", "house"]):
            continue
        if rule["keyword"] in _norm(remarks):
            return None, f"remarks:{rule['reason']}"

    quarter = Q.parse_period(raw.get("Period"))
    if quarter is None:
        return None, "period_invalid"

    price, why = parse_number(raw.get("TradePrice"))
    if price is None:
        return None, f"price_{why}"
    land_area, why = parse_number(raw.get("Area"))
    if land_area is None:
        return None, f"area_{why}"

    rec = {
        "city": raw.get("MunicipalityCode") or city,
        "town": (raw.get("DistrictName") or "").strip(),
        "kind": kind,
        "pc": price_classification,
        "quarter": list(quarter),
        "price": price,
        "land_area": land_area,
        "unit_price": price / land_area,
    }
    if t == TYPE_HOUSE:
        floor_area, why = parse_number(raw.get("TotalFloorArea"))
        if floor_area is None:
            return None, f"floor_area_{why}"
        build_year, why = parse_build_year(raw.get("BuildingYear"))
        if build_year is None:
            return None, f"build_year_{why}"
        if build_year > quarter[0]:
            return None, "build_year_after_trade"
        rec["floor_area"] = floor_area
        rec["build_year"] = build_year
    return rec, None


def cleanse(raw_files: list[dict], rules: dict) -> CleanResult:
    """raw_files: fetch.py が保存した {city, price_classification, records} の列。"""
    result = CleanResult()
    for f in raw_files:
        for raw in f["records"]:
            rec, why = normalize_record(raw, f["city"], f["price_classification"], rules)
            if rec is None:
                result.excluded[(f["city"], why)] += 1
            else:
                result.records.append(rec)
    result.records = _drop_iqr_outliers(result.records, result.excluded, rules.get("iqr_multiplier", 1.5))
    return result


def _drop_iqr_outliers(records: list[dict], excluded: Counter, k: float) -> list[dict]:
    """㎡単価（取引価格 ÷ 土地面積）の外れ値を、市区×種類ごとに IQR 法で除外する。

    ㎡単価の分布は右に裾が長く、そのままでは下限が負になって極端に安い取引を除外できないため、
    対数をとってから IQR 法を当てる（D-35）。
    """
    groups: dict[tuple, list[float]] = {}
    for r in records:
        groups.setdefault((r["city"], r["kind"]), []).append(math.log(r["unit_price"]))
    bounds = {g: iqr_bounds(v, k) for g, v in groups.items() if len(v) >= 4}
    kept = []
    for r in records:
        b = bounds.get((r["city"], r["kind"]))
        if b and not (b[0] <= math.log(r["unit_price"]) <= b[1]):
            excluded[(r["city"], "iqr_outlier")] += 1
            continue
        kept.append(r)
    return kept

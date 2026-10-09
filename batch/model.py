"""model.json の推定 — v1.1 対数線形回帰（docs/decisions.md D-40〜D-42）。

    log(価格) = α[町名 or 市区] + b1·log(土地面積) + b2·log(延床面積) + b3·(築年数/10) + b4·(築年数/10)² + b5·(時点 − 基準時点)

- 学習データは中古戸建て取引（新築を除く。取引価格01・成約価格02の両方）。
- 傾き b は全エリア共通。町名（N件以上）または「市区のその他」を固定効果とし、各グループ内で平均を引いてから
  5変数の正規方程式を解く（Frisch–Waugh–Lovell）。依存ライブラリなしで推定できる。
- 時点は基準時点（データの最新四半期）を0とするので、α はそのまま基準時点の水準になる。
- レンジの幅：残差 exp(実際 − 予測) のパーセンタイルを市区ごとに持つ（町名の効果で予測した場合と、市区の効果で予測した場合の2種類）。

フロントの public/js/estimator.js と同じ予測式を使う。一致は tests/fixtures/fixture_shared_cases.json で検証する。
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from . import quarters as Q
from .stats import median, percentile

SCHEMA_VERSION = 2
FEATURES = ["log_land", "log_floor", "age10", "age10_sq", "time"]


def is_new_build(r: dict, params: dict) -> bool:
    """取引年 − 築年 が new_build_max_age 以下の戸建て（D-29）。設定が無ければ新築扱いしない。"""
    max_age = params.get("new_build_max_age")
    return r["kind"] == "house" and max_age is not None and r["quarter"][0] - r["build_year"] <= max_age


def features(land_area: float, floor_area: float, age: float, time: float = 0.0) -> list[float]:
    a = age / 10
    return [math.log(land_area), math.log(floor_area), a, a * a, time]


def predict_log(alpha: float, coef: dict, land_area: float, floor_area: float, age: float, time: float = 0.0) -> float:
    return alpha + sum(coef[k] * x for k, x in zip(FEATURES, features(land_area, floor_area, age, time)))


# ---- 線形代数（5×5 程度なので素朴なガウスの消去法で十分） ----------------------------

def solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("説明変数が退化しています（データ不足）")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_fixed_effects(xs: list[list[float]], ys: list[float], groups: list[str]) -> list[float]:
    """グループ固定効果つきの最小二乗。グループ内で平均を引いてから傾きだけを解く。"""
    sums: dict[str, list] = defaultdict(lambda: [0, [0.0] * len(xs[0]), 0.0])
    for x, y, g in zip(xs, ys, groups):
        s = sums[g]
        s[0] += 1
        s[1] = [a + b for a, b in zip(s[1], x)]
        s[2] += y
    k = len(xs[0])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for x, y, g in zip(xs, ys, groups):
        n, sx, sy = sums[g]
        dx = [xi - si / n for xi, si in zip(x, sx)]
        dy = y - sy / n
        for i in range(k):
            xty[i] += dx[i] * dy
            for j in range(k):
                xtx[i][j] += dx[i] * dx[j]
    return solve(xtx, xty)


# ---- モデル全体 ----------------------------------------------------------------

def build_model(records: list[dict], areas: list[dict], params: dict, *, is_sample: bool = False,
                generated_at: str | None = None) -> dict:
    houses = [r for r in records if r["kind"] == "house" and not is_new_build(r, params)]
    if not houses:
        raise ValueError("中古戸建てのレコードが0件です")
    codes = {a["code"] for a in areas}
    houses = [h for h in houses if h["city"] in codes]
    ref = max(tuple(r["quarter"]) for r in houses)
    start = min(tuple(r["quarter"]) for r in houses)
    n_min = params["min_town_count"]

    town_count = defaultdict(int)
    for h in houses:
        if h["town"]:
            town_count[(h["city"], h["town"])] += 1

    def group(h):
        return f"{h['city']}|{h['town']}" if h["town"] and town_count[(h["city"], h["town"])] >= n_min else f"{h['city']}|*"

    def age(h):
        return h["quarter"][0] - h["build_year"]

    def tm(h):
        return Q.to_years(tuple(h["quarter"])) - Q.to_years(ref)

    xs = [features(h["land_area"], h["floor_area"], age(h), tm(h)) for h in houses]
    ys = [math.log(h["price"]) for h in houses]
    b = fit_fixed_effects(xs, ys, [group(h) for h in houses])
    coef = dict(zip(FEATURES, b))
    # 傾きを除いた部分（= α + 誤差）
    base = [y - sum(bi * xi for bi, xi in zip(b, x)) for x, y in zip(xs, ys)]

    lo_p, hi_p = params["input_clamp_percentiles"]
    clamp = {
        "land_area": [round(percentile([h["land_area"] for h in houses], p), 1) for p in (lo_p, hi_p)],
        "floor_area": [round(percentile([h["floor_area"] for h in houses], p), 1) for p in (lo_p, hi_p)],
        "age": [round(percentile([age(h) for h in houses], p)) for p in (lo_p, hi_p)],
    }

    cities = {}
    for area in areas:
        idx = [i for i, h in enumerate(houses) if h["city"] == area["code"]]
        cities[area["code"]] = _build_city(area, [houses[i] for i in idx], [base[i] for i in idx], n_min, params)

    return {
        "schema_version": SCHEMA_VERSION,
        "is_sample": is_sample,
        "generated_at": generated_at or dt.date.today().isoformat(),
        "data_period": {"from": Q.format_quarter(start), "to": Q.format_quarter(ref)},
        "params": {
            "coef": {k: round(v, 6) for k, v in coef.items()},
            "clamp": clamp,
            "range_percentiles": params["range_percentiles"],
            "rounding_yen": params["rounding_yen"],
        },
        "cities": cities,
    }


def _ratio_percentiles(residuals: list[float]) -> dict:
    ratios = [math.exp(e) for e in residuals]
    return {"count": len(ratios), **({f"p{p}": round(percentile(ratios, p), 4) for p in (10, 25, 50, 75, 90)} if ratios else {})}


def _build_city(area: dict, houses: list[dict], base: list[float], n_min: int, params: dict) -> dict:
    by_town: dict[str, list[int]] = defaultdict(list)
    for i, h in enumerate(houses):
        if h["town"]:
            by_town[h["town"]].append(i)

    city_alpha = sum(base) / len(base) if base else None
    town_alpha = {t: sum(base[i] for i in ix) / len(ix) for t, ix in by_town.items() if len(ix) >= n_min}

    towns = {}
    for name in sorted(by_town):
        ix = by_town[name]
        usable = name in town_alpha
        towns[name] = {
            "alpha": round(town_alpha[name], 6) if usable else None,
            "count": len(ix),
            "default_land_area": round(median([houses[i]["land_area"] for i in ix]), 1) if usable else None,
            "default_floor_area": round(median([houses[i]["floor_area"] for i in ix]), 1) if usable else None,
        }

    # 残差：町名の効果で予測した場合（町名の効果がある取引だけ）と、市区の効果だけで予測した場合（全取引）
    res_town = [base[i] - town_alpha[h["town"]] for i, h in enumerate(houses) if h["town"] in town_alpha]
    res_city = [e - city_alpha for e in base] if base else []

    return {
        "name": area["name"],
        "available": len(houses) >= params["min_correction_count"],
        "alpha": round(city_alpha, 6) if city_alpha is not None else None,
        "count": len(houses),
        "default_land_area": round(median([h["land_area"] for h in houses]), 1) if houses else None,
        "default_floor_area": round(median([h["floor_area"] for h in houses]), 1) if houses else None,
        "correction_town": _ratio_percentiles(res_town),
        "correction_city": _ratio_percentiles(res_city),
        "towns": towns,
    }

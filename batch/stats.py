"""小さな統計ユーティリティ（標準ライブラリのみ）。"""
from __future__ import annotations

import math
import statistics


def median(xs: list[float]) -> float:
    return statistics.median(xs)


def percentile(xs: list[float], p: float) -> float:
    """線形補間のパーセンタイル（Excel の PERCENTILE.INC / numpy の既定と同じ）。"""
    if not xs:
        raise ValueError("空のリストのパーセンタイルは計算できません")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def iqr_bounds(xs: list[float], multiplier: float = 1.5) -> tuple[float, float]:
    q1, q3 = percentile(xs, 25), percentile(xs, 75)
    iqr = q3 - q1
    return q1 - multiplier * iqr, q3 + multiplier * iqr


def ols_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx

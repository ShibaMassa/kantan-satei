"""四半期の表現 (year, quarter) と文字列 '2021Q1' の相互変換。"""
from __future__ import annotations

import datetime as dt
import re

Quarter = tuple[int, int]

_Q_RE = re.compile(r"^(\d{4})Q([1-4])$")
# API の Period 例：「2015年第2四半期」（公式API操作説明の出力例）
_PERIOD_RE = re.compile(r"^(\d{4})年第([1-4])四半期$")


def parse_quarter(s: str) -> Quarter:
    m = _Q_RE.match(s.strip())
    if not m:
        raise ValueError(f"四半期の形式が不正です（例: 2021Q1）: {s!r}")
    return int(m.group(1)), int(m.group(2))


def format_quarter(q: Quarter) -> str:
    return f"{q[0]}Q{q[1]}"


def parse_period(s: str | None) -> Quarter | None:
    if not s:
        return None
    m = _PERIOD_RE.match(s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def quarter_of(date: dt.date) -> Quarter:
    return date.year, (date.month - 1) // 3 + 1


def previous(q: Quarter) -> Quarter:
    y, n = q
    return (y - 1, 4) if n == 1 else (y, n - 1)


def next_(q: Quarter) -> Quarter:
    y, n = q
    return (y + 1, 1) if n == 4 else (y, n + 1)


def quarter_range(start: Quarter, end: Quarter) -> list[Quarter]:
    out = []
    q = start
    while q <= end:
        out.append(q)
        q = next_(q)
    return out


def latest_candidate(today: dt.date | None = None) -> Quarter:
    """取得を試みる最新の四半期 = 今日を含む四半期の1つ前。未公開ならAPIは空を返すだけ。"""
    return previous(quarter_of(today or dt.date.today()))


def to_years(q: Quarter) -> float:
    """四半期の中央時点を年の実数で表す（時点補正の計算用）。"""
    return q[0] + (q[1] - 1) / 4 + 0.125

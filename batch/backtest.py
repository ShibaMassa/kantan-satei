"""バックテスト（要件 11章）。結果は reports/backtest.md に出力する。

- 直近 holdout_quarters 四半期の戸建て取引（新築を除く）をテストデータとして取り分け、それより前のデータだけでモデルを作る。
- 予測には画面と同じ public/js/estimator.js を Node で呼ぶ（scripts/estimate_batch.mjs）。
- 指標：MAPE、±10%以内、±20%以内、レンジ内の割合（市区別と全体）。MAPE などは推定レンジの中央（基本式 × 補正係数の中央値）で測る。

    python -m batch.backtest
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from . import quarters as Q
from .build_model import load_raw_files
from .cleanse import cleanse
from .model import build_model, is_new_build
from .settings import RAW_DIR, REPORTS_DIR, ROOT, enabled_areas, load_config

ESTIMATE_SCRIPT = ROOT / "scripts" / "estimate_batch.mjs"


# ---- 予測と指標（自社データの評価 batch/eval_own_sales.py と共通） --------------------------

def run_estimates(model: dict, cases: list[dict]) -> list[dict]:
    payload = json.dumps({"model": model, "cases": cases}, ensure_ascii=False)
    out = subprocess.run(["node", str(ESTIMATE_SCRIPT)], input=payload, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def metrics(pairs: list[tuple[float, dict]]) -> dict:
    """pairs: (実際の価格, estimate() の結果)。価格を出さなかった件は coverage にだけ反映する。"""
    n = len(pairs)
    priced = [(actual, r) for actual, r in pairs if r["confidence"] != "none"]
    if not priced:
        return {"n": n, "priced": 0, "coverage": 0.0}
    ape = [abs(r["mid"] - actual) / actual for actual, r in priced]
    return {
        "n": n,
        "priced": len(priced),
        "coverage": len(priced) / n,
        "mape": sum(ape) / len(ape),
        "within10": sum(e <= 0.10 for e in ape) / len(ape),
        "within20": sum(e <= 0.20 for e in ape) / len(ape),
        "in_range": sum(r["low"] <= actual <= r["high"] for actual, r in priced) / len(priced),
    }


METRIC_HEADER = "| 件数 | 価格を表示 | MAPE | ±10%以内 | ±20%以内 | レンジ内 |"
METRIC_RULE = "---:|---:|---:|---:|---:|---:|"


def metric_cells(m: dict) -> str:
    if not m.get("priced"):
        return f"| {m['n']} | 0 | - | - | - | - |"
    return (f"| {m['n']} | {m['coverage']:.0%} | {m['mape']:.1%} | {m['within10']:.1%} | "
            f"{m['within20']:.1%} | {m['in_range']:.1%} |")


# ---- バックテスト本体 --------------------------------------------------------------

def split(records: list[dict], holdout_quarters: int) -> tuple[list[dict], list[dict], list]:
    last = max(tuple(r["quarter"]) for r in records)
    test_qs = [last]
    for _ in range(holdout_quarters - 1):
        test_qs.insert(0, Q.previous(test_qs[0]))
    cutoff = test_qs[0]
    train = [r for r in records if tuple(r["quarter"]) < cutoff]
    test = [r for r in records if tuple(r["quarter"]) >= cutoff]
    return train, test, test_qs


def to_case(h: dict, with_town: bool = True) -> dict:
    return {"cityCode": h["city"], "town": h["town"] if with_town else None, "buildYear": h["build_year"],
            "landArea": h["land_area"], "floorArea": h["floor_area"], "currentYear": h["quarter"][0]}


def evaluate(train: list[dict], test_houses: list[dict], areas: list[dict], params: dict) -> dict:
    model = build_model(train, areas, params, generated_at="backtest")
    res_town = run_estimates(model, [to_case(h) for h in test_houses])
    res_city = run_estimates(model, [to_case(h, with_town=False) for h in test_houses])
    return {"model": model, "town": list(zip([h["price"] for h in test_houses], res_town)),
            "city": list(zip([h["price"] for h in test_houses], res_city))}


def run(raw_dir: Path) -> tuple[str, bool]:
    """(レポートの Markdown, 合格したか) を返す。"""
    cfg = load_config("backtest")
    params = load_config("model_params")
    areas = enabled_areas(load_config("areas"))
    names = {a["code"]: a["name"] for a in areas}
    records = cleanse(load_raw_files(raw_dir), load_config("exclusion_rules")).records
    train, test_all, test_qs = split(records, cfg["holdout_quarters"])
    test_houses = [r for r in test_all if r["kind"] == "house" and not is_new_build(r, params)]
    v = evaluate(train, test_houses, areas, params)
    passed = metrics(v["town"]).get("within20", 0) >= cfg["pass_within_20_min"]
    return render(v, test_houses, test_qs, names, cfg), passed


def render(v: dict, test_houses: list[dict], test_qs: list, names: dict, cfg: dict) -> str:
    threshold = cfg["pass_within_20_min"]
    overall = metrics(v["town"])
    passed = overall.get("within20", 0) >= threshold
    out = ["# バックテスト結果（査定ロジック v1.1：対数線形回帰）", "",
           f"**判定：{'合格' if passed else '不合格'}**（±20%以内 {overall.get('within20', 0):.1%}、合格基準 {threshold:.0%} 以上）", "",
           f"- テスト期間：{Q.format_quarter(test_qs[0])}〜{Q.format_quarter(test_qs[-1])}（直近{len(test_qs)}四半期）の中古戸建て取引 {len(test_houses)}件"
           "（新築＝築1年以内を除く。取引価格(01)・成約価格(02)の両方）",
           f"- 学習データ：{Q.format_quarter(test_qs[0])} より前のデータだけで model.json を作って予測",
           "- 予測には画面と同じ査定ロジック（public/js/estimator.js）を使用。物件情報（市区・町名・築年・土地面積・延床面積）は実際の値を入力",
           "- MAPE・±10%・±20% は推定レンジの中央と実際の価格の差。レンジ内は、表示されるレンジに実際の価格が入った割合",
           "- 参考：要件 7章の比率方式（v1）は、同じテストデータで MAPE 40.3%、±20%以内 42.6%、レンジ内 63.0%（2026-10-09 計測、docs/decisions.md D-37）",
           "", "## 1. 市区別（町名を入力した場合）", "", "| 市区 " + METRIC_HEADER, "|---|" + METRIC_RULE]
    _by(out, v["town"], test_houses, lambda h: names.get(h["city"], h["city"]))
    out += ["", "## 2. 市区別（町名を「わからない」にした場合）", "", "| 市区 " + METRIC_HEADER, "|---|" + METRIC_RULE]
    _by(out, v["city"], test_houses, lambda h: names.get(h["city"], h["city"]))
    out += ["", "## 3. confidence 別（町名を入力した場合）", "", "| confidence " + METRIC_HEADER, "|---|" + METRIC_RULE]
    groups = defaultdict(list)
    for pair in v["town"]:
        groups[pair[1]["confidence"]].append(pair)
    for k in ("normal", "low", "none"):
        if k in groups:
            out.append(f"| {k} " + metric_cells(metrics(groups[k])))
    out += ["", "## 4. テストデータの価格区分別（町名を入力した場合）", "", "| 価格区分 " + METRIC_HEADER, "|---|" + METRIC_RULE]
    _by(out, v["town"], test_houses, lambda h: {"01": "取引価格(01)", "02": "成約価格(02)"}[h["pc"]], total=False)
    out += ["", "## 5. 築年数別（町名を入力した場合）", "", "| 築年数 " + METRIC_HEADER, "|---|" + METRIC_RULE]
    bands = [(2, 10), (10, 20), (20, 30), (30, 40), (40, 200)]
    labels = [f"{lo}〜{hi - 1}年" if hi < 200 else f"{lo}年以上" for lo, hi in bands]
    _by(out, v["town"], test_houses,
        lambda h: next(lb for (lo, hi), lb in zip(bands, labels) if lo <= h["quarter"][0] - h["build_year"] < hi),
        total=False, order=labels)
    return "\n".join(out) + "\n"


def _by(out: list[str], pairs: list, houses: list[dict], key, total: bool = True, order: list | None = None) -> None:
    groups = defaultdict(list)
    for h, pair in zip(houses, pairs):
        groups[key(h)].append(pair)
    for k in (order or groups):
        if k not in groups:
            continue
        out.append(f"| {k} " + metric_cells(metrics(groups[k])))
    if total:
        out.append("| **全体** " + metric_cells(metrics(pairs)))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=REPORTS_DIR / "backtest.md")
    ap.add_argument("--strict", action="store_true", help="合格基準を下回ったら終了コード1で終わる（四半期更新の自動公開を止める）")
    args = ap.parse_args(argv)
    md, passed = run(args.raw_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"wrote {args.out}（{'合格' if passed else '不合格'}）")
    if args.strict and not passed:
        raise SystemExit("バックテストが合格基準を下回ったため、model.json を更新しません。")


if __name__ == "__main__":
    main()

"""自社の成約データで model.json を評価する（要件 11章）。結果は reports/own_sales_eval.md に出力する。

CSV の形式は docs/own_sales_format.md を参照。指標はバックテストと同じ。

    python -m batch.eval_own_sales data/own_sales.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from .backtest import METRIC_HEADER, METRIC_RULE, metric_cells, metrics, run_estimates
from .settings import PUBLIC_DIR, REPORTS_DIR

COLUMNS = ["city_code", "town", "price", "land_area", "floor_area", "build_year", "contract_ym"]


def read_csv(path: Path) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"CSV の列が不足しています: {missing}（必要な列: {COLUMNS}）")
        for i, row in enumerate(reader, start=2):
            try:
                year = int(row["contract_ym"].strip()[:4])
                rows.append({
                    "city": row["city_code"].strip(),
                    "town": row["town"].strip() or None,
                    "price": float(row["price"]),
                    "land_area": float(row["land_area"]),
                    "floor_area": float(row["floor_area"]),
                    "build_year": int(row["build_year"]),
                    "year": year,
                })
            except (ValueError, KeyError) as e:
                errors.append(f"{i}行目: {e}")
    return rows, errors


def render(model: dict, rows: list[dict], errors: list[str]) -> str:
    cases = [{"cityCode": r["city"], "town": r["town"], "buildYear": r["build_year"], "landArea": r["land_area"],
              "floorArea": r["floor_area"], "currentYear": r["year"]} for r in rows]
    pairs = list(zip([r["price"] for r in rows], run_estimates(model, cases)))
    out = ["# 自社成約データによる評価", "",
           f"- model.json：データ期間 {model['data_period']['from']}〜{model['data_period']['to']}、生成日 {model['generated_at']}",
           f"- 評価件数：{len(rows)}件（読み込めなかった行：{len(errors)}件）", "",
           "| 市区 " + METRIC_HEADER, "|---|" + METRIC_RULE]
    groups = defaultdict(list)
    for r, pair in zip(rows, pairs):
        groups[model["cities"].get(r["city"], {}).get("name", r["city"])].append(pair)
    for k, g in groups.items():
        out.append(f"| {k} " + metric_cells(metrics(g)))
    out.append("| **全体** " + metric_cells(metrics(pairs)))
    if errors:
        out += ["", "## 読み込めなかった行", ""] + [f"- {e}" for e in errors[:50]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--model", type=Path, default=PUBLIC_DIR / "model.json")
    ap.add_argument("--out", type=Path, default=REPORTS_DIR / "own_sales_eval.md")
    args = ap.parse_args(argv)
    model = json.loads(args.model.read_text(encoding="utf-8"))
    rows, errors = read_csv(args.csv)
    args.out.write_text(render(model, rows, errors), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

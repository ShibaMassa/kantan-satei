"""データプロファイル（Phase 1 の成果物）を reports/data_profile.md に出力する。

- 価格区分（01 取引価格 / 02 成約価格）× 種類 ごとのフィールド充足率
- 除外理由別の件数
- 備考(Remarks)の値の頻度（除外ルールの見直し用）
- 市区×町名別の件数

    python -m batch.profile
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from .build_model import load_raw_files
from .cleanse import cleanse, normalize_type
from .model import is_new_build
from .settings import RAW_DIR, REPORTS_DIR, enabled_areas, load_config
from .stats import median

N_CANDIDATES = [5, 10, 15, 20, 30]

# 公式API操作説明の出力項目（XIT001）
API_FIELDS = [
    "Type", "Region", "MunicipalityCode", "Prefecture", "Municipality", "DistrictName", "TradePrice",
    "PricePerUnit", "FloorPlan", "Area", "UnitPrice", "LandShape", "Frontage", "TotalFloorArea",
    "BuildingYear", "Structure", "Use", "Purpose", "Direction", "Classification", "Breadth",
    "CityPlanning", "CoverageRatio", "FloorAreaRatio", "Period", "Renovation", "Remarks",
    "PriceCategory", "DistrictCode",
]


def _filled(v) -> bool:
    return v is not None and str(v).strip() != ""


def _n_sensitivity(records: list[dict], areas: list[dict], names: dict, params: dict) -> list[str]:
    """町名単位で計算する最低件数 N の候補ごとに、町名の効果を使える町の数と、中古戸建て取引のカバー率を示す。"""
    houses = [r for r in records if r["kind"] == "house" and not is_new_build(r, params)]
    out = ["", "## 4. 町名単位の最低件数 N の感度（中古戸建て取引・全期間）", "",
           "「町名数」は中古戸建て取引が N 件以上ある町名の数。「カバー率」は、その町名に属する中古戸建て取引の割合"
           "（＝利用者の物件が町名の効果で計算される割合の目安）。", "",
           "| 市区 | 町名数(全体) | " + " | ".join(f"N={n} 町名数 / カバー率" for n in N_CANDIDATES) + " |",
           "|---|---:|" + "---:|" * len(N_CANDIDATES)]
    for code in [a["code"] for a in areas]:
        hs = [h for h in houses if h["city"] == code]
        cnt = Counter(h["town"] for h in hs if h["town"])
        cells = []
        for n in N_CANDIDATES:
            ok = {t for t, c in cnt.items() if c >= n}
            cov = sum(1 for h in hs if h["town"] in ok) / len(hs) if hs else 0
            cells.append(f"{len(ok)} / {cov:.0%}")
        out.append(f"| {names.get(code, code)} | {len(cnt)} | " + " | ".join(cells) + " |")
    return out


def _compare_price_classifications(records: list[dict], areas: list[dict], names: dict) -> list[str]:
    """戸建ての取引価格(01)と成約価格(02)の中央値を比べる（どの工程でどちらを使うかの判断材料）。"""
    out = ["", "## 5. 戸建て：取引価格(01) と 成約価格(02) の中央値の比較（全期間）", "",
           "| 市区 | 件数 01 / 02 | 価格(万円) 01 / 02 | 土地面積(㎡) 01 / 02 | 延床(㎡) 01 / 02 | 築年 01 / 02 | 築1年以内の割合 01 / 02 |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for code in [a["code"] for a in areas]:
        g = {pc: [r for r in records if r["city"] == code and r["kind"] == "house" and r["pc"] == pc] for pc in ("01", "02")}

        def m(pc, key, scale=1.0, fmt="{:,.0f}"):
            xs = [r[key] / scale for r in g[pc]]
            return fmt.format(median(xs)) if xs else "-"

        def new(pc):
            xs = g[pc]
            return f"{sum(r['quarter'][0] - r['build_year'] <= 1 for r in xs) / len(xs):.0%}" if xs else "-"
        out.append(f"| {names.get(code, code)} | {len(g['01'])} / {len(g['02'])} | {m('01', 'price', 1e4)} / {m('02', 'price', 1e4)} | "
                   f"{m('01', 'land_area')} / {m('02', 'land_area')} | {m('01', 'floor_area')} / {m('02', 'floor_area')} | "
                   f"{m('01', 'build_year', fmt='{:.0f}')} / {m('02', 'build_year', fmt='{:.0f}')} | {new('01')} / {new('02')} |")
    return out


def render(raw_files: list[dict], areas: list[dict], rules: dict, params: dict) -> str:
    names = {a["code"]: a["name"] for a in areas}
    totals: Counter = Counter()
    filled: dict[tuple, Counter] = defaultdict(Counter)
    remarks: Counter = Counter()
    unknown_fields: Counter = Counter()
    for f in raw_files:
        for r in f["records"]:
            kind = normalize_type(r.get("Type")) or "対象外"
            key = (f["price_classification"], kind)
            totals[key] += 1
            for fld in API_FIELDS:
                if _filled(r.get(fld)):
                    filled[key][fld] += 1
            for fld in r:
                if fld not in API_FIELDS:
                    unknown_fields[fld] += 1
            if _filled(r.get("Remarks")):
                remarks[r["Remarks"]] += 1

    result = cleanse(raw_files, rules)
    out = ["# データプロファイル", ""]
    if any(f.get("_fixture") for f in raw_files):
        out += ["> **注意：テスト用 fixture から生成したレポートです。実データではありません。**", ""]

    out += ["## 1. フィールド充足率（価格区分 × 種類）", ""]
    keys = sorted(totals)
    out.append("| フィールド | " + " | ".join(f"pc{pc} {k} (n={totals[(pc, k)]})" for pc, k in keys) + " |")
    out.append("|---|" + "---:|" * len(keys))
    for fld in API_FIELDS:
        cells = [f"{filled[k][fld] / totals[k]:.0%}" for k in keys]
        out.append(f"| {fld} | " + " | ".join(cells) + " |")
    if unknown_fields:
        out += ["", "マニュアルに無いフィールド: " + ", ".join(f"{k}({v})" for k, v in unknown_fields.most_common())]

    out += ["", "## 2. 除外理由別の件数", "", "| 市区 | 理由 | 件数 |", "|---|---|---:|"]
    for (city, why), n in sorted(result.excluded.items()):
        out.append(f"| {names.get(city, city)} | {why} | {n} |")

    out += ["", "## 3. 備考(Remarks)の値の頻度（上位50）", "", "| 備考 | 件数 |", "|---|---:|"]
    for v, n in remarks.most_common(50):
        out.append(f"| {v} | {n} |")

    out += _n_sensitivity(result.records, areas, names, params)
    out += _compare_price_classifications(result.records, areas, names)

    out += ["", "## 6. 市区 × 町名別の件数（クレンジング後・全期間）", ""]
    by_city: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for r in result.records:
        by_city[r["city"]][r["town"] or "（町名なし）"][f"{r['kind']}_pc{r['pc']}"] += 1
    cols = ["land_pc01", "land_pc02", "house_pc01", "house_pc02"]
    for code in [a["code"] for a in areas]:
        towns = by_city.get(code, {})
        out += [f"### {names.get(code, code)}（{code}）", "",
                "| 町名 | 土地(01) | 土地(02) | 戸建て(01) | 戸建て(02) |", "|---|---:|---:|---:|---:|"]
        for town in sorted(towns):
            out.append(f"| {town} | " + " | ".join(str(towns[town][c]) for c in cols) + " |")
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=REPORTS_DIR / "data_profile.md")
    args = ap.parse_args(argv)
    raw_files = load_raw_files(args.raw_dir)
    if not raw_files:
        raise SystemExit(f"{args.raw_dir} にデータがありません。")
    md = render(raw_files, enabled_areas(load_config("areas")), load_config("exclusion_rules"),
                load_config("model_params"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

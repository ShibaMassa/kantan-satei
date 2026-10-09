# 自社成約データの CSV 形式

`python -m batch.eval_own_sales <CSVファイル>` で、公開データのバックテストと同じ指標（MAPE、±10%以内、±20%以内、レンジ内の割合）を市区別と全体で出力する。
出力先は `reports/own_sales_eval.md`。

- 文字コード：UTF-8（BOM付きでも可）
- 1行目は見出し行。列の順番は問わない
- **個人情報（氏名・住所の番地・連絡先）は入れない**。CSV は `data/` 配下に置く（`data/raw/` と同様にコミットしない運用にする）

| 列名 | 内容 | 例 |
|---|---|---|
| `city_code` | 市区町村コード（5桁） | `12204` |
| `town` | 町名（不動産情報ライブラリの DistrictName と同じ表記。空欄なら市区単位で計算） | `本町` |
| `price` | 成約価格（円） | `32800000` |
| `land_area` | 土地面積（㎡） | `120.5` |
| `floor_area` | 延床面積（㎡） | `98.3` |
| `build_year` | 築年（西暦） | `2003` |
| `contract_ym` | 成約年月（YYYY-MM） | `2025-11` |

ひな形：[own_sales_template.csv](own_sales_template.csv)

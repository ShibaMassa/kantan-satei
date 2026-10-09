# 中古戸建て かんたん相場査定

公開データ（国土交通省 不動産情報ライブラリ）をもとに、中古戸建ての概算価格レンジを表示し、精密査定フォームへ誘導する静的サイト。
要件は [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)、判断記録は [docs/decisions.md](docs/decisions.md)。

## 構成

```
config/             バッチ用の設定（対象エリア・取得・除外ルール・モデルのパラメータ）
batch/              データ取得・クレンジング・プロファイル・モデル推定（Python 3.11+、標準ライブラリのみ）
public/             公開する静的サイト（ビルド不要）
  site-config.json    ツール名・査定フォームURL・GA4測定ID・クレジット文言
  js/estimator.js     査定ロジック（純粋関数）
  sample/             UIプレビュー用の架空データ（「サンプルデータ」と明示して表示）
data/raw/           APIの取得結果のキャッシュ（コミットしない）
reports/            データプロファイル・バックテストの出力先
tests/              テスト（fixture はすべて架空のテスト用データ）
scripts/            補助スクリプト
```

## Phase 1 の始め方（APIキーが届いたら）

```bash
cp .env.example .env
```

`.env` の `REINFOLIB_API_KEY=` にキーを入れてから：

```bash
python3 -m batch.fetch --dry-run
```

```bash
python3 -m batch.fetch
```

```bash
python3 -m batch.profile
```

`reports/data_profile.md` が出力される。

## モデルの生成とバックテスト（Phase 2）

```bash
python3 -m batch.backtest
```

```bash
python3 -m batch.build_model
```

`reports/backtest.md` と `public/model.json` が出力される。自社の成約データの評価は [docs/own_sales_format.md](docs/own_sales_format.md) を参照。

## テスト

```bash
python3 -m pytest -q tests/py
```

```bash
npm test
```

## プレビュー

```bash
npm run serve
```

http://localhost:8080 を開く。`public/model.json` が無く、`site-config.json` の `allow_sample_preview` が true のときだけ、サンプルデータ（架空の値）で表示され、画面上部に赤帯が出る。

"""XIT001 から対象エリア×四半期×価格区分のデータを取得し、data/raw/ にキャッシュする。

使い方:
    python -m batch.fetch            # 未取得の四半期だけ取得
    python -m batch.fetch --dry-run  # 取得予定の一覧だけ表示（APIキー不要）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import quarters as Q
from .reinfolib import Client
from .settings import RAW_DIR, enabled_areas, get_api_key, load_config


def cache_path(raw_dir: Path, city: str, q: Q.Quarter, pc: str) -> Path:
    return raw_dir / city / f"{Q.format_quarter(q)}_pc{pc}.json"


def plan(fetch_cfg: dict, areas: list[dict], raw_dir: Path, today: dt.date | None = None) -> list[tuple]:
    """(city, quarter, price_classification, path) のうち取得が必要なものを返す。"""
    end = Q.latest_candidate(today) if fetch_cfg["end_quarter"] == "latest" else Q.parse_quarter(fetch_cfg["end_quarter"])
    base_start = Q.parse_quarter(fetch_cfg["start_quarter"])
    recent = set(Q.quarter_range(_back(end, fetch_cfg.get("refetch_recent_quarters", 0) - 1), end)) \
        if fetch_cfg.get("refetch_recent_quarters", 0) > 0 else set()
    jobs = []
    for area in areas:
        for pc in fetch_cfg["price_classifications"]:
            start = base_start
            ext = fetch_cfg.get("transaction_price_extended_start")
            if pc == "01" and ext:
                start = min(start, Q.parse_quarter(ext))
            if pc == "02":
                # 成約価格は2021年以降のみ指定可能（公式API操作説明）
                start = max(start, (2021, 1))
            for q in Q.quarter_range(start, end):
                path = cache_path(raw_dir, area["code"], q, pc)
                if path.exists() and q not in recent:
                    continue
                jobs.append((area["code"], q, pc, path))
    return jobs


def _back(q: Q.Quarter, n: int) -> Q.Quarter:
    for _ in range(max(n, 0)):
        q = Q.previous(q)
    return q


def run(jobs: list[tuple], client: Client) -> None:
    for i, (city, q, pc, path) in enumerate(jobs, 1):
        records = client.get(q[0], q[1], city, pc)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "city": city,
            "quarter": Q.format_quarter(q),
            "price_classification": pc,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "records": records,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        print(f"[{i}/{len(jobs)}] {city} {Q.format_quarter(q)} pc{pc}: {len(records)}件")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = ap.parse_args(argv)

    fetch_cfg = load_config("fetch")
    areas = enabled_areas(load_config("areas"))
    jobs = plan(fetch_cfg, areas, args.raw_dir)
    print(f"取得予定: {len(jobs)} リクエスト")
    if args.dry_run:
        for city, q, pc, path in jobs:
            print(f"  {city} {Q.format_quarter(q)} pc{pc} -> {path}")
        return
    client = Client(
        api_key=get_api_key(fetch_cfg["api_key_env"]),
        endpoint=fetch_cfg["endpoint"],
        header_name=fetch_cfg["api_key_header"],
        language=fetch_cfg.get("language", "ja"),
        request_interval_sec=fetch_cfg["request_interval_sec"],
        max_retries=fetch_cfg["max_retries"],
        backoff_base_sec=fetch_cfg["backoff_base_sec"],
        timeout_sec=fetch_cfg["timeout_sec"],
    )
    run(jobs, client)


if __name__ == "__main__":
    main()

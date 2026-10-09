"""受け入れ条件：APIキーが公開物に含まれない／実行時に外部APIを呼ばない／fixture が公開物に混ざらない。"""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public"


def public_text_files():
    return [p for p in PUBLIC.rglob("*") if p.is_file() and p.suffix in {".html", ".js", ".css", ".json"}]


def test_public_never_references_reinfolib_api():
    for p in public_text_files():
        text = p.read_text(encoding="utf-8")
        assert "ex-api" not in text, p
        assert "Ocp-Apim-Subscription-Key" not in text, p


def test_public_has_no_fixture_data():
    for p in public_text_files():
        text = p.read_text(encoding="utf-8")
        assert "_fixture" not in text and "TEST ONLY" not in text and "テスト町" not in text, p


def test_api_key_value_not_in_repo():
    key = os.environ.get("REINFOLIB_API_KEY") or ""
    env = ROOT / ".env"
    if env.exists():
        m = re.search(r"^REINFOLIB_API_KEY=(.*)$", env.read_text(encoding="utf-8"), re.M)
        key = key or (m.group(1).strip() if m else "")
    if not key:
        return
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and p.name != ".env" and "data" not in p.parts:
            try:
                assert key not in p.read_text(encoding="utf-8"), p
            except UnicodeDecodeError:
                pass


def test_env_and_raw_data_are_gitignored():
    out = subprocess.run(["git", "check-ignore", ".env", "data/raw/x.json"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.stdout.split() == [".env", "data/raw/x.json"]


def test_front_fetches_only_same_origin_json():
    app = (PUBLIC / "js" / "app.js").read_text(encoding="utf-8")
    hosts = {re.match(r"https?://([^/]+)", u).group(1) for u in re.findall(r"https?://[^\s\"'`]+", app)}
    assert hosts <= {"www.googletagmanager.com"}, hosts  # GA4（測定ID設定時のみ）以外の外部通信なし


def test_sample_model_is_flagged_and_uniform():
    m = json.loads((PUBLIC / "sample" / "model.sample.json").read_text(encoding="utf-8"))
    assert m["is_sample"] is True
    alphas = {c["alpha"] for c in m["cities"].values() if c["available"]}
    assert len(alphas) == 1  # 全市区同じ架空値（相場と誤認されないため）


def test_production_model_is_real_and_aggregate_only():
    p = PUBLIC / "model.json"
    if not p.exists():
        return
    m = json.loads(p.read_text(encoding="utf-8"))
    assert m["is_sample"] is False
    text = p.read_text(encoding="utf-8")
    for key in ("TradePrice", "Remarks", "DistrictCode", "_fixture"):
        assert key not in text

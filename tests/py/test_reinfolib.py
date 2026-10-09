import datetime as dt
import gzip
import io
import json
import urllib.error
import urllib.parse

import pytest

from batch import fetch
from batch.reinfolib import Client, ReinfolibError, ResponseFormatError, decode_body, extract_records

ENDPOINT = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"


class FakeResp(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_client(responses, sleeps):
    calls = []

    def opener(req, timeout):
        calls.append(req)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    c = Client("dummy-test-key", ENDPOINT, opener=opener, sleep=sleeps.append, request_interval_sec=0)
    return c, calls


def test_request_uses_documented_header_and_params():
    body = gzip.compress(json.dumps({"data": [{"Type": "宅地(土地)"}]}).encode())
    c, calls = make_client([FakeResp(body, {"Content-Encoding": "gzip"})], [])
    assert c.get(2024, 2, "12101", "02") == [{"Type": "宅地(土地)"}]
    req = calls[0]
    assert req.get_header("Ocp-apim-subscription-key") == "dummy-test-key"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
    assert q == {"year": ["2024"], "quarter": ["2"], "city": ["12101"], "priceClassification": ["02"],
                 "language": ["ja"]}
    assert "dummy-test-key" not in req.full_url


def test_decode_gzip_without_header_and_plain_list():
    assert decode_body(gzip.compress(b'[{"a":"1"}]')) == [{"a": "1"}]
    assert extract_records([{"a": "1"}]) == [{"a": "1"}]
    assert decode_body(b"") == []


def test_unknown_shape_raises_instead_of_guessing():
    with pytest.raises(ResponseFormatError):
        extract_records({"status": "OK", "items": []})


def _http_error(code):
    return urllib.error.HTTPError(ENDPOINT, code, "x", {}, None)


def test_retry_with_exponential_backoff():
    sleeps = []
    ok = FakeResp(json.dumps({"data": []}).encode())
    c, calls = make_client([_http_error(503), _http_error(429), ok], sleeps)
    assert c.get(2024, 1, "12101", "01") == []
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_no_retry_on_auth_error():
    c, calls = make_client([_http_error(401)], [])
    with pytest.raises(ReinfolibError):
        c.get(2024, 1, "12101", "01")
    assert len(calls) == 1


def test_plan_skips_cached_quarters_and_respects_contract_price_start(tmp_path):
    cfg = {"start_quarter": "2020Q3", "end_quarter": "2021Q2", "price_classifications": ["01", "02"],
           "transaction_price_extended_start": None, "refetch_recent_quarters": 0}
    areas = [{"code": "99901"}]
    cached = fetch.cache_path(tmp_path, "99901", (2020, 4), "01")
    cached.parent.mkdir(parents=True)
    cached.write_text("{}")
    jobs = fetch.plan(cfg, areas, tmp_path)
    got = {(q, pc) for _, q, pc, _ in jobs}
    assert ((2020, 4), "01") not in got                          # キャッシュ済みは取りに行かない
    assert ((2020, 3), "02") not in got                          # 成約価格は2021年以降のみ
    assert {((2021, 1), "02"), ((2021, 2), "02"), ((2020, 3), "01")} <= got


def test_plan_refetches_recent_quarters(tmp_path):
    cfg = {"start_quarter": "2021Q1", "end_quarter": "latest", "price_classifications": ["01"],
           "transaction_price_extended_start": None, "refetch_recent_quarters": 2}
    for q in [(2026, 2), (2026, 1), (2025, 4)]:
        p = fetch.cache_path(tmp_path, "99901", q, "01")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    jobs = fetch.plan(cfg, [{"code": "99901"}], tmp_path, today=dt.date(2026, 10, 8))
    got = {q for _, q, _, _ in jobs}
    assert (2026, 3) in got and (2026, 2) in got   # 直近2四半期は再取得
    assert (2026, 1) not in got and (2025, 4) not in got


def test_extended_start_only_for_transaction_price(tmp_path):
    cfg = {"start_quarter": "2021Q1", "end_quarter": "2021Q1", "price_classifications": ["01", "02"],
           "transaction_price_extended_start": "2020Q4", "refetch_recent_quarters": 0}
    jobs = fetch.plan(cfg, [{"code": "99901"}], tmp_path)
    assert {(q, pc) for _, q, pc, _ in jobs} == {((2020, 4), "01"), ((2021, 1), "01"), ((2021, 1), "02")}


def _http_error_body(code, body: bytes):
    return urllib.error.HTTPError(ENDPOINT, code, "x", {"Content-Encoding": "gzip"}, io.BytesIO(gzip.compress(body)))


def test_404_no_result_is_treated_as_empty():
    body = json.dumps({"message": "検索結果がありません。"}, ensure_ascii=False).encode()
    c, calls = make_client([_http_error_body(404, body)], [])
    assert c.get(2026, 2, "12101", "01") == []
    assert len(calls) == 1


def test_other_404_still_raises():
    c, _ = make_client([_http_error_body(404, b'{"message":"Resource not found"}')], [])
    with pytest.raises(ReinfolibError):
        c.get(2026, 2, "12101", "01")

"""不動産情報ライブラリ API (XIT001: 不動産価格（取引価格・成約価格）情報取得) のクライアント。

公式API操作説明 https://www.reinfolib.mlit.go.jp/help/apiManual/xit001/ で確認した仕様：
- 認証：リクエストヘッダー `Ocp-Apim-Subscription-Key` に発行されたAPIキー
- パラメータ：year(必須, 4桁), quarter(1〜4), city(5桁), priceClassification(01/02/未指定=両方), language(ja/en)
  ※ area / city / station のいずれか1つは必須
- 出力：gzip エンコードされた JSON。全フィールドが文字列型。
- 未確認：レスポンス最上位の構造（マニュアルの出力例が空）。`{"data": [...]}` と配列直下の両方を受け付け、
  それ以外は推測で処理せずエラーにする（docs/decisions.md D-03）。
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ReinfolibError(RuntimeError):
    pass


class ResponseFormatError(ReinfolibError):
    pass


def decode_body(body: bytes, content_encoding: str | None = None) -> object:
    """gzip（ヘッダー指定 or マジックバイト）なら展開してから JSON として読む。"""
    if (content_encoding or "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    if not body.strip():
        return []
    return json.loads(body.decode("utf-8"))


def extract_records(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
    raise ResponseFormatError(
        f"想定外のレスポンス構造です（最上位: {keys}）。実レスポンスを確認して extract_records を更新してください。"
    )


NO_RESULT_MESSAGE = "検索結果がありません。"


def _is_no_result(err: urllib.error.HTTPError) -> bool:
    """該当データなし（未公開の四半期など）は HTTP 404 + {"message": "検索結果がありません。"} で返る（実測、D-02）。
    この形の 404 だけを0件として扱い、それ以外の 404 はエラーにする。"""
    try:
        payload = decode_body(err.read() or b"", err.headers.get("Content-Encoding") if err.headers else None)
    except (ValueError, OSError):
        return False
    return isinstance(payload, dict) and payload.get("message") == NO_RESULT_MESSAGE


class Client:
    def __init__(
        self,
        api_key: str,
        endpoint: str,
        header_name: str = "Ocp-Apim-Subscription-Key",
        language: str = "ja",
        request_interval_sec: float = 1.5,
        max_retries: int = 5,
        backoff_base_sec: float = 2.0,
        timeout_sec: float = 60,
        opener: Callable = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("api_key が空です")
        self.api_key = api_key
        self.endpoint = endpoint
        self.header_name = header_name
        self.language = language
        self.request_interval_sec = request_interval_sec
        self.max_retries = max_retries
        self.backoff_base_sec = backoff_base_sec
        self.timeout_sec = timeout_sec
        self._open = opener
        self._sleep = sleep
        self._last_request_at: float | None = None

    def build_url(self, year: int, quarter: int, city: str, price_classification: str | None) -> str:
        params = {"year": f"{year:04d}", "quarter": str(quarter), "city": city}
        if price_classification:
            params["priceClassification"] = price_classification
        if self.language:
            params["language"] = self.language
        return f"{self.endpoint}?{urllib.parse.urlencode(params)}"

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self.request_interval_sec - (time.monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = time.monotonic()

    def get(self, year: int, quarter: int, city: str, price_classification: str | None = None) -> list[dict]:
        url = self.build_url(year, quarter, city, price_classification)
        req = urllib.request.Request(
            url, headers={self.header_name: self.api_key, "Accept-Encoding": "gzip"}
        )
        attempt = 0
        while True:
            self._throttle()
            try:
                with self._open(req, timeout=self.timeout_sec) as resp:
                    body = resp.read()
                    encoding = resp.headers.get("Content-Encoding") if resp.headers else None
                return extract_records(decode_body(body, encoding))
            except urllib.error.HTTPError as e:
                if e.code == 404 and _is_no_result(e):
                    return []
                if e.code not in RETRYABLE_STATUS or attempt >= self.max_retries:
                    # URL にキーは含まれないのでそのまま出してよい
                    raise ReinfolibError(f"HTTP {e.code}: {url}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt >= self.max_retries:
                    raise ReinfolibError(f"通信エラー: {url}: {e}") from e
            self._sleep(self.backoff_base_sec * (2 ** attempt))
            attempt += 1

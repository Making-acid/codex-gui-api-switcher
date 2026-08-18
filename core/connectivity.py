"""连通性测试：/responses smoke 为核心（硬条件），/models 为软探测。"""
from __future__ import annotations

import time
from urllib.parse import urljoin

import requests


class ConnectivityError(Exception):
    pass


def _normalize_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base.endswith("/v1") and not base.endswith("/responses"):
        return base
    return base


def smoke_test(base_url: str, api_key: str | None, model: str,
               headers: dict | None = None, query_params: dict | None = None,
               timeout: int = 20) -> dict:
    """硬条件：最小 POST {base_url}/responses 请求。"""
    url = urljoin(base_url.rstrip("/") + "/", "responses")
    payload = {"model": model, "input": "ping", "max_output_tokens": 1, "stream": False}
    req_headers = {"Content-Type": "application/json"}
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    if headers:
        req_headers.update(headers)

    start = time.time()
    try:
        resp = requests.post(url, json=payload, headers=req_headers,
                             params=query_params or {}, timeout=timeout)
        ms = int((time.time() - start) * 1000)
        ok = resp.status_code < 400
        error = None
        if not ok:
            error = _describe_error(resp, ms)
        return {"ok": ok, "status": resp.status_code, "ms": ms,
                "error": error, "url": url}
    except requests.exceptions.Timeout:
        return {"ok": False, "status": None, "ms": timeout * 1000,
                "error": f"请求超时（>{timeout}s）", "url": url}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": None, "ms": int((time.time() - start) * 1000),
                "error": "网络连接失败：无法访问该地址", "url": url}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "status": None, "ms": int((time.time() - start) * 1000),
                "error": f"请求异常: {exc}", "url": url}


def probe_models(base_url: str, api_key: str | None,
                 headers: dict | None = None, query_params: dict | None = None,
                 timeout: int = 15) -> dict:
    """软探测：GET {base_url}/models。失败不影响判定，仅作参考。"""
    url = urljoin(base_url.rstrip("/") + "/", "models")
    req_headers = {}
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    if headers:
        req_headers.update(headers)

    start = time.time()
    try:
        resp = requests.get(url, headers=req_headers,
                            params=query_params or {}, timeout=timeout)
        ms = int((time.time() - start) * 1000)
        models = []
        if resp.status_code < 400:
            data = resp.json()
            for item in data.get("data", []) if isinstance(data, dict) else []:
                mid = item.get("id")
                if mid:
                    models.append(str(mid))
        return {"ok": resp.status_code < 400, "status": resp.status_code, "ms": ms,
                "models": models[:50],
                "error": None if resp.status_code < 400
                else f"GET /models 返回 {resp.status_code}（不影响连通判定）"}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "status": None, "ms": int((time.time() - start) * 1000),
                "models": [], "error": f"GET /models 探测失败: {exc}（不影响连通判定）"}


def test_connection(base_url: str, api_key: str | None, model: str,
                    headers: dict | None = None, query_params: dict | None = None,
                    timeout: int = 20) -> dict:
    """组合测试：smoke 为硬条件 + models 软探测。"""
    smoke = smoke_test(base_url, api_key, model, headers, query_params, timeout)
    models = probe_models(base_url, api_key, headers, query_params)
    return {
        "smoke": smoke,
        "models": models,
        "passed": smoke["ok"],
        "summary": ("连通正常" if smoke["ok"] else f"连通失败: {smoke['error']}"),
    }


def _describe_error(resp: requests.Response, ms: int) -> str:
    detail = ""
    try:
        body = resp.json()
        detail = str(body.get("error", body))[:200]
    except Exception:
        detail = resp.text[:200]
    hint = ""
    if resp.status_code in (401, 403):
        hint = "（API key 无效或无权限）"
    elif resp.status_code == 404:
        hint = "（地址不存在；注意部分服务商需在 base_url 后保留 /v1）"
    elif resp.status_code == 429:
        hint = "（请求被限流）"
    return f"HTTP {resp.status_code} {hint}: {detail}"

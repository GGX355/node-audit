from node_audit.cli import _parse_services
from node_audit.core.services import (
    PROBE_URLS,
    _netflix_verdict,
    _openai_verdict,
    _tiktok_verdict,
)


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except Exception:
        return True


def test_openai_verdict():
    # 401 = 地区可用（匿名请求的预期响应）
    assert _openai_verdict(401, "")[0] == "ok"
    # 403 + unsupported 错误码 = 封区
    body = '{"error":{"code":"unsupported_country_region_territory","message":"..."}}'
    status, note = _openai_verdict(403, body)
    assert status == "blocked" and "不支持" in note
    # 403 无特征也按封禁处理
    assert _openai_verdict(403, "denied")[0] == "blocked"
    # 请求失败 / 意外状态码 = unknown
    assert _openai_verdict(None, "")[0] == "unknown"
    assert _openai_verdict(500, "")[0] == "unknown"


def test_netflix_verdict():
    assert _netflix_verdict(200, 200)[0] == "full"
    assert _netflix_verdict(200, 403)[0] == "original"
    assert _netflix_verdict(403, 403)[0] == "none"
    assert _netflix_verdict(200, None)[0] == "unknown"
    assert _netflix_verdict(None, 200)[0] == "full"


def test_err_note_timeout_and_reset():
    from node_audit.core.services import _err_note
    assert "超时" in _err_note("URLError: timed out")
    assert "重置" in _err_note("ConnectionResetError: [WinError 10054] reset")
    assert _err_note(None) == "请求失败"


def test_tiktok_verdict():
    assert _tiktok_verdict(200, "<html>normal page</html>")[0] == "ok"
    # 特征大小写不敏感
    assert _tiktok_verdict(200, "Please solve this CAPTCHA")[0] == "captcha"
    assert _tiktok_verdict(200, "redirect to /verify?x=1")[0] == "captcha"
    assert _tiktok_verdict(403, "")[0] == "blocked"
    assert _tiktok_verdict(429, "")[0] == "blocked"
    assert _tiktok_verdict(None, "")[0] == "unknown"


def test_parse_services():
    assert _parse_services("all") == ["netflix", "openai", "tiktok"]
    assert _parse_services("none") == []
    assert _parse_services("off") == []
    assert _parse_services("openai, tiktok") == ["openai", "tiktok"]
    assert _raises(lambda: _parse_services("bogus"))


def test_probe_urls_are_https_and_public():
    # 无 Cookie 保证的可核验依据：清单公开且全部为 HTTPS 匿名端点
    for service, urls in PROBE_URLS.items():
        assert urls, service
        for url in urls:
            assert url.startswith("https://"), url

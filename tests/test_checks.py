from node_audit.core import checks


def test_ipqs_goes_direct_ignores_proxy():
    seen = []
    orig = checks.http_get

    def fake(url, proxy, timeout=15, headers=None):
        seen.append((url, proxy))
        return 200, b'{"success": true, "fraud_score": 1, "proxy": false, "vpn": false, "tor": false}'

    checks.http_get = fake
    try:
        out = checks.check_ipqs("1.1.1.1", "secret-key", "http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert len(seen) == 1
    url, proxy = seen[0]
    assert proxy is None
    assert "secret-key" in url and "1.1.1.1" in url
    assert out["available"] is True
    assert out["fraud_score"] == 1

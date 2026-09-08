from node_audit.core import checks


def test_ptr_qname_v4_and_v6():
    assert checks.ptr_qname("1.2.3.4") == "4.3.2.1.in-addr.arpa"
    assert checks.ptr_qname("2001:db8::1") == (
        "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa"
    )
    assert checks.ptr_qname(None) is None
    assert checks.ptr_qname("") is None
    assert checks.ptr_qname("not-an-ip") is None


def test_check_ptr_queries_ip6_arpa():
    seen = []
    orig = checks.http_get

    def fake(url, proxy, timeout=15, headers=None):
        seen.append(url)
        return 200, b'{"Answer":[{"type":12,"data":"host.example."}]}'

    checks.http_get = fake
    try:
        out = checks.check_ptr("2001:db8::1", "http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert out == "host.example"
    assert "ip6.arpa" in seen[0]
    assert "in-addr.arpa" not in seen[0]


def test_check_ptr_skips_invalid():
    assert checks.check_ptr(None, "http://x") is None
    assert checks.check_ptr("nope", "http://x") is None


def _identity_fake(mapping):
    def fake(url, proxy, timeout=15, headers=None):
        for key, resp in mapping.items():
            if key in url:
                return resp
        return 500, b""
    return fake


def test_identity_dual_stack_prefers_ipapi_hosting():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "ip-api.com": (200, b'{"query":"1.2.3.4","country":"Japan","countryCode":"JP",'
                       b'"city":"Tokyo","isp":"Amazon","org":"AWS","as":"AS16509 Amazon",'
                       b'"asname":"AMAZON","proxy":false,"hosting":true}'),
        "api64.ipify.org": (200, b"2001:db8::1"),
        "ipwho.is": (200, b'{"success":true,"ip":"2001:db8::1","country":"Japan",'
                    b'"country_code":"JP","city":"Osaka",'
                    b'"connection":{"asn":16509,"org":"Amazon","isp":"Amazon"},'
                    b'"security":{"hosting":true}}'),
    })
    try:
        out = checks.check_identity("http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert out["query"] == "1.2.3.4"
    assert out["query6"] == "2001:db8::1"
    assert out["hosting"] is True
    assert out["city"] == "Tokyo"
    assert out["identity_source"] == "ip-api"
    assert out["v6"]["city"] == "Osaka"


def test_identity_v6_only_not_fatal():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "ip-api.com": (500, b""),
        "api64.ipify.org": (200, b"2001:db8::8"),
        "ipwho.is": (200, b'{"success":true,"ip":"2001:db8::8","country":"Japan",'
                    b'"country_code":"JP","city":"Tokyo",'
                    b'"connection":{"asn":2516,"org":"KDDI","isp":"KDDI"},'
                    b'"security":{"hosting":false}}'),
    })
    try:
        out = checks.check_identity("http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert out is not None
    assert out["query"] is None
    assert out["query6"] == "2001:db8::8"
    assert out["countryCode"] == "JP"
    assert out["hosting"] is False
    assert out["identity_source"] == "ipwho.is"


def test_identity_ipify_v4_means_no_v6():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "ip-api.com": (200, b'{"query":"8.8.8.8","country":"US","countryCode":"US",'
                       b'"city":"Mountain View","isp":"Google","org":"Google",'
                       b'"as":"AS15169","asname":"GOOGLE","proxy":false,"hosting":true}'),
        "api64.ipify.org": (200, b"8.8.8.8"),
    })
    try:
        out = checks.check_identity("http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert out["query"] == "8.8.8.8"
    assert out["query6"] is None
    assert out["v6"] is None


def test_identity_both_fail():
    orig = checks.http_get
    checks.http_get = _identity_fake({})
    try:
        assert checks.check_identity("http://127.0.0.1:1") is None
    finally:
        checks.http_get = orig


def test_identity_v6_without_whois_still_keeps_address():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "ip-api.com": (500, b""),
        "api64.ipify.org": (200, b"2001:db8::9"),
        "ipwho.is": (500, b""),
    })
    try:
        out = checks.check_identity("http://x")
    finally:
        checks.http_get = orig
    assert out["query6"] == "2001:db8::9"
    assert out["hosting"] is None


def test_ping0_queries_ip_path_not_homepage():
    seen = []
    orig = checks.http_get

    def fake(url, proxy, timeout=15, headers=None):
        seen.append(url)
        html = (
            "<html><body><div>家庭宽带 IP</div><div>原生 IP</div>"
            "<div>7%</div><div>极度纯净</div></body></html>"
        )
        return 200, html.encode()

    checks.http_get = fake
    try:
        out = checks.check_ping0("1.2.3.4", "http://127.0.0.1:1")
    finally:
        checks.http_get = orig
    assert any("/ip/1.2.3.4" in u for u in seen)
    assert out["available"] is True
    assert "家庭宽带" in (out["ip_type"] or "")
    assert out["risk_pct"] == 7


def test_ippure_json_residential():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "my.ippure.com": (200, b'{"ip":"36.1.1.1","fraudScore":8,'
                          b'"isResidential":true,"isBroadcast":false,'
                          b'"country":"Taiwan","countryCode":"TW","city":"Taipei",'
                          b'"asn":3462,"asOrganization":"CHT"}'),
    })
    try:
        out = checks.check_ippure("http://x")
    finally:
        checks.http_get = orig
    assert out["available"] is True
    assert out["is_residential"] is True
    assert out["fraud_score"] == 8


def test_identity_falls_back_to_ippure():
    orig = checks.http_get
    checks.http_get = _identity_fake({
        "my.ippure.com": (200, b'{"ip":"9.9.9.9","isResidential":false,'
                          b'"country":"US","countryCode":"US","city":"LA",'
                          b'"asn":1,"asOrganization":"Foo"}'),
    })
    try:
        out = checks.check_identity("http://x")
    finally:
        checks.http_get = orig
    assert out["query"] == "9.9.9.9"
    assert out["hosting"] is True
    assert out["identity_source"] == "ippure"


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

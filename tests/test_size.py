from node_audit.cli import _parse_size


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except Exception:
        return True


def test_parse_size_units():
    assert _parse_size("10MB") == 10_000_000
    assert _parse_size("2mb") == 2_000_000
    assert _parse_size("1GB") == 1_000_000_000
    assert _parse_size("500KB") == 500_000
    assert _parse_size("1000") == 1000


def test_parse_size_invalid():
    assert _raises(lambda: _parse_size("abc"))
    assert _raises(lambda: _parse_size("-5MB"))
    assert _raises(lambda: _parse_size(""))

import tempfile
from pathlib import Path

from node_audit.clash.discover import (
    Discovery, config_in_dir, discover, runtime_config_dirs,
)
from node_audit.core.isolated import core_binary_candidates, core_in_dir, core_names
from node_audit.paths import resolve_app_path


def test_runtime_dirs_rev_before_non_rev():
    dirs = runtime_config_dirs()
    labels = [label for label, _ in dirs]
    assert "Clash Verge Rev" in labels
    assert "Clash Verge" in labels
    assert labels.index("Clash Verge Rev") < labels.index("Clash Verge")
    # 每条都是 Path，且 Rev 的典型目录名在列表里
    joined = " ".join(str(p) for _, p in dirs)
    assert "clash-verge-rev" in joined.lower() or "clash-verge-rev" in joined


def test_describe_uses_app_label_not_hardcoded_rev():
    d = Discovery(config_path=str(Path("clash-verge.yaml")), app_label="Clash Verge")
    text = d.describe()
    assert "Clash Verge" in text
    assert "Verge Rev" not in text


def test_core_candidates_include_non_rev():
    names = [p.name.lower() for p in core_binary_candidates()]
    assert any("verge-mihomo" in n for n in names)
    paths = [str(p).lower() for p in core_binary_candidates()]
    assert any("clash verge" in p or "clash-verge" in p for p in paths)


def test_config_in_dir_prefers_clash_verge_yaml():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        assert config_in_dir(d) is None
        (d / "config.yaml").write_text("mixed-port: 1\n", encoding="utf-8")
        assert config_in_dir(d).name == "config.yaml"
        (d / "clash-verge.yaml").write_text("mixed-port: 2\n", encoding="utf-8")
        assert config_in_dir(d).name == "clash-verge.yaml"


def test_core_in_dir_finds_mihomo():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        assert core_in_dir(d) is None
        fake = d / core_names()[1]
        fake.write_bytes(b"x")
        found = core_in_dir(d)
        assert found == fake


def test_discover_explicit_config_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "mine.yaml"
        p.write_text("mixed-port: 12345\nsecret: abc\n", encoding="utf-8")
        disc = discover({"config": str(p)})
        assert disc.config_path == str(p)
        assert disc.app_label == "指定配置"
        assert disc.mixed_port == 12345
        assert disc.secret == "abc"


def test_resolve_app_path_relative_and_absolute():
    with tempfile.TemporaryDirectory() as td:
        abs_p = Path(td) / "a.yaml"
        abs_p.write_text("x", encoding="utf-8")
        got = resolve_app_path(str(abs_p))
        assert got == abs_p
        assert resolve_app_path("") is None
        assert resolve_app_path(None) is None

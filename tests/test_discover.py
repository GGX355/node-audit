from pathlib import Path

from node_audit.clash.discover import Discovery, runtime_config_dirs
from node_audit.core.isolated import core_binary_candidates


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

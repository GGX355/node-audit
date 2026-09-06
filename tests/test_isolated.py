"""顶层块抽取与临时配置拼装（isolated 模式的核心纯逻辑）。"""
from node_audit.core.isolated import build_config, extract_top_level_block

RUNTIME = """mode: rule
mixed-port: 7897
secret: something

proxies:
  - name: "节点A|5x倍率"
    type: ss
    server: a.example.com
    port: 8388
    cipher: aes-128-gcm
    password: "p@ss w0rd"
  - name: 节点B
    type: trojan
    server: b.example.com
    port: 443
    password: x

proxy-groups:
  - name: 组
    type: select
    proxies: [节点A, 节点B]
rules:
  - MATCH,DIRECT
"""


def test_extract_proxies_block():
    block = extract_top_level_block(RUNTIME, "proxies")
    assert block is not None
    assert block.startswith("proxies:")
    assert '"节点A|5x倍率"' in block
    # 不能越过 proxies 块吃到 proxy-groups
    assert "proxy-groups" not in block


def test_extract_zero_indent_sequence_items():
    # Verge 实际生成的格式：列表项零缩进，不能被当成“下一个顶层键”截断
    cfg = "mode: rule\nproxies:\n- name: a\n  type: ss\n- name: b\n  type: trojan\nrules:\n  - MATCH,DIRECT\n"
    block = extract_top_level_block(cfg, "proxies")
    assert block is not None
    assert "- name: b" in block and "type: trojan" in block
    assert "rules:" not in block


def test_extract_missing_block():
    assert extract_top_level_block("mode: rule\n", "proxies") is None
    # 单行空值不算有效块
    assert extract_top_level_block("proxies: []\nrules: []\n", "proxies") is None


def test_block_not_confused_by_nested_key():
    cfg = """tun:
  enable: true
  dns-ports: [1]
proxies:
  - name: a
foo: 1
"""
    block = extract_top_level_block(cfg, "proxies")
    assert block is not None
    assert "foo: 1" not in block


def test_build_config_pins_names_and_ports():
    block = extract_top_level_block(RUNTIME, "proxies")
    cfg = build_config(block, ["节点A|5x倍率", "节点B"], [41001, 41002], 41000, "s3cret")
    assert "    port: 41001" in cfg
    assert "    port: 41002" in cfg
    # 名称用双引号标量安全转义（含 | 等特殊字符）
    assert 'proxy: "节点A|5x倍率"' in cfg
    assert 'proxy: "节点B"' in cfg
    # 只监听本地回环
    assert cfg.count("listen: 127.0.0.1") == 2
    # 控制器仅绑回环且带随机 secret，unified-delay 与主实例口径一致
    assert "external-controller: 127.0.0.1:41000" in cfg
    assert 'secret: "s3cret"' in cfg
    assert "unified-delay: true" in cfg
    # 内联 proxies 块原样保留
    assert "cipher: aes-128-gcm" in cfg

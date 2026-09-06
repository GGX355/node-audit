from node_audit.core.filters import (
    heavy_traffic,
    is_real_node,
    rate_multiplier,
    region_from_name,
)


def test_pseudo_info_nodes_filtered():
    # 来自真实订阅的三种信息卡假节点
    assert not is_real_node("剩余流量：227.29 GB", "AnyTLS")
    assert not is_real_node("套餐到期：2027-07-15", "AnyTLS")
    assert not is_real_node("距离下次重置剩余：9 天", "AnyTLS")
    # 内置策略与代理组
    assert not is_real_node("DIRECT", "Direct")
    assert not is_real_node("REJECT", "Reject")
    assert not is_real_node("♻️ 自动选择", "URLTest")


def test_real_nodes_pass_through():
    assert is_real_node("台湾1|5x倍率|勿跑大流量", "AnyTLS")
    assert is_real_node("2x专线-新加坡-4 (IPv6)", "Trojan")
    assert is_real_node("韩国|移动优化", "Hysteria2")


def test_pseudo_pattern_does_not_hit_heavy_flag():
    # “勿跑大流量”包含“流量”，但伪节点正则不能误伤它
    assert is_real_node("香港原生IP-1|勿跑大流量", "AnyTLS")
    assert heavy_traffic("香港原生IP-1|勿跑大流量")
    assert not heavy_traffic("2x专线-日本-1")


def test_region_extraction():
    assert region_from_name("2x专线-日本-1") == ("JP", "日本")
    assert region_from_name("香港原生IP-1|勿跑大流量") == ("HK", "香港")
    assert region_from_name("美国洛杉矶|高速下载") == ("US", "美国")
    assert region_from_name("韩国|移动优化") == ("KR", "韩国")
    # 无地区信息的名称
    assert region_from_name("剩余流量：227.29 GB") == (None, None)


def test_region_indonesia_not_india():
    # 印度尼西亚不能被解析成印度
    assert region_from_name("印度尼西亚-雅加达")[0] is None


def test_rate_multiplier():
    assert rate_multiplier("台湾1|5x倍率|勿跑大流量") == 5.0
    assert rate_multiplier("0.5x倍率-测试") == 0.5
    assert rate_multiplier("2x专线-日本-1") is None

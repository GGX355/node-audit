"""节点过滤与名称标签解析。

机场订阅里混着三类“非节点”条目（代理组、DIRECT/REJECT 内置策略、
“剩余流量/套餐到期”等信息卡假节点），以及带运营语义的命名标签
（倍率、勿跑大流量、地区名），这里统一解析。
"""
from __future__ import annotations

import re

# 这些 type 不是真实节点
SPECIAL_TYPES = {
    "Selector", "URLTest", "Fallback", "LoadBalance", "Relay",
    "Compatible", "Direct", "Reject", "RejectDrop", "Pass", "PassRule",
}

# 信息卡假节点的命名特征（注意不能包含裸“流量”，会误伤“勿跑大流量”真实节点）
PSEUDO_NAME_PAT = re.compile(r"(剩余|到期|重置|套餐|官网|订阅|工单)")

# 节点名 -> 地区。用于“名称地区 vs IP 归属地”一致性与延迟合理性校验。
REGION_PATTERNS = [
    (r"台湾|台北|新北|彰化", "TW", "台湾"),
    (r"香港|Hong ?Kong", "HK", "香港"),
    (r"澳门", "MO", "澳门"),
    (r"日本|东京|大阪|Japan", "JP", "日本"),
    (r"韩国|首尔|Korea", "KR", "韩国"),
    (r"新加坡|狮城|Singapore", "SG", "新加坡"),
    (r"美国|洛杉矶|堪萨斯|圣何塞|西雅图|圣克拉拉|United States", "US", "美国"),
    (r"加拿大|Canada", "CA", "加拿大"),
    (r"英国|伦敦|United Kingdom", "GB", "英国"),
    (r"法国|巴黎|France", "FR", "法国"),
    (r"德国|法兰克福|Germany", "DE", "德国"),
    (r"荷兰|Netherlands", "NL", "荷兰"),
    (r"澳大利亚|悉尼|Australia", "AU", "澳大利亚"),
    (r"俄罗斯|Russia", "RU", "俄罗斯"),
    (r"印度(?!尼)", "IN", "印度"),
    (r"土耳其|Turkey", "TR", "土耳其"),
    (r"泰国|Thailand", "TH", "泰国"),
    (r"越南|Vietnam", "VN", "越南"),
    (r"马来西亚|Malaysia", "MY", "马来西亚"),
    (r"菲律宾|Philippines", "PH", "菲律宾"),
    (r"阿根廷|Argentina", "AR", "阿根廷"),
    (r"巴西|Brazil", "BR", "巴西"),
]

# 从中国大陆出发的 RTT 合理上限（ms）。超出即标记“落地存疑”。
# 该阈值按“用户在中国大陆”的场景校准；其他出发地请自行调整。
RTT_MAX_MS = {
    "HK": 150, "MO": 150, "TW": 150, "SG": 150,
    "JP": 180, "KR": 200,
    "US": 320, "CA": 320,
    "GB": 380, "FR": 380, "DE": 380, "NL": 380, "AU": 380, "RU": 380, "IN": 380,
}
DEFAULT_RTT_MAX_MS = 450


def is_real_node(name: str, ptype: str) -> bool:
    return ptype not in SPECIAL_TYPES and not PSEUDO_NAME_PAT.search(name)


def region_from_name(name: str):
    """返回 (国家码, 中文名)，节点名无地区信息时返回 (None, None)。"""
    for pat, code, cn in REGION_PATTERNS:
        if re.search(pat, name, re.I):
            return code, cn
    return None, None


def heavy_traffic(name: str) -> bool:
    """节点名标注了不宜跑大流量（如“勿跑大流量”）。"""
    return "勿跑大流量" in name


def rate_multiplier(name: str):
    """解析“N x倍率”计费倍率标签，无标注返回 None。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX×]\s*倍率", name)
    return float(m.group(1)) if m else None

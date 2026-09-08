# node-audit 节点质量审计报告（示例，数据为虚构演示）

- 生成时间: 2026-01-01T12:00:00
- 控制器: \\.\pipe\verge-mihomo | mixed-port 7897
- 运行模式: isolated
- 节点数: 3

## 摘要

- **机房**: 2
- **疑似真家宽·原生·风控7%**: 1

## 明细

| 节点 | 出口IP | 归属 | ISP | ASN | 类型 | PTR | 原生 | RTT(ms) | 速度(Mbps) | 一致性 | 风险 | 服务 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 示例-台湾家宽 | 36.227.213.17 / 2001:db8:1::2 | Taiwan Taipei | Chunghwa Telecom Co., Ltd. | AS3462 Data Communication Business Group | 住宅候选 | 36-227-213-17.dynamic-ip.hinet.net | 原生 | gstatic:53,cloudflare:75 | 12.3 | match | 0 | GPT ✓ / NF 全解锁 / TT 可用 | 疑似真家宽·原生·风控7% |
| 示例-东京机房 | 52.196.115.92 | Japan Tokyo | Amazon Technologies Inc. | AS16509 Amazon.com, Inc. | 机房 | ec2-52-196-115-92.ap-northeast-1.compute.amazonaws.com | - | gstatic:80,cloudflare:81 | 95.8 | match | 2 | GPT ✓ / NF 全解锁(JP) / TT 可用 | 机房 |
| 示例-首尔"优化" | 82.117.226.200 | South Korea Incheon | G-Core Labs S.A. | AS199524 G-Core Labs S.A. | 住宅候选 | - | 原生 | gstatic:422,cloudflare:391 | 4.7 | match | 41 | GPT ✓ / NF 仅自制 / TT 人机验证 | 疑似IDC·原生·风控96%（RTT 391ms 超出 韩国 合理上限 200ms，落地存疑；ip-api 标记为 proxy/VPN；Scamalytics 标记 Datacenter） |

## 失败节点

- 示例-失效节点: 无法通过该节点获取出口 IP（v4 ip-api 与 v6 ipify 均失败）

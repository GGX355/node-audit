# node-audit

Clash / mihomo 节点质量审计工具：对订阅里的**每一个节点**自动做「IP 身份 + 注册档案 + 纯净度 + 延迟 + 测速」检查，输出控制台表格与 JSON / Markdown 报告。

对标的手工流程：ip-api 查身份 → Scamalytics / ping0 查纯净度 → PTR / ASN / whois 查注册档案 → 逐节点测延迟测速。本工具把它固化成一条命令，并提供两种互斥的运行模式。

## 两种运行模式

| 模式 | 原理 | 适用 |
|---|---|---|
| **isolated**（v0.2，推荐） | 从 Verge 运行时配置原样搬运 `proxies:` 块，在本机拉起一个临时 mihomo 实例，为每个节点开一个只绑定 127.0.0.1 的独立端口并钉住该节点 | **全程零干扰**——你正在用的代理、浏览、下载都不受影响 |
| **attach**（v0.1） | 接管运行中的实例：记录快照 → 切 global 模式逐节点轮巡 → 还原 | 找不到内核二进制或订阅走 proxy-providers 时的回退；**期间流量会逐节点跳转** |

两种模式共用同一条检查管线与判定逻辑，报告格式完全一致。

## 安装与运行

零第三方依赖，Python ≥ 3.9：

```bash
# 直接运行（仓库根目录）
PYTHONPATH=src python -m node_audit discover

# 或安装为命令行工具
pip install .
node-audit discover
```

## 使用示例

```bash
# 只读探测：控制器信息、节点数、代理组
node-audit discover

# 列出将测哪些节点、解析出哪些标签，不做任何切换
node-audit audit --dry-run

# 零干扰全量审计（isolated 模式）
node-audit audit --mode isolated --yes

# attach 模式（⚠ 期间流量会逐节点跳转，建议空闲时跑）
node-audit audit --yes

# 小样本试跑：只测名称匹配的节点
node-audit audit --mode isolated --include "台湾|香港原生" --yes

# 全节点深检 + 官方风控 API（key 可用环境变量 NODE_AUDIT_IPQS_KEY / NODE_AUDIT_ABUSEIPDB_KEY）
node-audit audit --mode isolated --yes --deep all \
  --ipqs-key XXXX --abuseipdb-key XXXX
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--mode attach\|isolated` | 运行模式（默认 attach；isolated 需要能找到 mihomo 内核） |
| `--include` / `--exclude` | 按名称正则筛选节点 |
| `--limit N` | 最多测前 N 个 |
| `--speed-bytes 10MB` | 测速下载量；名称含“勿跑大流量”的节点自动降为 2MB |
| `--speed-max-seconds 60` | 单节点测速硬时限，到时按已收字节计算部分速度 |
| `--skip-speed` | 不测速 |
| `--deep auto\|off\|all` | 深检范围：auto=仅住宅候选节点 |
| `--ipqs-key` / `--abuseipdb-key` | 官方风控 API key（免费额度：IPQS 5000/月，AbuseIPDB 1000/天） |
| `--port-base 41000` | isolated 模式独立端口起始值 |
| `--core PATH` | isolated 模式的 mihomo 内核路径（默认自动查找 Clash Verge 安装目录） |
| `--out DIR` | 报告输出目录（默认 `./node-audit-report`） |
| `--api / --pipe / --secret / --mixed-port` | 手动指定控制器与代理端口（默认自动发现） |

## 检查项

| 阶段 | 检查项 | 数据源 |
|---|---|---|
| 快筛 | 出口 IP / 国家 / ISP / ASN / hosting / proxy 标记 | ip-api.com |
| 快筛 | PTR 反向解析（家宽型 vs 机房型） | Cloudflare / Google DoH |
| 快筛 | 注册组织 / 注册日期（自动路由正确 RIR） | rdap.org → ARIN/APNIC/RIPE… |
| 快筛 | 多目标延迟 + **延迟-地区一致性**（RTT 超出地区合理上限 → 落地存疑） | gstatic / cloudflare 204 探针 |
| 快筛 | 下载测速（Cloudflare 为主，cachefly 备用，带硬时限） | speed.cloudflare.com |
| 深检 | Fraud Score / Datacenter 标记 | Scamalytics（网页，best-effort） |
| 深检 | 家庭宽带/IDC机房、原生/广播、风控值 | ping0.cc（网页，best-effort） |
| 深检 | 信任分 / proxy-vpn-tor 标记 | IPQS 官方 API（需免费 key） |
| 深检 | 滥用举报置信度 | AbuseIPDB 官方 API（需免费 key） |

判定口径：`hosting=true` 直接判**机房**（生死线）；`hosting=false` 为**住宅候选**，再由 ping0 细分为「疑似真家宽·原生」等；官方 API 与网页源互相交叉验证——单一数据源漏判时（例如 ip-api 未标记某 CDN 机房段），其他来源的标记会写进 notes。

## 安全设计

- attach 模式：快照（mode + GLOBAL 选中节点）在 `finally` **和** `atexit` 两层兜底还原，Ctrl+C、异常、硬杀进程都会尽力恢复；
- isolated 模式：临时配置与日志放在系统临时目录，用完即删；listeners 只绑定 127.0.0.1，不向局域网开放；
- 所有请求显式走被测节点出口，不读取环境代理变量；
- 信息卡假节点（“剩余流量/套餐到期”等）、DIRECT、代理组自动过滤；“勿跑大流量”节点自动降级测速。

## 测试

```bash
python tests/run_all.py   # 零依赖
# 或 pip install pytest && pytest tests
```

## 已知限制

- 出口 IP 审计覆盖 IPv4（ip-api 免费端点仅 v4）；标 IPv6 的节点实际也多以 v4 出口被检测，v6-only 出口列入路线图；
- Scamalytics / ping0 为网页解析（best-effort），反爬策略变化时自动标记“不可用”而不阻塞整体；
- 延迟合理性阈值按“用户在中国大陆”校准，其他出发地请调整 `core/filters.py` 中的 `RTT_MAX_MS`；
- isolated 模式要求订阅以内联 `proxies:` 形式存在于 Verge 运行时配置（Clash Verge Rev 默认如此）；走 `proxy-providers` 的配置请用 attach 模式。

## 路线图

- [x] v0.1 attach 模式快筛 + 深检 + 表格/JSON/Markdown 报告
- [x] v0.2 isolated 零干扰模式；IPQS / AbuseIPDB 官方 API；测速硬时限；atexit 状态还原兜底；单元测试
- [ ] v0.3 服务风控探针（TikTok 验证码 / OpenAI 可用性 / Netflix 解锁）
- [ ] v0.4 HTML 报告 + SQLite 历史趋势
- [ ] v1.0 Go 重写单二进制；IPv6 出口审计

## 免责声明

本工具仅用于检测**自有订阅节点**的质量，不提供、不配置任何代理服务。Scamalytics / ping0 数据版权归原站，请控制请求频率。

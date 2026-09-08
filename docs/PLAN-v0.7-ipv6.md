# 下一步计划：v0.7 IPv6 出口审计

状态：**已落地为 0.7.0**（本文件保留为当时的计划书）。

原 README 把 v1.0 写成三件事捆在一起。**不要一次做完。**

| 原 v1.0 条目 | 现状 | 本轮 |
|---|---|---|
| SVG 趋势图 | 控制台已有 RTT / 速度 / 风控 SVG sparkline + IP 时间轴 | 不做新系统；以后最多补日期刻度 |
| IPv6 出口审计 | **未做**：ip-api 只认 v4；PTR 只处理带 `.` 的地址；isolated 写死 `ipv6: false` | **这就是下一刀** |
| Go 重写单二进制 | 等于整仓重写 | **不做**。要 exe 用 PyInstaller 打包现有 Python |

---

## 目标

每个节点同时探测 **v4 出口 + v6 出口**：

- 有 v4：继续 ip-api（现有逻辑）
- 有 v6：PTR 走 `ip6.arpa` 半字节反转；身份走 **ipwho.is**（免费、支持 v6、无 key）；RDAP `rdap.org/ip/{v6}` 本来就通
- 双栈：两个地址都显示；判定优先用能拿到 `hosting` 的那条；另一条写 notes
- 仅 v6：不再因为 ip-api 失败把整节点判死
- 控制台：出口栏显示 v4 / v6；「换」对两个地址分别标

isolated 临时内核：`ipv6: false` → `true`（DNS 也可开 v6）。请求仍走 `127.0.0.1` HTTP 代理，**本机有没有 IPv6 无所谓**。

## 数据

- `NodeReport.exit_ip6`
- schema **v3**：`results.exit_ip6 TEXT`（`_add_column_if_missing`）
- 趋势「换 IP」：v4 或 v6 任一变了都算换

身份探测（都走被测代理，不读环境代理）：

1. `http://ip-api.com/json/?fields=…` → v4 + hosting（现有）
2. `https://api64.ipify.org` → 返回含 `:` 则为 v6 出口
3. 有 v6 时 `https://ipwho.is/{v6}` 补国家 / ISP（v4 失败时顶上判定）

PTR：v4 保持 `in-addr.arpa`；v6 按 RFC 3596 展开到 `ip6.arpa`。

## 改哪些文件

| 文件 | 改动 |
|---|---|
| `src/node_audit/core/checks.py` | `check_identity` 双栈；`check_ptr` 支持 v6 |
| `src/node_audit/core/isolated.py` | `ipv6: true` |
| `src/node_audit/core/models.py` / `runner.py` | `exit_ip6`；失败文案区分 v4/v6 |
| `src/node_audit/core/history.py` | schema v3 + `exit_ip6` |
| `src/node_audit/report/dashboard.py` / `html.py` / `output.py` | 展示双地址 |
| `tests/` | PTR 展开、双栈 identity mock、schema v3 |

版本号 **0.7.0**。继续零第三方依赖。

## 本轮不要做

- Go 重写
- 新开 npm / 图表库
- 本机直连 IPv6（全部经节点 HTTP 代理）

## 再往后（v0.7 完成之后）

- 单二进制：`pyinstaller -F` 出 `node-audit.exe`（可选）
- Go：真要做再单独立项
- SVG 大图：给 sparkline 加日期刻度即可

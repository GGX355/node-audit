# 换电脑交接（2026-09-08）

仓库：https://github.com/GGX355/node-audit  
分支：`main`  
当前代码版本：**0.6.0**（上一发版是 v0.4.1；这次把 0.5 + 0.6 一起推上去）

下一刀计划（**尚未写代码**）：[`PLAN-v0.7-ipv6.md`](PLAN-v0.7-ipv6.md)

---

## 新电脑怎么接手

```powershell
git clone https://github.com/GGX355/node-audit.git
cd node-audit
# Python ≥ 3.9，零 pip 依赖
$env:PYTHONPATH='src'
python tests/run_all.py          # 应 61 passed
python -m node_audit --version   # node-audit 0.6.0
```

看界面（假数据，3 个节点）：

- 双击 `examples/sample-dashboard.html`
- 顶上黄条写着「演示数据，不是你的订阅」

看自己的订阅（全量节点）：

```powershell
$env:PYTHONPATH='src'
python -m node_audit audit --dry-run --mode isolated   # 只列表，应看到几十个
python -m node_audit audit --mode isolated --yes       # 全量，十几～二十分钟
# 然后打开 node-audit-report\latest.html
python -m node_audit serve --open                      # 或起本机页，只听 127.0.0.1
```

前提：这台电脑也装着 Clash Verge / Verge Rev，且至少成功跑过一次（磁盘上有 `clash-verge.yaml`）。isolated **不必**正在开着 Verge，但要能读到运行时配置、找得到 `verge-mihomo.exe`。

Windows 配置常见路径：

- `%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml`
- 内核：`%LOCALAPPDATA%\Programs\Clash Verge\verge-mihomo.exe`（或 Clash Verge Rev）

每日定时：`examples\register-daily-task.ps1`（04:00 isolated）。

不要把 `node-audit-report/` 和 `history.db` 提交进 git（已在 `.gitignore`）。

---

## 已经做完的（相对 v0.4.1）

**v0.5**

- `DeepCheck.to_dict`（否则住宅深检会把 HTML/历史库写崩）
- `latest.html` 固定入口
- 趋势：IP「换」、风控/RTT/速度 Δ、变慢置顶（速度掉 ≥40% 或 RTT 翻倍）
- `load_trend` 默认 30 次；`--trend-runs`
- isolated 可从 yaml 的 `proxies:` 列节点，不连正在跑的控制器
- schema `PRAGMA user_version` + 迁移
- IPQS 直连（key 不进被测节点）
- 端口占住到内核启动前
- 发现路径兼容非 Rev
- `examples/audit-daily.bat` + `register-daily-task.ps1`

**v0.6**

- 控制台 `src/node_audit/report/dashboard.py`（侧栏 / KPI / SVG 折线 / IP 时间轴）
- `node-audit serve`（`src/node_audit/serve.py`）
- `latest.html` = 控制台；`audit-*.html` 仍是表格归档
- 订阅隔离：节点名重叠 `|交集|/min(|A|,|B|) ≥ 90%` 视为同一订阅，否则新开时间轴；换回旧机场能对上原来那条
- 演示页 `examples/sample-dashboard.html`

测试：`python tests/run_all.py`，当前 **61 passed**。

---

## 下一刀（给下一台电脑上的 AI / 自己）

1. 先读本文件和 `docs/PLAN-v0.7-ipv6.md`
2. **只做 IPv6 出口审计**，不要开 Go 重写
3. 动手前确认这三处：
   - `checks.check_identity` → 只有 ip-api v4
   - `checks.check_ptr` → `if "." not in ip: return None`
   - `isolated.build_config` → `ipv6: false`
4. 做完把版本升到 **0.7.0**，补测试，更新 README 路线图
5. 本机无 IPv6 也能测：流量走节点 HTTP 代理去拨 v6 目标

---

## 不要搞混

| 文件 | 是什么 |
|---|---|
| `examples/sample-dashboard.html` | 写死的 3 个假节点，给人看 UI |
| `node-audit-report/latest.html` | 跑过 `audit` 之后才有，才是当前订阅全量 |

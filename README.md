# node-audit

Clash / mihomo **节点质量审计**：双击一个 exe，把订阅里每个节点的出口身份、纯净度、延迟、速度、解锁情况测一遍，生成可点的控制台页面。

默认 **isolated 零干扰**——另起临时内核，**不会切换你正在用的代理**。

[下载 node-audit.exe](https://github.com/GGX355/node-audit/releases/latest/download/node-audit.exe)
（Windows · 约 10 MB · [全部版本](https://github.com/GGX355/node-audit/releases)）

软件里有完整说明书：双击后选 **4**，或打开报告后点右上角 **说明**（快捷键 `?`）。

---

## 30 秒上手

1. 本机装着 **Clash Verge / Verge Rev**，并成功打开过一次（磁盘上要有 `clash-verge.yaml`）。
2. 下载 `node-audit.exe`，放到任意普通文件夹。
3. **双击**。黑窗口不要关。
4. 菜单选 **1**（或直接 Enter）开始全量审计，大约十几～二十分钟。
5. 结束后自动打开 `node-audit-report\latest.html`。

| 菜单 | 作用 |
|---|---|
| **1** | 全量审计（推荐） |
| **2** | 打开上次报告 |
| **3** | 只列出将测的节点 |
| **4** | 打开使用说明 |
| **Q** | 退出 |

第一次还会在 exe 旁边生成 `node-audit.ini`（默认就能跑）和 `使用说明.html`。

演示界面（假数据，3 个节点）：打开仓库里的 [`examples/sample-dashboard.html`](examples/sample-dashboard.html)。那不是你的订阅。

---

## 报告在哪、怎么看

都在 exe 旁边的 `node-audit-report\`：

| 文件 | 用途 |
|---|---|
| **`latest.html`** | 日常入口。左侧选节点；KPI；RTT / 速度 / 风控折线（带日期刻度）；IP 时间轴（「换」= 出口变了） |
| `latest.log` | 最近一次全过程。出错先看这个 |
| `audit-时间戳.*` | 这一次的归档（html / md / json / log） |
| `history.db` | 历史趋势库，别随便删 |
| `使用说明.html` | 软件内说明书的副本 |

控制台右上角可 **导出 CSV**。`j` / `k` 切换节点。

**判定怎么读**

- **机房**：hosting=true，云 / IDC / CDN 出口。
- **疑似真家宽**：hosting=false，再看 ping0 的家庭宽带 / 原生 / 风控%。
- **换**：相对上次，v4 或 v6 任一变了。
- **变慢**：速度掉 ≥40% 或 RTT 翻倍，整行标红置顶。
- GPT / Netflix / TikTok 是「这个出口能不能用」，不是安全分。

---

## 改设置

用记事本打开 exe 旁边的 `node-audit.ini`，保存后再双击。常用：

```ini
[audit]
mode = isolated          # 不要改成 attach（会切换你正在用的代理）
include = 台湾|香港原生    # 只测名称匹配的；留空 = 全量
limit =                  # 试跑可写成 5
skip_speed = false       # true 会快很多
deep = auto              # auto / off / all
```

每天定时、不要菜单：

```text
node-audit.exe run --yes
```

仓库 `examples\register-daily-task.ps1` 可注册每天 04:00 的计划任务。

---

## 常见问题

**找不到配置 / 内核**  
先打开一次 Clash Verge。内核常见路径：`%LOCALAPPDATA%\Programs\Clash Verge\verge-mihomo.exe`。

**窗口一闪就关**  
正常结束会停在「按 Enter 关闭窗口」。闪退去看 `node-audit-report\latest.log`。

**想测快点**  
`include` 只测一部分，或 `skip_speed = true`，或 `limit = 5`。

**本机没有 IPv6**  
没关系。探测走节点 HTTP 代理。

**会不会搞风控账号？**  
isolated 下浏览器流量不动。不要用 attach 还挂着已登录的网页。

**换了机场趋势乱了**  
节点名重叠不到 90% 会新开时间轴；换回去还能对上旧的。旧节点在控制台点「历史」。

---

## 它测什么

| 阶段 | 内容 | 数据源 |
|---|---|---|
| 快筛 | 出口 v4 / 国家 / ISP / hosting | ip-api.com |
| 快筛 | 出口 v6 | api64.ipify.org + ipwho.is |
| 快筛 | PTR、RDAP 注册档案 | DoH / rdap.org |
| 快筛 | 延迟、测速、地区是否对得上 | gstatic / Cloudflare |
| 深检 | 家宽/IDC、原生、风控 | **IPPure JSON**（优先）+ ping0.cc/ip/{地址} + iplark JSON；Scamalytics 网页备选。机房默认跳过网页深检。不加 ipjiance（要验证码） |
| 可选 | 欺诈分 / 滥用举报 | IPQS、AbuseIPDB（要免费 key，没有也能跑） |
| 探针 | GPT / Netflix / TikTok | 匿名 GET，不带 Cookie |

默认 isolated：从 Verge 配置里原样搬运 `proxies:`，为本机每个节点开一个只绑 `127.0.0.1` 的端口。你的上网不受影响。

`attach` 是回退：会切 global 轮巡节点，**期间你的流量会跳**。除非内核找不到，否则不要用。

---

## 源码运行 / 自己打包

零第三方依赖，Python ≥ 3.9：

```bash
git clone https://github.com/GGX355/node-audit.git
cd node-audit
# Windows
set PYTHONPATH=src
python -m node_audit
python tests/run_all.py
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
```

打 `v*` 标签会自动往 Release 挂 `node-audit.exe`。

更多命令见软件内说明，或 `python -m node_audit help`。开发交接：[`docs/HANDOFF.md`](docs/HANDOFF.md)。

---

## 免责声明

仅用于检测**自有订阅节点**质量，不提供、不配置任何代理服务。Scamalytics / ping0 数据版权归原站，请控制请求频率。

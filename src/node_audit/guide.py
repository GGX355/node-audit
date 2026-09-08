"""使用说明（软件内 + 独立 HTML）。文案只维护这一处。"""
from __future__ import annotations

import html
from pathlib import Path

from . import __version__

# (标题, HTML 片段) —— 给控制台浮层和 使用说明.html 共用
_SECTIONS: list[tuple[str, str]] = [
    ("这是什么", """
<p>node-audit 会把你订阅里的<strong>每一个真实节点</strong>测一遍：出口 IP（含 IPv6）、是不是机房、PTR/ASN、延迟、速度、风控，以及 GPT / Netflix / TikTok 能不能用。</p>
<p>默认用 <strong>isolated</strong>：在本机另起一个临时内核，<strong>不会切换你正在上网的代理</strong>。浏览器、下载、游戏都不受影响。</p>
<p>本工具只检测<strong>你自己的订阅</strong>，不提供、不配置任何代理服务。</p>
"""),
    ("使用前准备", """
<ol>
<li>安装 <strong>Clash Verge</strong> 或 <strong>Clash Verge Rev</strong>。</li>
<li>至少<strong>成功打开过一次</strong>，让磁盘上生成运行时配置（常见路径：<code>%APPDATA%\\io.github.clash-verge-rev.clash-verge-rev\\clash-verge.yaml</code>）。</li>
<li>订阅要以内联 <code>proxies:</code> 写在这份配置里（Verge 默认就是这样）。如果走的是 <code>proxy-providers</code> 远程提供者，本工具的 isolated 模式暂不支持。</li>
<li>审计期间 Verge <strong>不必开着</strong>，但配置文件和 <code>verge-mihomo.exe</code> 要在。</li>
</ol>
"""),
    ("第一次用（双击 exe）", """
<ol>
<li>到 GitHub Releases 下载 <code>node-audit.exe</code>，放到任意文件夹（不要放在需要管理员权限的目录）。</li>
<li><strong>双击</strong>。黑窗口不要关。</li>
<li>第一次会在 exe 旁边生成 <code>node-audit.ini</code>（默认就能跑）和本说明 <code>使用说明.html</code>。</li>
<li>菜单选：
  <ul>
    <li><strong>1</strong> 开始全量审计（推荐）</li>
    <li><strong>2</strong> 打开上次报告</li>
    <li><strong>3</strong> 只列出将测的节点，不真正测</li>
    <li><strong>4</strong> 打开这份使用说明</li>
    <li><strong>Q</strong> 退出</li>
  </ul>
</li>
<li>直接按 Enter 等于选 1。</li>
</ol>
<p>全量大约 <strong>十几到二十分钟</strong>（节点多会更久）。测速、深检都要联网。中途可 Ctrl+C，已测完的会保留。</p>
"""),
    ("跑完看什么", """
<p>报告都在 exe 旁边的 <code>node-audit-report</code> 文件夹：</p>
<table>
<tr><th>文件</th><th>干什么</th></tr>
<tr><td><code>latest.html</code></td><td><strong>控制台</strong>：日常就看这个。侧栏点节点，上面有 KPI，中间有折线和 IP 时间轴。</td></tr>
<tr><td><code>latest.log</code></td><td>最近一次审计的完整过程（出错先看这个）。</td></tr>
<tr><td><code>audit-时间戳.log / .html / .md / .json</code></td><td>这一次的归档：日志、表格、Markdown、原始 JSON。</td></tr>
<tr><td><code>history.db</code></td><td>历史库。折线、「换 IP」、变慢置顶都靠它。不要删，除非你想清空趋势。</td></tr>
<tr><td><code>使用说明.html</code></td><td>本说明的副本。</td></tr>
</table>
<p>跑完一般会自动用浏览器打开 <code>latest.html</code>。也可以以后再双击这个文件，或软件菜单选 2。</p>
<p><code>examples/sample-dashboard.html</code>（仓库里）是 <strong>3 个假节点的演示</strong>，不是你的订阅。</p>
"""),
    ("控制台怎么看", """
<ul>
<li><strong>左侧</strong>：搜索框 + 筛选（家宽 / 机房 / 变慢 / 换 IP / 失败 / 历史）。键盘 <kbd>j</kbd> / <kbd>k</kbd> 上下切换节点。</li>
<li><strong>KPI</strong>：节点数、成功、家宽、机房、变慢、换 IP、失败。</li>
<li><strong>身份卡</strong>：出口 v4 / v6、归属、ISP、ASN、PTR、RDAP、类型（机房/住宅）、RTT、速度、风控、一致性，以及 GPT/NF/TT。</li>
<li><strong>折线</strong>：延迟、速度、风控。横轴是日期（月-日）。鼠标悬停圆点可看该次的日期和数值。</li>
<li><strong>出口 IP 时间轴</strong>：每次的 v4 / v6。变了会标黄「换」，下面有日期。</li>
<li><strong>导出 CSV</strong>：右上角，导出当前这次测到的节点。</li>
<li><strong>说明</strong>：右上角，打开与本文相同的使用说明。快捷键 <kbd>?</kbd>，<kbd>Esc</kbd> 关闭。</li>
</ul>
<p>「历史」筛选 = 换订阅之后，旧订阅残留的节点，不是这次测的。</p>
"""),
    ("判定怎么读", """
<ul>
<li><strong>机房</strong>：ip-api 的 hosting=true，生死线。CDN / 云厂商出口几乎都是这个。</li>
<li><strong>住宅候选 / 疑似真家宽</strong>：hosting=false，再用 ping0 看「家庭宽带 / 原生 / 风控%」。</li>
<li><strong>疑似IDC</strong>：ip-api 说住宅，但 ping0 写成机房。</li>
<li><strong>一致性 ✗</strong>：节点名写着某国，出口 IP 在另一国。</li>
<li><strong>落地存疑</strong>：RTT 对名字上的地区不合理（按「人在中国大陆」校准）。</li>
<li><strong>换</strong>：相对上次，v4 或 v6 任一变了。家宽经常换，机房很少换。</li>
<li><strong>变慢（整行标红置顶）</strong>：速度掉 ≥40%，或 RTT 翻倍。</li>
</ul>
<p>GPT / NF / TT 是实测能否打开，不是「这个 IP 安不安全」的分数。</p>
"""),
    ("改设置 node-audit.ini", """
<p>和 exe 放在同一文件夹，用记事本打开。改完保存，下次双击生效。行首 <code>#</code> 是注释。</p>
<table>
<tr><th>项</th><th>默认</th><th>说明</th></tr>
<tr><td><code>mode</code></td><td>isolated</td><td>千万别随便改成 attach。attach 会把你正在用的代理切来切去。</td></tr>
<tr><td><code>include</code></td><td>空=全量</td><td>只测名称匹配的节点，正则。例如 <code>台湾|香港原生</code>。</td></tr>
<tr><td><code>exclude</code></td><td>空</td><td>排除匹配的名称。</td></tr>
<tr><td><code>limit</code></td><td>空</td><td>最多测前 N 个，试跑用。</td></tr>
<tr><td><code>workers</code></td><td>3</td><td>isolated 同时测几个节点（1–8）。测速会并行；ip-api 仍然排队。attach 无效。</td></tr>
<tr><td><code>speed_bytes</code></td><td>10MB</td><td>测速下载量。名称含「勿跑大流量」的节点会自动降到 2MB。</td></tr>
<tr><td><code>skip_speed</code></td><td>false</td><td>true = 不测速，会快很多。</td></tr>
<tr><td><code>deep</code></td><td>auto</td><td>auto=只对住宅做网页深检；off=不做；all=每个都做（慢）。</td></tr>
<tr><td><code>services</code></td><td>all</td><td>all / none / openai,netflix,tiktok</td></tr>
<tr><td><code>ipqs_key</code> / <code>abuseipdb_key</code></td><td>空</td><td>可选官方风控 API。没有也能跑。</td></tr>
<tr><td><code>dir</code></td><td>空</td><td>报告目录。空 = 程序旁边的 node-audit-report。</td></tr>
<tr><td><code>open_report</code></td><td>true</td><td>跑完是否自动打开 latest.html。</td></tr>
</table>
"""),
    ("每天自动跑", """
<p>计划任务不要弹菜单，用：</p>
<pre>node-audit.exe run --yes</pre>
<p>仓库 <code>examples\\register-daily-task.ps1</code> 会注册每天 04:00 的任务 <code>node-audit-daily</code>（跑 <code>examples\\audit-daily.bat</code>）。</p>
<pre>schtasks /Run /TN node-audit-daily
schtasks /Delete /TN node-audit-daily /F</pre>
<p>改成每周日：把 ps1 里的 <code>/SC DAILY /ST 04:00</code> 换成 <code>/SC WEEKLY /D SUN /ST 04:00</code>。</p>
"""),
    ("命令行（可选）", """
<p>双击等于 <code>node-audit run</code>。还可以：</p>
<pre>node-audit.exe --version
node-audit.exe help              打开使用说明
node-audit.exe run --yes         跳过菜单，直接全量
node-audit.exe discover          只看控制器和节点数
node-audit.exe audit --dry-run   只列表
node-audit.exe audit --yes --include "台湾"
node-audit.exe serve --open      本机打开控制台（只听 127.0.0.1）</pre>
"""),
    ("常见问题", """
<dl>
<dt>提示找不到配置 / 内核</dt>
<dd>先打开一次 Clash Verge。内核一般在 <code>%LOCALAPPDATA%\\Programs\\Clash Verge\\verge-mihomo.exe</code>。也可在命令行 <code>--core</code> 指定路径。</dd>
<dt>窗口一闪就关</dt>
<dd>双击结束后会「按 Enter 关闭窗口」。若闪退，到 <code>node-audit-report\\latest.log</code> 看最后几行。</dd>
<dt>测了很久 / 想加快</dt>
<dd>ini 里 <code>include</code> 只测一部分，或 <code>skip_speed = true</code>，或 <code>limit = 5</code> 先试 5 个。</dd>
<dt>换了机场，趋势乱了</dt>
<dd>节点名重叠不到 90% 会自动开一条新时间轴。换回旧机场还能对上原来那条。旧节点在控制台点「历史」。</dd>
<dt>exe 放在「下载」文件夹行不行？</dt>
<dd>可以。路径不是问题。很多节点「失败」通常是节点本身连不上，或 ip-api 免费接口被该出口限流（每分钟约 45 次）。0.11 起会再用 ipify / IPPure 兜底。</dd>
<dt>为什么 ping0 没出结果？</dt>
<dd>两件事：① <code>deep = auto</code> 时<strong>机房节点默认不跑网页深检</strong>（hosting=true 已经够判机房）。② ping0.cc / scamalytics 网页经常反爬，扒首页会空。0.11 起改查 <code>ping0.cc/ip/地址</code>，并加上 <strong>IPPure JSON</strong>（无验证码，有风险分/是否住宅）和 iplark JSON。不会加 ipjiance.com——要写验证码，自动化跑不了。</dd>
<dt>本机没有 IPv6</dt>
<dd>没关系。探测走节点的 HTTP 代理，不要求你电脑有 IPv6。</dd>
<dt>会不会把我的账号搞风控？</dt>
<dd>isolated 下探针走临时端口，你的浏览器不动。不要用 attach 模式还挂着已登录的网页。</dd>
</dl>
"""),
    ("隐私与安全", """
<ul>
<li>所有检测请求显式走<strong>被测节点</strong>，不读系统环境代理。</li>
<li>服务探针不带 Cookie / Token / 登录态。</li>
<li>临时内核只监听 <code>127.0.0.1</code>，不向局域网开放。</li>
<li>IPQS 的 API key 走直连，不送进被测节点。</li>
<li>「剩余流量 / 套餐到期」这类信息卡、DIRECT、代理组会自动跳过。</li>
</ul>
"""),
]


def sections() -> list[tuple[str, str]]:
    return list(_SECTIONS)


def guide_article_html() -> str:
    parts = [f"<p class='guide-ver'>node-audit {html.escape(__version__)}</p>"]
    for i, (title, body) in enumerate(_SECTIONS, 1):
        parts.append(f"<h2 id='g{i}'>{html.escape(title)}</h2>")
        parts.append(body.strip())
    return "\n".join(parts)


def render_guide_html() -> str:
    css = """
:root{--bg:#0c0d10;--text:#e8eaed;--muted:#8b93a1;--stroke:rgba(255,255,255,.1);--accent:#7aa2ff}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.65}
.wrap{max-width:820px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:28px;margin:0 0 8px}
.sub{color:var(--muted);margin:0 0 28px}
h2{font-size:18px;margin:28px 0 10px;padding-top:8px;border-top:1px solid var(--stroke)}
p,li,dd,dt{font-size:15px}
.guide-ver{color:var(--muted);font-size:13px}
code,pre,kbd{font-family:ui-monospace,Consolas,monospace;font-size:13px}
code,kbd{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:4px}
pre{background:rgba(255,255,255,.06);padding:12px 14px;border-radius:10px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0 16px}
th,td{border:1px solid var(--stroke);padding:6px 8px;text-align:left;vertical-align:top}
th{background:rgba(255,255,255,.04);color:var(--muted)}
a{color:var(--accent)}
dl{margin:0} dt{font-weight:650;margin-top:12px} dd{margin:4px 0 0 0;color:var(--muted)}
ul,ol{padding-left:1.3em}
"""
    toc = "".join(
        f"<li><a href='#g{i}'>{html.escape(t)}</a></li>"
        for i, (t, _) in enumerate(_SECTIONS, 1)
    )
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>node-audit 使用说明</title><style>{css}</style></head><body>"
        "<div class='wrap'><h1>node-audit 使用说明</h1>"
        "<p class='sub'>Clash / mihomo 节点质量审计 · 双击即可 · 零干扰</p>"
        f"<ol>{toc}</ol>{guide_article_html()}"
        "<p class='sub'>仅用于检测自有订阅节点质量。</p>"
        "</div></body></html>"
    )


def write_guide(path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_guide_html(), encoding="utf-8")
    return dest

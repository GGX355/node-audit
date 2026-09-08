# 换电脑交接（2026-09-08）

仓库：https://github.com/GGX355/node-audit  
分支：`main`  
当前代码版本：**0.8.0**（一键 exe + v0.7 IPv6）

下载给用户用的程序：GitHub **Releases** 里的 `node-audit.exe`（不要从源码树里找，exe 不进 git）。

---

## 给使用者（不需要 AI）

1. 装着 Clash Verge / Verge Rev，并成功打开过一次
2. 下载 `node-audit.exe`，放到任意文件夹，双击
3. 选 `1` 全量审计；报告 `node-audit-report\latest.html`；日志 `latest.log`
4. 设置：旁边的 `node-audit.ini`（第一次自动生成）

---

## 新电脑怎么接手源码

```powershell
git clone https://github.com/GGX355/node-audit.git
cd node-audit
$env:PYTHONPATH='src'
python tests/run_all.py          # 应全部 passed
python -m node_audit --version   # node-audit 0.8.0
```

打包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
# 产物 dist\node-audit.exe
```

打 tag 会走 `.github/workflows/release.yml` 自动挂 exe 到 Release。

---

## 已经做完的

**v0.7** IPv6 出口审计（双栈、ip6.arpa、schema v3、isolated `ipv6: true`）。计划书 [`PLAN-v0.7-ipv6.md`](PLAN-v0.7-ipv6.md)。

**v0.8**

- 无参数 / 双击 = `run`：菜单 + `node-audit.ini` + 日志 + 打开报告
- `run --yes` 给计划任务
- PyInstaller 单文件控制台 exe
- Releases workflow

---

## 原 v1.0 怎么拆

| 原 v1.0 | 结论 |
|---|---|
| SVG 趋势图 | 控制台已经有折线，不当新项目 |
| IPv6 出口审计 | 已做完（v0.7） |
| Go 单二进制 | **不做**。exe 用 PyInstaller（v0.8） |

---

## 下一刀

1. **不要开 Go 重写**
2. 可选：sparkline 日期刻度
3. 把本机打出来的 exe 挂到 GitHub Release `v0.8.0`（若 Actions 没跑）

---

## 不要搞混

| 文件 | 是什么 |
|---|---|
| `examples/sample-dashboard.html` | 写死的 3 个假节点，给人看 UI |
| `node-audit-report/latest.html` | 跑过审计之后才有，才是当前订阅全量 |
| `node-audit.ini` | 双击后生成在 exe 旁边，不是仓库里的配置 |
| `dist/node-audit.exe` | 本地打包产物，不要 commit |

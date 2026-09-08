# 换电脑交接（2026-09-08）

仓库：https://github.com/GGX355/node-audit  
分支：`main`  
当前代码版本：**0.11.0**（IPPure/iplark 深检 + ping0 按 IP 查）

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
python -m node_audit --version   # node-audit 0.10.0
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

**v0.8** 一键 exe（菜单 / ini / 日志 / Releases）。

**v0.9** 控制台日期刻度、PTR/ASN、CSV。

**v0.10**

- GitHub README 改成给使用者看的首页（下载 / 30 秒上手 / 报告 / 设置 / FAQ）
- 软件内使用说明：双击菜单 4、`node-audit help`、控制台右上角「说明」/`?`
- 报告目录和 exe 旁边会写 `使用说明.html`

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
2. 路线图已清空。proxy-providers 的 isolated 支持仍是已知限制，不是这轮范围。

---

## 不要搞混

| 文件 | 是什么 |
|---|---|
| `examples/sample-dashboard.html` | 写死的 3 个假节点，给人看 UI |
| `node-audit-report/latest.html` | 跑过审计之后才有，才是当前订阅全量 |
| `node-audit.ini` | 双击后生成在 exe 旁边，不是仓库里的配置 |
| `dist/node-audit.exe` | 本地打包产物，不要 commit |

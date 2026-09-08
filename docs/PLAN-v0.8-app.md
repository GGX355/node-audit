# v0.8 一键程序（Windows exe）

状态：本轮落地。Go 仍然不做。

## 要解决什么

v0.7 还是「装 Python、设 PYTHONPATH、记一长串命令」。目标：从 GitHub Releases 下一份 `node-audit.exe`，双击就能用，不需要再找 AI 帮忙跑。

## 做法

- PyInstaller `-F` 打成单个控制台 exe（看得到进度；不要窗口程序藏日志）
- 双击 = `node-audit run`：简单菜单（审计 / 打开上次报告 / 只列表）
- 旁边自动生成 `node-audit.ini`（默认就能跑，改了下次生效）
- 日志：`node-audit-report/latest.log` + 带时间戳的 `audit-*.log`
- 跑完自动打开 `latest.html`
- 计划任务：`node-audit.exe run --yes`（无菜单，直接测）
- 运行时仍然零 pip 依赖；PyInstaller 只在打包机上用

## 不要做

- Go 重写
- 复杂 GUI / 安装向导
- 把 exe 提交进 git（走 GitHub Releases）

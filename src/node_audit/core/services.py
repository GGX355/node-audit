"""v0.3 服务风控探针：OpenAI / Netflix / TikTok。

设计硬约束（README 有完整说明）：
- 只发匿名只读 GET：不带任何 Cookie / Token / 登录态，与用户的浏览器身份
  不存在可关联的凭据；
- 每服务每节点最多 2 个请求，超时 8 秒，失败归为 unknown，绝不阻塞审计；
- 全部打点 URL 在 PROBE_URLS 公开，便于核验；分类特征集中在
  TIKTOK_CAPTCHA_MARKERS 等常量表，反爬变化时只需改表。

分类逻辑拆成纯函数（_openai_verdict 等），不触网、可单元测试；
probe_* 函数只负责取数据并调用分类。
"""
from __future__ import annotations

import re
import time

from .checks import http_get

# 公开的请求清单（无 Cookie 保证的可核验依据）
PROBE_URLS = {
    "openai": [
        "https://api.openai.com/cdn-cgi/trace",
        "https://api.openai.com/v1/models",  # 无凭据：401=地区可用 / 403=封区
    ],
    "netflix": [
        "https://www.netflix.com/",
        "https://www.netflix.com/title/81280792",  # 非自制内容解锁测试的惯例 ID
    ],
    "tiktok": [
        "https://www.tiktok.com/",
    ],
}

# 非自制内容 title（若该 ID 失效，结果整体转 unknown/仅自制，不会误报全解锁）
NETFLIX_NON_ORIGINAL_TITLE = 81280792

# TikTok 风控页特征：命中即判 captcha；反爬变化时更新此表即可
TIKTOK_CAPTCHA_MARKERS = ("captcha", "/verify", "punish", "security check")

TIMEOUT = 15  # IPv6 / 高延迟节点 8s 经常来不及握完 TLS

PROBES = {}  # 文件末尾注册
SERVICE_SHORT = {"openai": "GPT", "netflix": "NF", "tiktok": "TT"}


def _blank(service: str) -> dict:
    return {"service": service, "status": "unknown", "region": None, "note": ""}


def _err_note(err: str | None) -> str:
    if not err:
        return "请求失败"
    low = err.lower()
    if "timed out" in low or "timeout" in low:
        return "超时（节点慢或目标不可达）"
    if "reset" in low or "10054" in err or "104" in err:
        return "连接被重置"
    if "refused" in low:
        return "连接被拒绝"
    if "503" in err or "502" in err or "504" in err:
        return err
    return err[:80]


def _get_retry(url: str, proxy: str, attempts: int = 2):
    """带一次重试的 GET；全部失败返回 (None, 错误摘要)。"""
    last = ""
    for i in range(attempts):
        try:
            status, data = http_get(url, proxy, TIMEOUT)
            if status in (502, 503, 504) and i + 1 < attempts:
                last = f"HTTP {status}"
                time.sleep(0.6)
                continue
            return (status, data), None
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:80]}"
            if i + 1 < attempts:
                time.sleep(0.6)
    return None, last


# ---------- OpenAI ----------

def _openai_verdict(models_status: int | None, models_body: str) -> tuple[str, str]:
    """/v1/models 无凭据请求：401=地区允许，403=地区封禁。"""
    if models_status == 401:
        return "ok", "地区可用（匿名探测，未携带凭据）"
    if models_status == 403:
        if "unsupported" in models_body.lower():
            return "blocked", "地区不支持"
        return "blocked", "拒绝访问"
    if models_status is None:
        return "unknown", "请求失败"
    return "unknown", f"意外状态码 {models_status}"


def probe_openai(proxy: str) -> dict:
    out = _blank("openai")
    region = None
    trace, _ = _get_retry(PROBE_URLS["openai"][0], proxy)
    if trace is not None and trace[0] == 200:
        m = re.search(r"^loc=([A-Za-z]{2})\s*$",
                      trace[1].decode(errors="replace"), re.M)
        if m:
            region = m.group(1).upper()
    models, models_err = _get_retry(PROBE_URLS["openai"][1], proxy)
    models_status, body = None, ""
    if models is not None:
        models_status, data = models
        body = data.decode(errors="replace")[:500]
    status, note = _openai_verdict(models_status, body)
    if models_status is None:
        note = _err_note(models_err)
    out.update(status=status, region=region, note=note)
    return out


# ---------- Netflix ----------

def _netflix_verdict(home_status: int | None, title_status: int | None) -> tuple[str, str]:
    """非自制 title 200=全解锁；打不开但首页正常=仅自制或受限。"""
    if title_status == 200:
        return "full", "非自制内容可访问"
    if title_status in (403, 404):
        if home_status == 200:
            return "original", "仅自制内容（或该 IP 受限）"
        return "none", "无法访问"
    if title_status is None:
        return "unknown", "请求失败"
    return "unknown", f"意外状态码 {title_status}"


def probe_netflix(proxy: str) -> dict:
    out = _blank("netflix")
    region, home_status = None, None
    home, home_err = _get_retry(PROBE_URLS["netflix"][0], proxy)
    if home is not None:
        home_status, data = home
        if home_status == 200:
            text = data.decode(errors="replace")[:80000]
            for pat in (r'"currentRegion"\s*:\s*"([A-Z]{2})"',
                        r'"geo"\s*:\s*"([A-Z]{2})"',
                        r'"countryOfSignup"\s*:\s*"([A-Z]{2})"'):
                m = re.search(pat, text)
                if m:
                    region = m.group(1)
                    break
    title, title_err = _get_retry(PROBE_URLS["netflix"][1], proxy)
    title_status = title[0] if title is not None else None

    if home is None and title is None:
        # 两个请求都在连接层失败（重置/握手超时）：Netflix 边缘在拦截该出口 IP
        out.update(status="none",
                   note=f"连接失败，疑似被边缘拦截（{title_err or home_err}）")
        return out
    status, note = _netflix_verdict(home_status, title_status)
    if title_err and not title_status:
        note = f"{note}（title 请求异常: {title_err}）"
    out.update(status=status, region=region, note=note)
    return out


# ---------- TikTok ----------

def _tiktok_verdict(status: int | None, page_text: str) -> tuple[str, str]:
    if status == 200:
        low = page_text.lower()
        if any(marker in low for marker in TIKTOK_CAPTCHA_MARKERS):
            return "captcha", "触发人机验证"
        return "ok", "正常返回"
    if status in (403, 429):
        return "blocked", f"被拒绝（HTTP {status}）"
    if status is None:
        return "unknown", "请求失败"
    return "unknown", f"意外状态码 {status}"


def probe_tiktok(proxy: str) -> dict:
    out = _blank("tiktok")
    region = None
    got, err = _get_retry(PROBE_URLS["tiktok"][0], proxy)
    if got is None:
        out.update(status="unknown", note=_err_note(err))
        return out
    status, data = got
    text = data.decode(errors="replace")[:30000]
    m = re.search(r'"region"\s*:\s*"([A-Z]{2})"', text)
    if m:
        region = m.group(1)
    st, note = _tiktok_verdict(status, text)
    out.update(status=st, region=region, note=note)
    return out


PROBES.update({
    "openai": probe_openai,
    "netflix": probe_netflix,
    "tiktok": probe_tiktok,
})

# 状态码 -> 控制台/报告用符号与中文
STATUS_MARK = {
    "ok": "✓", "full": "✓", "original": "~",
    "captcha": "验", "blocked": "✗", "none": "✗", "unknown": "?",
}
STATUS_CN = {
    "ok": "可用", "full": "全解锁", "original": "仅自制",
    "captcha": "人机验证", "blocked": "封禁", "none": "不可用", "unknown": "未知",
}

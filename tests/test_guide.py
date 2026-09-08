import tempfile
from pathlib import Path

from node_audit.guide import guide_article_html, render_guide_html, sections, write_guide
from node_audit.report.dashboard import demo_payload, render_dashboard


def test_guide_covers_first_run_and_ini():
    titles = [t for t, _ in sections()]
    assert "第一次用（双击 exe）" in titles
    assert "改设置 node-audit.ini" in titles
    assert "常见问题" in titles
    body = guide_article_html()
    assert "isolated" in body
    assert "latest.html" in body
    assert "node-audit.ini" in body
    assert "verge-mihomo" in body


def test_write_guide_html_file():
    with tempfile.TemporaryDirectory() as td:
        path = write_guide(Path(td) / "使用说明.html")
        text = path.read_text(encoding="utf-8")
        assert "<!doctype html>" in text
        assert "node-audit 使用说明" in text
        assert "开始全量审计" in text
        assert "<script" not in text.lower()


def test_dashboard_embeds_help_overlay():
    html = render_dashboard(demo_payload())
    assert "id='help'" in html
    assert "id='help-btn'" in html
    assert "使用说明" in html
    assert "openHelp" in html
    assert "第一次用（双击 exe）" in html

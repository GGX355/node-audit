import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

from node_audit.core.history import save_run
from node_audit.core.models import NodeReport
from node_audit.serve import make_server


def _open(opener, url: str, timeout: float = 5):
    last = None
    for _ in range(20):
        try:
            return opener.open(url, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (ConnectionResetError, ConnectionRefusedError, TimeoutError, OSError) as e:
            last = e
            time.sleep(0.05)
    raise last


def test_serve_dashboard_and_api():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        r = NodeReport(name="节点A", node_type="ss")
        r.exit_ip = "1.1.1.1"
        r.hosting = False
        r.rtt_min = 40
        r.speed_mbps = 10.0
        r.verdict = "住宅候选"
        save_run([r], {"run_id": "run1", "mode": "isolated",
                       "controller": "t", "generated_at": "2026-01-01T00:00:00"}, db)
        httpd = make_server(db, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            # 显式禁用环境代理：本机 Clash mixed-port 常在 HTTP_PROXY 里，
            # urlopen 会把请求送进 7897 并被 RST。
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            html = _open(opener, f"http://127.0.0.1:{port}/").read().decode()
            assert "id='na-app'" in html
            payload = json.loads(
                _open(opener, f"http://127.0.0.1:{port}/api/data").read().decode()
            )
            assert payload["kpis"]["nodes"] == 1
            assert payload["nodes"][0]["name"] == "节点A"
            try:
                _open(opener, f"http://127.0.0.1:{port}/nope")
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            httpd.shutdown()
            httpd.server_close()

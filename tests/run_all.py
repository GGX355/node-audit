"""极简测试执行器：python tests/run_all.py（无需 pytest）。

测试文件同时兼容 pytest：pip install pytest 后直接 `pytest tests` 亦可。
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

failed = 0
total = 0
for m in sorted(Path(__file__).parent.glob("test_*.py")):
    mod = __import__(m.stem)
    for fname in sorted(dir(mod)):
        if not fname.startswith("test_"):
            continue
        fn = getattr(mod, fname)
        if not callable(fn):
            continue
        total += 1
        try:
            fn()
            print(f"PASS  {m.stem}::{fname}")
        except Exception:
            failed += 1
            print(f"FAIL  {m.stem}::{fname}")
            traceback.print_exc()

print(f"\n{total - failed}/{total} passed")
sys.exit(1 if failed else 0)

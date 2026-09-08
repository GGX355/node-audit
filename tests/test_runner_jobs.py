import time

from node_audit.core.runner import run_jobs_ordered


def test_run_jobs_ordered_serial_preserves_order():
    seq = []

    def mk(i):
        def fn():
            seq.append(i)
            return i * 10
        return str(i), fn

    out = run_jobs_ordered([mk(i) for i in range(4)], workers=1)
    assert out == [0, 10, 20, 30]
    assert seq == [0, 1, 2, 3]


def test_run_jobs_ordered_parallel_result_order_not_finish_order():
    def mk(i, delay):
        def fn():
            time.sleep(delay)
            return i
        return str(i), fn

    # 后提交的先跑完，结果仍应按 0,1,2
    jobs = [mk(0, 0.08), mk(1, 0.04), mk(2, 0.01)]
    out = run_jobs_ordered(jobs, workers=3)
    assert out == [0, 1, 2]

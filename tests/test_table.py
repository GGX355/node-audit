from node_audit.report.table import dwidth, pad, render


def test_display_width_cjk():
    assert dwidth("ab") == 2
    assert dwidth("台湾") == 4
    assert dwidth("台湾2") == 5


def test_pad_truncates_and_aligns():
    cell = pad("台湾1|5x倍率|勿跑大流量", 10)
    assert dwidth(cell) == 10  # 截断后加省略号仍对齐


def test_render_table_shape():
    table = render([["a", "b"]], ["h1", "h2"])
    lines = table.split("\n")
    assert len(lines) == 5  # 上边框 + 表头 + 分隔 + 数据 + 下边框
    assert lines[0].startswith("+") and lines[-1].startswith("+")
    assert lines[1].startswith("|")
    # 中文表头不破坏列对齐：数据行（含表头行）应各有 3 个竖线
    table2 = render([["节点名", "1"]], ["节点", "值"])
    data_lines = [line for line in table2.split("\n") if line.startswith("|")]
    assert len(data_lines) == 2
    for line in data_lines:
        assert line.count("|") == 3

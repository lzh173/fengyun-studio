"""图表控件的回归测试。

对应一个真实的"功能存在但不可用"缺陷：
StatsGrid 的 CELLS 用字段名 vmin/vmax 取数，而 StatSummary.as_dict()
返回的是 min/max，导致统计面板的「最小值/最大值」恒显示「—」。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fysat.gui import chartwidgets as cw


def test_as_dict_provides_every_cell_key():
    """CELLS 里每个 key 都必须能从 as_dict() 取到，否则那一格永远是「—」。"""
    st = cw.summarize(np.array([[1.0, 2.0], [3.0, np.nan]]))
    d = st.as_dict()
    missing = [k for _, k, _ in cw.StatsGrid.CELLS if k not in d]
    assert not missing, f"这些统计项取不到值，会显示成「—」: {missing}"


def test_summarize_basic_values():
    st = cw.summarize(np.array([[1.0, 2.0], [3.0, np.nan]]))
    assert st.vmin == pytest.approx(1.0)
    assert st.vmax == pytest.approx(3.0)
    assert st.mean == pytest.approx(2.0)
    assert st.n_valid == 3
    assert st.valid_pct == pytest.approx(75.0)


def test_summarize_all_nan_is_safe():
    st = cw.summarize(np.full((4, 4), np.nan))
    assert st.n_valid == 0
    d = st.as_dict()
    # 全 NaN 不能抛异常，值应为非有限数
    assert not np.isfinite(d["vmin"])


def test_summarize_handles_rgb_and_large():
    rgb = np.random.default_rng(0).random((50, 60, 3)).astype(np.float32)
    st = cw.summarize(rgb)
    assert np.isfinite(st.vmin) and np.isfinite(st.vmax)
    assert st.vmin <= st.vmax

"""科学制图的体积与栅格化回归。

对应缺陷：热图不做栅格化时，矢量导出会失控
（实测 PDF 3.36 MB / SVG 26.99 MB，一张 400x340 的图！），
分享与投稿都没法用。加 rasterized=True 后降到 0.16 / 0.29 MB。
"""
from __future__ import annotations

import numpy as np
import pytest

from fysat.sciencefig import FigureSpec, render_science_figure


def _grid(h=340, w=400):
    lon, lat = np.meshgrid(np.linspace(100, 130, w), np.linspace(5, 35, h))
    data = (280 + 25 * np.sin(np.linspace(0, 6, w))[None, :]
            + 10 * np.cos(np.linspace(0, 5, h))[:, None])
    return data, lat, lon


def _render(tmp_path, ext):
    data, lat, lon = _grid()
    spec = FigureSpec(out_path=tmp_path / f"t{ext}", dpi=300, figsize=(13.5, 6.4),
                      title="体积测试", draw_coast=True)
    thermal = {"data": data, "lat": lat, "lon": lon,
               "label": "BT", "unit": "K", "cmap": "turbo"}
    return render_science_figure(thermal, None, spec)


@pytest.mark.parametrize("ext,limit_mb", [(".pdf", 1.0), (".svg", 2.0)])
def test_vector_export_is_not_bloated(tmp_path, ext, limit_mb):
    out = _render(tmp_path, ext)
    mb = out.stat().st_size / 1e6
    assert mb < limit_mb, (
        f"{ext} 导出 {mb:.2f} MB，超过 {limit_mb} MB —— "
        f"热图没有栅格化（pcolormesh/imshow 缺 rasterized=True）"
    )


def test_png_export_still_works(tmp_path):
    out = _render(tmp_path, ".png")
    assert out.exists() and out.stat().st_size > 50_000

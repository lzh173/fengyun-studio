"""科学制图：把框选区域导出成出版级图文（对标用户提供的参考图）。

设计目标
--------
用户在画布上框一块区域，点一下就得到可直接放进报告/论文的图：
- 双面板（可见光真彩色 + 红外亮温），或单面板
- 经纬网 + 刻度标注（°E / °N）
- 海岸线叠加
- 色标（竖直，带单位与刻度）
- 标题 / 文件信息 / 页脚署名 / 统计量

为什么用 matplotlib 而不是 QPainter
-----------------------------------
1. 矢量输出（PDF/SVG）只有 matplotlib 能做
2. 刻度、色标、字体排版是出版级要求，matplotlib 已成熟
3. 与 GUI 解耦，命令行也能出图（批量场景必需）

坐标系
------
卫星数据多为"条带/扫描"几何，经纬度随行列变化。这里统一用 pcolormesh
绘制非规则网格，因此不需要投影库；给出的 extent 只用于粗定位与刻度范围。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class FigureSpec:
    """一次科学制图的参数。"""

    out_path: Path | str = "figure.png"
    # 版式
    layout: str = "double"          # single | double
    dpi: int = 300
    figsize: tuple[float, float] = (12.0, 6.2)
    # 内容
    title: str = ""
    subtitle: str = ""
    footer: str = ""
    # 经纬网
    draw_grid: bool = True
    grid_step: float | None = None   # None = 自动
    draw_coast: bool = True
    coastline_path: Path | str | None = None
    # 色标
    colorbar: bool = True
    cmap_thermal: str = "turbo"
    thermal_range: tuple[float, float] | None = None
    # 区域（度）；None = 全幅
    extent: tuple[float, float, float, float] | None = None
    # 其它
    dpi_heatmap: bool = True
    transparent: bool = False
    font_family: str = "Microsoft YaHei"

    def resolved_path(self) -> Path:
        return Path(self.out_path)


# ---------------- 色标与刻度 ----------------

def _auto_step(span: float) -> float:
    """按跨度选一个好看的经纬网间隔。"""
    for step in (0.25, 0.5, 1, 2, 5, 10, 15, 20, 30, 45):
        if span / step <= 10:
            return step
    return 45.0


def _apply_cjk_font(font_family: str) -> None:
    """matplotlib 中文字体，避免标题/刻度变方框。"""
    import matplotlib

    candidates = [font_family, "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["font.sans-serif"] = [c for c in candidates if c]
    matplotlib.rcParams["axes.unicode_minus"] = False


def _load_coastlines(path: Path | str | None) -> list[np.ndarray]:
    """读 Natural Earth GeoJSON 海岸线（项目内置 110m）。"""
    import json

    if path is None:
        here = Path(__file__).resolve()
        # 资源在工程根 assets/ 下：src/fysat/sciencefig.py → 上溯 3 层
        for base in (here.parents[2], here.parents[1], here.parent):
            cand = base / "assets" / "ne_110m_coastline.geojson"
            if cand.exists():
                path = cand
                break
        else:
            path = here.parents[2] / "assets" / "ne_110m_coastline.geojson"
    p = Path(path)
    if not p.exists():
        return []
    try:
        gj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                       # noqa: BLE001
        return []

    segs = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {}) or {}
        coords = geom.get("coordinates", [])
        gtype = geom.get("type")
        if gtype == "LineString":
            segs.append(np.asarray(coords, dtype=float))
        elif gtype == "MultiLineString":
            segs.extend(np.asarray(c, dtype=float) for c in coords)
    return [s for s in segs if s.ndim == 2 and s.shape[0] >= 2]


def _subset(lat: np.ndarray | None, lon: np.ndarray | None,
            data: np.ndarray, extent: tuple[float, float, float, float] | None):
    """按经纬度框选子区域。没有经纬度时按像素比例裁。"""
    if extent is None or lat is None or lon is None:
        return lat, lon, data

    lon0, lon1, lat0, lat1 = extent
    with np.errstate(invalid="ignore"):
        mask = (lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1)
    if not mask.any():
        return lat, lon, data

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    return lat[r0:r1, c0:c1], lon[r0:r1, c0:c1], data[r0:r1, c0:c1]


def _frame_axes(ax, lat, lon, coastlines, spec: FigureSpec,
                shape: tuple[int, int] | None = None) -> None:
    """统一的经纬网/海岸线/刻度装饰。

    不用 axvline/axhline（在非规则网格下会画出满屏刻度的乱码），
    而是先确定真实的经纬度范围，只设刻度与范围。
    """
    if lat is not None and lon is not None:
        with np.errstate(invalid="ignore"):
            lat0, lat1 = float(np.nanmin(lat)), float(np.nanmax(lat))
            lon0, lon1 = float(np.nanmin(lon)), float(np.nanmax(lon))
        if not (np.isfinite(lat0) and np.isfinite(lon0)) or lon1 <= lon0 or lat1 <= lat0:
            lat = lon = None

    if lat is None or lon is None:
        # 没有经纬度：不画地理装饰，只去掉刻度数字
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#cbd5e1")
        return

    span_lon, span_lat = lon1 - lon0, lat1 - lat0
    step = spec.grid_step or min(_auto_step(span_lon), _auto_step(span_lat))

    xt = np.arange(np.floor(lon0 / step) * step, lon1 + step * 0.5, step)
    yt = np.arange(np.floor(lat0 / step) * step, lat1 + step * 0.5, step)
    xt = xt[(xt >= lon0 - 1e-6) & (xt <= lon1 + 1e-6)]
    yt = yt[(yt >= lat0 - 1e-6) & (yt <= lat1 + 1e-6)]

    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_xticks(xt)
    ax.set_yticks(yt)
    ax.set_xticklabels([f"{v:g}°E" for v in xt], fontsize=8)
    ax.set_yticklabels([f"{v:g}°N" if v >= 0 else f"{abs(v):g}°S" for v in yt], fontsize=8)

    if spec.draw_grid:
        ax.grid(color="#94a3b8", lw=0.35, alpha=0.55, ls=":", zorder=3)

    if spec.draw_coast and coastlines:
        for seg in coastlines:
            lons, lats = seg[:, 0], seg[:, 1]
            # 只画落在范围内的线段，避免把整条全球海岸线塞进来拖慢渲染
            if lons.max() < lon0 or lons.min() > lon1:
                continue
            if lats.max() < lat0 or lats.min() > lat1:
                continue
            ax.plot(lons, lats, color="#1e293b", lw=0.55, alpha=0.8, zorder=4)

    for s in ax.spines.values():
        s.set_color("#cbd5e1")
    ax.tick_params(labelsize=8, colors="#334155")


def _pcolormesh_safe(ax, lat, lon, data, **kwargs):
    """安全地画非规则网格。

    pcolormesh 遇到非单调坐标会画崩（甚至只画出一条对角线），
    因此先把坐标按行列排序并同步重排数据；仍失败时退回 imshow。
    """
    import numpy as np

    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    data = np.asarray(data, dtype=float)

    if lat.shape != data.shape or lon.shape != data.shape:
        # 形状对不上，直接按 extent 画
        kwargs.setdefault("rasterized", True)
        return ax.imshow(data, origin="upper", aspect="auto", **{
            k: v for k, v in kwargs.items() if k not in ("shading",)})

    # 按中心行/列排序，保证单调
    row_key = np.nanmedian(lat, axis=1)
    col_key = np.nanmedian(lon, axis=0)
    ri = np.argsort(np.nan_to_num(row_key, nan=0.0))
    ci = np.argsort(np.nan_to_num(col_key, nan=0.0))

    lat_s = lat[np.ix_(ri, ci)]
    lon_s = lon[np.ix_(ri, ci)]
    data_s = data[np.ix_(ri, ci)]

    # 热图必须栅格化：40 万个四边形若全转成矢量，SVG 会到几十 MB、
    # PDF 也上兆，根本没法分享。rasterized=True 让矢量文件里嵌一张位图，
    # 而标题/经纬网/海岸线/色标仍然是矢量。
    kwargs.setdefault("rasterized", True)
    try:
        return ax.pcolormesh(lon_s, lat_s, data_s, shading="auto", **kwargs)
    except Exception:                        # noqa: BLE001
        kwargs.setdefault("rasterized", True)
        return ax.imshow(data_s, origin="upper", aspect="auto",
                         extent=[float(np.nanmin(lon_s)), float(np.nanmax(lon_s)),
                                 float(np.nanmin(lat_s)), float(np.nanmax(lat_s))],
                         **{k: v for k, v in kwargs.items() if k != "shading"})


# ---------------- 主入口 ----------------

def render_science_figure(
    thermal: dict[str, Any],
    visible: dict[str, Any] | None = None,
    spec: FigureSpec | None = None,
) -> Path:
    """生成科学制图。

    参数
    ----
    thermal : dict
        {"data": 二维数组, "lat": 数组|None, "lon": 数组|None,
         "label": "红外亮温 CH24 10.8μm", "unit": "K" 或 "°C", "cmap": "turbo"}
    visible : dict | None
        {"rgb": uint8 RGB 数组 或 "data": 二维数组, "lat":..., "lon":..., "label": "可见光真彩色"}
    spec : FigureSpec
        版式与装饰参数

    返回
    ----
    实际写出的文件路径
    """
    import matplotlib

    # 必须 force=True：GUI 启动时 app.py 已把后端设成 QtAgg，
    # force=False 不会切换，图就在 Qt 后端里创建 —— 在无头/后台线程下
    # 会引发堆损坏（退出码 0xC0000374）或直接段错误。
    # 本模块只往文件出图，从不需要交互后端，一律用 Agg。
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    spec = spec or FigureSpec()
    _apply_cjk_font(spec.font_family)
    coastlines = _load_coastlines(spec.coastline_path) if spec.draw_coast else []

    two_panel = spec.layout == "double" and visible is not None
    ncols = 2 if two_panel else 1
    fig, axes = plt.subplots(1, ncols, figsize=spec.figsize, dpi=spec.dpi)
    if ncols == 1:
        axes = [axes]
    fig.patch.set_facecolor("white")

    # ---- 左：可见光 ----
    if two_panel:
        ax = axes[0]
        v = visible
        vlat, vlon = v.get("lat"), v.get("lon")
        if v.get("rgb") is not None:
            rgb = np.asarray(v["rgb"])
            ext = None
            if vlat is not None and vlon is not None:
                ext = [float(np.nanmin(vlon)), float(np.nanmax(vlon)),
                       float(np.nanmin(vlat)), float(np.nanmax(vlat))]
            ax.imshow(rgb, origin="upper", extent=ext, aspect="auto", zorder=1, rasterized=True)
        else:
            d = np.asarray(v["data"], dtype=float)
            _, _, d = _subset(vlat, vlon, d, spec.extent)
            vlat, vlon, _ = _subset(vlat, vlon, np.asarray(v["data"], dtype=float), spec.extent)
            if vlat is not None and vlat.shape == d.shape:
                _pcolormesh_safe(ax, vlat, vlon, d, cmap="gray", zorder=1)
            else:
                ax.imshow(d, cmap="gray", origin="upper", aspect="auto", zorder=1, rasterized=True)
        _frame_axes(ax, vlat, vlon, coastlines, spec)
        ax.set_title(v.get("label", "可见光真彩色"), fontsize=11, color="#111827")

    # ---- 右（或单图）：红外 ----
    ax2 = axes[1] if two_panel else axes[0]
    t = thermal
    tlat, tlon = t.get("lat"), t.get("lon")
    tdata = np.asarray(t["data"], dtype=float)

    tlat, tlon, tdata = _subset(tlat, tlon, tdata, spec.extent)

    vmin, vmax = spec.thermal_range or (float(np.nanpercentile(tdata, 1)),
                                        float(np.nanpercentile(tdata, 99)))
    cmap = t.get("cmap") or spec.cmap_thermal
    if tlat is not None and tlat.shape == tdata.shape:
        m = _pcolormesh_safe(ax2, tlat, tlon, tdata, cmap=cmap,
                             vmin=vmin, vmax=vmax, zorder=1)
    else:
        m = ax2.imshow(tdata, cmap=cmap, vmin=vmin, vmax=vmax,
                       origin="upper", aspect="auto", zorder=1, rasterized=True)
    _frame_axes(ax2, tlat, tlon, coastlines, spec)
    ax2.set_title(t.get("label", "红外亮温"), fontsize=11, color="#111827")

    # ---- 色标 ----
    if spec.colorbar:
        cb = fig.colorbar(m, ax=ax2, fraction=0.035, pad=0.02)
        cb.set_label(t.get("unit_label", t.get("unit", "")), fontsize=9)
        cb.ax.tick_params(labelsize=8)

    # ---- 标题 / 页脚 ----
    if spec.title:
        fig.suptitle(spec.title, fontsize=12.5, y=0.985, color="#111827")
    if spec.subtitle:
        fig.text(0.012, 0.955, spec.subtitle, fontsize=8, color="#334155")
    if spec.footer:
        fig.text(0.012, 0.012, spec.footer, fontsize=8.5, color="#e2e8f0",
                 bbox=dict(facecolor="#0f172a", edgecolor="none", pad=4))

    fig.subplots_adjust(left=0.05, right=0.955, top=0.90, bottom=0.07,
                        wspace=0.10 if two_panel else 0.0)

    out = spec.resolved_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="white" if not spec.transparent else "none")
    plt.close(fig)
    return out


# ---------------- 便捷封装：直接从 SatDataset 出图 ----------------

def figure_from_dataset(
    ds,
    thermal_var: str,
    thermal_band: int = 0,
    thermal_unit: str = "K",
    visible_vars: tuple[str, str, str] | None = None,
    visible_bands: tuple[int, int, int] = (0, 0, 0),
    region: tuple[int, int, int, int] | None = None,
    spec: FigureSpec | None = None,
    provenance: dict[str, str] | None = None,
) -> Path:
    """从数据集直接生成科学制图。

    region: 像素框 (r0, r1, c0, c1)；None 表示全幅
    """
    from .render import composite, display_band
    from .render import Stretch

    spec = spec or FigureSpec()

    var_t = ds.load(thermal_var)
    tdata = display_band(var_t, thermal_band, physical=True)

    lat = lon = None
    geo = getattr(ds, "geolocation", None)
    if geo is not None and geo.is_nav:
        lat = np.asarray(geo.lat, dtype=float)
        lon = np.asarray(geo.lon, dtype=float)
        # 粗网格 → 全分辨率时按比例放大（仅仅为了显示刻度，不追求逐像元精确）
        if lat.shape != tdata.shape:
            lat = _resize_grid(lat, tdata.shape)
            lon = _resize_grid(lon, tdata.shape)

    if region is not None:
        r0, r1, c0, c1 = region
        tdata = tdata[r0:r1, c0:c1]
        if lat is not None:
            lat = lat[r0:r1, c0:c1]
            lon = lon[r0:r1, c0:c1]

    # 抽稀到可渲染规模（原图 400 万像素级，出图不需要那么多）
    tdata, lat, lon = downsample_for_display(tdata, lat, lon)

    thermal = {
        "data": tdata, "lat": lat, "lon": lon,
        "label": f"{thermal_var.split('/')[-1]}" + (f" 通道{thermal_band+1}" if thermal_band else ""),
        "unit": thermal_unit,
        "unit_label": f"BT ({thermal_unit})" if thermal_unit else "",
        "cmap": spec.cmap_thermal,
    }

    visible = None
    if visible_vars:
        chans = [display_band(ds.load(n), b, physical=True) for n, b in
                 zip(visible_vars, visible_bands)]
        if region is not None:
            r0, r1, c0, c1 = region
            chans = [c[r0:r1, c0:c1] for c in chans]
        rgb = composite(*chans, st=Stretch(method="percentile", pct=(0.5, 99.5), gamma=1.1))
        visible = {"rgb": rgb, "lat": lat, "lon": lon, "label": "可见光真彩色"}

    if spec.footer == "" and provenance:
        from .provenance import as_text

        spec.footer = "  |  ".join(
            f"{k}={v}" for k, v in provenance.items()
            if k in ("software", "software_version", "modified", "commit", "generated_at"))

    return render_science_figure(thermal, visible, spec)


def _resize_grid(grid: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """把粗经纬网格最近邻放大到目标形状（仅为出图刻度服务）。"""
    h, w = shape
    gh, gw = grid.shape
    if (gh, gw) == (h, w):
        return grid
    ri = np.clip((np.arange(h) * gh / h).astype(int), 0, gh - 1)
    ci = np.clip((np.arange(w) * gw / w).astype(int), 0, gw - 1)
    return grid[np.ix_(ri, ci)]


def downsample_for_display(data: np.ndarray, lat, lon, max_cells: int = 300_000):
    """把大数组抽稀到可渲染规模，保证出图速度。

    2000x2048 = 409 万点直接 pcolormesh 会很慢（几十秒量级），
    而出版级图不需要那么多点，按 max_cells 自动抽稀。
    """
    h, w = data.shape[:2]
    total = h * w
    if total <= max_cells:
        return data, lat, lon

    step = int(np.ceil(np.sqrt(total / max_cells)))
    d = data[::step, ::step]
    la = lat[::step, ::step] if lat is not None and lat.shape == data.shape else lat
    lo = lon[::step, ::step] if lon is not None and lon.shape == data.shape else lon
    return d, la, lo

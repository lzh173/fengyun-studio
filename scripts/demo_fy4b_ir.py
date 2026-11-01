"""端到端验证 D：FY-4B 红外通道 → LUT 定标 → 标称投影 → 重采样 → 出图。

用 4000M（2748²，含 15 通道）而不是 1000M，因为 1000M 只有 3 个可见光通道，
而可见光在夜间 granule 上全黑，无法用肉眼判断链路是否正确。
"""
from __future__ import annotations

import glob
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fysat.calib import lookup_table  # noqa: E402
from fysat.export import ExportOptions, export  # noqa: E402
from fysat.geo import nominal_geos_lonlat, reproject_to_grid  # noqa: E402
from fysat.palettes import bt_to_rgb  # noqa: E402
from fysat.readers import open_file  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"


def pick_4000m() -> Path:
    hits = glob.glob(r"Y:\download-data\**\FY4B-*4000M*.HDF", recursive=True)
    if not hits:
        raise SystemExit("找不到 FY-4B 4000M 样本")
    return Path(hits[0])


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    src = pick_4000m()
    ds = open_file(src, load=False)
    print(f"1) {src.name}\n   {ds.platform} {ds.instrument} {ds.level} · {len(ds.variables)} 变量")

    # 文件名为 4000M，像元尺寸必须是 4000 m，否则标称投影只能覆盖中央一小块
    pixel_size = 4000.0
    print(f"2) 像元尺寸 {pixel_size:.0f} m（取自文件名 4000M）")

    # 红外窗口 CH12
    ch = 12
    name = f"Data/NOMChannel{ch:02d}"
    dn = ds.load(name).data
    lut = ds.load(f"Calibration/CALChannel{ch:02d}").data.reshape(-1)
    print(f"3) {name}  DN {dn.min()}~{dn.max()}   LUT 长度 {lut.size}  "
          f"LUT 值域 {lut.min():.1f}~{lut.max():.1f}（单位 K）")

    # LUT 定标：AGRI 的 CALChannel 是 DN→物理量 查找表。
    # 注意 DN 可能超出 LUT 长度（4096），这里用 nearest + 越界掩 NaN。
    phys = lookup_table(dn, lut, kind="nearest")
    print(f"4) 定标后 {np.nanmin(phys):.1f} ~ {np.nanmax(phys):.1f} K  "
          f"中位 {np.nanmedian(phys):.1f} K  有效 {np.isfinite(phys).mean()*100:.1f}%"
          f"   ({time.time()-t0:.1f}s)")

    # 定位（关键：pixel_size 必须与产品分辨率一致）
    sub_lon = float(ds.attrs.get("Nominal Satellite Subpoint Longitude", 105.0))
    sat_h = float(ds.attrs.get("Nominal Satellite Height", 35786023.0))
    lat, lon = nominal_geos_lonlat(dn.shape, sub_lon=sub_lon, sub_lat=0.0,
                                   sat_height=sat_h, pixel_size=pixel_size)
    print(f"5) 标称投影 {sub_lon}°E → lon {np.nanmin(lon):.1f}~{np.nanmax(lon):.1f}"
          f"  lat {np.nanmin(lat):.1f}~{np.nanmax(lat):.1f}   ({time.time()-t0:.1f}s)")

    # 重采样到 0.5°（4 km 全盘 5496 px 用 0.5° 足够看结构）
    t1 = time.time()
    grid = reproject_to_grid(phys, lat, lon, res=0.5)
    print(f"6) 重采样 0.5° → {grid.shape}  extent {tuple(round(v,1) for v in grid.extent)}"
          f"   ({time.time()-t1:.1f}s)")

    vmin, vmax = (float(np.nanpercentile(phys, 1)), float(np.nanpercentile(phys, 99)))
    print(f"7) 亮温区间 p1={vmin:.1f} p99={vmax:.1f} K")
    rgb = bt_to_rgb(grid.data, vmin_k=vmin, vmax_k=vmax)

    print("8) 导出：")
    for kind, name2, kw, arr in [
        ("tiff", "fy4b_ir_grid.tif", {}, grid.data.astype(np.float32)),
        ("png_full", "fy4b_ir_grid_full.png", {}, rgb),
        ("png_compressed", "fy4b_ir_grid_l9.png", {"compress_level": 9}, rgb),
    ]:
        out = export(arr, ExportOptions(kind=kind, path=OUT / name2, **kw))
        print(f"   {kind:15s} {out.name:28s} {out.stat().st_size/1e6:7.2f} MB")

    print(f"\n总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

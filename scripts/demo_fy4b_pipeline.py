"""端到端验证 C：定标 → 标称投影定位 → 等经纬网格重采样 → 三格式导出。

这条链路把 reader / calib / geo / export 串起来，是 GUI 之前最重要的一次集成验证。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

from fysat.calib import reflectance_from_lut  # noqa: E402
from fysat.export import ExportOptions, export  # noqa: E402
from fysat.geo import nominal_geos_lonlat, reproject_to_grid  # noqa: E402
from fysat.palettes import bt_to_rgb  # noqa: E402
from fysat.readers import open_file  # noqa: E402

# 样本目录与输出目录都走环境变量/相对路径，开源版不写死任何人的机器
SAMPLE_ROOT = Path(os.environ.get("FYSAT_SAMPLE_ROOT", ""))


def _require_sample_root() -> Path:
    """开发脚本必须显式指定样本目录，避免把某台机器的路径写进仓库。"""
    if not str(SAMPLE_ROOT) or not SAMPLE_ROOT.is_dir():
        raise SystemExit(
            "请先设置环境变量 FYSAT_SAMPLE_ROOT 指向 NSMC 产品目录\n"
            "  PowerShell:  $env:FYSAT_SAMPLE_ROOT = \"D:\\samples\"\n"
            "  bash:        export FYSAT_SAMPLE_ROOT=/data/samples")
    return SAMPLE_ROOT

_OUT = Path(__file__).resolve().parents[1] / "out"


def _sample(rel: str) -> Path:
    return SAMPLE_ROOT / rel


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


OUT = Path(__file__).resolve().parents[1] / "out"
FY4B = _sample(r"FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20261030154500_20261030155959_1000M_V0001.HDF")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()

    ds = open_file(FY4B, load=False)
    print(f"1) 读取 {ds.platform} {ds.instrument} {ds.level}")

    # --- 定标：DN → 反射率(%) ---
    dn = ds.load("Data/NOMChannel02").data
    lut = ds.load("Calibration/CALChannel02").data.reshape(-1)
    refl = reflectance_from_lut(dn, lut)
    ok = np.isfinite(refl)
    print(f"2) 定标 CH02 反射率 {np.nanmin(refl):.2f}% ~ {np.nanmax(refl):.2f}%  "
          f"有效 {ok.mean()*100:.1f}%   ({time.time()-t0:.1f}s)")

    # --- 定位：标称投影 ---
    sub_lon = float(ds.attrs.get("Nominal Satellite Subpoint Longitude", 105.0))
    sat_h = float(ds.attrs.get("Nominal Satellite Height", 35786023.0))
    print(f"3) 标称投影 星下点 {sub_lon}°E 高度 {sat_h/1000:.0f} km")
    lat, lon = nominal_geos_lonlat(dn.shape, sub_lon=sub_lon, sub_lat=0.0, sat_height=sat_h)
    print(f"   经纬度范围 lon {np.nanmin(lon):.1f}~{np.nanmax(lon):.1f}  "
          f"lat {np.nanmin(lat):.1f}~{np.nanmax(lat):.1f}   ({time.time()-t0:.1f}s)")

    # --- 重采样到 0.1° 等经纬网格（全盘 0.05° 太慢，演示用 0.1°）---
    t1 = time.time()
    grid = reproject_to_grid(refl, lat, lon, res=0.1)
    print(f"4) 重采样 0.1° → {grid.shape}  extent {tuple(round(v,1) for v in grid.extent)}"
          f"   ({time.time()-t1:.1f}s)")

    # --- 导出三种格式 ---
    rgb = bt_to_rgb(grid.data, vmin_k=270.0, vmax_k=320.0)   # 复用上色，把反射率当温度色阶演示
    print("5) 导出：")
    for kind, name, kw, arr in [
        ("tiff", "fy4b_ch02_refl_grid.tif", {}, grid.data.astype(np.float32)),
        ("png_full", "fy4b_ch02_refl_grid_full.png", {}, rgb),
        ("png_compressed", "fy4b_ch02_refl_grid_l9.png", {"compress_level": 9}, rgb),
        ("png_compressed", "fy4b_fullres_l9.png", {"compress_level": 9, "scale": 0.2}, refl),
    ]:
        out = export(arr, ExportOptions(kind=kind, path=OUT / name, **kw))
        print(f"   {kind:15s} {out.name:34s} {out.stat().st_size/1e6:7.2f} MB")

    print(f"\n总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

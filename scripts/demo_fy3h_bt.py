"""端到端演示（B）：FY-3H MERSI 红外亮温 → 三种格式导出。

选择红外通道是因为它不依赖光照，任何轨道时次都有信号，
能直观验证"读 → 定标 → 渲染 → 导出"整条链路。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fysat.export import ExportOptions, export  # noqa: E402
from fysat.palettes import bt_to_rgb  # noqa: E402
from fysat.readers import open_file  # noqa: E402
from fysat.render import display_array  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"
SRC = Path(r"Y:\download-data\FY3H_MERSI_GRAN_L1_20261022_1810_0250M_V0.hdf")

C1, C2 = 1.1910427e-5, 1.4387752


def dn_to_bt(dn: np.ndarray, scale: float, offset: float, wavelength_um: float) -> np.ndarray:
    """DN → 辐亮度 → 亮温(K)。MERSI 红外：L = DN*scale + offset，单位 mW/(m²·sr·cm⁻¹)。"""
    nu = 1e4 / wavelength_um
    rad = dn.astype(np.float64) * scale + offset
    with np.errstate(invalid="ignore", divide="ignore"):
        bt = (C2 * nu) / np.log(C1 * nu ** 3 / rad + 1.0)
    return np.where((bt > 100) & (bt < 400), bt, np.nan).astype(np.float32)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    ds = open_file(SRC, load=False)
    print(f"打开 {SRC.name}")
    print(f"  {ds.platform} {ds.instrument} {ds.level} · 定位 {ds.geolocation.kind} step={ds.geolocation.step}")

    var = ds.load("Data/EV_250_Emissive_b24")
    print(f"  {var.name} {var.shape} {var.dtype} units={var.unit} Slope={var.scale_factor}")
    dn = display_array(var, physical=False)          # 已把 65535 填充值置 NaN
    bt = dn_to_bt(dn, var.scale_factor or 0.01, var.add_offset or 0.0, 10.7)
    print(f"  亮温范围 {np.nanmin(bt):.1f} ~ {np.nanmax(bt):.1f} K  (中位数 {np.nanmedian(bt):.1f} K)")

    # 上色：增强红外色表（业务习惯），TIFF 保留原始 16 位 DN
    rgb = bt_to_rgb(bt, vmin_k=190.0, vmax_k=315.0)
    print(f"  渲染完成 {rgb.shape} {rgb.dtype}")

    jobs = [
        ("tiff", "fy3h_bt_ch24.tif", {}, dn),
        ("png_full", "fy3h_bt_ch24_full.png", {}, rgb),
        ("png_compressed", "fy3h_bt_ch24_l9.png", {"compress_level": 9}, rgb),
        ("png_compressed", "fy3h_bt_ch24_l3.png", {"compress_level": 3}, rgb),
        ("png_compressed", "fy3h_preview.png", {"compress_level": 9, "scale": 0.15}, rgb),
    ]
    print("\n导出：")
    for kind, name, kw, data in jobs:
        t1 = time.time()
        out = export(data, ExportOptions(kind=kind, path=OUT / name, **kw))
        print(f"  {kind:15s} {out.name:28s} {out.stat().st_size/1e6:7.2f} MB  {time.time()-t1:5.1f}s")

    print(f"\n总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

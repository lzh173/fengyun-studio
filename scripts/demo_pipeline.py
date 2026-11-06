from __future__ import annotations

import os
from pathlib import Path

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


"""端到端演示：读真实产品 → 合成 RGB / 定标亮温 → 三种格式导出。

用法:
    python scripts/demo_pipeline.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fysat.export import ExportOptions, export  # noqa: E402
from fysat.readers import open_file  # noqa: E402
from fysat.render import Stretch, composite, display_array  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"
FY4B = _sample(r"FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20261030154500_20261030155959_1000M_V0001.HDF")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    ds = open_file(FY4B, load=False)
    print(f"打开 {FY4B.name}")
    print(f"  {ds.platform} {ds.instrument} {ds.level} {ds.product} · {len(ds.variables)} 个变量")

    r = display_array(ds.load("Data/NOMChannel02"))   # 0.65 µm
    g = display_array(ds.load("Data/NOMChannel01"))   # 0.47 µm
    b = display_array(ds.load("Data/NOMChannel03"))   # 0.83 µm
    print(f"  三个通道已载入 {r.shape}，用时 {time.time()-t0:.1f}s")

    rgb = composite(r, g, b * 0.85, st=Stretch(pct=(0.5, 99.5), gamma=1.1))
    print(f"  RGB 合成完成 {rgb.shape} {rgb.dtype}")

    jobs = [
        ("tiff", OUT / "fy4b_truecolor.tif", {}),
        ("png_full", OUT / "fy4b_truecolor_full.png", {}),
        ("png_compressed", OUT / "fy4b_truecolor_l9.png", {"compress_level": 9}),
        ("png_compressed", OUT / "fy4b_truecolor_l0.png", {"compress_level": 0}),
    ]
    print("\n导出：")
    for kind, path, kw in jobs:
        t1 = time.time()
        out = export(rgb, ExportOptions(kind=kind, path=path, **kw))
        mb = out.stat().st_size / 1e6
        print(f"  {kind:15s} {out.name:32s} {mb:7.2f} MB   {time.time()-t1:5.1f}s")

    # 灰度单通道也验证一遍（TIFF 保留 16 位原始 DN）
    dn = ds.load("Data/NOMChannel02").data
    out = export(dn, ExportOptions(kind="tiff", path=OUT / "fy4b_ch02_dn.tif"))
    print(f"\n  16 位 DN TIFF  {out.name:32s} {out.stat().st_size/1e6:7.2f} MB (原始 {dn.dtype})")

    # 下采样预览
    small = export(rgb, ExportOptions(kind="png_compressed", path=OUT / "fy4b_preview.png", scale=0.08, compress_level=9))
    print(f"  预览图         {small.name:32s} {small.stat().st_size/1e3:7.1f} KB")

    print(f"\n总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

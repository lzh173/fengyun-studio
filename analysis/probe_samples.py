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


# -*- coding: utf-8 -*-
"""对几类新样本做结构探针：确认能否用 h5py 打开、顶层结构长什么样。"""
import glob
import os

import h5py

ROOT = SAMPLE_ROOT


def pick(pattern):
    hits = glob.glob(os.path.join(ROOT, "**", pattern), recursive=True)
    return hits[0] if hits else None


TARGETS = [
    ("FY-4B AGRI L1 FDI 4000M", "FY4B-*L1-_FDI-_*4000M*.HDF"),
    ("FY-4B AGRI L1 FDI 1000M", "FY4B-*L1-_FDI-_*1000M*.HDF"),
    ("FY-3F MERSI L1 1000M", "FY3F_MERSI_GRAN_L1_*1000M*.hdf"),
    ("FY-3G PMR L2 KuR", "FY3G_PMR*.HDF"),
    ("FY-2G FDI L1", "FY2G_FDI_ALL_NOM_*.hdf"),
]

for label, pat in TARGETS:
    path = pick(pat)
    if not path:
        print(f"\n### {label}: 未找到")
        continue
    print(f"\n### {label}")
    print("  file:", os.path.basename(path), f"{os.path.getsize(path)/1e6:.1f} MB")
    try:
        with h5py.File(path, "r") as f:
            keys = list(f.keys())
            print("  顶层:", keys[:12], "…" if len(keys) > 12 else "")
            n_attr = len(list(f.attrs.items()))
            print(f"  全局属性 {n_attr} 个，示例:", [k for k, _ in list(f.attrs.items())[:6]])
            shown = 0
            for k in keys:
                obj = f[k]
                if isinstance(obj, h5py.Dataset):
                    print(f"   DS {k} {obj.shape} {obj.dtype}")
                    shown += 1
                else:
                    sub = list(obj.keys())
                    print(f"   GRP {k}/ ({len(sub)}) -> {sub[:5]}")
                    for s in sub[:3]:
                        o = obj[s]
                        if isinstance(o, h5py.Dataset):
                            print(f"        DS {k}/{s} {o.shape} {o.dtype}")
                if shown > 6:
                    break
    except Exception as ex:
        print("  ERR", type(ex).__name__, ex)

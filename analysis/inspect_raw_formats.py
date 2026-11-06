"""检查 GK-2A / AWX / FY-2 DAT 的具体结构，确认格式归属。"""

from __future__ import annotations

import glob
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

ROOT = SAMPLE_ROOT

print("== gk2a 目录")
for d in glob.glob(os.path.join(ROOT, "gk2a*")):
    fs = os.listdir(d)
    print(" ", os.path.basename(d), "->", len(fs), "个文件")
    for f in fs[:6]:
        p = os.path.join(d, f)
        with open(p, "rb") as fh:
            head = fh.read(8)
        print(f"    {os.path.getsize(p)/1e6:8.2f}MB head={head!r} {f[:76]}")

print("\n== AWX 头 64 字节")
for p in glob.glob(os.path.join(ROOT, "**", "*.AWX"), recursive=True)[:3]:
    with open(p, "rb") as fh:
        b = fh.read(64)
    print(" ", os.path.basename(p)[:60])
    print("    hex:", b[:32].hex(" "))
    print("    ascii:", b[:24])

print("\n== FY-2 DAT 头")
for p in glob.glob(os.path.join(ROOT, "**", "FY2G_CSV*.DAT"), recursive=True)[:2]:
    with open(p, "rb") as fh:
        b = fh.read(48)
    print(" ", os.path.basename(p), os.path.getsize(p) / 1e6, "MB")
    print("    hex:", b[:32].hex(" "))

print("\n== FY-1D L1B 头 64 字节")
for p in glob.glob(os.path.join(ROOT, "**", "*.L1B"), recursive=True)[:2]:
    with open(p, "rb") as fh:
        b = fh.read(64)
    print(" ", os.path.basename(p)[:60], os.path.getsize(p) / 1e6, "MB")
    print("    hex:", b[:32].hex(" "))
    print("    ascii:", bytes(c if 32 <= c < 127 else 46 for c in b[:48]))

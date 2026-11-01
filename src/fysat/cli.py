"""命令行入口：info / ls / export / formats。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import __version__
from .detect import parse_name, sniff
from .export import KINDS, ExportOptions, describe_kinds, export
from .readers import open_file
from .readers.hdf5 import list_tree


def _parse_range(s: str) -> tuple[float, float]:
    lo, hi = s.split(",")
    return float(lo), float(hi)


def cmd_info(args) -> int:
    kind = sniff(args.file)
    ds = open_file(args.file, load=False)
    payload = ds.summary()
    payload["container"] = kind
    payload["file_mb"] = round(Path(args.file).stat().st_size / 1e6, 2)
    ni = parse_name(args.file)
    if ni.start_time:
        payload["time_from_name"] = ni.start_time.isoformat(sep=" ")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"文件      {Path(args.file).name}")
    print(f"容器      {kind}    {payload['file_mb']} MB")
    print(f"卫星      {ds.platform or '?'} / {ds.instrument or '?'} / {ds.level or '?'} / {ds.product or '?'}")
    print(f"通道数    {len(ds.variables)}")
    geo = ds.geolocation
    if geo.is_nav:
        b = geo.bounds()
        print(f"定位      {geo.kind}  经度 {b[0]:.2f}~{b[1]:.2f}  纬度 {b[2]:.2f}~{b[3]:.2f}  抽稀 {geo.step}")
    else:
        print(f"定位      {geo.kind}")
    for v in list(ds.variables.values())[: args.limit]:
        print(f"  {v.name:38s} {str(v.shape):18s} {str(v.dtype):8s} {v.unit}")
    if len(ds.variables) > args.limit:
        print(f"  … 共 {len(ds.variables)} 个")
    return 0


def cmd_ls(args) -> int:
    for row in list_tree(args.file, max_items=args.limit):
        shape = row.get("shape", "")
        print(f"{row['kind']:8s} {row['path']:52s} {str(shape):18s} {row.get('dtype','')}")
    return 0


def cmd_export(args) -> int:
    ds = open_file(args.file, load=False)
    if args.var not in ds.variables:
        names = ", ".join(list(ds.variables)[:12])
        print(f"找不到变量 {args.var}；可选：{names} …", file=sys.stderr)
        return 2
    var = ds.load(args.var)
    if args.physical:
        from .render import display_array

        data = display_array(var, physical=True)
    else:
        data = var.data

    opts = ExportOptions(
        kind=args.kind,
        path=args.out,
        stretch=_parse_range(args.stretch) if args.stretch else None,
        vmin=args.vmin,
        vmax=args.vmax,
        gamma=args.gamma,
        cmap=args.cmap,
        compress_level=args.level,
        scale=args.scale,
        deflate=not args.no_deflate,
    )
    out = export(data, opts)
    size_mb = out.stat().st_size / 1e6
    print(f"已导出 {out}  ({size_mb:.2f} MB, {args.kind})")
    return 0


def cmd_formats(_args) -> int:
    print(describe_kinds())
    for k, v in KINDS.items():
        print(f"  {k}: 后缀 {v['ext']} | 无损={v['lossless']} | 可缩放={v['scale']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("fysat", description="风云卫星官方数据解码与制图工具")
    p.add_argument("--version", action="version", version=f"fysat {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("info", help="查看文件概况")
    pi.add_argument("file")
    pi.add_argument("--limit", type=int, default=15)
    pi.add_argument("--json", action="store_true")
    pi.set_defaults(func=cmd_info)

    pl = sub.add_parser("ls", help="列出文件内部结构")
    pl.add_argument("file")
    pl.add_argument("--limit", type=int, default=60)
    pl.set_defaults(func=cmd_ls)

    pe = sub.add_parser("export", help="导出为 TIFF / PNG")
    pe.add_argument("file")
    pe.add_argument("var")
    pe.add_argument("--kind", choices=list(KINDS), default="png_full")
    pe.add_argument("--out", required=True)
    pe.add_argument("--stretch", default="2,98", help="百分位拉伸，如 2,98；传空则用 min/max")
    pe.add_argument("--vmin", type=float)
    pe.add_argument("--vmax", type=float)
    pe.add_argument("--gamma", type=float, default=1.0)
    pe.add_argument("--cmap", default=None, help="色标名（png_compressed 生效）")
    pe.add_argument("--level", type=int, default=6, help="PNG 压缩强度 0-9")
    pe.add_argument("--scale", type=float, default=1.0, help="缩放（png_compressed 生效）")
    pe.add_argument("--physical", action="store_true", help="应用定标后再导出")
    pe.add_argument("--no-deflate", action="store_true")
    pe.set_defaults(func=cmd_export)

    pf = sub.add_parser("formats", help="列出可用导出形式")
    pf.set_defaults(func=cmd_formats)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

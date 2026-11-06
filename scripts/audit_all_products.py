"""对数据文件夹里**每一类产品**跑完整链路测试。

链路：识别容器 → 打开 → 判定仪器 → 解析合成配方 → 选通道渲染 → 导出缩略图

输出一张覆盖矩阵，明确每类产品：支持 / 部分支持 / 不支持，以及原因。
每类取一个代表文件（同族文件结构相同，逐个跑 250 个文件没有必要，
但**每一类都覆盖到**）。

用法：python scripts/audit_all_products.py [--all] [--out DIR]
    --all  不按产品族归并，逐文件跑（慢）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path

import numpy as np  # noqa: E402

from fysat import composites, detect  # noqa: E402
from fysat.readers import open_file  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


DATA = Path(os.environ.get("FYSAT_SAMPLE_ROOT", ""))
if not str(DATA) or not DATA.is_dir():
    raise SystemExit("请先设置环境变量 FYSAT_SAMPLE_ROOT 指向 NSMC 产品目录")
SKIP_EXT = {".enp", ".jpg", ".png", ".txt", ".xml", ".csv", ".db", ".json",
            ".npz", ".npy", ".cbor", ".raw"}


def families() -> OrderedDict[str, Path]:
    """按「容器 + 产品族」归并，每族取体积最大的代表文件。"""
    out: OrderedDict[str, Path] = OrderedDict()
    best: dict[str, int] = {}
    for p in sorted(DATA.rglob("*")):
        if not p.is_file() or p.suffix.lower() in SKIP_EXT:
            continue
        try:
            kind = detect.sniff(p)
        except Exception:                            # noqa: BLE001
            kind = "unknown"
        toks = [t for t in re.split(r"[_\-]", p.stem) if t and not t.isdigit()]
        fam = "_".join(toks[:3]) or p.stem
        key = f"{kind} | {fam}"
        size = p.stat().st_size
        if size > best.get(key, -1):
            best[key] = size
            out[key] = p
    return out


def run_one(kind: str, path: Path, out_dir: Path) -> dict:
    res = {
        "kind": kind, "file": path.name, "mb": path.stat().st_size / 1e6,
        "open": False, "platform": "", "instrument": "", "nvars": 0,
        "composites": [], "rendered": "", "export": "", "status": "", "why": "",
    }
    t0 = time.time()
    try:
        ds = open_file(path, load=False)
        res["open"] = True
        res["platform"] = ds.platform or ""
        res["instrument"] = ds.instrument or ""
        res["nvars"] = len(ds.variables)
    except Exception as exc:                          # noqa: BLE001
        res["status"] = "FAIL-OPEN"
        res["why"] = f"{type(exc).__name__}: {exc}"
        res["secs"] = time.time() - t0
        return res

    # 合成配方
    try:
        inst = composites.instrument_of(ds)
        comps = composites.composites_for(ds, inst)
        res["instrument_key"] = inst or ""
        res["composites"] = [c.key for c in comps if c.ready]
        res["composites_broken"] = [c.key for c in comps if not c.ready]
    except Exception as exc:                          # noqa: BLE001
        res["why"] = f"合成解析异常 {type(exc).__name__}: {exc}"

    # 渲染 + 导出：优先用第一个可用的合成，否则用第一个可成像变量
    try:
        from fysat.export import ExportOptions, export
        from fysat.render import display_band

        target = None
        for c in composites.composites_for(ds, res.get("instrument_key") or None):
            if c.ready and c.kind == "single":
                target = c
                break
        if target is not None:
            ref = target.refs[0]
            var = ds.load(ref.variable)
            data = display_band(var, ref.index, physical=True)
            res["rendered"] = f"{target.key}:{ref.variable}[{ref.index}]"
        else:
            from fysat.gui.varcatalog import classify_dataset

            classes = classify_dataset(ds)
            # 回退时优先真正的大尺寸影像，避免挑到 ColumnNumber 这类辅助列
            cands = [(n, c) for n, c in classes.items() if c.is_image]
            cands.sort(key=lambda kv: (
                0 if kv[1].kind in ("image", "band_stack") else 1,
                -(int(np.prod(tuple(kv[1].shape) or (1,)))),
            ))
            pick = cands[0] if cands else None
            if pick is None:
                res["status"] = "NO-IMAGE"
                res["why"] = "没有可成像变量（廓线/表格/质量码类产品）"
                res["secs"] = time.time() - t0
                return res
            name, c = pick
            var = ds.load(name)
            data = display_band(var, 0, physical=True)
            res["rendered"] = f"fallback:{name}[0]"

        if data is None or not np.isfinite(data).any():
            res["status"] = "EMPTY"
            res["why"] = "渲染结果全为无效值"
            res["secs"] = time.time() - t0
            return res

        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]", "_", res["file"])[:60]
        png = out_dir / f"{safe}.png"
        export(data.astype("float32"),
               ExportOptions(kind="png_compressed", path=png,
                             compress_level=6, scale=1.0))
        res["export"] = f"{png.name} ({png.stat().st_size // 1024} KB)"
        res["status"] = "OK"
    except Exception as exc:                          # noqa: BLE001
        res["status"] = "FAIL-RENDER"
        res["why"] = f"{type(exc).__name__}: {exc}"
        res["trace"] = traceback.format_exc(limit=3)
    res["secs"] = time.time() - t0
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "audit_all"))
    ap.add_argument("--only", default="", help="只跑匹配该子串的产品族")
    args = ap.parse_args()
    out_dir = Path(args.out)

    fams = families()
    if args.only:
        fams = OrderedDict((k, v) for k, v in fams.items() if args.only.lower() in k.lower())

    print(f"共 {len(fams)} 类产品，逐类跑完整链路\n", flush=True)
    print(f"{'状态':10s} {'容器':10s} {'产品族':40s} {'MB':>7s}  说明")
    print("-" * 118)

    results = []
    for key, path in fams.items():
        kind, fam = key.split(" | ", 1)
        r = run_one(kind, path, out_dir)
        results.append((key, r))
        why = r.get("why") or r.get("rendered", "")
        comps = r.get("composites") or []
        extra = f"合成 {len(comps)}" if comps else ""
        print(f"{r['status']:10s} {kind:10s} {fam[:40]:40s} {r['mb']:7.1f}  "
              f"{extra} {why[:52]}", flush=True)

    ok = sum(1 for _, r in results if r["status"] == "OK")
    print("\n" + "=" * 118)
    print(f"通过 {ok} / {len(results)} 类")
    bad = [(k, r) for k, r in results if r["status"] != "OK"]
    if bad:
        print("\n未通过：")
        for k, r in bad:
            print(f"  [{r['status']}] {k}\n        {r.get('why', '')}")

    # 汇总
    summary = out_dir / "SUMMARY.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(summary, "w", encoding="utf-8") as f:
        for k, r in results:
            f.write(f"{r['status']}\t{k}\t{r.get('why','')}\t{r.get('rendered','')}\n")
    print(f"\n明细已写入 {summary}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

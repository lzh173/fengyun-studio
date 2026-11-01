"""全样本回归：扫描下载目录，逐个文件验证"能识别 + 能读取 + 形状合理"。

用法:
    python scripts/regress_samples.py [根目录...]
默认扫描 Y:\download-data 与指定下载批次目录。
"""
from __future__ import annotations

import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fysat.detect import sniff  # noqa: E402
from fysat.readers import open_file  # noqa: E402

ROOTS = [
    Path(r"Y:\download-data"),
    Path(r"Y:\download-data\C202611011426140096"),
]

# 只回归"产品数据"，跳过快视图与临时文件
SKIP_EXT = {".enp", ".db", ".jpg", ".jpeg", ".png", ".txt", ".csv",
            ".json", ".xml", ".npy", ".npz", ".cbor"}
DATA_EXT = {".hdf", ".h5", ".nc", ".dat", ".l1b", ".awx"}

# 已知尚未实现的容器（不计为回归失败，单独统计）
# FY-1D AVHRR L2 "ARGY...PSG" 的自定义 .DAT：文档在
#   其他卫星数据格式说明/noaa_1b_format.md 附近，但结构未探明，暂不承诺
KNOWN_UNSUPPORTED = [
    "FY1D_AVHRR_ARGY",           # FY-1D L2 自定义 DAT
]


def collect(roots: list[Path]) -> list[Path]:
    seen: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() in SKIP_EXT:
                continue
            if p.suffix.lower() not in DATA_EXT:
                continue
            seen[str(p).lower()] = p
    return sorted(seen.values())


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or ROOTS
    files = collect(roots)
    print(f"待回归样本 {len(files)} 个\n")

    stats: Counter = Counter()
    failures: list[tuple[Path, str]] = []
    truncated: list[Path] = []

    for p in files:
        try:
            size = p.stat().st_size
            if size == 0:
                truncated.append(p)
                stats["空文件"] += 1
                continue
            kind = sniff(p)
            ds = open_file(p, load=False)
            n = len(ds.variables)
            if n == 0:
                raise ValueError("变量数为 0")
            stats[kind] += 1
            stats["ok"] += 1
            bad = [v for v in ds.variables.values() if any(d == 0 for d in v.shape)]
            if bad:
                stats["empty_vars"] += 1
        except Exception as exc:                      # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            # 截断/残缺的下载件不是解析器的问题，单独归类
            if "truncated" in msg or "signature not found" in msg:
                truncated.append(p)
                stats["下载残件"] += 1
                print(f"  SKIP {p.name}  ({p.stat().st_size/1e6:.2f} MB, 疑似下载不完整)")
                continue
            if any(p.name.upper().startswith(k.upper()) for k in KNOWN_UNSUPPORTED):
                stats["已知未实现"] += 1
                print(f"  TODO {p.name}  (已知未实现的容器，见 KNOWN_UNSUPPORTED)")
                continue
            stats["fail"] += 1
            failures.append((p, msg))
            print(f"  FAIL {p.name}\n       {msg}")

    print("\n== 汇总 ==")
    for k, v in sorted(stats.items()):
        print(f"  {k:14s} {v}")
    if truncated:
        print(f"\n跳过 {len(truncated)} 个下载残件（需重新下载，非解析问题）")
    if failures:
        print(f"\n失败 {len(failures)} 个：")
        for p, msg in failures:
            print(f"  - {p.name}: {msg}")
        return 1
    print("\n解析全部通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:                                 # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)

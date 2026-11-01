# -*- coding: utf-8 -*-
"""把 Y:\download-data 归并成"样本覆盖表"（markdown），供 PLAN.md 使用。"""
import os
import re
import collections

ROOT = r"Y:\download-data"
SKIP = {".enp", ".db", ".json", ".xml", ".txt", ".cbor", ".npy", ".npz"}

SAT = [
    ("FY4B", "FY-4B"), ("FY4A", "FY-4A"), ("FY3H", "FY-3H"), ("FY3G", "FY-3G"),
    ("FY3F", "FY-3F"), ("FY3E", "FY-3E"), ("FY3D", "FY-3D"), ("FY3C", "FY-3C"),
    ("FY2G", "FY-2G"), ("FY2F", "FY-2F"), ("FY1D", "FY-1D"), ("NA18", "NOAA-18"),
    ("N18", "NOAA-18"), ("GK2A", "GK-2A"), ("MST2", "Meteosat-2"),
]


def classify(path, name):
    n = name.upper()
    sat = "其他"
    for k, v in SAT:
        if k in n:
            sat = v
            break
    ext = os.path.splitext(name)[1].lower()

    # 产品族
    if "MERSI" in n:
        prod = "MERSI L1"
        res = re.search(r"_(0250M|1000M|GEOQK)_", n)
        prod += " " + (res.group(1) if res else "")
    elif "AGRI" in n:
        lvl = re.search(r"_L(\d)-", n)
        inst = "AGRI L" + (lvl.group(1) if lvl else "?")
        ptype = re.search(r"_L\d-([A-Z]{4})-", n)
        res = re.search(r"_(4000M|2000M|1000M|0500M|500M)_", n)
        prod = f"{inst} {ptype.group(1) if ptype else ''} {res.group(1) if res else ''}".strip()
    elif "GHI" in n:
        prod = "GHI L1 REGX"
    elif "PMR" in n:
        prod = "PMR L2 KuR"
    elif "GNOSO" in n:
        prod = "GNOSO L1 掩星"
    elif "FDI" in n:
        prod = "FDI L1 全圆盘"
    elif "CSV" in n:
        prod = "CSV L1 数据集"
    elif "AVHRR" in n:
        lvl = "L1B" if "L1" in n else ("L2" if "_L2_" in n else "?")
        prod = f"AVHRR {lvl}"
    elif ext == ".awx":
        prod = "AWX 2.1 图像"
    elif ext == ".raw":
        prod = "原始通道流"
    elif ext == ".png":
        prod = "PNG 快视图"
    else:
        prod = ext.lstrip(".").upper() or "其他"
    return sat, prod


def main():
    rows = collections.defaultdict(lambda: {"n": 0, "b": 0, "exts": collections.Counter()})
    for dp, dn, fn in os.walk(ROOT):
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext in SKIP:
                continue
            try:
                s = os.path.getsize(os.path.join(dp, f))
            except Exception:
                continue
            sat, prod = classify(dp, f)
            d = rows[(sat, prod)]
            d["n"] += 1
            d["b"] += s
            d["exts"][ext] += 1

    order = {"FY-4B": 0, "FY-4A": 1, "FY-3H": 2, "FY-3G": 3, "FY-3F": 4, "FY-3E": 5,
             "FY-3D": 6, "FY-3C": 7, "FY-2G": 8, "FY-1D": 9, "NOAA-18": 10,
             "Meteosat-2": 11, "GK-2A": 12, "其他": 13}
    print("| 卫星 | 产品 | 文件数 | 体积 | 容器 |")
    print("|---|---|---:|---:|---|")
    for (sat, prod), d in sorted(rows.items(), key=lambda x: (order.get(x[0][0], 99), -x[1]["b"])):
        exts = "/".join(f"{e}({c})" for e, c in d["exts"].most_common())
        print(f"| {sat} | {prod} | {d['n']} | {d['b']/1e9:.2f} GB | {exts} |")
    tot = sum(d["n"] for d in rows.values())
    gb = sum(d["b"] for d in rows.values()) / 1e9
    print(f"\n合计 {tot} 个文件 · {gb:.2f} GB")


if __name__ == "__main__":
    main()

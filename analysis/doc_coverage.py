# -*- coding: utf-8 -*-
"""最终支持范围判定：文档 × 样本可得性。

样本来源：样本根目录（环境变量 FYSAT_SAMPLE_ROOT）与用户提供的产品清单。
规则：有样本 → 支持；无样本 → 默认不支持（按用户要求）。
"""
import os
import re
import collections

DOC_ROOT = r"D:\desktop_dp\temp\nsmc-doc\md\数据格式说明"

# (匹配规则, 归类, 是否有样本)
RULES = [
    (r"^index\.md$|^_report\.md$", "（索引/报告）", "skip"),
    (r"Tan1_CAPIX", "TanSat CAPIX", False),
    (r"FY-?3[CDEFGH].*MWRI|MWRI.*Ascending|MWRI.*Descending|MWTSMWHS", "FY-3 MWRI/MWTS-MWHS", False),
    (r"FY4_.*HRIT|FY4_.*GIIRS", "FY-4 HRIT/GIIRS", False),
    (r"hdf50_userguid|hdf43_userguid|HDF_Format_Description", "HDF 手册（非产品）", "manual"),
    (r"FY-3_L1_Product_Format|FY-3_L2_L3_Product_Format|FY-3_Satellite_Orbital", "FY-3A/B 产品格式", False),
    (r"eos_1b_format|gms_1b_format", "国外 1B（EOS/GMS）", False),
    (r"AWX", "AWX 2.1", True),
    (r"FY-?3D", "FY-3D", True),
    (r"FY-?3C", "FY-3C", True),
    (r"FY-?3F", "FY-3F", True),
    (r"FY-?3G", "FY-3G", True),
    (r"FY-?3H", "FY-3H", True),
    (r"FY-?4A", "FY-4A", True),
    (r"FY-?4B", "FY-4B", True),
    (r"FY-?2", "FY-2 系列", True),
    (r"FY-?1", "FY-1D（1B）", True),
    (r"NOAA", "NOAA-18（1B）", True),
    (r"TANSAT|TanSat", "TanSat ACGS", True),
]


def classify(name):
    for pat, fam, has in RULES:
        if re.search(pat, name, re.I):
            return fam, has
    return "其他/未归类", False


def main():
    agg = collections.defaultdict(lambda: {"n": 0, "has": None})
    for dp, dn, fn in os.walk(DOC_ROOT):
        for f in fn:
            if not f.endswith(".md"):
                continue
            fam, has = classify(f)
            agg[fam]["n"] += 1
            agg[fam]["has"] = has

    sup = drop = manual = 0
    print(f"{'归类':24s}{'文档':>5s}  结论")
    for fam, d in sorted(agg.items(), key=lambda x: -x[1]["n"]):
        if d["has"] == "skip":
            verdict = "—"; manual += d["n"]
        elif d["has"] == "manual":
            verdict = "参考（非产品）"; manual += d["n"]
        elif d["has"]:
            verdict = "✅ 支持（有样本）"; sup += d["n"]
        else:
            verdict = "❌ 默认不支持（无样本）"; drop += d["n"]
        print(f"{fam:24s}{d['n']:5d}  {verdict}")

    total = sup + drop + manual
    prod = sup + drop
    print(f"\n产品类文档 {prod} 篇：支持 {sup}（{sup/prod*100:.1f}%）· 放弃 {drop}（{drop/prod*100:.1f}%）")
    print(f"另有 {manual} 篇为索引/HDF 手册（不计入产品支持率）· 全部 md 共 {total} 篇")


if __name__ == "__main__":
    main()

"""仪器维度 × 样本可得性 → 最终支持范围与补样本建议。"""
import collections
import os
import re

DOC_ROOT = r"D:\desktop_dp\temp\nsmc-doc\md\数据格式说明"

# 仪器识别（按文档文件名）
INST = ["MERSI", "VIRR", "MWRI", "MWTS", "MWHS", "IRAS", "HIRAS", "ERM", "GNOSO",
        "PMR", "TOU", "SBUS", "SIM", "XEU", "WAAS", "LTO", "OMS", "GAS", "IPM",
        "AVHRR", "AGRI", "GIIRS", "CAPIX", "ACGS"]

# 当前是否已有真实样本
HAS_SAMPLE = {
    "AGRI": True, "MERSI": True, "GNOSO": True, "PMR": True, "AVHRR": True,
    "ACGS": True, "AWX": True, "FDI": True,
}
# 补充一个文件即可救回的文档数
SUGGEST = {
    "MWRI": "MWRI L1（升/降轨各 1 个，约 300–800 MB）",
    "MWTS": "MWTS L1（1 个，约 20–60 MB）",
    "MWHS": "MWHS L1（1 个，约 20–60 MB）",
    "VIRR": "VIRR L1（1 个，约 100–200 MB）",
    "IRAS": "IRAS L1（1 个，约 100–200 MB）",
    "GIIRS": "GIIRS L1（FY-4A，1 个，约 1–2 GB）",
    "CAPIX": "TanSat CAPIX 1B SCI（1 个，约 100–300 MB）",
    "HIRAS": "HIRAS L1（FY-3D，1 个，约 1 GB）",
}


def bucket(name):
    u = name.upper()
    for i in INST:
        if i in u:
            return i
    if "AWX" in u:
        return "AWX"
    if re.search(r"FDI|NOMChannel", u):
        return "FDI"
    if re.search(r"FY-?3A|FY-?3B|hdf50|hdf43|HDF_Format", u):
        return "FY-3A/B·HDF4"
    if re.search(r"eos_1b|gms_1b", u):
        return "EOS/GMS 1B"
    if re.search(r"^index|^_report", u):
        return "（索引）"
    return "（无仪器标识·多为 L2 产品）"


def main():
    agg = collections.Counter()
    for dp, dn, fn in os.walk(DOC_ROOT):
        for f in fn:
            if f.endswith(".md"):
                agg[bucket(f)] += 1

    sup = drop = other = 0
    rows = []
    for k, n in agg.most_common():
        if k in ("（索引）",):
            state = "—"; other += n
        elif HAS_SAMPLE.get(k):
            state = "✅ 有样本"; sup += n
        elif k == "（无仪器标识·多为 L2 产品）":
            state = "🟡 部分（依赖同卫星样本）"; sup += n
        else:
            state = "❌ 无样本"; drop += n
        rows.append((k, n, state))

    print("| 仪器 / 类别 | 文档数 | 样本状态 |")
    print("|---|---:|---|")
    for k, n, s in rows:
        print(f"| {k} | {n} | {s} |")
    tot = sup + drop
    print(f"\n有样本/部分 {sup} 篇（{sup/tot*100:.0f}%）· 无样本 {drop} 篇（{drop/tot*100:.0f}%）· 索引 {other} 篇")

    print("\n### 补样本建议（按性价比排序）")
    need = [(k, n) for k, n, s in rows if s == "❌ 无样本"]
    need.sort(key=lambda x: -x[1])
    acc = 0
    for k, n in need:
        acc += n
        tip = SUGGEST.get(k, "1 个可读样本")
        print(f"- **{k}**：{n} 篇文档 ← {tip}　（补后累计救回 {acc} 篇）")


if __name__ == "__main__":
    main()

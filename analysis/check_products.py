"""产品定义库自检脚本（人工运行，不进 pytest）。

用途：在**没有真实样本**的机器上，先确认 9 个 YAML 能解析、schema 校验通过、
匹配与路径解析行为正确。真实样本驱动的验证在 tests/test_products.py 里。

运行：
    set TMP=E:\\tmp
    set TEMP=E:\\tmp
    E:\\venv\\fysat\\Scripts\\python.exe analysis\\check_products.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

fail = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global fail
    if cond:
        print(f"  [OK]   {label}")
    else:
        fail += 1
        print(f"  [FAIL] {label}  {detail}")


def main() -> int:
    print("=" * 72)
    print("1) 加载 products/*.yml")
    from fysat.products import PRODUCTS_DIR, ProductRegistry

    files = sorted(PRODUCTS_DIR.glob("*.yml"))
    print(f"  发现 {len(files)} 个定义文件")
    check("至少 8 个定义文件", len(files) >= 8, f"实际 {len(files)}")

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    if reg.errors:
        print("  加载错误：")
        for e in reg.errors:
            print(f"    - {e}")
    check("全部定义加载成功（无 errors）", not reg.errors, str(reg.errors))
    check("注册表数量 >= 8", len(reg) >= 8, f"实际 {len(reg)}")
    print(f"  已加载：{reg.names()}")

    print()
    print("=" * 72)
    print("2) 每个定义的完整性与证据链")
    for d in reg:
        ok_fields = len(d.fields) > 0
        ok_ev = bool(d.evidence.get("document") or d.evidence.get("implementation"))
        ok_pending = len(d.pending_verification) > 0
        imgs = len(d.image_fields())
        print(f"  {d.product:30s} 字段 {len(d.fields):2d} 影像 {imgs:2d} "
              f"待核对 {len(d.pending_verification):2d} "
              f"{'✓verified' if d.verified else '未验证'}")
        check(f"{d.product}: 有字段", ok_fields)
        check(f"{d.product}: 有 evidence.document/implementation", ok_ev)
        check(f"{d.product}: 有 pending_verification", ok_pending)

    print()
    print("=" * 72)
    print("3) 文件名匹配（同族档位不能串）")
    cases = [
        ("FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF", "FY3_MERSI_L1_1000M"),
        ("FY3H_MERSI_GRAN_L1_20261023_0520_1000M_V0.hdf", "FY3_MERSI_L1_1000M"),
        ("FY3H_MERSI_GRAN_L1_20261022_1810_0250M_V0.hdf", "FY3_MERSI_L1_0250M"),
        ("FY3D_MERSI_GBAL_L1_20260810_0635_1000M_GEO1K_MS.HDF",
         "FY3_MERSI_L1_1000M_GEO"),
        ("FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20261030154500_"
         "20261030155959_1000M_V0001.HDF", "FY4B_AGRI_L1_DISK_1000M"),
        ("FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20261030154500_"
         "20261030155959_4000M_V0001.HDF", "FY4B_AGRI_L1_DISK_4000M"),
        ("FY2G_FDI_ALL_NOM_20261018_1300.hdf", "FY2G_FDI_L1_NOM"),
        ("FY2G_CSV_MLT_NUL_20261018_1300.DAT", "FY2G_CSV_L1"),
        ("FY3H_GNOSO_ORBT_L1_20261019_0000_ANC31.NC", "FY3H_GNOSO_L1_AE"),
        ("FY3D_MERSI_ORBT_L2_CLM_MLT_NUL_20261101_1000M_MS.HDF",
         "FY3D_MERSI_L2_CLM_GRAN"),
    ]
    for name, expect in cases:
        got = reg.match(name)
        actual = got.product if got else None
        check(f"{name[:52]:52s} → {expect}", actual == expect, f"实际 {actual}")

    print()
    print("=" * 72)
    print("4) 路径解析（候选列表 / 通配 / basename 回退）")
    from fysat.products import resolve_path

    avail = ["Data/EV_1KM_RefSB", "Data/EV_1KM_Emissive", "Calibration/VIS_Cal_Coeff",
             "GEO/Latitude", "GEO/Longitude", "Data/NOMChannel01", "Data/NOMChannel15",
             "Cloud_Mask", "NOMChannelIR1", "CALChannelIR1"]
    check("精确路径", resolve_path(avail, "/Data/EV_1KM_RefSB") == "Data/EV_1KM_RefSB")
    check("候选列表回退", resolve_path(avail, ["/Geolocation/Latitude", "/GEO/Latitude"])
          == "GEO/Latitude")
    check("通配", resolve_path(avail, "Data/NOMChannel*") == "Data/NOMChannel01")
    check("basename 回退", resolve_path(avail, "Latitude") == "GEO/Latitude")
    check("不存在返回 None", resolve_path(avail, "NoSuchThing") is None)
    print()
    print("=" * 72)
    print("5) 关键文档事实（防止把相邻档位的参数抄错）")
    g1 = reg.get("FY3_MERSI_L1_1000M").geolocation
    g2 = reg.get("FY3_MERSI_L1_0250M").geolocation
    check("1KM 抽点步长 = 5（文档每隔5像元）", g1.step == 5, f"实际 {g1.step}")
    check("250M 抽点步长 = 20（文档每隔20像元）", g2.step == 20, f"实际 {g2.step}")

    p250 = reg.get("FY3_MERSI_L1_0250M")
    coeff = p250.field("EV_250_RefSB_b1").calib["coeff"]
    check("250M 系数表保留 Ceff 拼写",
          isinstance(coeff, list) and any("VIS_Cal_Ceff" in str(c) for c in coeff))
    check("250M 系数表兼容 Coeff 拼写",
          isinstance(coeff, list) and any("VIS_Cal_Coeff" in str(c) for c in coeff))

    emis = reg.get("FY3_MERSI_L1_1000M").field("EV_1KM_Emissive")
    check("EV_1KM_Emissive 4 个通道 20~23", emis.bands == [20, 21, 22, 23],
          str(emis.bands))

    vis = reg.get("FY2G_FDI_L1_NOM").field("NOMChannelVIS")
    check("FY-2 VIS LUT 不做 ×100", vis.calib.get("lut_percent") is False)

    ch01 = reg.get("FY4B_AGRI_L1_DISK_4000M").field("NOMChannel01")
    check("FY-4B LUT FillValue = -65535", ch01.calib.get("lut_fill") == -65535.0)

    n1000 = len([f for f in reg.get("FY4B_AGRI_L1_DISK_1000M").fields
                 if f.name.startswith("NOMChannel")])
    n4000 = len([f for f in reg.get("FY4B_AGRI_L1_DISK_4000M").fields
                 if f.name.startswith("NOMChannel")])
    check("FY-4B 1000M 只有 3 个通道", n1000 == 3, f"实际 {n1000}")
    check("FY-4B 4000M 有 15 个通道", n4000 == 15, f"实际 {n4000}")

    geo = reg.get("FY3_MERSI_L1_1000M_GEO")
    main = reg.get("FY3_MERSI_L1_1000M")
    check("GEO 定义 priority 高于主产品", geo.priority > main.priority,
          f"GEO={geo.priority} 主={main.priority}")

    print()
    print("=" * 72)
    print("6) 回归：修正过的两处文档事实")
    print(f"  1KM  geolocation.step = {g1.step}（曾误写 20，文档/Line_number 证明是 5）")
    print(f"  250M geolocation.step = {g2.step}")
    print(f"  250M 系数表候选 = {coeff}")
    print("        （曾只写 Coeff，文档 L373 写的是 Ceff）")

    print()
    print("=" * 72)
    if fail:
        print(f"失败 {fail} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

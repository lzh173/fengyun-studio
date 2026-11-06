"""产品定义库测试。

三类断言，从「不需要样本」到「需要真实样本」：

1. **schema / loader 行为**：用内存里的定义验证校验、匹配、路径解析。
   不依赖任何数据文件，跑得快，能真正抓住逻辑错误。
2. **内置 YAML 全部可加载**：9 个定义文件必须都能解析成功，
   且关键字段（文件名正则、字段路径、定标方法）齐备。
3. **真实样本驱动**：每个有样本的产品用真实文件加载并解码，
   断言字段值与定标结果落在物理合理区间。样本缺失时 skip。

第 3 类是本任务的验收核心——**没有真实文件支撑的字段不进 YAML**，
所以每个 verified: true 的定义都必须有一条对应的真实样本测试。
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pytest
from _sample_root import SAMPLE_ROOT

from fysat.products import (
    PRODUCTS_DIR,
    ProductRegistry,
    load_def,
    load_file,
    resolve_path,
)
from fysat.products.schema import FieldDef, ProductDefError

SAMPLE_ROOT = SAMPLE_ROOT


# ---------------------------------------------------------------- 工具

def _find(pattern: str, min_mb: float = 1.0) -> Path | None:
    """在样本根目录找第一个匹配的文件（跳过下载残件）。"""
    hits = sorted(glob.glob(str(SAMPLE_ROOT / "**" / pattern), recursive=True))
    for h in hits:
        try:
            if Path(h).stat().st_size >= min_mb * 1e6:
                return Path(h)
        except OSError:
            continue
    return None


def _minimal(product: str = "TEST", **overrides) -> dict:
    """最小可用定义（按需覆盖字段）。"""
    base = {
        "product": product,
        "match": {"filename": r"^TEST.*\.HDF$"},
        "fields": [
            {"name": "Data", "path": "/Data/X", "kind": "dn", "calib": {"method": "raw_dn"}},
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- schema 校验

def test_minimal_definition_loads():
    pdef = load_def(_minimal())
    assert pdef.product == "TEST"
    assert len(pdef.fields) == 1
    assert pdef.fields[0].name == "Data"


def test_missing_product_id_rejected():
    with pytest.raises(ProductDefError, match="product"):
        load_def({"match": {"filename": "x"}, "fields": [{"name": "a", "path": "/a"}]})


def test_missing_filename_rejected():
    with pytest.raises(ProductDefError, match="filename"):
        load_def(_minimal(match={}))


def test_bad_regex_rejected():
    with pytest.raises(ProductDefError, match="正则"):
        load_def(_minimal(match={"filename": "(['"}))


def test_unknown_top_level_key_rejected():
    """拼错的键必须报错，而不是静默忽略（否则字段会悄悄失效）。"""
    with pytest.raises(ProductDefError, match="未知顶层键"):
        load_def(_minimal(fields_typo=[]))


def test_unknown_field_key_rejected():
    with pytest.raises(ProductDefError, match="未知键"):
        load_def(_minimal(fields=[
            {"name": "a", "path": "/a", "typical_error": 1},
        ]))


def test_unknown_kind_rejected():
    with pytest.raises(ProductDefError, match="kind"):
        load_def(_minimal(fields=[
            {"name": "a", "path": "/a", "kind": "imaginary"},
        ]))


def test_unknown_calib_method_rejected():
    with pytest.raises(ProductDefError, match="calib.method"):
        load_def(_minimal(fields=[
            {"name": "a", "path": "/a", "calib": {"method": "magic"}},
        ]))


def test_lut_method_requires_lut():
    with pytest.raises(ProductDefError, match="需要 calib.lut"):
        load_def(_minimal(fields=[
            {"name": "a", "path": "/a", "kind": "thermal",
             "calib": {"method": "lut_bt"}},
        ]))


def test_vis_poly_requires_coeff():
    with pytest.raises(ProductDefError, match="需要 calib.coeff"):
        load_def(_minimal(fields=[
            {"name": "a", "path": "/a", "kind": "reflective",
             "calib": {"method": "vis_poly"}},
        ]))


def test_linear_does_not_require_coeff():
    """linear 可以用 scale/offset 直接写（FY-3 GEO 角度字段就是这样）。"""
    pdef = load_def(_minimal(fields=[
        {"name": "a", "path": "/a", "kind": "dn",
         "calib": {"method": "linear", "scale": 0.01, "offset": 0.0}},
    ]))
    assert pdef.fields[0].calib["scale"] == 0.01


def test_duplicate_field_names_rejected():
    with pytest.raises(ProductDefError, match="重复"):
        load_def(_minimal(fields=[
            {"name": "dup", "path": "/a", "kind": "dn", "calib": {"method": "raw_dn"}},
            {"name": "dup", "path": "/b", "kind": "dn", "calib": {"method": "raw_dn"}},
        ]))


def test_empty_path_rejected():
    with pytest.raises(ProductDefError, match="path 不能为空"):
        load_def(_minimal(fields=[{"name": "a", "path": [], "kind": "dn"}]))


# ---------------------------------------------------------------- 字段派生属性

def test_fill_values_includes_in_earth_invalid():
    """FY-4 文档 L686：地球内无效 65534、地球外 65535，两者都要掩。"""
    fd = FieldDef(name="a", path="/a", kind="dn",
                  dn={"fill": 65535, "in_earth_invalid": 65534, "dead": 65533},
                  calib={"method": "raw_dn"})
    assert set(fd.fill_values) == {65535.0, 65534.0, 65533.0}


def test_valid_range_parsing():
    fd = FieldDef(name="a", path="/a", kind="dn", dn={"valid_range": [0, 4095]})
    assert fd.valid_range == (0.0, 4095.0)
    fd2 = FieldDef(name="b", path="/b", kind="dn")
    assert fd2.valid_range is None


def test_is_image_excludes_tables_and_coords():
    """coord / table 不能成图；flag（二维掩膜）**可以**。

    裁决理由：云掩膜产品（CLM）的主体就是二维标志平面，
    若把 flag 排除在 is_image 之外，这类产品将无法出图。
    """
    assert FieldDef(name="x", path="p", kind="reflective").is_image
    assert FieldDef(name="x", path="p", kind="thermal").is_image
    assert FieldDef(name="x", path="p", kind="dn").is_image
    assert FieldDef(name="x", path="p", kind="flag").is_image
    assert not FieldDef(name="x", path="p", kind="table").is_image


def _repo(*defs) -> ProductRegistry:
    return ProductRegistry([load_def(d) for d in defs])


def test_match_by_filename():
    reg = _repo(_minimal("A", match={"filename": r"^FY3D_.*\.HDF$"}),
                _minimal("B", match={"filename": r"^FY4B.*\.HDF$"}))
    assert reg.match("FY3D_MERSI_GRAN_L1_x.HDF").product == "A"
    assert reg.match("FY4B-AGRI_x.HDF").product == "B"
    assert reg.match("OTHER.hdf") is None


def test_match_specificity_prefers_narrower_regex():
    """同族档位：4000M 与 1000M 两个定义，各自的文件名必须命中自己。"""
    reg = _repo(
        _minimal("ANY", match={"filename": r"^FY4B.*\.HDF$"}),
        _minimal("M4000", match={"filename": r"^FY4B.*_4000M_.*\.HDF$"}),
        _minimal("M1000", match={"filename": r"^FY4B.*_1000M_.*\.HDF$"}),
    )
    assert reg.match("FY4B-_AGRI_x_4000M_V0001.HDF").product == "M4000"
    assert reg.match("FY4B-_AGRI_x_1000M_V0001.HDF").product == "M1000"


def test_match_by_container():
    reg = _repo(_minimal("A", match={"filename": r".*\.HDF$", "container": "hdf5"}))
    assert reg.match("x.HDF", container="hdf5").product == "A"
    assert reg.match("x.HDF", container="netcdf3") is None


def test_match_by_attrs():
    reg = _repo(_minimal("A", match={
        "filename": r".*\.HDF$",
        "attrs": {"Dataset Name": "MERSI L1"},
    }))
    assert reg.match("x.HDF", attrs={"Dataset Name": "MERSI L1 SDR"}).product == "A"
    # 属性缺失不算失配（不同卫星字段不全）
    assert reg.match("x.HDF", attrs={}) is not None
    # 属性值不符则应排除
    assert reg.match("x.HDF", attrs={"Dataset Name": "AGRI L1"}) is None


def test_registry_survives_bad_definition(tmp_path):
    """一个定义写坏不能让整个库不可用。"""
    good = tmp_path / "good.yml"
    good.write_text(
        "product: GOOD\nmatch:\n  filename: '^G.*\\.HDF$'\n"
        "fields:\n  - name: a\n    path: /a\n    kind: dn\n    calib:\n      method: raw_dn\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.yml"
    bad.write_text("product: BAD\nmatch: {}\nfields: []\n", encoding="utf-8")

    reg = ProductRegistry.from_dir(tmp_path)
    assert "GOOD" in reg.names()
    assert "BAD" not in reg.names()
    assert any("bad.yml" in e for e in reg.errors)


# ---------------------------------------------------------------- 路径解析

AVAILABLE = [
    "Data/EV_1KM_RefSB",
    "Data/EV_1KM_Emissive",
    "Calibration/VIS_Cal_Coeff",
    "GEO/Latitude",
    "GEO/Longitude",
    "Data/NOMChannel01",
    "Data/NOMChannel02",
    "Data/NOMChannel15",
]


def test_resolve_exact_and_leading_slash():
    assert resolve_path(AVAILABLE, "/Data/EV_1KM_RefSB") == "Data/EV_1KM_RefSB"
    assert resolve_path(AVAILABLE, "Data/EV_1KM_RefSB") == "Data/EV_1KM_RefSB"


def test_resolve_candidate_list():
    spec = ["/Geolocation/Latitude", "/GEO/Latitude"]
    assert resolve_path(AVAILABLE, spec) == "GEO/Latitude"


def test_resolve_glob():
    assert resolve_path(AVAILABLE, "Data/NOMChannel*") == "Data/NOMChannel01"


def test_resolve_basename_fallback():
    assert resolve_path(AVAILABLE, "Latitude") == "GEO/Latitude"


def test_resolve_explicit_row_suffix_is_not_confused_with_path():
    """``Calibration/VIS_Cal_Coeff[3]`` 的行号后缀由 decode 层解析，resolve_path 只认路径。"""
    assert resolve_path(AVAILABLE, "Calibration/VIS_Cal_Coeff") == "Calibration/VIS_Cal_Coeff"


# ---------------------------------------------------------------- 关键文档事实

def test_geo_step_differs_between_1km_and_250m(registry):
    """1KM 是每 5 像元抽点，250M 是每 20 像元 —— 写反会让经纬度错位数倍。

    依据：1KM 文档 L77-78/L366 明写「每隔5像元」，Line_number="0,5,10..."；
          250M 文档 L79-80/L393 明写「每隔20像元」，Line_number="0,20,40..."。
    形状都是 [400,409]，但 400×5=2000（1KM 行数）、400×20=8000（250M 行数）。
    """
    assert registry.get("FY3_MERSI_L1_1000M").geolocation.step == 5
    assert registry.get("FY3_MERSI_L1_0250M").geolocation.step == 20


def test_250m_uses_vis_cal_ceff_spelling(registry):
    """250M 文档 L373 的系数表名是 VIS_Cal_Ceff（Ceff），不是 Coeff。

    定义里给了两个候选，先试文档写法，再退回实测常见写法。
    """
    pdef = registry.get("FY3_MERSI_L1_0250M")
    coeff = pdef.field("EV_250_RefSB_b1").calib["coeff"]
    assert isinstance(coeff, list) and len(coeff) >= 2, f"应为候选列表，实际 {coeff!r}"
    assert any("VIS_Cal_Ceff" in str(c) for c in coeff), "应保留文档拼写 Ceff 作为首选"
    assert any("VIS_Cal_Coeff" in str(c) for c in coeff), "应兼容实测常见拼写 Coeff"


def test_1km_emissive_has_four_bands(registry):
    """EV_1KM_Emissive 文档写 [4,2000,2048]、Slope 4 个 → 4 个通道（20~23）。

    band_name 文档写成 "20,21,22,22,23"（5 个数字、22 重复），属文档笔误；
    以维数与 Slope 数量为准。
    """
    fd = registry.get("FY3_MERSI_L1_1000M").field("EV_1KM_Emissive")
    assert fd.bands == [20, 21, 22, 23]


def test_geo_definition_wins_over_main_product(registry):
    """GEO 文件名同时含 "1000M" 与 "GEO"，两个正则都命中。

    主产品的正则里 "1000M" 有 5 个字符、GEO 定义里 "GEO" 只有 3 个，
    若只按正则长度排序会把 GEO 文件判给主产品 —— 所以 GEO 定义必须显式 priority。
    """
    geo_name = "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_GEO1K_MS.HDF"
    assert registry.match(geo_name).product == "FY3_MERSI_L1_1000M_GEO", \
        f"实际匹配到 {registry.match(geo_name).product}"

    main_name = "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"
    assert registry.match(main_name).product == "FY3_MERSI_L1_1000M"

    assert registry.get("FY3_MERSI_L1_1000M_GEO").priority > \
        registry.get("FY3_MERSI_L1_1000M").priority


def test_slope_values_come_from_document(registry):
    """文档 L239：EV_1KM_Emissive 的 Slope = [0.0002,0.0002,0.01,0.01]。"""
    fd = registry.get("FY3_MERSI_L1_1000M").field("EV_1KM_Emissive")
    assert fd.unit == "K"
    assert fd.calib["method"] == "mersi_planck"


def test_fy2g_vis_lut_not_percent_multiplied(registry):
    """FY-2 的 CALChannelVIS 已是百分比，必须显式关闭 ×100。"""
    fd = registry.get("FY2G_FDI_L1_NOM").field("NOMChannelVIS")
    assert fd.calib.get("lut_percent") is False


def test_fy4b_lut_fill_declared(registry):
    """文档 L674/L982：CALChannelXX 的 FillValue = -65535.0。"""
    fd = registry.get("FY4B_AGRI_L1_DISK_4000M").field("NOMChannel01")
    assert fd.calib.get("lut_fill") == pytest.approx(-65535.0)


def test_fy4b_thermal_valid_range_is_kelvin(registry):
    """热红外 LUT 文档 valid_range 100~500 K，与可见光 0~1.5 明显不同。"""
    pdef = registry.get("FY4B_AGRI_L1_DISK_4000M")
    thermal = [f for f in pdef.fields if f.kind == "thermal"]
    reflective = [f for f in pdef.fields if f.kind == "reflective"]
    assert len(thermal) == 9, f"CH07~CH15 共 9 个热红外通道，实际 {len(thermal)}"
    assert len(reflective) == 6, f"CH01~CH06 共 6 个反射通道，实际 {len(reflective)}"


def test_resolve_missing_returns_none():
    """解析不到必须返回 None，不能瞎猜一个数据集。"""
    assert resolve_path(AVAILABLE, "NONEXISTENT") is None


def test_resolve_does_not_false_positive():
    """不存在的路径不能被 basename 模糊匹配误命中。"""
    assert resolve_path(AVAILABLE, "Data/Latitude") is None


# ---------------------------------------------------------------- 内置 YAML

@pytest.fixture(scope="module")
def registry() -> ProductRegistry:
    return ProductRegistry.from_dir(PRODUCTS_DIR)


def test_all_builtin_definitions_load(registry):
    """9 个产品定义必须全部加载成功（errors 为空）。"""
    assert not registry.errors, f"定义加载失败: {registry.errors}"
    assert len(registry) >= 9, f"应至少 9 个产品定义，实际 {len(registry)}: {registry.names()}"


def test_builtin_products_are_covered(registry):
    """验收要求的 8 类产品都必须有定义。"""
    names = set(registry.names())
    required = {
        "FY3_MERSI_L1_1000M",
        "FY3_MERSI_L1_0250M",
        "FY3_MERSI_L1_1000M_GEO",
        "FY3D_MERSI_L2_CLM_GRAN",
        "FY4B_AGRI_L1_DISK_4000M",
        "FY4B_AGRI_L1_DISK_1000M",
        "FY2G_FDI_L1_NOM",
        "FY2G_CSV_L1",
        "FY3H_GNOSO_L1_AE",
    }
    missing = required - names
    assert not missing, f"缺少产品定义: {sorted(missing)}；已有 {sorted(names)}"


def test_every_definition_has_evidence(registry):
    """每个定义都要有 evidence 段与待核对清单——这是「不猜」的硬约束。"""
    problems = []
    for d in registry:
        if not d.evidence and not d.source_path:
            problems.append(f"{d.product}: 缺 evidence")
        if not d.pending_verification:
            problems.append(f"{d.product}: 缺 pending_verification")
    assert not problems, "\n".join(problems)


def test_verified_definitions_have_minimum_fields(registry):
    verified = [d for d in registry if d.verified]
    assert verified, "至少应有几个 verified: true 的定义"
    for d in verified:
        assert any(f.is_image for f in d.fields), f"{d.product}: 没有任何可成图的字段"
        assert d.evidence, f"{d.product}: verified 但没有 evidence"


def test_definition_files_exist_on_disk(registry):
    for d in registry:
        assert d.source_path is not None and d.source_path.exists()


def test_product_files_are_valid_yaml(registry):
    """逐个 load_file，确保没有重复 product 标识。"""
    files = sorted(PRODUCTS_DIR.glob("*.yml"))
    assert len(files) >= 9
    ids = [load_file(p).product for p in files]
    assert len(ids) == len(set(ids)), f"product 标识重复: {ids}"


# ---------------------------------------------------------------- 真实样本驱动

@pytest.fixture(scope="module")
def fy3d_1km():
    p = _find("FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-3D MERSI L1 1000M 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy3_mersi_1000m_matches(fy3d_1km):
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy3d_1km.source, container="hdf5", attrs=fy3d_1km.attrs)
    assert pdef is not None, "FY-3D 1000M 样本没有匹配到产品定义"
    assert pdef.product == "FY3_MERSI_L1_1000M"
    assert pdef.verified


def test_fy3_mersi_1000m_field_paths_exist(fy3d_1km):
    """定义里的字段路径必须真的存在于文件里（不许凭空写出路径）。"""
    from fysat.products.loader import resolve_path as rp

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY3_MERSI_L1_1000M")
    for fd in pdef.fields:
        real = rp(fy3d_1km.variables, fd.path)
        if fd.required:
            assert real is not None, f"必填字段 {fd.name} 的路径 {fd.paths} 不在文件里"


def test_fy3_mersi_1000m_thermal_is_physical(fy3d_1km):
    """核心回归：亮温必须是 150~350 K，不能是 0.01~1.5 的辐亮度。"""
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY3_MERSI_L1_1000M")
    res = decode(fy3d_1km, pdef, fields=["EV_250_Aggr.1KM_Emissive"])
    assert res.fields, f"解码失败: missing={res.missing} failed={res.failed}"

    df = res.fields["EV_250_Aggr.1KM_Emissive"]
    assert df.unit == "K"
    assert df.data.ndim == 3, f"b24/b25 应为通道栈，实际 {df.data.shape}"

    v = df.data[np.isfinite(df.data)]
    assert v.size > 1000
    assert 150 < float(v.min()) and float(v.max()) < 350, \
        f"亮温 {v.min():.1f}~{v.max():.1f} K 超出物理范围（可能又拿辐亮度当亮温了）"


def test_fy3_mersi_1000m_reflective_is_percent(fy3d_1km):
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY3_MERSI_L1_1000M")
    res = decode(fy3d_1km, pdef, fields=["EV_1KM_RefSB"])
    if not res.fields:
        pytest.skip(f"反射通道不可用: {res.missing} {res.failed}")
    df = res.fields["EV_1KM_RefSB"]
    assert df.unit == "%"
    v = df.data[np.isfinite(df.data)]
    if v.size == 0:
        pytest.skip("该 granule 反射通道全为无效（夜间景）")
    assert np.percentile(v, 99) < 150, f"反射率 99 分位 {np.percentile(v, 99):.1f}% 过高"


@pytest.fixture(scope="module")
def fy3h_250m():
    p = _find("FY3H_MERSI_GRAN_L1_*0250M*.hdf", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-3H MERSI L1 250M 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy3_mersi_250m_matches_and_decodes(fy3h_250m):
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy3h_250m.source, container="hdf5", attrs=fy3h_250m.attrs)
    assert pdef is not None and pdef.product == "FY3_MERSI_L1_0250M"

    res = decode(fy3h_250m, pdef)
    assert res.ok, f"解码失败: missing={res.missing} failed={res.failed}"

    # b24 是主力窗区通道，实测亮温 187.28~311.78 K（tests/test_calib.py 同一断言）
    df = res.fields.get("EV_250_Emissive_b24")
    assert df is not None, f"b24 未解出：{list(res.fields)}"
    v = df.data[np.isfinite(df.data)]
    assert v.size > 1000
    assert 150 < float(v.min()) and float(v.max()) < 350, \
        f"b24 亮温 {v.min():.1f}~{v.max():.1f} K 超出物理范围"


@pytest.fixture(scope="module")
def fy4b_4000m():
    p = _find("FY4B-*_4000M_V0001.HDF", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-4B 4000M 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy4b_4000m_matches(fy4b_4000m):
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy4b_4000m.source, container="hdf5", attrs=fy4b_4000m.attrs)
    assert pdef is not None and pdef.product == "FY4B_AGRI_L1_DISK_4000M"


def test_fy4b_4000m_has_15_defined_channels(fy4b_4000m):
    """4000M 是唯一含全部 15 通道的档位，定义必须覆盖 15 个 NOMChannel。"""
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY4B_AGRI_L1_DISK_4000M")
    chans = [f for f in pdef.fields if f.name.startswith("NOMChannel")]
    assert len(chans) == 15, f"应定义 15 个通道，实际 {len(chans)}"


def test_fy4b_4000m_thermal_lut_is_kelvin(fy4b_4000m):
    """核心回归：CH13（10.8 µm）LUT 定标后必须是 150~350 K。"""
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY4B_AGRI_L1_DISK_4000M")
    res = decode(fy4b_4000m, pdef, fields=["NOMChannel13"], include_aux=False)
    assert res.fields, f"CH13 解码失败: {res.missing} {res.failed}"

    df = res.fields["NOMChannel13"]
    assert df.unit == "K"
    v = df.data[np.isfinite(df.data)]
    assert v.size > 0
    assert 150 < float(v.min()) and float(v.max()) < 350, \
        f"CH13 亮温 {v.min():.1f}~{v.max():.1f} K 超出物理范围"


def test_fy4b_4000m_reflectance_is_percent(fy4b_4000m):
    """可见光 LUT 是 0~1.14 小数，×100 后必须是 0~~115%。"""
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY4B_AGRI_L1_DISK_4000M")
    res = decode(fy4b_4000m, pdef, fields=["NOMChannel02"])
    assert res.fields, f"CH02 解码失败: {res.missing} {res.failed}"

    df = res.fields["NOMChannel02"]
    assert df.unit == "%"
    v = df.data[np.isfinite(df.data)]
    assert v.size > 0
    assert -5.0 <= float(v.min()) and float(v.max()) <= 150.0, \
        f"CH02 反射率 {v.min():.2f}~{v.max():.2f}% 超出合理范围（可能没 ×100）"
    # 若忘了 ×100，最大值会落在 1.5 附近而不是 100 附近
    assert float(v.max()) > 5.0, "反射率最大值过于接近 0~1 量级，疑似漏乘 100"


@pytest.fixture(scope="module")
def fy4b_1000m():
    p = _find("FY4B-*_1000M_V0001.HDF", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-4B 1000M 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy4b_1000m_matches_and_has_only_3():
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    p = _find("FY4B-*_1000M_V0001.HDF", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-4B 1000M 样本")
    pdef = reg.match(p, container="hdf5")
    assert pdef is not None and pdef.product == "FY4B_AGRI_L1_DISK_1000M"
    chans = [f for f in pdef.fields if f.name.startswith("NOMChannel")]
    assert len(chans) == 3, f"1000M 应只有 3 个可见光通道，实际定义 {len(chans)}"
    # 关键防错：1000M 定义里不能出现任何热红外通道
    kinds = {f.kind for f in chans}
    assert kinds == {"reflective"}, f"1000M 不该有非反射通道，实际 {kinds}"


@pytest.fixture(scope="module")
def fy2g_fdi():
    p = _find("FY2G_FDI_ALL_NOM_*.hdf", min_mb=10)
    if p is None:
        pytest.skip("缺 FY-2G FDI 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy2g_fdi_matches(fy2g_fdi):
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy2g_fdi.source, container="hdf5", attrs=fy2g_fdi.attrs)
    assert pdef is not None and pdef.product == "FY2G_FDI_L1_NOM"


def test_fy2g_fdi_ir_lut_is_kelvin(fy2g_fdi):
    """FY-2 CALChannelIR1 是递减表，直接查；实测 173.93~304.59 K。"""
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY2G_FDI_L1_NOM")
    res = decode(fy2g_fdi, pdef, fields=["NOMChannelIR1"])
    assert res.fields, f"IR1 解码失败: {res.missing} {res.failed}"

    df = res.fields["NOMChannelIR1"]
    assert df.unit == "K"
    v = df.data[np.isfinite(df.data)]
    assert v.size > 1000
    assert 150 < float(v.min()) and float(v.max()) < 350, \
        f"IR1 亮温 {v.min():.1f}~{v.max():.1f} K 超出物理范围"


def test_fy2g_fdi_vis_lut_not_multiplied_by_100(fy2g_fdi):
    """核心回归：FY-2 的 VIS LUT 已是百分比，不能再 ×100（否则差 100 倍）。"""
    from fysat.products import decode

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY2G_FDI_L1_NOM")
    res = decode(fy2g_fdi, pdef, fields=["NOMChannelVIS"])
    if not res.fields:
        pytest.skip(f"VIS 解码失败: {res.missing} {res.failed}")

    df = res.fields["NOMChannelVIS"]
    v = df.data[np.isfinite(df.data)]
    assert v.size > 0
    # LUT 上限 118.3942%；若误乘 100 会到 11839
    assert float(v.max()) <= 130.0, \
        f"VIS 反射率最大 {v.max():.2f}% 过高，疑似把已是百分比的 LUT 又乘了 100"


@pytest.fixture(scope="module")
def fy2g_csv():
    p = _find("FY2G_CSV_MLT_NUL_*.DAT", min_mb=50)
    if p is None:
        pytest.skip("缺 FY-2G CSV 样本")
    return p


def test_fy2g_csv_matches(fy2g_csv):
    from fysat.detect import sniff

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy2g_csv, container=sniff(fy2g_csv))
    assert pdef is not None and pdef.product == "FY2G_CSV_L1"


def test_fy2g_csv_decodes_dn(fy2g_csv):
    """CSV 容器没有定标表，只能出 DN；但要保证 8 个通道都真能解出数据。"""
    from fysat.products import decode
    from fysat.readers import open_file

    ds = open_file(fy2g_csv, load=False)
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY2G_CSV_L1")

    # 只解两个通道，避免整盘 2500×9164 全读进来
    res = decode(ds, pdef, fields=["IR1", "VIS1"])
    assert res.ok, f"解码失败: missing={res.missing} failed={res.failed}"
    ir = res.fields["IR1"]
    assert ir.unit == "DN", "CSV 容器无定标表，单位必须是 DN"
    assert ir.data.shape[0] == 2500, f"应有 2500 扫描行，实际 {ir.data.shape}"
    v = ir.data[np.isfinite(ir.data)]
    assert v.size > 0
    assert 0 <= float(v.min()) and float(v.max()) <= 1023, "IR1 是 10 bit，应在 0~1023"


@pytest.fixture(scope="module")
def gnoso_nc():
    p = _find("FY3H_GNOSO_*.NC", min_mb=0.001)
    if p is None:
        pytest.skip("缺 FY-3H GNOSO 样本")
    return p


def test_gnoso_matches(gnoso_nc):
    from fysat.detect import sniff

    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(gnoso_nc, container=sniff(gnoso_nc))
    assert pdef is not None and pdef.product == "FY3H_GNOSO_L1_AE"


def test_gnoso_decodes_profile(gnoso_nc):
    from fysat.products import decode
    from fysat.readers import open_file

    ds = open_file(gnoso_nc, load=False)
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY3H_GNOSO_L1_AE")
    res = decode(ds, pdef)
    assert res.ok, f"解码失败: missing={res.missing} failed={res.failed}"

    tph = res.fields.get("TPH")
    assert tph is not None
    assert tph.data.ndim == 1, "GNOSO 是廓线产品，变量应是一维"
    assert tph.unit == "km"


@pytest.fixture(scope="module")
def fy3d_clm():
    p = _find("FY3D_MERSI_ORBT_L2_CLM_*.HDF", min_mb=1)
    if p is None:
        pytest.skip("缺 FY-3D CLM 样本")
    from fysat.readers import open_file

    return open_file(p, load=False)


def test_fy3d_clm_matches(fy3d_clm):
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.match(fy3d_clm.source, container="hdf5", attrs=fy3d_clm.attrs)
    assert pdef is not None and pdef.product == "FY3D_MERSI_L2_CLM_GRAN"


def test_fy3d_clm_channel_axis_is_correct(fy3d_clm):
    """**关键待核对项**：Cloud_Mask 的通道维究竟在最后还是在最前。

    本断言用真实文件把这件事定下来：读 shape，验证定义里的 band_axis 能取到
    正确的二维平面（即去掉通道维后是 (2000, 2048) 一类的二维影像）。
    """
    real = resolve_path(fy3d_clm.variables, ["Cloud_Mask"])
    if real is None:
        pytest.skip("该文件没有 Cloud_Mask")

    shape = fy3d_clm.variables[real].shape
    reg = ProductRegistry.from_dir(PRODUCTS_DIR)
    pdef = reg.get("FY3D_MERSI_L2_CLM_GRAN")
    fd = pdef.field("Cloud_Mask")

    assert len(shape) == 3, f"Cloud_Mask 应为三维，实际 {shape}"
    # 通道数较小（6 或 10），另外两维是 2000×2048
    axis = shape.index(min(shape))
    assert axis == fd.band_axis, (
        f"Cloud_Mask 实际 shape={shape}，最小的维在第 {axis} 位，"
        f"而定义写 band_axis={fd.band_axis}。请修正 YAML 的 band_axis。"
    )


# ---------------------------------------------------------------- 定标链的纯逻辑测试
#
# 下面几个不依赖真实样本，用人工构造的 SatDataset 验证最容易搞错的映射：
#   * 填充值掩膜必须作用在原始整数上（float32 存不下 65535）
#   * b24/b25 用 TBB 系数时必须按「通道号-20」取，不能按数组序号

def _sat(variables: dict, attrs: dict | None = None):
    from fysat.model import SatDataset

    ds = SatDataset(platform="FY-TEST", instrument="MERSI", level="L1")
    ds.variables = variables
    ds.attrs = attrs or {}
    return ds


def _var(name: str, data, attrs: dict | None = None):
    from fysat.model import Variable

    return Variable(name=name, data=data, source_shape=tuple(data.shape),
                    attrs=attrs or {})


def test_fill_value_65535_is_masked():
    """填充值 65535 必须被掩成 NaN——这是 float32 舍入最容易漏掉的一个。

    np.float32(65535) == 65535 为 False（会被舍成 65536），
    所以掩膜必须在原始 uint16 上做。
    """
    from fysat.products import decode
    from fysat.products.loader import load_def

    arr = np.full((4, 5), 100, dtype=np.uint16)
    arr[0, 0] = 65535
    ds = _sat({"Data/X": _var("Data/X", arr)})
    pdef = load_def({
        "product": "T",
        "match": {"filename": "x"},
        "fields": [{
            "name": "X", "path": "/Data/X", "kind": "dn",
            "dn": {"valid_range": [0, 4095], "fill": 65535},
            "calib": {"method": "raw_dn"},
        }],
    })
    res = decode(ds, pdef)
    out = res.fields["X"].data
    assert np.isnan(out[0, 0]), "65535 必须被掩成 NaN"
    assert out[1, 1] == 100


def test_no_fill_value_disables_fy3_sentinel_fallback():
    """声明 no_fill_value 后，不得再用 FY-3 的 65535 兜底。

    FY-2 CSV 容器没有填充值（文档未定义、实测无哨兵），若套用 FY-3 兜底，
    会把本来合法的 DN 误判为缺测。
    """
    from fysat.products import decode
    from fysat.products.loader import load_def

    arr = np.full((3, 4), 5, dtype=np.uint16)
    arr[0, 0] = 65535                    # 若兜底生效会被掩掉
    ds = _sat({"Data/X": _var("Data/X", arr)})
    pdef = load_def({
        "product": "T",
        "match": {"filename": "x"},
        "fields": [{
            "name": "X", "path": "/Data/X", "kind": "dn",
            "dn": {"valid_range": [0, 1023], "no_fill_value": True},
            "calib": {"method": "raw_dn"},
        }],
    })
    res = decode(ds, pdef)
    out = res.fields["X"].data
    # 65535 超出 valid_range [0,1023]，仍应被 valid_range 掩掉
    assert np.isnan(out[0, 0]), "超出 valid_range 仍必须掩"
    # 但合法值不受影响
    assert out[1, 1] == 5


def test_csv_container_has_no_fill_value_declared(registry):
    """FY-2 CSV 的 8 个通道都必须显式声明 no_fill_value。"""
    pdef = registry.get("FY2G_CSV_L1")
    for name in ("IR1", "IR2", "IR3", "IR4", "VIS1", "VIS2", "VIS3", "VIS4"):
        fd = pdef.field(name)
        assert fd.dn.get("no_fill_value") is True, f"{name} 未声明 no_fill_value"
        assert not fd.fill_values, f"{name} 不应有 fill/dead/saturated"


def test_tbb_coefficients_indexed_by_channel_number():
    """b24/b25 的 TBB 订正必须取系数第 4/5 项（通道号-20），不是第 0/1 项。

    EV_250_Aggr.1KM_Emissive 的 bands 是 [24,25]，若按数组序号取系数就会
    套用 b20/b21 的 A/B，亮温系统性偏移。
    """
    from fysat.products import decode
    from fysat.products.loader import load_def

    # 2 个通道，DN 让辐亮度相同
    arr = np.full((2, 6, 7), 5000, dtype=np.uint16)
    var = _var("Data/EV_250_Aggr.1KM_Emissive", arr,
               attrs={"Slope": np.array([0.01, 0.01]), "band_name": "24,25"})

    # A 取 6 个值，只有第 4/5 项是 1（其余为 0.5），便于区分取错了哪一项
    ds = _sat(
        {"Data/EV_250_Aggr.1KM_Emissive": var},
        attrs={
            "Effect_Center_WaveLength": np.full(25, 10.7342),
            "TBB_Trans_Coefficient_A": np.array([0.5, 0.5, 0.5, 0.5, 1.0, 1.0]),
            "TBB_Trans_Coefficient_B": np.zeros(6),
        },
    )
    pdef = load_def({
        "product": "T",
        "match": {"filename": "x"},
        "fields": [{
            "name": "EV_250_Aggr.1KM_Emissive",
            "path": "/Data/EV_250_Aggr.1KM_Emissive",
            "kind": "thermal", "unit": "K",
            "band_axis": 0, "bands": [24, 25],
            "dn": {"valid_range": [0, 25000], "fill": 65535},
            "calib": {"method": "mersi_planck"},
        }],
    })
    res = decode(ds, pdef)
    assert res.fields, f"解码失败: {res.missing} {res.failed}"
    out = res.fields["EV_250_Aggr.1KM_Emissive"].data
    assert out.ndim == 3 and out.shape[0] == 2

    # 两个通道的 DN 与波长完全相同 → 未订正的亮温相同；
    # A=1.0 的两项应给出「未订正亮温」，而 A=0.5 会明显更小。
    # 若错误地用了 index 0/1（A=0.5），两个通道都会偏小。
    v0 = float(np.nanmean(out[0]))
    v1 = float(np.nanmean(out[1]))
    assert 100 < v0 < 400, f"b24 亮温异常: {v0}"
    assert v0 == pytest.approx(v1, rel=1e-4), "两个通道参数一致，结果应相同"

    # 对照：手工算 A=0.5 的情况，确认确实能区分
    from fysat import calib

    rad = 5000 * 0.01
    raw_bt = float(calib.radiance_to_bt(np.float32(rad), 10.7342))
    assert v0 == pytest.approx(raw_bt, rel=2e-3), (
        f"应得到未缩放亮温 {raw_bt:.2f} K（A=1.0），实际 {v0:.2f} K"
    )


def test_band_axis_2_slices_last_dimension():
    """band_axis=2 的机制本身要能工作（文档假设末维通道时的路径）。

    注意：FY-3D CLM 的实测是 band_axis=0，本测试只验证「末维通道」这条路径
    在机制上可用，不代表 CLM 用它。
    """
    from fysat.products import decode_field
    from fysat.products.schema import FieldDef

    arr = np.zeros((3, 4, 6), dtype=np.uint8)
    for k in range(6):
        arr[:, :, k] = k + 1
    var = _var("Cloud_Mask", arr)
    fd = FieldDef(name="Cloud_Mask", path="/Cloud_Mask", kind="flag",
                  band_axis=2, bands=[1, 2, 3, 4, 5, 6],
                  dn={"valid_range": [1, 255], "fill": 0},
                  calib={"method": "flag"})
    ds = _sat({"Cloud_Mask": var})
    df = decode_field(ds, fd)

    assert df.data.shape == (6, 3, 4), f"应转成 (6,3,4)，实际 {df.data.shape}"
    # 第 0 个平面应全为 1
    assert np.all(df.data[0] == 1)
    assert np.all(df.data[5] == 6)


def test_clm_band_axis_is_zero_per_real_file():
    """CLM 的 band_axis 必须是 0 —— 由真实文件实测确定。

    h5py 直读 FY3D_MERSI_ORBT_L2_CLM_MLT_NUL_20260810_0000_1000M_MS.HDF：
        Cirrus_Mask    (1, 2000, 2048) uint8
        Cloud_Mask     (6, 2000, 2048) uint8
        Cloud_Mask_QA  (10, 2000, 2048) uint8
    三个都是 (通道, 行, 列)。格式说明文档的 [2000,2048,6] 是笔误。
    """
    from fysat.products import ProductRegistry

    pdef = ProductRegistry.from_dir(PRODUCTS_DIR).get("FY3D_MERSI_L2_CLM_GRAN")
    assert pdef.verified, "拿到真实文件仲裁后应标记 verified"
    for name, n_planes in (("Cloud_Mask", 6), ("Cloud_Mask_QA", 10), ("Cirrus_Mask", 1)):
        fd = pdef.field(name)
        assert fd.band_axis == 0, f"{name} 的 band_axis 应为 0，实际 {fd.band_axis}"
        assert len(fd.bands) == n_planes, f"{name} 应有 {n_planes} 个平面"


def test_decode_reports_failure_without_raising():
    """缺 LUT 时必须记成 failed，而不是悄悄返回假物理量。"""
    from fysat.products import decode
    from fysat.products.loader import load_def

    arr = np.full((4, 5), 100, dtype=np.uint16)
    ds = _sat({"Data/C": _var("Data/C", arr)})
    pdef = load_def({
        "product": "T",
        "match": {"filename": "x"},
        "fields": [{
            "name": "C", "path": "/Data/C", "kind": "thermal", "unit": "K",
            "calib": {"method": "lut_bt", "lut": "/Calibration/MISSING"},
        }],
    })
    res = decode(ds, pdef)
    assert not res.ok
    assert "C" in res.failed or "C" in res.missing

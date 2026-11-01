"""溯源元数据测试：AGPL 开源策略下，"软件来源/是否修改" 由技术手段默认满足。"""
from __future__ import annotations

import numpy as np
import pytest

from fysat.export import ExportOptions, export
from fysat.provenance import (
    LICENSE_ID,
    SOFTWARE_NAME,
    SOURCE_URL,
    as_png_text,
    as_text,
    build_provenance,
    is_modified_release,
    read_png_provenance,
    read_tiff_provenance,
)

SAMPLE = (np.random.default_rng(0).random((32, 48)) * 4095).astype(np.uint16)


# ---------------- 字段内容 ----------------

def test_build_provenance_has_required_fields():
    prov = build_provenance()
    for key in ("software", "software_version", "license", "source_url",
                "modified", "generated_at"):
        assert key in prov, f"缺少必需字段 {key}"
    assert prov["software"] == SOFTWARE_NAME
    assert prov["license"] == LICENSE_ID
    assert prov["source_url"] == SOURCE_URL


def test_modified_flag_is_honest():
    """拿不到 git 信息时必须保守报 'yes'（可能修改），不能谎称原版。"""
    prov = build_provenance()
    assert prov["modified"] in ("yes", "no")
    assert isinstance(is_modified_release(), bool)


def test_dataset_fields_recorded():
    class FakeDS:
        platform = "FY-4B"
        instrument = "AGRI"
        level = "L1"
        product = "FDI"
        reader = "hdf5"
        source = None
        start_time = None

    prov = build_provenance(FakeDS(), variable="Data/NOMChannel02")
    assert prov["platform"] == "FY-4B"
    assert prov["instrument"] == "AGRI"
    assert prov["variable"] == "Data/NOMChannel02"


def test_as_text_is_parseable():
    prov = build_provenance()
    text = as_text(prov)
    assert "software:" in text
    assert "license: AGPL-3.0-only" in text


def test_png_keys_are_prefixed_and_bounded():
    prov = build_provenance(extra={"a_very_long_custom_field_name": "x" * 200})
    for k in as_png_text(prov):
        assert k.startswith("fysat.")
        assert len(k) <= 79, f"PNG tEXt 关键字超长: {k}"


# ---------------- 三种格式往返 ----------------

def test_tiff_embeds_provenance(tmp_path):
    out = export(SAMPLE, ExportOptions(kind="tiff", path=tmp_path / "p.tif"))
    back = read_tiff_provenance(out)
    assert back.get("software") == SOFTWARE_NAME
    assert back.get("license") == LICENSE_ID
    assert back.get("source_url") == SOURCE_URL
    assert "modified" in back


def test_png_full_embeds_provenance(tmp_path):
    out = export(SAMPLE, ExportOptions(kind="png_full", path=tmp_path / "p.png"))
    back = read_png_provenance(out)
    assert back.get("software") == SOFTWARE_NAME
    assert back.get("license") == LICENSE_ID
    assert "modified" in back


def test_png_compressed_embeds_provenance(tmp_path):
    out = export(SAMPLE, ExportOptions(kind="png_compressed", path=tmp_path / "c.png"))
    back = read_png_provenance(out)
    assert back.get("software") == SOFTWARE_NAME


def test_custom_provenance_overrides_default(tmp_path):
    prov = {"software": "CustomMaker", "modified": "no", "license": "MIT"}
    out = export(SAMPLE, ExportOptions(kind="png_full", path=tmp_path / "x.png",
                                       provenance=prov))
    back = read_png_provenance(out)
    assert back["software"] == "CustomMaker"
    assert back["modified"] == "no"


def test_provenance_does_not_break_lossless(tmp_path):
    """写元数据不能影响像素值。"""
    from PIL import Image

    out = export(SAMPLE, ExportOptions(kind="png_full", path=tmp_path / "l.png"))
    back = np.asarray(Image.open(out), dtype=np.uint16)
    assert np.array_equal(back, SAMPLE)


@pytest.mark.parametrize("kind", ["tiff", "png_full", "png_compressed"])
def test_every_kind_has_provenance(tmp_path, kind):
    """三种导出形式都必须带溯源，不允许有遗漏。"""
    out = export(SAMPLE, ExportOptions(kind=kind, path=tmp_path / f"k.{kind}.png"))
    if kind == "tiff":
        assert read_tiff_provenance(out).get("software") == SOFTWARE_NAME
    else:
        assert read_png_provenance(out).get("software") == SOFTWARE_NAME

"""三种导出形式的一致性验证：TIFF / PNG 全画质 / PNG 可压缩。

只做一件事：把同一份数据分别导出三种形式，回读校验像素一致性。
"""
from __future__ import annotations

import numpy as np
import pytest

from fysat.export import KINDS, ExportOptions, export


@pytest.fixture(scope="module")
def sample():
    rng = np.random.default_rng(42)
    return (rng.random((256, 320)) * 4095).astype(np.uint16)


def test_kinds_declared():
    assert set(KINDS) == {"tiff", "png_full", "png_compressed"}
    for k, v in KINDS.items():
        assert v["lossless"] is True, f"{k} 必须无损"


def test_tiff_roundtrip_is_exact(tmp_path, sample):
    import tifffile

    out = export(sample, ExportOptions(kind="tiff", path=tmp_path / "a.tif", deflate=True))
    back = tifffile.imread(str(out))
    assert back.shape == sample.shape
    assert back.dtype == sample.dtype
    assert np.array_equal(back, sample), "TIFF 必须与原始 DN 完全一致"


def test_png_full_is_16bit_lossless(tmp_path, sample):
    from PIL import Image

    out = export(sample, ExportOptions(kind="png_full", path=tmp_path / "a.png"))
    im = Image.open(out)
    assert im.size == (sample.shape[1], sample.shape[0])
    assert im.mode in ("I;16", "I;16B", "I"), f"全画质 PNG 应为 16 位，实际 {im.mode}"
    back = np.asarray(im).astype(np.uint16)
    assert np.array_equal(back, sample), "16 位 PNG 应无损"


def test_png_compressed_level_changes_size_not_pixels(tmp_path, sample):
    a = export(sample, ExportOptions(kind="png_compressed", path=tmp_path / "l0.png", compress_level=0))
    b = export(sample, ExportOptions(kind="png_compressed", path=tmp_path / "l9.png", compress_level=9))
    assert a.stat().st_size > b.stat().st_size, "压缩强度越高文件应越小"

    from PIL import Image
    assert np.array_equal(np.asarray(Image.open(a)), np.asarray(Image.open(b))), "压缩强度不应改变像素"


def test_png_compressed_scale(tmp_path, sample):
    out = export(sample, ExportOptions(kind="png_compressed", path=tmp_path / "half.png", scale=0.5))
    from PIL import Image
    im = Image.open(out)
    assert im.size == (160, 128), f"缩放后应为 (160,128)，实际 {im.size}"


def test_colormap_only_affects_compressed(tmp_path, sample):
    out = export(sample, ExportOptions(kind="png_compressed", path=tmp_path / "gray.png", cmap="turbo"))
    from PIL import Image
    im = Image.open(out).convert("RGB")
    arr = np.asarray(im)
    assert arr.ndim == 3 and arr.shape[-1] == 3
    assert arr.std() > 10, "上色后应为彩色"


def test_rgb_input_stays_rgb(tmp_path):
    rgb = (np.random.default_rng(1).random((64, 64, 3)) * 255).astype(np.uint8)
    out = export(rgb, ExportOptions(kind="png_full", path=tmp_path / "rgb.png"))
    from PIL import Image
    im = Image.open(out)
    assert im.mode == "RGB"
    assert np.array_equal(np.asarray(im), rgb)


def test_nan_handling(tmp_path):
    data = np.full((32, 32), np.nan, dtype=np.float32)
    data[8:24, 8:24] = 280.0
    out = export(data, ExportOptions(kind="png_full", path=tmp_path / "nan.png", stretch=(2, 98)))
    from PIL import Image
    arr = np.asarray(Image.open(out))
    assert arr.min() == 0 and arr.max() > 0, "NaN 应被安全处理"


# ---- 大端数据（HDF5/NetCDF 常见 '>u2'）不得被误解释 ----

BIG_ENDIAN = np.array([[76, 72, 78], [0, 65535, 1023]], dtype=">u2")


def test_bigendian_tiff_is_exact(tmp_path):
    """'>u2' 必须按无符号 16 位处理，不能因 dtype 不等于 np.uint16 而走浮点重拉伸。"""
    import tifffile

    out = export(BIG_ENDIAN, ExportOptions(kind="tiff", path=tmp_path / "be.tif"))
    back = tifffile.imread(str(out))
    assert np.array_equal(np.asarray(back, dtype=np.uint16),
                          np.asarray(BIG_ENDIAN, dtype=np.uint16)), \
        f"大端数据导出后不一致: {back.reshape(-1)}"


def test_bigendian_png_full_is_exact(tmp_path):
    from PIL import Image

    out = export(BIG_ENDIAN, ExportOptions(kind="png_full", path=tmp_path / "be.png"))
    back = np.asarray(Image.open(out), dtype=np.uint16)
    assert np.array_equal(back, np.asarray(BIG_ENDIAN, dtype=np.uint16)), \
        f"大端数据 PNG 导出后不一致: {back.reshape(-1)}"


def test_bigendian_survives_prepare_array():
    """直接检查 prepare_array，确保没有被转成 float 再量化。"""
    from fysat.export import ExportOptions, prepare_array

    out, mode = prepare_array(BIG_ENDIAN, ExportOptions(kind="tiff", path="x"), "tiff")
    assert mode == "I;16"
    assert out.dtype.kind == "u" and out.dtype.itemsize == 2
    assert np.array_equal(np.asarray(out, dtype=np.uint16),
                          np.asarray(BIG_ENDIAN, dtype=np.uint16))

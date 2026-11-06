"""批量解码测试。

分层策略（与 test_products.py 一致）：

1. **不依赖样本**：用临时目录 + 合成文件验证扫描、匹配、错误隔离、
   输出命名、进度回调、干跑。这些能真正跑起来抓逻辑错误。
2. **真实样本小批量**：拿 3~5 个真实文件跑一遍，验证输出文件数与格式，
   以及「单文件失败不影响整体」。

合成文件用 np 直接写最小 HDF5（h5py），让 batch 走真实的 open_file 通路，
而不是 mock —— mock 掉读取器就测不到「错误隔离」这个核心目标了。
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pytest
from _sample_root import SAMPLE_ROOT

from fysat import batch as batch_mod
from fysat.batch import BatchResult, FileResult, preview, run, scan
from fysat.export import KINDS
from fysat.products import ProductRegistry

SAMPLE_ROOT = SAMPLE_ROOT

# 一个只认 TEST_*.HDF 的测试产品定义（避免依赖内置定义的行为变化）
TEST_YAML = """\
product: TEST_HDF
title: 测试用最小 HDF5 产品
platform: TEST
instrument: SYN
level: L1
container: hdf5
verified: false
match:
  filename: '^TEST_.*\\.HDF$'
  container: hdf5
fields:
  - name: Data
    path: /Data/Field
    kind: reflective
    unit: '%'
    dn:
      valid_range: [0, 4095]
      fill: 65535
    calib:
      method: linear
      scale: 1.0
      offset: 0.0
pending_verification:
  - 测试用定义，不承载真实科学语义
"""


# ---------------------------------------------------------------- 工具

def _write_hdf(path: Path, *, shape=(32, 48), fill_dn: int | None = None,
               value: int = 100) -> Path:
    """写一个最小 HDF5，让 batch 走真实 open_file 通路。"""
    import h5py

    data = np.full(shape, value, dtype=np.uint16)
    if fill_dn is not None:
        data[0, 0] = fill_dn
    with h5py.File(str(path), "w") as f:
        ds = f.create_dataset("Data/Field", data=data)
        ds.attrs["valid_range"] = np.array([0, 4095], dtype=np.int32)
        ds.attrs["FillValue"] = np.uint16(65535)
    return path


@pytest.fixture
def registry(tmp_path) -> ProductRegistry:
    d = tmp_path / "products"
    d.mkdir()
    (d / "test_hdf.yml").write_text(TEST_YAML, encoding="utf-8")
    reg = ProductRegistry.from_dir(d)
    assert not reg.errors, reg.errors
    return reg


# ---------------------------------------------------------------- 扫描

def test_scan_finds_matching_files(tmp_path):
    _write_hdf(tmp_path / "a.HDF")
    _write_hdf(tmp_path / "b.hdf")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "empty.HDF").write_bytes(b"")

    found = scan(tmp_path)
    names = {p.name for p in found}
    assert "a.HDF" in names
    assert "b.hdf" in names
    assert "notes.txt" not in names
    assert "empty.HDF" not in names, "0 字节文件应被跳过"


def test_scan_is_recursive(tmp_path):
    sub = tmp_path / "sub" / "deeper"
    sub.mkdir(parents=True)
    _write_hdf(sub / "deep.HDF")
    found = scan(tmp_path)
    assert any(p.name == "deep.HDF" for p in found)


def test_scan_non_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_hdf(sub / "deep.HDF")
    _write_hdf(tmp_path / "top.HDF")
    found = scan(tmp_path, recursive=False)
    names = {p.name for p in found}
    assert "top.HDF" in names and "deep.HDF" not in names


def test_scan_ignores_temp_files(tmp_path):
    _write_hdf(tmp_path / "real.HDF")
    (tmp_path / "partial.enp").write_bytes(b"x" * 100)
    found = scan(tmp_path)
    assert not any(p.suffix == ".enp" for p in found)


def test_scan_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "nope")


def test_scan_file_path_raises(tmp_path):
    f = tmp_path / "a.HDF"
    _write_hdf(f)
    with pytest.raises(NotADirectoryError):
        scan(f)


# ---------------------------------------------------------------- 单文件

def test_process_file_success(tmp_path, registry):
    src = _write_hdf(tmp_path / "TEST_ok.HDF")
    out = tmp_path / "out"
    res = batch_mod.process_file(src, out_dir=out, kind="png_full", registry=registry)

    assert res.status == "ok", res.reason or res.error
    assert res.product == "TEST_HDF"
    assert res.n_images == 1
    assert len(res.outputs) == 1
    assert res.outputs[0].exists()
    assert res.outputs[0].suffix == ".png"
    assert res.bytes_written > 0


def test_process_file_skips_unmatched(tmp_path, registry):
    src = _write_hdf(tmp_path / "OTHER_nomatch.HDF")
    res = batch_mod.process_file(src, out_dir=tmp_path / "out",
                                 kind="png_full", registry=registry)
    assert res.status == "skipped"
    assert "没有匹配" in res.reason


def test_process_file_failure_is_isolated(tmp_path, registry):
    """坏文件必须记成 failed，不能抛异常打断批处理。"""
    bad = tmp_path / "TEST_broken.HDF"
    bad.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 128)   # HDF5 魔数但内容损坏

    res = batch_mod.process_file(bad, out_dir=tmp_path / "out",
                                 kind="png_full", registry=registry)
    assert res.status in ("failed", "skipped")
    assert not res.ok


def test_output_naming_is_filesystem_safe(tmp_path, registry):
    src = _write_hdf(tmp_path / "TEST_ok.HDF")
    res = batch_mod.process_file(src, out_dir=tmp_path / "out",
                                 kind="png_full", registry=registry)
    name = res.outputs[0].name
    assert "TEST_ok" in name
    assert "Data_Field" in name or "Data/Field" not in name


def test_output_does_not_overwrite(tmp_path, registry):
    """重复跑同一批不能覆盖已有文件。"""
    src = _write_hdf(tmp_path / "TEST_ok.HDF")
    out = tmp_path / "out"
    r1 = batch_mod.process_file(src, out_dir=out, kind="png_full", registry=registry)
    r2 = batch_mod.process_file(src, out_dir=out, kind="png_full", registry=registry)

    assert r1.outputs[0] != r2.outputs[0], "第二次应写新文件而不是覆盖"
    assert r1.outputs[0].exists() and r2.outputs[0].exists()


def test_all_export_kinds_work(tmp_path, registry):
    src = _write_hdf(tmp_path / "TEST_ok.HDF")
    for kind in KINDS:
        res = batch_mod.process_file(src, out_dir=tmp_path / f"out_{kind}",
                                     kind=kind, registry=registry)
        assert res.status == "ok", f"{kind}: {res.reason or res.error}"
        assert res.outputs[0].suffix == KINDS[kind]["ext"]


def test_unknown_kind_rejected(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_ok.HDF")
    with pytest.raises(ValueError, match="未知导出类型"):
        run(tmp_path, out_dir=tmp_path / "out", kind="webp", registry=registry)


# ---------------------------------------------------------------- 批量

def test_run_handles_mixed_directory(tmp_path, registry):
    """混合目录：好文件成功、未匹配跳过、坏文件失败，整体不中断。"""
    _write_hdf(tmp_path / "TEST_a.HDF")
    _write_hdf(tmp_path / "TEST_b.HDF")
    _write_hdf(tmp_path / "OTHER_c.HDF")
    (tmp_path / "TEST_bad.HDF").write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 64)

    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full", registry=registry)

    assert isinstance(result, BatchResult)
    assert result.n_total == 4
    assert result.n_ok == 2, f"应有 2 个成功，实际 {result.n_ok}: {result.report_lines()}"
    assert result.n_skipped >= 1
    assert result.n_failed >= 1
    assert result.n_outputs == 2


def test_run_progress_callback(tmp_path, registry):
    for i in range(3):
        _write_hdf(tmp_path / f"TEST_{i}.HDF")

    seen: list[tuple[int, int, str]] = []

    def cb(done, total, path):
        seen.append((done, total, path.name))

    run(tmp_path, out_dir=tmp_path / "out", kind="png_full",
        registry=registry, progress=cb)

    assert len(seen) == 3
    assert seen[0][0] == 1 and seen[-1][0] == 3
    assert all(t == 3 for _, t, _ in seen)


def test_run_on_file_callback(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    got: list[FileResult] = []
    run(tmp_path, out_dir=tmp_path / "out", kind="png_full",
        registry=registry, on_file=got.append)
    assert len(got) == 1 and got[0].status == "ok"


def test_progress_callback_error_does_not_break_batch(tmp_path, registry):
    """GUI 回调抛异常不能把批处理带崩。"""
    _write_hdf(tmp_path / "TEST_a.HDF")

    def boom(done, total, path):
        raise RuntimeError("UI 炸了")

    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full",
                 registry=registry, progress=boom)
    assert result.n_ok == 1


def test_run_limit(tmp_path, registry):
    for i in range(5):
        _write_hdf(tmp_path / f"TEST_{i}.HDF")
    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full",
                 registry=registry, limit=2)
    assert result.n_total == 2


def test_run_empty_directory(tmp_path, registry):
    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full", registry=registry)
    assert result.n_total == 0
    assert result.n_ok == 0
    assert result.summary()["total"] == 0


# ---------------------------------------------------------------- 干跑

def test_dry_run_writes_nothing(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    out = tmp_path / "out"
    result = run(tmp_path, out_dir=out, kind="png_full", registry=registry, dry_run=True)

    assert result.n_total == 1
    assert result.n_ok == 1
    assert result.n_outputs == 0
    assert not out.exists() or not any(out.iterdir()), "干跑不应写任何文件"


def test_dry_run_reports_matched_product(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    result = run(tmp_path, out_dir=tmp_path / "out", registry=registry, dry_run=True)
    assert result.files[0].product == "TEST_HDF"


def test_preview(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    _write_hdf(tmp_path / "OTHER_b.HDF")
    rows = preview(tmp_path, registry=registry)
    assert len(rows) == 2
    products = {r["product"] for r in rows}
    assert "TEST_HDF" in products
    assert "" in products, "未匹配的文件 product 应为空"


# ---------------------------------------------------------------- 结果对象

def test_result_counts_and_summary(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full", registry=registry)
    s = result.summary()
    assert s["total"] == 1 and s["ok"] == 1
    assert s["outputs"] == 1
    # mb 是四舍五入到 3 位小数的**显示值**，2x2 测试图只有几百字节会被舍成 0.0，
    # 因此这里断言原始字节数（bytes）而不是显示用的小数。
    assert s["bytes"] > 0
    assert s["mb"] >= 0
    assert "TEST_HDF" in s["by_product"]
    assert s["bytes"] == result.total_bytes


def test_report_lines_are_readable(tmp_path, registry):
    _write_hdf(tmp_path / "TEST_a.HDF")
    (tmp_path / "OTHER_b.HDF").write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 64)
    result = run(tmp_path, out_dir=tmp_path / "out", kind="png_full", registry=registry)
    lines = result.report_lines()
    assert any("共" in ln for ln in lines)
    assert any("输出" in ln for ln in lines)


# ---------------------------------------------------------------- 真实样本小批量

def _real_samples() -> list[Path]:
    """挑 3~5 个体积较小的真实样本（避免批量测试跑成几十 GB）。"""
    picked: list[Path] = []
    budget = 700 * 1024 * 1024                    # 总量控制在 ~700 MB
    patterns = [
        "FY3H_GNOSO_*.NC",                        # 最小（~1 MB）
        "FY2G_FDI_ALL_NOM_*.hdf",                 # ~40 MB
        "FY3D_MERSI_ORBT_L2_CLM_*.HDF",           # ~40 MB
    ]
    total = 0
    for pat in patterns:
        for hit in sorted(glob.glob(str(SAMPLE_ROOT / "**" / pat), recursive=True)):
            p = Path(hit)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size == 0 or total + size > budget:
                continue
            picked.append(p)
            total += size
            break                                  # 每个模式只取 1 个
    return picked


@pytest.fixture(scope="module")
def real_dir(tmp_path_factory) -> Path:
    samples = _real_samples()
    if len(samples) < 2:
        pytest.skip("真实样本不足，跳过批量实跑")
    d = tmp_path_factory.mktemp("real_batch")
    import shutil

    for p in samples:
        shutil.copy2(p, d / p.name)                # 复制小文件，避免动原始数据
    return d


def test_real_batch_end_to_end(real_dir, tmp_path):
    """真实文件跑一遍：验证输出文件数与格式正确。"""
    out = tmp_path / "batch_out"
    result = run(real_dir, out_dir=out, kind="png_compressed",
                 max_bands=1, export_options={"scale": 0.25})

    assert result.n_total >= 2
    # 至少有一个文件能出图（CLM 或 FDI）；GNOSO 是廓线，会跳过
    assert result.n_ok >= 1, f"没有一个真实样本成功: {result.report_lines()}"
    assert result.n_outputs >= 1

    for f in result.files:
        for p in f.outputs:
            assert p.exists() and p.suffix == ".png"
            assert p.stat().st_size > 0

    # 廓线产品必须被跳过而不是失败
    nc_files = [f for f in result.files if f.path.suffix.upper() == ".NC"]
    assert nc_files, "样本里应有 GNOSO"
    assert all(f.status == "skipped" for f in nc_files), \
        "廓线产品应被跳过（无法成图），不是失败"


def test_real_batch_products_matched(real_dir, tmp_path):
    result = run(real_dir, out_dir=tmp_path / "o", kind="png_compressed",
                 max_bands=1, dry_run=True)
    products = {f.product for f in result.files if f.product}
    assert products, f"真实样本没有匹配到任何产品定义: {result.report_lines()}"
    # 用到的必须是内置定义里真实存在的产品名
    builtin = set(ProductRegistry.from_dir().names())
    assert products <= builtin | {"TEST_HDF"}, \
        f"匹配到了未注册的产品 {products - builtin}"

# -*- coding: utf-8 -*-
"""FY-2 CSV 数据集容器测试。

两部分：
1. 合成容器 —— 自己按文档造一个 3 记录的小文件（元数据 + 2 条扫描行），
   逐位写进已知 DN，再读回来比对。不依赖任何样本，能真正验证位流解包。
2. 真实样本 —— ``Y:\\download-data`` 下的 103 MB 业务文件，验证容器尺寸、
   整圆盘结构、逐行元信息与元数据记录语义。样本缺失时自动跳过。
"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT

import glob
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from fysat.detect import sniff
from fysat.readers import fy2_csv

SAMPLE_GLOB = str(SAMPLE_ROOT / r"**\FY2G_CSV_MLT_NUL_*.DAT")


# ---------------------------------------------------------------- 合成容器


def _pack_bits(values: np.ndarray, nbits: int, seg_no: int, seg_len: int) -> bytes:
    """把一列整数值打成 MSB 优先位流，前面加 2 字节段标志，尾部补 0 到段长。"""
    arr = np.asarray(values, dtype=np.uint16)
    bits = np.zeros((arr.size, nbits), dtype=np.uint8)
    for k in range(nbits):
        bits[:, k] = (arr >> (nbits - 1 - k)) & 1
    payload = np.packbits(bits.reshape(-1), bitorder="big").tobytes()
    out = bytes((0, seg_no)) + payload
    assert len(out) <= seg_len, f"{len(out)} > {seg_len}"
    return out + b"\x00" * (seg_len - len(out))


def _bcd_time(dt: datetime, cs: int) -> bytes:
    def two(v: int) -> bytes:
        return bytes((v // 10 << 4 | v % 10,))

    return (two(dt.year // 100) + two(dt.year % 100) + two(dt.month) + two(dt.day)
            + two(dt.hour) + two(dt.minute) + two(dt.second) + two(cs))


def _meta_record(n_data: int, first: datetime, last: datetime) -> bytes:
    rec = bytearray(b" " * fy2_csv.RECORD_LEN)
    rec[0:2] = (0).to_bytes(2, "big")
    rec[2] = 0
    fields = {
        "file_name": b"FY2G_CSV_MLT_NUL_20261018_1300.DAT",
        "format": b"CSVS",
        "version": b"V1.0",
        "producer": b"NSMC/CMA",
        "obs_time": b"20261018130000",
        "gen_time": b"20261018130000",
        "satellite": b"FY-2G",
        "instrument": b"VISSR",
        "record_length": b"41260",
        "record_count": f"{n_data:04d}".encode(),
        "quality_id": b"0001",
    }
    for name, off, length in fy2_csv.META_TEXT_FIELDS:
        rec[off:off + len(fields[name])] = fields[name]
    qual = {
        "first_row_no": b"0001",
        "first_row_time": first.strftime("%Y%m%d%H%M%S").encode() + b"00",
        "last_row_no": f"{n_data:04d}".encode(),
        "last_row_time": last.strftime("%Y%m%d%H%M%S").encode() + b"13",
        "total_scanned_rows": f"{n_data:04d}".encode(),
        "corrected_row_count": b"0000",
        "corrected_time_count": b"0000",
        "throw_lines": b"0000",
        "error_rate": b"0000",
        "file_quality": b"0001",
    }
    for name, off, length in fy2_csv.META_QUAL_FIELDS:
        rec[off:off + len(qual[name])] = qual[name]
    rec[fy2_csv.META_SDB_FLAG] = 0
    rec[fy2_csv.META_LINE_QUALITY_OFFSET:
        fy2_csv.META_LINE_QUALITY_OFFSET + fy2_csv.META_LINE_QUALITY_LEN] = bytes(
            fy2_csv.META_LINE_QUALITY_LEN)
    return bytes(rec)


def _data_record(rec_no: int, obstime: datetime, cs: int,
                 ir: np.ndarray, vis: np.ndarray) -> bytes:
    rec = bytearray(fy2_csv.RECORD_LEN)
    rec[0:2] = rec_no.to_bytes(2, "big")
    rec[2] = 0
    # --- DOC 段
    doc = bytearray(fy2_csv.DOC_LEN - fy2_csv.DOC_HEAD)
    doc[fy2_csv.DOC_PICTURE_FLAG] = 0xFF
    doc[fy2_csv.DOC_WEST_EDGE[0]:fy2_csv.DOC_WEST_EDGE[1]] = (1).to_bytes(2, "big")
    doc[fy2_csv.DOC_EAST_EDGE[0]:fy2_csv.DOC_EAST_EDGE[1]] = (2292).to_bytes(2, "big")
    lo, hi = fy2_csv.DOC_TIME_BCD
    doc[lo:hi] = _bcd_time(obstime, cs)
    lo, hi = fy2_csv.DOC_SCAN_COUNT
    doc[lo:hi] = rec_no.to_bytes(2, "big")
    lo = fy2_csv.DOC_SUBCOMM[0]
    doc[lo:lo + 4] = bytes((0, 3, 0, 0))                 # 子交换：第 4 组、重复 0
    mlo, mhi = fy2_csv.DOC_MAPPING
    doc[mlo:mhi] = bytes(((rec_no * 7) % 256,)) * (mhi - mlo)
    doc_seg = bytes((0, 1)) + bytes(doc)
    rec[fy2_csv.DOC_OFFSET:fy2_csv.DOC_OFFSET + len(doc_seg)] = doc_seg

    # --- 影像段
    for name, off, length, bits, count in fy2_csv.SEGMENTS:
        values = ir if name.startswith("IR") else vis
        if name == "IR1":
            payload = values
        elif name == "VIS1":
            payload = values
        else:
            payload = np.zeros(count, dtype=np.uint16)
        seg = _pack_bits(payload, bits, fy2_csv.SEGMENT_IDS[name], length)
        rec[off:off + len(seg)] = seg
    return bytes(rec)


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> tuple[Path, np.ndarray, np.ndarray]:
    """造一个 3 记录（元数据 + 2 行）的合法 CSV 容器。"""
    n_data = 2
    first = datetime(2026, 10, 18, 13, 0, 2)
    last = datetime(2026, 10, 18, 13, 0, 3)
    ir = (np.arange(fy2_csv.IR_PIXELS) % 1024).astype(np.uint16)
    vis = (np.arange(fy2_csv.VIS_PIXELS) % 64).astype(np.uint8)

    blob = _meta_record(n_data, first, last)
    blob += _data_record(1, first, 0, ir, vis)
    blob += _data_record(2, last, 13, ir, vis)

    path = tmp_path_factory.mktemp("fy2") / "FY2G_CSV_MLT_NUL_20261018_1300.DAT"
    path.write_bytes(blob)
    return path, ir, vis


def test_layout_constants_are_consistent():
    """段表必须首尾相接地铺满 41260 字节。"""
    end = fy2_csv.DOC_OFFSET + fy2_csv.DOC_LEN
    assert fy2_csv.DOC_OFFSET == 3 and fy2_csv.DOC_LEN == 2293
    for name, off, length, bits, count in fy2_csv.SEGMENTS:
        assert off == end, f"{name} 段偏移 {off} != 上一段结束 {end}"
        assert bits * count <= (length - 2) * 8, f"{name} 段容量不足"
        assert (length - 2) * 8 - bits * count < 8, f"{name} 段尾部填充应少于 8 bit"
        end = off + length
    assert end == fy2_csv.RECORD_LEN == 41260
    # 元数据记录与 Table 4.20 的 C 结构体逐字段相加
    assert fy2_csv.META_LINE_QUALITY_OFFSET == 124 + 4 + 16 + 4 + 16 + 4 + 4 + 4 + 1 + 4 + 4 + 4
    assert fy2_csv.META_RESERVED_ESC == 189 + 2500
    assert fy2_csv.RECORD_LEN - fy2_csv.META_RESERVED_ESC == 38571  # char fill[38571]


def test_synthetic_file_is_detected_and_sized(synthetic):
    path, _, _ = synthetic
    size = path.stat().st_size
    assert size == 3 * fy2_csv.RECORD_LEN
    assert sniff(path) == "fy2_csv", "魔数识别应命中 FY-2 CSV"


def test_synthetic_header_only(synthetic):
    path, _, _ = synthetic
    ds = fy2_csv.read(path, load=False)
    assert ds.reader == "fy2_csv"
    assert ds.platform == "FY-2G" and ds.instrument == "VISSR" and ds.level == "L1"
    assert ds.start_time == datetime(2026, 10, 18, 13, 0, 0)
    assert len(ds.variables) == 14
    ir1 = ds["IR1"]
    assert ir1.shape == (2, 2291) and ir1.dtype == np.uint16
    assert ir1.data.size == 0, "load=False 不应解码数据"
    assert ds["VIS1"].shape == (2, 9164) and ds["VIS1"].dtype == np.uint8
    assert ds.geolocation.kind == "nominal", "合成文件映射块不完整，应退回 nominal"


def test_synthetic_bitstream_roundtrip(synthetic):
    """逐位写入的已知 DN 必须原样读回来。"""
    path, ir, vis = synthetic
    ds = fy2_csv.read(path)
    assert np.array_equal(ds["IR1"].data[0], ir), "IR1 10 bit 解包不一致"
    assert np.array_equal(ds["IR1"].data[1], ir)
    assert np.array_equal(ds["VIS1"].data[0], vis.astype(np.uint8)), "VIS1 6 bit 解包不一致"
    for name in ("IR2", "IR3", "IR4", "VIS2", "VIS3", "VIS4"):
        assert not ds[name].data.any(), f"{name} 应为全 0"


def test_synthetic_per_line_metadata(synthetic):
    path, _, _ = synthetic
    ds = fy2_csv.read(path)
    assert ds["scan_count"].data.tolist() == [1, 2]
    assert ds["picture_flag"].data.tolist() == [255, 255]
    assert ds["line_quality"].data.tolist() == [0, 0]
    assert ds["earth_edge_west"].data.tolist() == [1, 1]
    assert ds["earth_edge_east"].data.tolist() == [2292, 2292]
    stamps = ds["line_time"].data
    assert stamps[1] - stamps[0] == pytest.approx(1.13, abs=1e-6), "13:00:02.00 → 13:00:03.13"


def test_synthetic_meta_fields(synthetic):
    path, _, _ = synthetic
    meta = fy2_csv.parse_meta(path.read_bytes()[:fy2_csv.RECORD_LEN])
    assert meta["record_no"] == 0 and meta["record_quality"] == 0
    assert meta["format"] == "CSVS" and meta["version"] == "V1.0"
    assert meta["producer"] == "NSMC/CMA" and meta["satellite"] == "FY-2G"
    assert meta["record_length"] == "41260" and meta["record_count"] == "0002"
    assert meta["obs_datetime"] == datetime(2026, 10, 18, 13, 0, 0)
    assert meta["quality"]["first_row_datetime"] == datetime(2026, 10, 18, 13, 0, 2)
    assert meta["quality"]["last_row_datetime"] == datetime(2026, 10, 18, 13, 0, 3, 130000)
    # 元数据占用满 41260 字节：189 + 2500 + 38571，尾部填充 0x20
    assert meta["reserved_fill"] == [0x20]
    assert sum(meta["line_quality"]) == 0


def test_synthetic_variable_contract(synthetic):
    path, _, _ = synthetic
    ds = fy2_csv.read(path)
    for name, var in ds.variables.items():
        assert var.unit, f"{name} 缺少 unit"
        assert var.valid_range is not None, f"{name} 缺少 valid_range"
        assert var.dims, f"{name} 缺少 dims"
    assert ds["IR1"].valid_range == (0.0, 1023.0)
    assert ds["VIS1"].valid_range == (0.0, 63.0)
    # IR/VIS 原始 DN 没有哨兵值 → fill_value 留空（模块文档说明理由）
    assert ds["IR1"].fill_value is None
    # 地球边缘未检测到时有文档明示的 0xFFFF
    assert ds["earth_edge_west"].fill_value == float(fy2_csv.EDGE_UNDETECTED)


def test_bad_container_rejected(tmp_path):
    bad = tmp_path / "broken.DAT"
    bad.write_bytes(b"\x00" * (fy2_csv.RECORD_LEN + 7))
    with pytest.raises(ValueError, match="整数倍"):
        fy2_csv.read(bad)


# ---------------------------------------------------------------- 真实样本


@pytest.fixture(scope="module")
def sample() -> Path:
    hits = sorted(glob.glob(SAMPLE_GLOB, recursive=True))
    if not hits:
        pytest.skip(f"未找到 FY-2 CSV 样本（{SAMPLE_GLOB}）")
    # 优先选 2026-10-18 13:00 那份，便于与文档/元数据互证
    for hit in hits:
        if "20261018_1300" in hit:
            return Path(hit)
    return Path(hits[0])


def test_sample_container_geometry(sample):
    size = sample.stat().st_size
    assert size % fy2_csv.RECORD_LEN == 0, "文件必须是 41260 的整数倍"
    n_rec = size // fy2_csv.RECORD_LEN
    assert n_rec == 2501, f"应为 1 条元数据 + 2500 条扫描行，实际 {n_rec}"
    assert size == 103_191_260, "官方全圆盘 CSV 固定 103.19 MB"
    # 前 4 字节按大端整数读是 70 —— 只是 'F' 而已，不是长度前缀
    head = sample.read_bytes()[:8]
    assert head[0:3] == b"\x00\x00\x00"
    assert head[3:8] == b"FY2G_", "文件名紧跟 3 字节记录头，没有长度字段"


def test_sample_header_only(sample):
    ds = fy2_csv.read(sample, load=False)
    assert len(ds.variables) == 14
    assert ds["IR1"].shape == (2500, 2291)
    assert ds["VIS1"].shape == (2500, 9164)
    assert ds.attrs["record_length"] == 41260
    assert ds.attrs["record_count"] == 2500
    assert ds.attrs["calibration_tables_present"] is False
    # load=False 的目的是**不加载大数组**（每通道 2500x2291/9164）；
    # 逐行元信息（scan_count/line_quality/... 各 2500 点，共几十 KB）必须读出来，
    # 否则产品定义解码时 ds.load() 会因 read_variable 只认 8 个图像通道而失败。
    for name, var in ds.variables.items():
        if var.data.ndim == 2 and var.data.size:
            raise AssertionError(f"{name} 是二维图像通道，load=False 时不应加载")
    # 一维元信息允许且应当已填充
    assert ds["scan_count"].data.size == 2500


def test_sample_full_disc_structure(sample):
    """整盘：帧内应有地球圆盘，四角为太空，扫描行号 1..2500。"""
    ds = fy2_csv.read(sample)
    ir = ds["IR1"].data
    vis = ds["VIS1"].data
    print(f"IR1 {ir.shape} min={ir.min()} max={ir.max()} mean={ir.mean():.1f}")
    print(f"VIS1 {vis.shape} min={vis.min()} max={vis.max()} mean={vis.mean():.2f}")

    assert ir.dtype == np.uint16 and ir.shape == (2500, 2291)
    assert vis.dtype == np.uint8 and vis.shape == (2500, 9164)
    assert 0 <= ir.min() and ir.max() <= 1023
    assert 0 <= vis.min() and vis.max() <= 63

    assert ds["scan_count"].data.tolist() == list(range(1, 2501))
    assert np.all(ds["picture_flag"].data == 0xFF), "全部扫描行都应含图像数据"
    assert np.all(ds["line_quality"].data == 0), "综合行质量码应全为正常"

    # 圆盘面积：红外(5km) 等效半径约 1065 像素 → 约 3.5e6 像素；实测「非太空」占 1e6~4e6
    disc = int((ir < 1000).sum())
    print(f"地球圆盘像素数 {disc}")
    assert 1_000_000 < disc < 4_000_000, f"圆盘像素数异常：{disc}"
    # 四角是太空（红外 DN 接近最大值 1023）。注意第 0 行是定标行、不是地球影像，
    # 取第 1 行（全太空行）与最后一行来判。
    corners = [int(ir[1, 0]), int(ir[1, -1]), int(ir[-1, 0]), int(ir[-1, -1])]
    print("四角 DN:", corners)
    assert min(corners) >= 990, f"四角应为太空，实际 {corners}"
    # 圆盘横向居中、纵向中心
    col_profile = (ir < 1000).sum(axis=0)
    center_col = int(np.argmax(col_profile))
    row_profile = (ir < 1000).sum(axis=1)
    center_row = int(np.argmax(row_profile))
    print(f"圆盘中心 行={center_row} 列={center_col}")
    assert 900 < center_col < 1400, "圆盘应在画面水平中部"
    assert 900 < center_row < 1600, "圆盘应在画面垂直中部"


def test_sample_line_meta_matches_header(sample):
    """逐行 DOC 的首末行时刻必须与元数据记录一致（跨结构互验）。"""
    ds = fy2_csv.read(sample)
    meta = fy2_csv.parse_meta(sample.read_bytes()[:fy2_csv.RECORD_LEN])
    epoch = datetime(1970, 1, 1)
    first = float(ds["line_time"].data[0])
    last = float(ds["line_time"].data[-1])
    expect_first = (meta["quality"]["first_row_datetime"] - epoch).total_seconds()
    expect_last = (meta["quality"]["last_row_datetime"] - epoch).total_seconds()
    print(f"首行 {datetime.fromtimestamp(first)} / 元数据 {meta['quality']['first_row_time']}")
    print(f"末行 {datetime.fromtimestamp(last)} / 元数据 {meta['quality']['last_row_time']}")
    assert first == pytest.approx(expect_first, abs=1e-6)
    assert last == pytest.approx(expect_last, abs=1e-6)
    stamps = ds["line_time"].data
    assert np.all(np.diff(stamps) > 0), "逐行时刻应严格递增"
    span = stamps[-1] - stamps[0]
    print(f"整盘扫描耗时 {span:.2f} s")
    assert 1200 < span < 1800, f"全圆盘扫描约 25 分钟，实测 {span:.0f} s"


def test_sample_nav_grid(sample):
    grid = fy2_csv.nav_grid(sample)
    assert grid, "简化映射块应能收齐 25 组"
    line, pixel = grid["line"], grid["pixel"]
    assert line.shape == pixel.shape == (25, 25)
    assert grid["lat"][0] == pytest.approx(60.0) and grid["lat"][-1] == pytest.approx(-60.0)
    assert grid["lon"][0] == pytest.approx(45.0) and grid["lon"][-1] == pytest.approx(165.0)
    assert 0 <= pixel.min() and pixel.max() <= 2290
    assert 0 <= line.min() and line.max() <= 2499
    # 赤道那一行（第 12 行）的行号应落在画面垂直中部
    equator_line = float(line[12].mean())
    print(f"赤道平均行号 {equator_line:.0f}，网格像素范围 {pixel.min():.0f}~{pixel.max():.0f}")
    assert 1100 < equator_line < 1500, "赤道应位于画面上半部"
    geo = fy2_csv.read(sample, load=False).geolocation
    assert geo.kind == "glt"
    assert geo.params["grid_line"].shape == (25, 25)
    assert geo.params["vis_to_ir_scale"] == 4


def test_sample_read_variable_matches(sample):
    ds = fy2_csv.read(sample, channels=["IR4"])
    only = fy2_csv.read_variable(sample, "IR4")
    assert np.array_equal(ds["IR4"].data, only), "按需读取应与整读一致"
    assert ds["IR1"].data.size == 0, "未指定的通道不应解码"


def test_cli_info(sample, capsys):
    from fysat.cli import main

    assert main(["info", str(sample)]) == 0
    out = capsys.readouterr().out
    print(out)
    assert "fy2_csv" in out
    assert "IR1" in out and "(2500, 2291)" in out
    assert "FY-2G" in out and "VISSR" in out

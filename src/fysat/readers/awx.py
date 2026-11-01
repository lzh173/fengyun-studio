"""AWX 2.1 图像产品读取器（国家卫星气象中心《气象卫星分发产品及其格式规范 AWX2.1》）。

============================================================================
样本与字节级探针结论
============================================================================
样本：`MST2_SEC_VIS_LCN_20151204_0032.AWX` 等 22 个同族文件，大小全为 265216 B。
文件结构（全部由真实字节反推，并与文档 §3.3 / §4.1 / §4.3 对照）：

  一级文件头（40 B，**小端**：文件内 "整型数字节顺序" 字段 @12 = 0 → Intel 排列）
    @0:12   C*12 Sat96 文件名（样本 "EVLD0401.AWX"，是占位名，不是真实产品名）
    @12:14  i16 整型数字节顺序（0 = 小端，非 0 = 大端）
    @14:16  i16 一级文件头长度（样本 40）
    @16:18  i16 二级文件头长度（样本 2112 = 64 描述 + 2048 定标表）
    @18:20  i16 填充段长度（样本 408）
    @20:22  i16 记录长度（样本 512）
    @22:24  i16 文件头占用记录数（样本 6 → 3072 B）
    @24:26  i16 产品数据占用记录数（样本 512 → 262144 B）
    @26:28  i16 产品类别（1 静止图像 / 2 极轨图像 / 3 格点场 / 4 离散场 / 5 图形分析）
    @28:30  i16 压缩方式（0 未压缩 / 1 行程编码 / 2 LZW / 3 特定）
    @30:38  C*8 格式说明（样本 "SAT2004"）
    @38:40  i16 产品数据质量标记

  二级文件头·描述部分
    静止图像产品 64 B（doc §4.1），样本实测偏移：
      @40:48 卫星名 "MST1"；@48..56 年/月/日/时/分（2015/12/4/0/32，与文件名一致）
      @58 通道号（4 = 可见光）；@60 投影方式（1 = 兰勃托）；@62/@64 宽/高（512×512）
      @66/@68 左上角扫描线号/象元号；@70 抽样率
      @72..78 地理范围 北/南/西/东 —— **样本反推，文档待核对**：文档写"单位为度"，
        样本是 6052 / -64 / 8659 / 16177，只有 ×0.01 才成立（60.52°N / 0.64°S /
        86.59°E / 161.77°E），故按 ×100 处理
      @80/@82 投影中心纬度/经度（×100 → 30.00°N / 110.00°E）
      @84/@86 标准纬度 1/2（×100 → 30°/60°，兰勃托双标准纬线）
      @88/@90 水平/垂直分辨率（公里×100 → 13.00 km）
      @92/@94 地理网格叠加标志/叠加值；@96/@98/@100 调色表/定标表/定位块长度（0/2048/0）
    极轨图像产品 88 B（doc §5.1）：在静止版基础上插入结束时间、R/G/B 通道号、升降轨、
      轨道号、"一个像元占字节数"等字段，本模块按文档偏移实现（**无样本验证**）。

  数据块（紧跟描述部分，仅解析长度声明 > 0 的块）
    调色表：768 B = R/G/B 各 256 级
    定标表：1024 × i16 = 2048 B，单位 0.01%（反射率）或 0.01 K（亮温），按查找表使用
    定位块：描述 16 B + (行号, 列号) i16 对（样本长度为 0）

  填充段 + 扩展段
    样本：40 + 2112 + 408 = 2560，再加扩展段 512（1 记录）→ 3072 = 6 记录。
    扩展段是 ASCII：真实路径 "/DPCMTST/L1/SEC/MST2_SEC_VIS_LCN_20151204_0032.AWX"、
    "SAT2004"、"NSMC"（制作单位）、"MST1"（卫星名）、"V1.0"（产品版本）、"NSMC"。
    → 级别 L1 只能从这里取（文件名是 SAT96 命名，没有 `_L1_` 段，detect.parse_name 取不到）。

  图象数据段：3072 起 262144 B = 512 × 512，8 bit/像元，未压缩。
    样本实测：DN 0..180、156 个不同值、邻像元相关 0.83、行间相关 0.82；渲染出来正是
    东亚—西北太平洋的兰勃托可见光扇区图（西侧夜区为 0）→ 8 bit 逐行光栅判读正确。

============================================================================
样本里两个必须人工核对的点（已写进 attrs["unparsed"] / attrs["notes"]）
============================================================================
1. **定标表只覆盖 DN 2..63**（值 9..606，即 0.09%..6.06%），而图象 DN 实际到 180。
   定标表明显是按 6 bit 可见光产品填的（doc §4.3 说明 2 也提到 6 bit 查 0..63），
   与样本的 8 bit 数据对不上 → 故**不填 scale_factor/add_offset**（线性系数无法表达
   查找表，且覆盖不全），只把表作为 `calibration_lut` 变量给出，另提供 `to_physical()`
   （超出覆盖范围的像元返回 NaN，绝不外推）。
2. **卫星名不一致**：二级头写 "MST1"，文件名写 "MST2"。platform 取文件名（SAT96 命名），
   头里的值保留在 attrs["satellite_name_header"]，两处都可追溯。

原则：字节能确认的字段全部解析；不能确认的（兰勃托椭球参数、6bit/8bit 不一致带来的换算、
压缩图象数据、非图像类产品的数据段）一律不猜，写进 attrs["unparsed"]。
"""
from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..detect import parse_name
from ..model import Geolocation, SatDataset, Variable

L1_HEADER_LEN = 40
GEO_DESC_LEN = 64      # 静止气象卫星图像产品二级头描述部分
POLAR_DESC_LEN = 88    # 极轨气象卫星图像产品二级头描述部分
PALETTE_LEN = 768      # R/G/B 各 256 B
CALIB_LEN = 2048       # 1024 × i16
NAV_DESC_LEN = 16

CATEGORY_NAMES = {0: "未定义类型", 1: "静止气象卫星图像产品", 2: "极轨气象卫星图像产品",
                  3: "格点场定量产品", 4: "离散场定量产品", 5: "图形和分析产品"}
COMPRESSION_NAMES = {0: "未压缩", 1: "行程编码压缩", 2: "LZW 方式压缩", 3: "特定方式压缩"}
PROJECTION_NAMES = {0: "未投影(卫星投影)", 1: "兰勃托投影", 2: "麦卡托投影", 3: "极射投影",
                    4: "等经纬度投影", 5: "等面积投影"}
CHANNEL_NAMES = {
    0: ("RGB", "三通道合成图", ""),
    1: ("IR1", "红外通道 10.3-11.3 um", "K"),
    2: ("WV", "水汽通道 6.3-7.6 um", "K"),
    3: ("IR2", "红外分裂窗 11.5-12.5 um", "K"),
    4: ("VIS", "可见光通道 0.5-0.9 um", "%"),
    5: ("MIR", "中红外通道 3.5-4.0 um", "K"),
}
# 卫星系列 → 成像仪名（产品头没有仪器名字段，此处按卫星族推断，仅用于展示）
INSTRUMENT_BY_PREFIX = {
    "FY2": "VISSR", "MST": "IMAGER", "MTS": "IMAGER",
    "GMS": "VISSR", "MSAT": "IMAGER", "MET": "SEVIRI",
}


# ---------------------------------------------------------------- 小工具


def _text(b: bytes, start: int, stop: int) -> str:
    return b[start:stop].decode("latin-1").strip("\x00 ").strip()


def _printable_runs(b: bytes, min_len: int = 4) -> list[str]:
    """取出字节块里长度 ≥ min_len 的可打印 ASCII 串。"""
    out: list[str] = []
    buf = bytearray()
    for byte in b:
        if 32 <= byte < 127:
            buf.append(byte)
        else:
            if len(buf) >= min_len:
                out.append(buf.decode("latin-1"))
            buf = bytearray()
    if len(buf) >= min_len:
        out.append(buf.decode("latin-1"))
    return out


class _Ints:
    """按文件自己声明的字节顺序读整型。"""

    def __init__(self, little: bool) -> None:
        self.bo = "<" if little else ">"

    def i16(self, b: bytes, off: int) -> int:
        return struct.unpack(self.bo + "h", b[off:off + 2])[0]

    def arr16(self, b: bytes, count: int, dtype: str = "i2") -> np.ndarray:
        return np.frombuffer(b[: count * 2], dtype=np.dtype(self.bo + dtype)).astype(np.int32)


def _instrument_for(platform: str) -> str:
    key = platform.upper().replace("-", "")
    for prefix, name in INSTRUMENT_BY_PREFIX.items():
        if key.startswith(prefix.replace("-", "")):
            return name
    return ""


def _product_from_name(path: Path) -> tuple[str, str]:
    """SAT96 文件名 → (卫星码, 产品码)，如 MST2_SEC_VIS_LCN_20151204_0032。"""
    parts = [s for s in path.stem.split("_") if s]
    if not parts:
        return "", ""
    sat = parts[0]
    prod = "_".join(p for p in parts[1:] if not p.isdigit() and len(p) < 12)
    return sat, prod


def _safe_dt(year: int, month: int, day: int, hour: int, minute: int) -> datetime | None:
    try:
        if not (1900 <= year <= 2100):
            return None
        return datetime(year, month, day, max(0, min(23, hour)), max(0, min(59, minute)))
    except ValueError:
        return None


def _lut_coverage(lut: np.ndarray | None) -> tuple[int, int] | None:
    """定标表的非零覆盖区间（文档：查找不涉及的区域一律充 0）。"""
    if lut is None or lut.size == 0:
        return None
    nz = np.nonzero(lut)[0]
    if nz.size == 0:
        return None
    return int(nz[0]), int(nz[-1])


# ---------------------------------------------------------------- 二级头描述部分


def _parse_geo_desc(l2: bytes, it: _Ints) -> dict[str, Any]:
    """静止气象卫星图像产品二级头描述部分（64 B，偏移已由样本确认）。"""
    return {
        "satellite_name": _text(l2, 0, 8),
        "start_time": (it.i16(l2, 8), it.i16(l2, 10), it.i16(l2, 12), it.i16(l2, 14), it.i16(l2, 16)),
        "end_time": None,
        "channel": it.i16(l2, 18),
        "projection": it.i16(l2, 20),
        "width": it.i16(l2, 22),
        "height": it.i16(l2, 24),
        "scan0": it.i16(l2, 26),
        "pixel0": it.i16(l2, 28),
        "sampling": it.i16(l2, 30),
        "bbox": (it.i16(l2, 32), it.i16(l2, 34), it.i16(l2, 36), it.i16(l2, 38)),
        "center": (it.i16(l2, 40), it.i16(l2, 42)),
        "std_parallels": (it.i16(l2, 44), it.i16(l2, 46)),
        "resolution": (it.i16(l2, 48), it.i16(l2, 50)),
        "grid": (it.i16(l2, 52), it.i16(l2, 54)),
        "blocks": (it.i16(l2, 56), it.i16(l2, 58), it.i16(l2, 60)),
        "bytes_per_pixel": 0,
        "rgb_channels": None,
        "ascending": None,
        "orbit_number": None,
        "product_type": None,
    }


def _parse_polar_desc(l2: bytes, it: _Ints) -> dict[str, Any]:
    """极轨气象卫星图像产品二级头描述部分（88 B，偏移按文档 §5.1，无样本验证）。"""
    return {
        "satellite_name": _text(l2, 0, 8),
        "start_time": (it.i16(l2, 8), it.i16(l2, 10), it.i16(l2, 12), it.i16(l2, 14), it.i16(l2, 16)),
        "end_time": (it.i16(l2, 18), it.i16(l2, 20), it.i16(l2, 22), it.i16(l2, 24), it.i16(l2, 26)),
        "channel": it.i16(l2, 28),
        "rgb_channels": (it.i16(l2, 30), it.i16(l2, 32), it.i16(l2, 34)),
        "ascending": it.i16(l2, 36),
        "orbit_number": it.i16(l2, 38),
        "bytes_per_pixel": it.i16(l2, 40),
        "projection": it.i16(l2, 42),
        "product_type": it.i16(l2, 44),
        "width": it.i16(l2, 46),
        "height": it.i16(l2, 48),
        "scan0": it.i16(l2, 50),
        "pixel0": it.i16(l2, 52),
        "sampling": it.i16(l2, 54),
        "bbox": (it.i16(l2, 56), it.i16(l2, 58), it.i16(l2, 60), it.i16(l2, 62)),
        "center": (it.i16(l2, 64), it.i16(l2, 66)),
        "std_parallels": (it.i16(l2, 68), it.i16(l2, 70)),
        "resolution": (it.i16(l2, 72), it.i16(l2, 74)),
        "grid": (it.i16(l2, 76), it.i16(l2, 78)),
        "blocks": (it.i16(l2, 80), it.i16(l2, 82), it.i16(l2, 84)),
    }


# ---------------------------------------------------------------- 入口


def read(path: str | Path, load: bool = True, *, geo: str = "nominal", **_: Any) -> SatDataset:
    """读取 AWX 2.1 图像产品 → SatDataset。

    参数：
        load  True 时解出图象数据；False 只解析文件头（形状保存在 Variable.source_shape）。
        geo   "nominal"（投影参数 + 地理范围）/ "none"。

    仅支持产品类别 1（静止图像）与 2（极轨图像）；其余类别（格点场/离散场/图形分析）
    的数据段布局不同，抛 NotImplementedError 而不是按光栅硬读。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    size = p.stat().st_size
    with open(p, "rb") as fh:
        l1 = fh.read(L1_HEADER_LEN)
    if len(l1) < L1_HEADER_LEN:
        raise ValueError(f"{p.name} 太短（{size} B），不是 AWX 文件")

    little = struct.unpack("<h", l1[12:14])[0] == 0
    it = _Ints(little)
    l2_len = it.i16(l1, 16)
    pad_len = it.i16(l1, 18)
    rec_len = it.i16(l1, 20)
    n_hdr_rec = it.i16(l1, 22)
    n_data_rec = it.i16(l1, 24)
    category = it.i16(l1, 26)
    compression = it.i16(l1, 28)
    fmt = _text(l1, 30, 38)
    quality = it.i16(l1, 38)

    if category not in (1, 2):
        raise NotImplementedError(
            f"{p.name}: AWX 产品类别 {category}（{CATEGORY_NAMES.get(category, '未知')}）"
            f"的数据段不是光栅图象，本读取器只支持类别 1/2"
        )
    if l2_len <= 0 or rec_len <= 0 or n_hdr_rec <= 0:
        raise ValueError(f"{p.name} 一级文件头字段不自洽"
                         f"（二级头 {l2_len} B，记录长度 {rec_len}，头记录数 {n_hdr_rec}）")
    header_bytes = n_hdr_rec * rec_len
    if header_bytes > size:
        raise ValueError(f"{p.name} 文件头 {header_bytes} B 超出文件大小 {size} B")

    with open(p, "rb") as fh:
        fh.seek(L1_HEADER_LEN)
        l2 = fh.read(l2_len)
        fh.seek(header_bytes)
        raster_raw = fh.read(n_data_rec * rec_len) if load else b""
        fh.seek(L1_HEADER_LEN + l2_len + pad_len)
        ext = fh.read(max(0, header_bytes - (L1_HEADER_LEN + l2_len + pad_len)))
    if len(l2) < l2_len:
        raise ValueError(f"{p.name} 二级文件头被截断（{len(l2)} / {l2_len} B）")

    desc_len = GEO_DESC_LEN if category == 1 else POLAR_DESC_LEN
    if len(l2) < desc_len:
        raise ValueError(f"{p.name} 二级文件头 {l2_len} B 小于描述部分 {desc_len} B"
                         f"（产品类别 {category}）")
    d = _parse_geo_desc(l2, it) if category == 1 else _parse_polar_desc(l2, it)

    sat_code, prod_code = _product_from_name(p)
    name_info = parse_name(p)
    ext_strings = _printable_runs(ext)
    ds = SatDataset(source=p, reader="awx")
    ds.platform = sat_code or d["satellite_name"] or name_info.platform
    ds.instrument = _instrument_for(ds.platform) or name_info.instrument
    ds.product = prod_code or name_info.product
    # 文件名是 SAT96 命名（没有 _L1_ 段），级别只能从扩展段路径里取
    ds.level = name_info.level or ("L1" if "/L1/" in "".join(ext_strings) else "")
    ds.start_time = _safe_dt(*d["start_time"]) or name_info.start_time
    ds.end_time = _safe_dt(*d["end_time"]) if d["end_time"] else None

    channel = d["channel"]
    width, height = d["width"], d["height"]
    pal_len, cal_len, nav_len = d["blocks"]
    ds.attrs.update({
        "container": "awx2.1",
        "byte_order": "little-endian" if little else "big-endian",
        "format_string": fmt,
        "product_category": category,
        "product_category_name": CATEGORY_NAMES.get(category, f"未知({category})"),
        "product_type": d.get("product_type"),
        "compression": compression,
        "compression_name": COMPRESSION_NAMES.get(compression, f"未知({compression})"),
        "quality_flag": quality,
        "record_length": rec_len,
        "level1_header_length": L1_HEADER_LEN,
        "level2_header_length": l2_len,
        "level2_description_length": desc_len,
        "padding_length": pad_len,
        "header_records": n_hdr_rec,
        "header_bytes": header_bytes,
        "data_records": n_data_rec,
        "data_bytes_expected": n_data_rec * rec_len,
        "data_bytes_actual": max(0, size - header_bytes),
        "satellite_name_header": d["satellite_name"],
        "satellite_code_filename": sat_code,
        "channel": channel,
        "channel_name": CHANNEL_NAMES.get(channel, (f"CH{channel:02d}", "", ""))[0],
        "projection": d["projection"],
        "projection_name": PROJECTION_NAMES.get(d["projection"], f"未知({d['projection']})"),
        "image_width": width,
        "image_height": height,
        "upper_left_scan_line": d["scan0"],
        "upper_left_pixel": d["pixel0"],
        "sampling_rate": d["sampling"],
        "geographic_range_deg": {"north": d["bbox"][0] * 0.01, "south": d["bbox"][1] * 0.01,
                                 "west": d["bbox"][2] * 0.01, "east": d["bbox"][3] * 0.01},
        "projection_center_deg": {"lat": d["center"][0] * 0.01, "lon": d["center"][1] * 0.01},
        "standard_parallels_deg": (d["std_parallels"][0] * 0.01, d["std_parallels"][1] * 0.01),
        "resolution_km": {"x": d["resolution"][0] * 0.01, "y": d["resolution"][1] * 0.01},
        "grid_overlay": {"flag": d["grid"][0], "value": d["grid"][1]},
        "block_lengths": {"palette": pal_len, "calibration": cal_len, "navigation": nav_len},
        "extension_strings": ext_strings,
        "rgb_channels": d.get("rgb_channels"),
        "ascending": d.get("ascending"),
        "orbit_number": d.get("orbit_number"),
        "bytes_per_pixel_declared": d.get("bytes_per_pixel") or None,
    })

    # ---- 数据块（只解析声明长度 > 0 的块）
    pos = desc_len
    palette = None
    if pal_len > 0 and pos + PALETTE_LEN <= len(l2):
        palette = np.frombuffer(l2[pos:pos + PALETTE_LEN], dtype=np.uint8).reshape(3, 256).copy()
        pos += pal_len
    lut = None
    if cal_len > 0:
        n = min(cal_len, max(0, len(l2) - pos))
        if n >= 4:
            lut = it.arr16(l2[pos:pos + n], n // 2, "u2")
        pos += cal_len
    nav = _parse_nav(l2[pos:pos + nav_len], it) if nav_len >= NAV_DESC_LEN else None

    # ---- 图象数据
    ch_name, ch_desc, ch_unit = CHANNEL_NAMES.get(channel, (f"CH{channel:02d}", f"通道 {channel}", ""))
    n_px = width * height
    data_bytes = max(0, size - header_bytes)
    bpp = int(d.get("bytes_per_pixel") or 0)
    if bpp <= 0:
        bpp = 1
        if n_px and data_bytes >= n_px * 2:
            bpp = 2      # 静止图像二级头无"每像元字节数"字段 → 由数据长度反推
    dtype = np.dtype(np.uint8) if bpp == 1 else np.dtype(it.bo + "u2")

    planes: dict[str, np.ndarray] = {}
    unparsed: list[dict[str, Any]] = []
    if compression != 0:
        unparsed.append({
            "field": "图象数据段",
            "reason": f"压缩方式 {compression}（{COMPRESSION_NAMES.get(compression)}）"
                      f"未实现解压，仅保留数据段位置信息",
        })
    elif load and raster_raw and n_px:
        if channel == 0 and len(raster_raw) >= n_px * 3:
            for i, nm in enumerate(("R", "G", "B")):
                planes[nm] = np.frombuffer(raster_raw[i * n_px:(i + 1) * n_px],
                                           dtype=np.uint8).reshape(height, width).copy()
        elif len(raster_raw) >= n_px * bpp:
            planes[ch_name] = np.frombuffer(raster_raw[:n_px * bpp], dtype=dtype) \
                .reshape(height, width).copy()

    if not planes:
        # 不载数据 / 压缩 / 数据不足：仍给出形状正确的空变量
        names = [ch_name] if channel != 0 else ["R", "G", "B"]
        for nm in names:
            planes[nm] = np.empty((0,), dtype=np.uint8 if channel == 0 else dtype)

    coverage = _lut_coverage(lut)
    for nm, data in planes.items():
        ds.variables[nm] = Variable(
            name=nm,
            data=data,
            unit="count",
            long_name=f"AWX {nm}（{ch_desc}；{ds.attrs['projection_name']}）",
            valid_range=None,
            fill_value=None,
            dims=("line", "pixel"),
            source_shape=(height, width),
            attrs={
                "channel": channel,
                "channel_name": ch_name,
                "projection": d["projection"],
                "bytes_per_pixel": bpp,
                "physical_unit": ch_unit,
                "calibration_variable": "calibration_lut" if lut is not None else "",
                "calibration_coverage": coverage,
            },
        )

    cal_info: dict[str, Any] = {"present": lut is not None, "length": cal_len,
                                "coverage": coverage,
                                "unit": "0.01 " + (ch_unit or "count"),
                                "method": "physical = lut[dn] * 0.01（见 awx.to_physical）"}
    if lut is not None:
        ds.variables["calibration_lut"] = Variable(
            name="calibration_lut", data=lut.astype(np.uint16), unit="0.01",
            long_name=f"定标查找表（1024×i16，{ch_unit or '原始量'} ×0.01）",
            dims=("dn",), source_shape=(lut.size,),
            attrs={"unit_scale": 0.01, "nonzero_range": coverage},
        )
    ds.attrs["calibration"] = cal_info
    if palette is not None:
        ds.variables["palette"] = Variable(
            name="palette", data=palette, unit="", long_name="调色表 R/G/B 各 256 级",
            dims=("rgb", "level"), source_shape=(3, 256))
    ds.attrs["navigation_block"] = nav

    # ---- 定位
    ds.geolocation = _build_geo(geo, ds, nav, width, height)

    # ---- 未解析 / 待核对
    if coverage is None and lut is None:
        unparsed.append({"field": "定标数据块", "reason": "文件声明长度为 0，无定标表"})
    elif coverage is not None:
        lo, hi = coverage
        var = ds.variables.get(ch_name)
        if var is not None and var.data.size:
            over = float((var.data > hi).mean())
            if over > 0:
                unparsed.append({
                    "field": f"定标表（覆盖 DN {lo}..{hi}）",
                    "reason": f"图象 DN 最大 {int(var.data.max())}，{over * 100:.1f}% 像元超出"
                              f"定标表覆盖范围（该表按 6 bit 产品填，见文档 §4.3 说明 2），"
                              f"这些像元无法换算 → 故不填 scale_factor/add_offset，"
                              f"请用 awx.to_physical()",
                })
        else:
            unparsed.append({
                "field": f"定标表（覆盖 DN {lo}..{hi}）",
                "reason": "DN 超出覆盖范围的部分无法换算（load=False 未统计具体比例）",
            })
    if nav_len == 0:
        unparsed.append({"field": "定位数据块", "reason": "文件声明长度为 0，仅有投影参数与地理范围"})
    if 0 < cal_len != CALIB_LEN:
        unparsed.append({"field": "定标数据块长度",
                         "reason": f"声明 {cal_len} B，规范为 {CALIB_LEN} B（1024×i16）"})
    if category == 2:
        unparsed.append({"field": "极轨图像产品二级头偏移",
                         "reason": "按文档 §5.1 实现，无真实样本验证（样本反推，文档待核对）"})
    ds.attrs["unparsed"] = unparsed
    ds.attrs["notes"] = [
        "整型字段按一级头 @12 声明的字节顺序解析（样本为小端）",
        "地理范围字段样本实测需 ×0.01 才是度（文档标注单位为度，样本反推，文档待核对）",
        f"卫星名：头里 {d['satellite_name']!r}，文件名 {sat_code!r}，platform 取文件名",
        "图象数据为逐行光栅（未压缩），行号自上而下，与图幅左上角对应",
    ]
    return ds


def _parse_nav(blk: bytes, it: _Ints) -> dict[str, Any] | None:
    """定位数据块：描述部分 16 B + 网格点 (行号, 列号) i16 对。"""
    if len(blk) < NAV_DESC_LEN:
        return None
    desc = {
        "coordinate_definition": it.i16(blk, 0),     # 0 图象坐标 / 1 卫星坐标
        "source": it.i16(blk, 2),                    # 0 图象网格 / 1 星上 5 度简化网格
        "grid_degree": it.i16(blk, 4) * 0.01,
        "origin_lat": it.i16(blk, 6) * 0.01,
        "origin_lon": it.i16(blk, 8) * 0.01,
        "nx": it.i16(blk, 10),
        "ny": it.i16(blk, 12),
    }
    body = blk[NAV_DESC_LEN:]
    count = min(desc["nx"] * desc["ny"], len(body) // 4) if desc["nx"] > 0 and desc["ny"] > 0 else 0
    points = None
    if count > 0:
        points = it.arr16(body, count * 2, "i2").reshape(count, 2)
        desc["n_points"] = int(count)
    return {"description": desc, "points": points}


def _build_geo(mode: str, ds: SatDataset, nav: dict[str, Any] | None,
               width: int, height: int) -> Geolocation:
    if (mode or "nominal").lower() == "none":
        return Geolocation(kind="none")
    params: dict[str, Any] = {
        "projection": ds.attrs["projection"],
        "projection_name": ds.attrs["projection_name"],
        "center_deg": ds.attrs["projection_center_deg"],
        "standard_parallels_deg": ds.attrs["standard_parallels_deg"],
        "resolution_km": ds.attrs["resolution_km"],
        "geographic_range_deg": ds.attrs["geographic_range_deg"],
        "image_size": (width, height),
        "note": "投影参数取自二级文件头；未实现兰勃托/麦卡托反投影（规范未给椭球参数，不猜）",
    }
    if nav and nav.get("points") is not None:
        pts = nav["points"]
        params["nav_points"] = pts
        params["note"] = "定位块给出网格点的图象行列号（GLT），经纬度网格步长见 grid_degree"
        return Geolocation(kind="glt", x=pts[:, 1].copy(), y=pts[:, 0].copy(), step=1, params=params)
    return Geolocation(kind="nominal", params=params)


def load_array(path: str | Path, name: str, **kwargs: Any) -> np.ndarray:
    """按需读取单个变量（供 SatDataset.load 的按需加载分支使用）。"""
    ds = read(path, load=True, **kwargs)
    if name not in ds.variables:
        raise KeyError(f"变量不存在: {name}；可选 {list(ds.variables)}")
    return ds.variables[name].data


def list_tree(path: str | Path, max_items: int = 60) -> list[dict]:
    """列出文件结构（供 CLI `ls` / GUI 树使用，行格式与 hdf5.list_tree 一致）。"""
    ds = read(path, load=False)
    rows: list[dict] = [
        {"path": "/", "kind": "group", "attrs": len(ds.attrs)},
        {"path": "/level1_header", "kind": "group", "attrs": 9},
        {"path": "/level2_header", "kind": "group",
         "attrs": ds.attrs.get("level2_header_length", 0)},
        {"path": "/padding", "kind": "group", "attrs": ds.attrs.get("padding_length", 0)},
        {"path": "/extension", "kind": "group", "attrs": len(ds.attrs.get("extension_strings", []))},
    ]
    for var in ds.variables.values():
        rows.append({"path": "/" + var.name, "kind": "dataset", "attrs": len(var.attrs),
                     "shape": list(var.shape), "dtype": str(var.dtype)})
    return rows[:max_items]


def to_physical(ds: SatDataset, name: str | None = None) -> np.ndarray:
    """用定标表把 DN 换成物理量（反射率 % 或亮温 K）。

    定标表未覆盖的 DN（文档规定"查找不涉及的区域一律充 0"）返回 NaN ——
    宁可给 NaN，也不外推猜值。
    """
    if name is None:
        for cand in ds.variables:
            if cand not in ("calibration_lut", "palette"):
                name = cand
                break
    if name is None or name not in ds.variables:
        raise KeyError(f"找不到图象变量：{name}")
    if "calibration_lut" not in ds.variables:
        raise KeyError("该文件没有定标数据块，无法换算物理量")
    lut = ds.variables["calibration_lut"].data.astype(np.float32)
    dn = ds.variables[name].data
    out = np.full(dn.shape, np.nan, dtype=np.float32)
    if dn.size == 0:
        return out
    coverage = _lut_coverage(lut.astype(np.uint16))
    inside = np.zeros(dn.shape, dtype=bool)
    if coverage is not None:
        inside = dn <= coverage[1]
    idx = np.where(inside, dn, 0)
    vals = lut[idx] * np.float32(0.01)
    out[inside] = vals[inside]
    return out

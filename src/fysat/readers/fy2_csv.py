"""FY-2 压缩 S-VISSR（CSV / ``CSVS V1.0``）数据集容器读取器。

字节级结构（由 28 个真实样本反推，并与官方文档互验）
-------------------------------------------------------
* 文件 = N 个 **定长 41260 字节** 记录首尾相接，无额外前缀／后缀::

      103_191_260 B = 2501 × 41260 B      ← 全部 28 个样本都是这个尺寸

  记录 0 为元数据记录（Table 4.20），记录 1..N-1 各为一条扫描行。

* 文档里 ``Record length RECL=41257`` 指的是**数据区**长度，
  加上 2 字节记录号 + 1 字节质量码才是磁盘上的 41260。

* 每条数据记录的段表（偏移相对记录起点，已逐字节核对）::

        0      2   记录号    u16 BE，1..2500
        2      1   质量码    u8，0 = 正常
        3   2293   DOC 段     段标志 00 01 + 2291 B S-VISSR 文档扇区
     2296   2866   IR1       段标志 00 02 + 2291 × 10 bit（MSB 优先）+ 2 bit 填充
     5162   2866   IR2       段标志 00 03
     8028   2866   IR3       段标志 00 04
    10894   2866   IR4       段标志 00 05
    13760   6875   VIS1      段标志 00 06 + 9164 × 6 bit
    20635   6875   VIS2      段标志 00 07
    27510   6875   VIS3      段标志 00 08
    34385   6875   VIS4      段标志 00 09
    41260  ── 记录结束

  2293 + 4×2866 + 4×6875 = 41257 ✓（与 Table 4.19/4.21/4.22/4.23 完全一致）

* 警告：文件前 4 个字节按大端整数读出来是 70 只是巧合
  （记录号 ``0000`` + 质量码 ``00`` + 文件名的首字母 ``'F'``=0x46），
  **不存在长度前缀**。

DOC 段（``rec[3:2296]``，去掉 2 字节段标志后 2291 字节 = S-VISSR 文档扇区）
--------------------------------------------------------------------------
======  ===========================================================
偏移     内容（实测取值已验证）
======  ===========================================================
0..1     段内头（实测 ``00 33``，文档未定义）
2        图像标志（picture flag），0xFF = 本行含图像数据
3        帧标志（frame flag）
10..14   地球东西边缘像素号（u16 BE；0xFFFF = 未检测到该边缘）
14       同步锁 Q/D（0 = 正常）
17..25   本行观测时刻，8 字节 BCD：``YYYY MM DD hh mm ss cc``（cc = 1/100 秒）
65..67   扫描行号 u16 BE，1..2500（与记录号一致）
190..194 子交换 ID：``00 | 组号 0..24 | 00 | 重复号 0..7``（每 200 行轮完一轮）
194..294 简化映射块（一组 100 B；25 组合并 = 2500 B = 625 个网格点）
294..422 轨道／姿态块（一组 128 B）
422..832 MANAM 块（一组 410 B，ASCII）
832..1088 定标块 1（一组 256 B）
1088..2112 定标块 2（一组 1024 B）
======  ===========================================================

映射块（Table 11）：25×25 个网格点 = 纬度 60°N→60°S（步长 5°）× 经度 45°E→165°E
（步长 5°），每点 4 字节 = (行号 u16 BE, 像素号 u16 BE)。

物理量说明
----------
定标块 2 中本应给出 64 级 VIS 反照率表与 1024 级 IR 亮温表，但**业务文件里这两张表
全为 0**（实测 4 个 VIS + 4 个 IR 查找表全零），因此只能给出原始 DN；
无法从容器内推导亮温/反照率，故 ``unit="DN"``、不给 ``scale_factor``。

同理，本例 CSV 容器**没有 DN 填充值**（Table 4.19~4.23 未定义，实测也无哨兵值），
``fill_value`` 留空；无效行由 ``line_quality`` / ``picture_flag`` / ``scan_count``
三个 1 维变量标识，需要掩膜时用它们，不要臆造填充值。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..model import Geolocation, SatDataset, Variable

# ---------------------------------------------------------------- 容器常量

RECORD_LEN = 41260              # 记录长度（含记录号、质量码）
DOC_OFFSET = 3                  # DOC 段在记录内的偏移
DOC_LEN = 2293                  # DOC 段长度（2 字节段标志 + 2291 字节文档）
DOC_HEAD = 2                    # 段标志长度

IR_PIXELS = 2291                # 每条红外扫描行的像素数
VIS_PIXELS = 9164               # 每条可见光扫描行的像素数（= 4 × 2291）
IR_BITS = 10
VIS_BITS = 6

# (段名, 记录内偏移, 段长, 每像素位数, 像素数)  —— 偏移与长度之和必须等于 41260
SEGMENTS: tuple[tuple[str, int, int, int, int], ...] = (
    ("IR1", 2296, 2866, IR_BITS, IR_PIXELS),
    ("IR2", 5162, 2866, IR_BITS, IR_PIXELS),
    ("IR3", 8028, 2866, IR_BITS, IR_PIXELS),
    ("IR4", 10894, 2866, IR_BITS, IR_PIXELS),
    ("VIS1", 13760, 6875, VIS_BITS, VIS_PIXELS),
    ("VIS2", 20635, 6875, VIS_BITS, VIS_PIXELS),
    ("VIS3", 27510, 6875, VIS_BITS, VIS_PIXELS),
    ("VIS4", 34385, 6875, VIS_BITS, VIS_PIXELS),
)
CHANNELS: tuple[str, ...] = tuple(s[0] for s in SEGMENTS)

# 元数据记录（Table 4.20 / FY2C_CSV_FIRST_LINE）的 ASCII 字段：名 -> (偏移, 长度)
META_TEXT_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("file_name", 3, 40),
    ("format", 44, 4),
    ("version", 49, 4),
    ("producer", 54, 8),
    ("obs_time", 63, 15),
    ("gen_time", 79, 15),
    ("satellite", 95, 5),
    ("instrument", 101, 5),
    ("record_length", 107, 5),
    ("record_count", 113, 4),
    ("quality_id", 118, 4),
)

# 质量信息段（Table 4.24）
META_QUAL_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("first_row_no", 124, 4),
    ("first_row_time", 128, 16),
    ("last_row_no", 144, 4),
    ("last_row_time", 148, 16),
    ("total_scanned_rows", 164, 4),
    ("corrected_row_count", 168, 4),
    ("corrected_time_count", 172, 4),
    ("throw_lines", 177, 4),
    ("error_rate", 181, 4),
    ("file_quality", 185, 4),
)
META_SDB_FLAG = 176             # 1 字节：S/DB 预报图像是否成功
META_LINE_QUALITY_OFFSET = 189  # 每行综合质量码，2500 字节
META_LINE_QUALITY_LEN = 2500
META_RESERVED_ESC = 2689        # 其后为 38571 字节 0x20 填充

# DOC 段（去掉段标志后 doc[0:] 对应 S-VISSR 文档扇区字节 3..，见模块文档）
DOC_PICTURE_FLAG = 2
DOC_FRAME_FLAG = 3
DOC_WEST_EDGE = (10, 12)
DOC_EAST_EDGE = (12, 14)
DOC_SYNC_LOCK = 14
DOC_TIME_BCD = (17, 25)
DOC_SCAN_COUNT = (65, 67)
DOC_SUBCOMM = (190, 194)
DOC_MAPPING = (194, 294)        # 简化映射块（一组 100 字节）
SUBCOMM_GROUPS = 25
SUBCOMM_REPEATS = 8

EDGE_UNDETECTED = 0xFFFF

# 简化映射网格：60°N → 60°S、45°E → 165°E，步长 5°，25×25
NAV_LAT0, NAV_LAT1, NAV_LAT_STEP = 60.0, -60.0, -5.0
NAV_LON0, NAV_LON1, NAV_LON_STEP = 45.0, 165.0, 5.0

CHUNK_RECORDS = 64              # 分批解码的记录数（控制内存）

# 段标志校验表：段名 -> 段号（Table 4.21~4.23 注）
SEGMENT_IDS = {"DOC": 1, "IR1": 2, "IR2": 3, "IR3": 4, "IR4": 5,
               "VIS1": 6, "VIS2": 7, "VIS3": 8, "VIS4": 9}


# ---------------------------------------------------------------- 小工具


def _text(raw: bytes) -> str:
    """把定长 ASCII 字段转成 str（去掉 NUL 与空格填充）。"""
    return raw.decode("ascii", "replace").replace("\x00", " ").strip()


def _int(raw: bytes | str) -> int | None:
    """解析数字字段，非数字返回 None。"""
    t = _text(raw) if isinstance(raw, bytes) else raw.strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _bcd(raw: bytes) -> int:
    """两字节以内的高低位压缩 BCD → 十进制整数。"""
    value = 0
    for byte in raw:
        hi, lo = byte >> 4, byte & 0x0F
        if hi > 9 or lo > 9:
            raise ValueError(f"非法 BCD 字节 0x{byte:02x}")
        value = value * 100 + hi * 10 + lo
    return value


def _parse_ascii_time(raw: bytes) -> datetime | None:
    """解析 ``YYYYMMDDhhmmss`` / ``YYYYMMDDhhmmsscc`` 形式的 ASCII 时刻。"""
    t = _text(raw)
    if len(t) < 14 or not t[:14].isdigit():
        return None
    try:
        dt = datetime.strptime(t[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if len(t) >= 16 and t[14:16].isdigit():          # cc = 1/100 秒
        dt = dt.replace(microsecond=int(t[14:16]) * 10000)
    return dt


def _parse_bcd_time(raw: bytes) -> datetime | None:
    """解析 DOC 里 8 字节 BCD 时刻 ``YYYY MM DD hh mm ss cc``。"""
    if len(raw) < 8:
        return None
    try:
        year, month, day, hour, minute, second, cs = (
            _bcd(raw[0:2]), _bcd(raw[2:3]), _bcd(raw[3:4]), _bcd(raw[4:5]),
            _bcd(raw[5:6]), _bcd(raw[6:7]), _bcd(raw[7:8]),
        )
        return datetime(year, month, day, hour, minute, second, cs * 10000)
    except ValueError:
        return None


def _bcd_array(raw: np.ndarray) -> np.ndarray:
    """向量化 BCD 数组解码：输入 (n, k) uint8 → 输出 (n,) int64（非法处置 -1）。"""
    n, k = raw.shape
    digits = np.empty((n, k * 2), dtype=np.int64)
    digits[:, 0::2] = raw >> 4
    digits[:, 1::2] = raw & 0x0F
    ok = digits < 10
    value = np.zeros(n, dtype=np.int64)
    for col in range(k * 2):
        value = value * 10 + np.where(ok[:, col], digits[:, col], 0)
    value[~ok.all(axis=1)] = -1
    return value


def _unpack_bits(raw: np.ndarray, nbits: int, count: int) -> np.ndarray:
    """MSB 优先的定长位流解包。

    raw : (n, bytes) uint8，**已跳过段标志**（调用方保证 payload 足够长）
    -> (n, count) uint16
    """
    bits = np.unpackbits(raw, axis=1, bitorder="big")[:, : nbits * count]
    out = np.zeros((raw.shape[0], count), dtype=np.uint16)
    for k in range(nbits):
        out = (out << 1) | bits[:, k::nbits]
    return out


def _check_layout() -> None:
    """段表自检：最后一段必须正好结束在 41260。"""
    end = DOC_OFFSET + DOC_LEN
    for name, off, length, _, _ in SEGMENTS:
        if off < end:
            raise AssertionError(f"{name} 段与前一段重叠")
        end = off + length
    if end != RECORD_LEN:
        raise AssertionError(f"段表合计 {end} != 记录长度 {RECORD_LEN}")


_check_layout()


# ---------------------------------------------------------------- 元数据记录


def parse_meta(record: bytes) -> dict[str, Any]:
    """解析记录 0（元数据记录，Table 4.20）。"""
    if len(record) < RECORD_LEN:
        raise ValueError(f"元数据记录长度不足（{len(record)} < {RECORD_LEN}）")

    raw: dict[str, Any] = {}
    for name, off, length in META_TEXT_FIELDS:
        raw[name] = _text(record[off:off + length])

    quality: dict[str, Any] = {}
    for name, off, length in META_QUAL_FIELDS:
        cell = record[off:off + length]
        quality[name] = _text(cell)
        if name.endswith("_time"):
            quality[name.replace("_time", "_datetime")] = _parse_ascii_time(cell)

    line_quality = np.frombuffer(
        record[META_LINE_QUALITY_OFFSET:META_LINE_QUALITY_OFFSET + META_LINE_QUALITY_LEN],
        dtype=np.uint8,
    )
    return {
        "record_no": int.from_bytes(record[0:2], "big"),
        "record_quality": int(record[2]),
        **raw,
        "obs_datetime": _parse_ascii_time(record[63:78]),
        "gen_datetime": _parse_ascii_time(record[79:94]),
        "sdb_flag": int(record[META_SDB_FLAG]),
        "quality": quality,
        "line_quality": line_quality,
        "line_quality_nonzero": int(np.count_nonzero(line_quality)),
        "reserved_fill": sorted(set(record[META_RESERVED_ESC:])),
    }


# ---------------------------------------------------------------- DOC 段


def parse_doc(segment: bytes) -> dict[str, Any]:
    """解析一条扫描行的 DOC 段（含 2 字节段标志）。"""
    doc = segment[DOC_HEAD:]
    west = int.from_bytes(doc[DOC_WEST_EDGE[0]:DOC_WEST_EDGE[1]], "big")
    east = int.from_bytes(doc[DOC_EAST_EDGE[0]:DOC_EAST_EDGE[1]], "big")
    counts = doc[DOC_SUBCOMM[0]:DOC_SUBCOMM[1]]
    return {
        "segment_flag": (segment[0], segment[1]),
        "picture_flag": int(doc[DOC_PICTURE_FLAG]),
        "frame_flag": int(doc[DOC_FRAME_FLAG]),
        "sync_lock": int(doc[DOC_SYNC_LOCK]),
        "scan_count": int.from_bytes(doc[DOC_SCAN_COUNT[0]:DOC_SCAN_COUNT[1]], "big"),
        "west_edge": west,
        "east_edge": east,
        "obstime": _parse_bcd_time(doc[DOC_TIME_BCD[0]:DOC_TIME_BCD[1]]),
        "subcomm_group": int(counts[1]),
        "subcomm_repeat": int(counts[3]),
        "mapping_group": bytes(doc[DOC_MAPPING[0]:DOC_MAPPING[1]]),
    }


# ---------------------------------------------------------------- 定位


def nav_grid(path: str | Path) -> dict[str, Any]:
    """从 DOC 简化映射块还原 25×25 的 (纬度, 经度) → (行, 像素) 对照网格。

    映射块按子交换技术分 25 组下发，每组 100 字节 = 25 个点 × 4 字节，
    每 8 行重复一次，200 行收齐一轮；这里取重复号 0 的 25 组拼接。
    """
    p = Path(path)
    size = p.stat().st_size
    n_rec = size // RECORD_LEN
    if n_rec <= 1:
        return {}

    groups: dict[int, bytes] = {}
    with open(p, "rb") as fh:
        for i in range(1, min(n_rec, 1 + SUBCOMM_GROUPS * SUBCOMM_REPEATS)):
            fh.seek(i * RECORD_LEN + DOC_OFFSET + DOC_HEAD)
            doc = fh.read(DOC_LEN - DOC_HEAD)
            if len(doc) < DOC_MAPPING[1]:
                break
            group = int(doc[DOC_SUBCOMM[0] + 1])
            repeat = int(doc[DOC_SUBCOMM[0] + 3])
            if repeat == 0 and group < SUBCOMM_GROUPS and group not in groups:
                groups[group] = bytes(doc[DOC_MAPPING[0]:DOC_MAPPING[1]])
            if len(groups) == SUBCOMM_GROUPS:
                break

    if len(groups) != SUBCOMM_GROUPS:
        return {}

    block = b"".join(groups[k] for k in range(SUBCOMM_GROUPS))
    pts = np.frombuffer(block, dtype=">u2").astype(np.float32).reshape(SUBCOMM_GROUPS, SUBCOMM_GROUPS, 2)
    lat = np.linspace(NAV_LAT0, NAV_LAT1, SUBCOMM_GROUPS, dtype=np.float32)
    lon = np.linspace(NAV_LON0, NAV_LON1, SUBCOMM_GROUPS, dtype=np.float32)
    return {
        "lat": lat,
        "lon": lon,
        "line": np.ascontiguousarray(pts[:, :, 0]),
        "pixel": np.ascontiguousarray(pts[:, :, 1]),
    }


def _geolocation(path: Path, n_lines: int) -> Geolocation:
    grid = nav_grid(path)
    params: dict[str, Any] = {
        "projection": "geostationary full-disc (S-VISSR 简化映射块)",
        "n_lines": n_lines,
        "ir_pixels": IR_PIXELS,
        "vis_pixels": VIS_PIXELS,
        "vis_to_ir_scale": VIS_PIXELS // IR_PIXELS,
    }
    if grid:
        params.update({
            "grid_lat": grid["lat"],
            "grid_lon": grid["lon"],
            "grid_line": grid["line"],
            "grid_pixel": grid["pixel"],
            "grid_shape": tuple(int(v) for v in grid["line"].shape),
            "grid_note": "纬度 60°N→60°S、经度 45°E→165°E，步长 5°；"
                         "grid_line/grid_pixel 为该网格点在 2500×2291 红外网格上的行列号，"
                         "可见光像素号 = 红外像素号 × 4",
        })
        kind = "glt"
    else:
        kind = "nominal"
    return Geolocation(kind=kind, step=1, params=params)


# ---------------------------------------------------------------- 主读取器


def _read_channel_arrays(path: Path, n_lines: int, wanted: set[str]) -> dict[str, np.ndarray]:
    """一次顺序扫描，把需要的通道解成 (lines, pixels)。"""
    dtype = {name: np.uint16 if bits >= 9 else np.uint8 for name, _, _, bits, _ in SEGMENTS}
    out: dict[str, np.ndarray] = {}
    for name, _, _, _bits, count in SEGMENTS:
        if name in wanted:
            out[name] = np.empty((n_lines, count), dtype=dtype[name])

    todo = [s for s in SEGMENTS if s[0] in wanted]
    with open(path, "rb") as fh:
        for start in range(0, n_lines, CHUNK_RECORDS):
            stop = min(start + CHUNK_RECORDS, n_lines)
            n = stop - start
            fh.seek((start + 1) * RECORD_LEN)          # 跳过记录 0
            buf = np.frombuffer(fh.read(n * RECORD_LEN), dtype=np.uint8)
            if buf.size != n * RECORD_LEN:
                raise ValueError("文件被截断，记录数不足")
            rows = buf.reshape(n, RECORD_LEN)
            for name, off, length, bits, count in todo:
                block = rows[:, off + DOC_HEAD:off + length]
                out[name][start:stop] = _unpack_bits(block, bits, count)
    return out


def _read_line_meta(path: Path, n_lines: int) -> dict[str, np.ndarray]:
    """扫描所有记录的 DOC 头部，取逐行元信息（不需要整段数据）。"""
    scan_count = np.zeros(n_lines, dtype=np.uint16)
    quality = np.zeros(n_lines, dtype=np.uint8)
    picture = np.zeros(n_lines, dtype=np.uint8)
    west = np.zeros(n_lines, dtype=np.uint16)
    east = np.zeros(n_lines, dtype=np.uint16)
    time_cs = np.full(n_lines, -1, dtype=np.int64)     # 未填 = -1

    with open(path, "rb") as fh:
        for start in range(0, n_lines, CHUNK_RECORDS):
            stop = min(start + CHUNK_RECORDS, n_lines)
            n = stop - start
            fh.seek((start + 1) * RECORD_LEN)
            buf = np.frombuffer(fh.read(n * RECORD_LEN), dtype=np.uint8)
            rows = buf.reshape(n, RECORD_LEN)
            quality[start:stop] = rows[:, 2]
            doc = rows[:, DOC_OFFSET + DOC_HEAD:DOC_OFFSET + DOC_HEAD + 128]
            picture[start:stop] = doc[:, DOC_PICTURE_FLAG]
            west[start:stop] = doc[:, DOC_WEST_EDGE[0]:DOC_WEST_EDGE[1]].reshape(n, 2) @ np.array([256, 1])
            east[start:stop] = doc[:, DOC_EAST_EDGE[0]:DOC_EAST_EDGE[1]].reshape(n, 2) @ np.array([256, 1])
            scan_count[start:stop] = doc[:, DOC_SCAN_COUNT[0]:DOC_SCAN_COUNT[1]].reshape(n, 2) @ np.array([256, 1])
            # 8 字节 BCD -> YYYYMMDDhhmmsscc 的数值形（仅用于排序/取差值）
            time_cs[start:stop] = _bcd_array(
                doc[:, DOC_TIME_BCD[0]:DOC_TIME_BCD[1]].reshape(n, 8)
            )
    return {
        "scan_count": scan_count,
        "line_quality": quality,
        "picture_flag": picture,
        "earth_edge_west": west,
        "earth_edge_east": east,
        "obstime_bcd": time_cs,
    }


_EPOCH = datetime(1970, 1, 1)


def _bcd_to_epoch_seconds(codes: np.ndarray) -> np.ndarray:
    """把 ``YYYYMMDDhhmmsscc`` 的十进制数拆成 POSIX 秒（非法值置 NaN）。"""
    out = np.full(codes.shape, np.nan, dtype=np.float64)
    for i, code in enumerate(codes.tolist()):
        if code < 0:
            continue
        try:
            year = code // 10 ** 12
            month = code // 10 ** 10 % 100
            day = code // 10 ** 8 % 100
            hour = code // 10 ** 6 % 100
            minute = code // 10 ** 4 % 100
            second = code // 100 % 100
            cs = code % 100
            dt = datetime(year, month, day, hour, minute, second, cs * 10000)
        except ValueError:
            continue
        out[i] = (dt - _EPOCH).total_seconds()
    return out


def read(path: str | Path, load: bool = True, channels: list[str] | None = None,
         nav: bool = True) -> SatDataset:
    """读取 FY-2 CSV 数据集容器，返回统一数据模型。

    参数
    ----
    load      : True 时解码全部通道数据；False 时只解析头部（变量 data 为空、
                但 ``source_shape`` 保留真实形状，``fysat.cli info`` 用这个模式）。
    channels  : 只加载这些通道（默认全部 IR1~IR4 / VIS1~VIS4）。
    nav       : 是否解析 DOC 简化映射块来构建定位信息。
    """
    p = Path(path)
    size = p.stat().st_size
    n_rec, remainder = divmod(size, RECORD_LEN)
    if remainder:
        raise ValueError(
            f"{p.name}: 文件长度 {size} 不是 {RECORD_LEN} 的整数倍（余 {remainder}），"
            "不符合 FY-2 CSV 容器格式"
        )
    if n_rec < 2:
        raise ValueError(f"{p.name}: 只有 {n_rec} 条记录，缺少元数据记录或数据记录")

    n_lines = n_rec - 1
    with open(p, "rb") as fh:
        meta = parse_meta(fh.read(RECORD_LEN))
        head = fh.read(RECORD_LEN)                     # 记录 1：用于取段标志与样例 DOC
    sample_doc = parse_doc(head[DOC_OFFSET:DOC_OFFSET + DOC_LEN])

    ds = SatDataset(source=p, reader="fy2_csv")
    ds.platform = meta["satellite"] or ""
    ds.instrument = meta["instrument"] or ""
    ds.level = "L1"                                    # CSV 归档的是 S-VISSR L1 数据
    ds.product = "CSV"
    ds.start_time = meta["obs_datetime"]
    ds.end_time = meta["quality"].get("last_row_datetime") or meta["obs_datetime"]

    ds.attrs = {
        "container": "FY-2 CSV (CSVS V1.0)",
        "file_name": meta["file_name"],
        "format": meta["format"],
        "version": meta["version"],
        "producer": meta["producer"],
        "observation_time": meta["obs_time"],
        "generation_time": meta["gen_time"],
        "satellite": meta["satellite"],
        "instrument": meta["instrument"],
        "record_length": _int(meta["record_length"]) or RECORD_LEN,
        "record_count": _int(meta["record_count"]) or n_lines,
        "quality_id": meta["quality_id"],
        "records_in_file": n_rec,
        "scan_lines": n_lines,
        "file_size": size,
        "sdb_flag": meta["sdb_flag"],
        "quality": {k: v for k, v in meta["quality"].items() if not k.endswith("_datetime")},
        "line_quality_nonzero_rows": meta["line_quality_nonzero"],
        "sample_doc": {k: v for k, v in sample_doc.items() if k != "mapping_group"},
        "calibration_tables_present": False,
        "calibration_note": "DOC 定标块 2 的 VIS 反照率表与 IR 亮温表在业务文件中全为 0，"
                            "故只提供原始 DN；无法从容器内推导物理量。",
    }

    wanted = set(CHANNELS) if channels is None else {c.upper() for c in channels}
    unknown = wanted - set(CHANNELS)
    if unknown:
        raise KeyError(f"未知通道 {sorted(unknown)}，可选 {list(CHANNELS)}")

    arrays = _read_channel_arrays(p, n_lines, wanted) if load else {}
    for name, off, length, bits, count in SEGMENTS:
        is_ir = name.startswith("IR")
        dtype = np.uint16 if bits >= 9 else np.uint8
        data = arrays.get(name, np.empty((0,), dtype=dtype))
        ds.variables[name] = Variable(
            name=name,
            data=data,
            unit="DN",
            long_name=f"{name} {'10' if is_ir else '6'}-bit raw digital number",
            valid_range=(0.0, float((1 << bits) - 1)),
            fill_value=None,          # 容器未定义填充值，见模块文档
            dims=("line", "pixel"),
            source_shape=(n_lines, count),
            attrs={
                "segment": name,
                "segment_flag": SEGMENT_IDS[name],
                "record_offset": off,
                "segment_length": length,
                "bits_per_pixel": bits,
                "pixels_per_line": count,
                "quantization_levels": 1 << bits,
                "calibrated": False,
            },
        )

    # 逐行元信息只有 n_lines（2500）个元素，代价可忽略；
    # 无论 load 与否都必须读出来 —— 它们是产品定义里的正式字段，
    # 而 read_variable 只认得 8 个图像通道名，取不到就会报「变量不存在」。
    lines = _read_line_meta(p, n_lines)
    per_line: tuple[tuple[str, np.dtype, str, str, tuple[float, float] | None], ...] = (
        ("scan_count", np.dtype(np.uint16), "1", "DOC 扫描行号（1..2500）", (1.0, 2500.0)),
        ("line_quality", np.dtype(np.uint8), "1", "CSV 记录质量码（0 = 正常）", (0.0, 255.0)),
        ("picture_flag", np.dtype(np.uint8), "1", "DOC 图像标志（0xFF = 含图像数据）", (0.0, 255.0)),
    )
    for name, dtype, unit, long_name, valid in per_line:
        ds.variables[name] = Variable(
            name=name,
            data=(lines[name] if lines is not None else np.empty((0,), dtype=dtype)),
            unit=unit,
            long_name=long_name,
            valid_range=valid,
            fill_value=None,
            dims=("line",),
            source_shape=(n_lines,),
            attrs={"source": "DOC 段" if name != "line_quality" else "记录第 3 字节"},
        )
    for name, long_name in (("earth_edge_west", "地球西边缘像素号"),
                            ("earth_edge_east", "地球东边缘像素号")):
        ds.variables[name] = Variable(
            name=name,
            data=(lines[name] if lines is not None else np.empty((0,), dtype=np.uint16)),
            unit="pixel",
            long_name=long_name,
            valid_range=(0.0, float(IR_PIXELS)),
            fill_value=float(EDGE_UNDETECTED),      # 0xFFFF = 未检测到边缘（文档明示）
            dims=("line",),
            source_shape=(n_lines,),
            attrs={"source": "DOC 段", "undefined": EDGE_UNDETECTED},
        )

    obstime = (_bcd_to_epoch_seconds(lines["obstime_bcd"]) if lines is not None
               else np.empty((0,), dtype=np.float64))
    ds.variables["line_time"] = Variable(
        name="line_time",
        data=obstime,
        unit="s since 1970-01-01 00:00:00",
        long_name="本行观测时刻（DOC 内 8 字节 BCD）",
        valid_range=(0.0, 4102444800.0),      # 1970-01-01 .. 2100-01-01
        fill_value=float("nan"),
        dims=("line",),
        source_shape=(n_lines,),
        attrs={
            "source": "DOC 段",
            "bcd_field": "YYYYMMDDhhmmsscc",
            "tz_note": "直接按文件内 BCD 时刻与 1970-01-01 相减，不做时区换算",
        },
    )

    ds.geolocation = _geolocation(p, n_lines) if nav else Geolocation(kind="nominal")
    return ds


def scan_line_records(path: str | Path) -> np.ndarray:
    """逐行元信息的结构化数组（扫描行号 / 质量码 / 图像标志 / 时刻 / 边缘 / 子交换）。"""
    p = Path(path)
    n_lines = p.stat().st_size // RECORD_LEN - 1
    lines = _read_line_meta(p, n_lines)
    dtype = [
        ("scan_count", "u2"), ("line_quality", "u1"), ("picture_flag", "u1"),
        ("earth_edge_west", "u2"), ("earth_edge_east", "u2"),
        ("obstime_bcd", "i8"), ("obstime", "O"),
    ]
    out = np.zeros(n_lines, dtype=dtype)
    for name in ("scan_count", "line_quality", "picture_flag",
                 "earth_edge_west", "earth_edge_east", "obstime_bcd"):
        out[name] = lines[name]
    out["obstime"] = _bcd_to_epoch_seconds(lines["obstime_bcd"])
    return out


def read_variable(path: str | Path, name: str) -> np.ndarray:
    """按需读取单个通道（等价于 ``read(path)[name].data``，但只解码一个通道）。"""
    key = name.upper()
    if key not in CHANNELS:
        raise KeyError(f"变量不存在: {name}；可选 {list(CHANNELS)}")
    p = Path(path)
    n_lines = p.stat().st_size // RECORD_LEN - 1
    return _read_channel_arrays(p, n_lines, {key})[key]

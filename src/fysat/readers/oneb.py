"""1B 定长字节记录读取器（HRPT L1B）—— 支持 FY-1C/D 与 NOAA-K/L/M/N 两种变体。

本模块的字段偏移全部来自对真实样本的字节级探针，不依赖文档猜测；与文档冲突处
一律以样本为准，并在下方注明「样本反推，文档待核对」。

============================================================================
变体 A：FY-1C/D（`SMC.HRPT` TBM 头）—— 样本 FY1D_AVHRR_HRPT_L1_…_20120329_0743_1100M_PJ.L1B
============================================================================
文件 = 定长记录 28400 字节 × N（样本 128623600 B = 28400 × 4529）：

    记录 0      TBM 头（ASCII + 空格/NUL 填充，有效 122 B）
    记录 1      数据头（大端二进制）
    记录 2..N-1 数据记录，每条扫描线一条

* 记录长度 28400 与 FY-1（02）批 1B 文档一致（`fy1_02_1b_format.md` §3.1），
  且 128623600 / 28400 = 4529 整除 —— 双重确认，非猜测。
* TBM 头（样本实测）：
    [0:30]   空格；[30:74] 数据集名 "SMC.HRPT.\\0\\0\\0\\012089.S0743.E0756.B2079494.PP."
    [74:97]  文本字段 "T014061007501250743013"（起始/结束经纬、时分、时段）
    [96]     增加数据选择 'Y'；[97:117] 通道选择 "1111111111" + 空格
    [400:414] TBM 文件名 "p1bm2974.f1d"（Polar-1B 生成系统命名）
* 数据头记录（大端，0 based 偏移）：
    @0 u8 卫星标识（样本 114 = FY-1D，见文档 §3.2 表 "FY-1D: 114"）
    @1 u8 资料类型  @2 i16 年开始年（样本 12）  @4 i16 日计数（样本 89）
    @6 i32 开始毫秒    @10 i16 扫描线数（样本 4526；实际记录 4527 条）
    @12 i16 结束年  @14 i16 结束日计数  @16 i32 结束毫秒
    @198 i16 轨道号  @200..211 i16×6 历元 年月日时分秒(秒×100)
    @212 i32 半长轴(×1e-3 km, 样本 7236908 → 7236.9 km)
    @216 i32 偏心率(×1e-8)  @220 i32 倾角(×1e-6 度)  @224 升交点赤经  @228 近地点幅角
    @232 i32 平近点角(×1e-6 度)  @236 i32 轨道周期  @240 i16 轨道数  @242 i16 升降轨
    @244..255 i32×3 姿态角(×1e-6 度)   @256..287 i32×8 四角点经纬度(×1e-4 度, lat/lon 交替)
* 数据记录（0 based）：
    @0 i16 扫描线号  @2 i16 年  @4 i16 日计数  @6 i32 毫秒  @10 u16 质量标记
    @16 i32×10 定标斜率  @56 i32×10 定标截距   （文档 §3.1 3) 的镜像，实测吻合）
    @96  i16×51 太阳天顶角(×1/128 度)   @198 i16×51 卫星天顶角
    @300 i16×51 太阳相对卫星方位角     @402 i16×51×2 定位点经纬度（**lat/lon 交替**，×1/128 度）
    @608 300 B HRPT 帧遥测（本读取器不解，记入 attrs["unparsed"]）
    @1000 27308 B = 6827 字 × 4 B → 每字 3 个 10 bit 样本，**填充位在高 2 bit**
          （样本反推：bit 31..30 恒为 0；样本 = bit29..20 / bit19..10 / bit9..0）
          2048 像元 × 10 通道，**像元优先交织**（每像元依次 ch1..ch10），
          最后 1 字只含 2 个样本（ch9/ch10），故有效样本 20480 个。
* 定位点与像元对应：文档未给出 51 个定位点的像元号；样本反推为 25 + 40·k
  （k=0..50 → 25..2025），与 NOAA 文档明确的取点规则一致，「样本反推，文档待核对」。
* 定标：`@16/@56` 的 20 个 i32 用文档给出的 2^-30 / 2^-22 缩放**无法**得到自洽的
  物理量（通道 2/4/5 增益为负、通道 8/10 得 600% 反射率），本读取器**不做物理定标**，
  只把系数原样放进 attrs["calibration"]，并把该字段记入 attrs["unparsed"]。

============================================================================
变体 B：NOAA-K/L/M/N（`/N1BD/…` 数据集名）—— 样本 NA18_AVHRR_HRPT_L1_…_20180308_0054_1100M_PJ.L1B
============================================================================
文件 = 定长记录 22016 字节 × N（样本 99908608 B = 22016 × 4538）：

    记录 0      头记录（1 条，字段 "头记录所占记录数" 实测 = 1）
    记录 1..N-1 数据记录，每条扫描线一条（样本 4537 条，扫描线号 1..4537 连续）

* 22016 = 0x5600 正好是头记录 @10 i16「逻辑记录长度」的实测值 → 结构自证。
* 头记录（大端）：
    @4 i16 格式版本  @6 i16 版本年(2005)  @8 i16 版本日(167)  @10 i16 记录长度(22016)
    @14 i16 头记录数(1)  @22:64 C*42 数据集名 "/N1BD/N18/NOAA18_AVHRR_CHINA_L1_2018…"
    @72 i16 NOAA 星标识（样本 13 → NOAA-18；文档示例 "4 = NOAA-15" 与本样本不符，
        以数据集名 "/N18/" "NOAA18" 为准，「样本反推，文档待核对」）
    @74 i16 仪器标识  @76 i16 数据类型（3 = HRPT）  @78 i16 TIP 原码
    @80 i32 开始日(自1950-01-01，样本 24904) @84 i16 年(2018) @86 i16 日计数(67) @88 i32 毫秒
    @92..103 结束日/年/日计数/毫秒；@104..107 末次 CPIDS 年/日计数
    @128 i16 扫描线数(4537) @130 i16 定标定位扫描线数(4537)
    @256..316 辐射转换系数（CH1/2/3a 太阳辐照度与等效带宽；CH3b/4/5 中心波数）
    @328:336 C*8 参考椭球 "WGS-72  "  @348 i16 历元年 @350 i16 历元日计数
    @356 i32 半长轴(×1e-5 km) @360 i32 偏心率(×1e-8) @364 i32 倾角(×1e-5 度)
* 数据记录（0 based）：
    @0 i16 扫描线号 @2 i16 年 @4 i16 日计数 @6 i16 时钟漂移(ms) @8 i32 UTC 毫秒
    @12 u16 bit0=CH3 选择(0=3A,1=3B) bit15=升降轨(1=降轨) bit14 时钟修正 bit13 TIP 姿态
    @24/@28 u32 质量标记  @48 i32×45 可见光定标（3 通道 × 3 组 × 5 系数）
    @228 i32×18 红外定标（3 通道 × 2 组 × 3 系数）
    @320 i16×3 姿态角(×1e-3 度) @326 i16 平均高度(×10 km)
    @328 i16×153 = 51 点 ×（太阳天顶角, 卫星天顶角, 相对方位角），×0.01 度
    @640 i32×102 = 51 点 ×（纬度, 经度）**交替**，×1e-4 度（N/E 为正）
    @1056 206 B HRPT 副帧遥测（不解，记入 attrs["unparsed"]）
    @1264 20480 B = 2048 像元 × 5 通道，每像元一个大端 u16（10 bit 右对齐，实测 0..1023），
          **不是** 3/4 字节的 10 bit 位压缩（样本 u16 邻元相关 0.98 vs 位解包 0.29）
    @21744..22016 填充
* 定标（样本已数值验证）：
    可见光 R% = a1·(C/1000) + a2·(C/1000)²，系数取 @48 中「业务用」组：
      CH1 slope1=0.0540 offset1=-2.13 slope2=0.1610 offset2=-55.37 交叉点 501
      （两段线性在交叉点连续：24.92% vs 25.29% —— 说明缩放 1e-10/1e-7 与分段约定正确）
    红外用 Planck 反演：N = a1·(C/1000) + a2·(C/1000)²（mW/(m²·sr·cm⁻¹)），
      T = c2·νc / ln(1 + c1·νc³/N)，c1=1.1910659e-5, c2=1.438833，
      νc 取头记录中心波数 ×1e-2（CH3b 2669.36 / CH4 926.29 / CH5 839.82 cm⁻¹；
      文档 CH4/CH5 标注 ×1e3，与样本实测 ×1e2 不符，「样本反推，文档待核对」）。
      实测 BT：CH4 中位 297.9 K、CH5 286.5 K、CH3b（白天含反射）338.7 K，物理自洽。
* CH3 的 3A/3B 归属存疑：样本每扫描线 bit0 全为 0（声明 3A 反射通道），但 DN 中位 973、
  按可见光定标给 ~100% 反射率、按红外定标给 ~339 K，两种解释都不典型 —— 该字段的含义
  需人工核对，本读取器只如实保存 bit0（attrs["ch3_selection"]）与两套定标，不下结论。

============================================================================
为什么 Variable 不填 scale_factor / add_offset
============================================================================
1B 的物理定标是**分段线性**（NOAA 可见光两段）或 **Planck 非线性**（NOAA 红外），
无法用单一线性 (scale, offset) 表达；FY-1D 的定标系数与文档量纲不自洽，属于未解字段。
因此 data 保留原始 DN（unit="count"，valid_range=(0,1023)），
NOAA 变体另提供 `reflectance(ds)` / `brightness_temperature(ds)` 两个函数做精确转换，
两个变体的原始定标数据都放在 attrs["calibration"] 里，供后续物理层使用。
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from ..detect import parse_name
from ..model import Geolocation, SatDataset, Variable

# ---------------------------------------------------------------- 常量

FY1D_RECORD = 28400
FY1D_TBM_RECORDS = 1
FY1D_HEADER_RECORDS = 1
FY1D_DATA_OFFSET = 1000
FY1D_DATA_BYTES = 27308
FY1D_PIXELS = 2048
FY1D_CHANNELS = 10

NOAA_RECORD = 22016
NOAA_HEADER_RECORDS = 1
NOAA_DATA_OFFSET = 1264
NOAA_DATA_BYTES = 20480
NOAA_PIXELS = 2048
NOAA_CHANNELS = 5

NAV_POINTS = 51
NAV_FIRST_PIXEL = 25
NAV_PIXEL_STEP = 40
NAV_PIXELS = NAV_FIRST_PIXEL + NAV_PIXEL_STEP * np.arange(NAV_POINTS)

# AVHRR 通道定义（波长取自 FY-1（02）批与 NOAA 系列数据格式文档的通道表）
FY1D_BANDS = (
    ("CH1", "0.58-0.68", "visible"),
    ("CH2", "0.84-0.89", "near-infrared"),
    ("CH3", "3.55-3.95", "infrared"),
    ("CH4", "10.3-11.3", "infrared"),
    ("CH5", "11.5-12.5", "infrared"),
    ("CH6", "1.58-1.64", "shortwave-infrared"),
    ("CH7", "0.43-0.48", "visible"),
    ("CH8", "0.48-0.53", "visible"),
    ("CH9", "0.53-0.58", "visible"),
    ("CH10", "0.90-0.965", "near-infrared"),
)
NOAA_BANDS = (
    ("CH1", "0.58-0.68", "visible"),
    ("CH2", "0.725-1.00", "near-infrared"),
    ("CH3", "3.55-3.93", "infrared"),      # 白天 3A（反射）/ 夜间 3B，见 per-scan bit0
    ("CH4", "10.3-11.3", "infrared"),
    ("CH5", "11.5-12.5", "infrared"),
)

REGION_TYPES = {"visible": "%", "near-infrared": "%", "shortwave-infrared": "%",
                "infrared": "K"}

# NOAA 红外 Planck 常数（NOAA KLM 1B 约定：N 单位 mW/(m²·sr·cm⁻¹)，ν 单位 cm⁻¹）
PLANCK_C1 = 1.1910659e-5
PLANCK_C2 = 1.438833


# ---------------------------------------------------------------- 小工具


def _u8(b: bytes, off: int) -> int:
    return b[off]


def _i16(b: bytes, off: int) -> int:
    return struct.unpack(">h", b[off:off + 2])[0]


def _i32(b: bytes, off: int) -> int:
    return struct.unpack(">i", b[off:off + 4])[0]


def _u32(b: bytes, off: int) -> int:
    return struct.unpack(">I", b[off:off + 4])[0]


def _text(b: bytes, start: int, stop: int) -> str:
    """ASCII 字段：去掉 NUL / 空格。"""
    return b[start:stop].decode("latin-1").strip("\x00 ").strip()


def _dt_from(year: int, doy: int, millis: int) -> datetime | None:
    """年（可为两位年）+ 日计数（1 = 1 月 1 日）+ 当日毫秒 → datetime。"""
    if not (1 <= year <= 99 or 1950 <= year <= 2100) or not (1 <= doy <= 366):
        return None
    if year < 100:
        year += 2000
    try:
        return datetime(year, 1, 1) + timedelta(days=doy - 1, milliseconds=int(millis))
    except (ValueError, OverflowError):
        return None


def _unpack_10bit_pixelmajor(block: np.ndarray) -> np.ndarray:
    """FY-1D 数据块 → (n, 20480) uint16。

    block: (n, 27308) uint8，每 4 字节 1 字 = 2 bit 填充（高）+ 3 × 10 bit 样本。
    """
    block = np.ascontiguousarray(block)
    n, width = block.shape
    words = block.reshape(n, width // 4, 4).astype(np.uint32)
    w = (words[..., 0] << 24) | (words[..., 1] << 16) | (words[..., 2] << 8) | words[..., 3]
    out = np.empty((n, w.shape[1] * 3), dtype=np.uint16)
    out[:, 0::3] = ((w >> 20) & 0x3FF).astype(np.uint16)
    out[:, 1::3] = ((w >> 10) & 0x3FF).astype(np.uint16)
    out[:, 2::3] = (w & 0x3FF).astype(np.uint16)
    return out


def _strided_block(p: Path, record_size: int, first_record: int, n_records: int,
                   lo: int, hi: int) -> np.ndarray:
    """从定长记录文件里按列取字节块 → (n_records, hi-lo) uint8。

    用 memmap 跨步切片，只真正读到需要的字节（load=False 时不必把 128 MB 全读一遍）。
    """
    if n_records <= 0:
        return np.empty((0, hi - lo), dtype=np.uint8)
    n_total = p.stat().st_size // record_size
    mm = np.memmap(p, dtype=np.uint8, mode="r", shape=(n_total, record_size))
    try:
        out = np.asarray(mm[first_record:first_record + n_records, lo:hi])
    finally:
        del mm
    return out


def _nav_grid(lat_nav: np.ndarray, lon_nav: np.ndarray, *, full: bool,
              pixels: int = FY1D_PIXELS) -> tuple[np.ndarray, np.ndarray]:
    """把 51 个定位点插值成逐像元经纬度网格（fp32）。

    lat_nav/lon_nav: (n_scans, 51)。full=False 时原样返回（列 = 51 个定位点）。
    两端的延伸像元（<25 或 >2025）由 np.interp 按端点值平推。
    """
    if not full:
        return (lat_nav.astype(np.float32), lon_nav.astype(np.float32))
    grid = np.arange(pixels, dtype=np.float64)
    lat = np.empty((lat_nav.shape[0], grid.size), dtype=np.float32)
    lon = np.empty_like(lat)
    xp = NAV_PIXELS.astype(np.float64)
    for i in range(lat_nav.shape[0]):
        lat[i] = np.interp(grid, xp, lat_nav[i])
        lon[i] = np.interp(grid, xp, lon_nav[i])
    return lat, lon


def _var(name: str, band: str, kind: str, data: np.ndarray, shape: tuple[int, int],
         extra: dict[str, Any] | None = None) -> Variable:
    unit_phys = REGION_TYPES.get(kind, "")
    attrs: dict[str, Any] = {"band_type": kind, "wavelength_um": band,
                             "physical_unit": unit_phys}
    if extra:
        attrs.update(extra)
    return Variable(
        name=name,
        data=data,
        unit="count",
        long_name=f"AVHRR {name} ({band} um, {kind})",
        valid_range=(0.0, 1023.0),
        fill_value=None,
        dims=("scan", "pixel"),
        source_shape=shape,
        attrs=attrs,
    )


def _name_meta(path: Path) -> dict[str, Any]:
    """文件名解析（与 hdf5 读取器保持一致的平台/仪器/级别/时间口径）。"""
    info = parse_name(path)
    product = ""
    parts = [s for s in path.stem.split("_") if s]
    for j, s in enumerate(parts):
        if s.upper().startswith("L1") or s.upper().startswith("L2"):
            if j + 1 < len(parts):
                product = parts[j + 1].strip("-")
            break
    return {
        "platform": info.platform,
        "instrument": info.instrument,
        "level": info.level,
        "product": product,
        "start_time": info.start_time,
    }


def detect_variant(path: str | Path) -> str:
    """按头记录判断 1B 变体：fy1d（SMC.HRPT）/ noaa（N1BD）。"""
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(max(FY1D_RECORD, 128))
    if b"SMC.HRPT" in head[:FY1D_RECORD]:
        return "fy1d"
    if b"/N1BD/" in head[:64] or b"N1B" in head[:64]:
        return "noaa"
    size = p.stat().st_size
    if size % FY1D_RECORD == 0:
        return "fy1d"
    if size % NOAA_RECORD == 0:
        return "noaa"
    raise ValueError(f"无法识别 1B 变体：{p.name}（头 {head[:16]!r}，大小 {size}）")


# ---------------------------------------------------------------- FY-1C/D


def _read_fy1d(p: Path, *, load: bool, max_scans: int | None, geo: str) -> SatDataset:
    size = p.stat().st_size
    if size % FY1D_RECORD:
        raise ValueError(f"{p.name} 大小 {size} 不是 {FY1D_RECORD} 的整数倍，不是 FY-1 1B")
    n_records = size // FY1D_RECORD
    if n_records < 2:
        raise ValueError(f"{p.name} 记录数 {n_records} < 2，缺少数据头")

    with open(p, "rb") as fh:
        tbm = fh.read(FY1D_RECORD)
        hdr = fh.read(FY1D_RECORD)

    n_scans = n_records - FY1D_TBM_RECORDS - FY1D_HEADER_RECORDS
    if max_scans is not None:
        n_scans = min(n_scans, int(max_scans))

    meta = _name_meta(p)
    ds = SatDataset(source=p, reader="oneb")
    ds.platform = meta["platform"] or ""
    ds.instrument = meta["instrument"] or "AVHRR"
    ds.level = meta["level"] or "L1"
    ds.product = meta["product"]

    # ---- 数据头
    sat_id = _u8(hdr, 0)
    data_type = _u8(hdr, 1)
    start = _dt_from(_i16(hdr, 2), _i16(hdr, 4), _u32(hdr, 6))
    end = _dt_from(_i16(hdr, 12), _i16(hdr, 14), _u32(hdr, 16))
    declared_scans = _i16(hdr, 10)
    corners = [_i32(hdr, 256 + 4 * k) / 1e4 for k in range(8)]
    epoch = [_i16(hdr, 200 + 2 * k) for k in range(6)]
    ds.start_time = start or meta["start_time"]
    ds.end_time = end

    ds.attrs.update(
        {
            "variant": "fy1d",
            "record_length": FY1D_RECORD,
            "n_records": n_records,
            "n_scans": n_scans,
            "n_scans_in_file": n_records - 2,
            "n_scans_declared": declared_scans,
            "satellite_id": sat_id,
            "data_type": data_type,
            "tbm_name": _text(tbm, 30, 74),
            "tbm_header_text": _text(tbm, 74, 97),
            "tbm_channel_select": _text(tbm, 97, 117),
            "tbm_file_name": _text(tbm, 400, 416),
            "orbit_number": _i16(hdr, 198),
            "orbit_epoch": epoch,
            "semi_major_km": _i32(hdr, 212) / 1e3,
            "eccentricity": _i32(hdr, 216) / 1e8,
            "inclination_deg": _i32(hdr, 220) / 1e6,
            "ascending_node_deg": _i32(hdr, 224) / 1e6,
            "arg_perigee_deg": _i32(hdr, 228) / 1e6,
            "mean_anomaly_deg": _i32(hdr, 232) / 1e6,
            "ascending_descending": _i16(hdr, 242),
            "attitude_deg": [_i32(hdr, 244 + 4 * k) / 1e6 for k in range(3)],
            "corner_latlon_deg": [(corners[2 * k], corners[2 * k + 1]) for k in range(4)],
            "bits_per_sample": 10,
            "packing": "3 samples / 4 bytes, 2 pad bits at MSB",
        }
    )

    # ---- 逐扫描线元数据 + 51 个定位点（一次跨步读取 0..606 字节）
    block = _strided_block(p, FY1D_RECORD, FY1D_TBM_RECORDS + FY1D_HEADER_RECORDS,
                           n_scans, 0, 606)
    scan_no = block[:, 0:2].copy().view(">i2").reshape(-1).astype(np.int32)
    quality = block[:, 10:12].copy().view(">u2").reshape(-1).astype(np.uint16)
    sun_zen = block[:, 96:198].copy().view(">i2").reshape(n_scans, NAV_POINTS) / 128.0
    sat_zen = block[:, 198:300].copy().view(">i2").reshape(n_scans, NAV_POINTS) / 128.0
    rel_azi = block[:, 300:402].copy().view(">i2").reshape(n_scans, NAV_POINTS) / 128.0
    ll = block[:, 402:606].copy().view(">i2").reshape(n_scans, NAV_POINTS, 2) / 128.0
    lat_nav = ll[:, :, 0]
    lon_nav = ll[:, :, 1]

    # ---- 通道数据
    data = [np.empty((0,), dtype=np.uint16) for _ in range(FY1D_CHANNELS)]
    if load and n_scans:
        per_ch = [np.empty((n_scans, FY1D_PIXELS), dtype=np.uint16) for _ in range(FY1D_CHANNELS)]
        with open(p, "rb") as fh:
            for chunk_start in range(0, n_scans, 128):
                k = min(128, n_scans - chunk_start)
                fh.seek(FY1D_RECORD * (2 + chunk_start))
                buf = np.frombuffer(fh.read(FY1D_RECORD * k), dtype=np.uint8).reshape(k, FY1D_RECORD)
                block = buf[:, FY1D_DATA_OFFSET:FY1D_DATA_OFFSET + FY1D_DATA_BYTES]
                samples = _unpack_10bit_pixelmajor(block)[:, : FY1D_PIXELS * FY1D_CHANNELS]
                cube = samples.reshape(k, FY1D_PIXELS, FY1D_CHANNELS)
                for c in range(FY1D_CHANNELS):
                    per_ch[c][chunk_start:chunk_start + k] = cube[:, :, c]
        data = per_ch

    for c, (name, band, kind) in enumerate(FY1D_BANDS):
        ds.variables[name] = _var(name, band, kind, data[c], (n_scans, FY1D_PIXELS))

    # ---- 定标系数（字段原样保留，不作物理转换）
    cal = _read_fy1d_calibration(p, n_scans)
    ds.attrs["calibration"] = cal

    # ---- 定位对象
    ds.geolocation = _build_geo(lat_nav, lon_nav, geo, extra={
        "nav_points": NAV_POINTS,
        "nav_pixels": NAV_PIXELS.tolist(),
        "angle_scale": 1.0 / 128.0,
        "sun_zenith_deg": sun_zen,
        "satellite_zenith_deg": sat_zen,
        "relative_azimuth_deg": rel_azi,
        "note": "51 定位点的像元位置为样本反推 25+40k，文档待核对",
    })

    # ---- 质量与未解析字段
    ds.attrs["scan_numbers"] = scan_no
    ds.attrs["scan_quality_flagged"] = int(np.count_nonzero(quality))
    gaps = np.nonzero(np.diff(scan_no) != 1)[0] if scan_no.size > 1 else np.array([], dtype=int)
    ds.attrs["scan_number_gaps"] = [
        {"after_index": int(i), "from": int(scan_no[i]), "to": int(scan_no[i + 1])} for i in gaps[:20]
    ]
    ds.attrs["unparsed"] = [
        {"field": "data_record[16:96] 定标斜率/截距 (20×i32)",
         "reason": "按文档 2^-30(斜率)/2^-22(截距) 缩放得到的物理量不自洽"
                   "（ch2/ch4/ch5 增益为负，ch8/ch10 反射率达 600%），"
                   "系数原样存入 attrs['calibration']，未用于 physical()"},
        {"field": "data_record[608:908] HRPT 帧遥测 (300 B)",
         "reason": "工程遥测参数表未随本格式文档提供，仅保留原始字节位置说明"},
        {"field": "data_record[908:1000] 备用段 (92 B)",
         "reason": "文档标注『空』，未解析"},
    ]
    ds.attrs["notes"] = [
        "数据头声明扫描线数 %d，文件实际数据记录 %d 条" % (declared_scans, n_records - 2),
        "10 bit 样本的 2 个填充位在高位（样本反推，文档图例一致）",
    ]
    return ds


def _read_fy1d_calibration(p: Path, n_scans: int) -> dict[str, Any]:
    """取首条数据记录的 20 个定标 i32（样本中逐扫描线一致，抽查 3 条相同）。"""
    if n_scans <= 0:
        return {}
    with open(p, "rb") as fh:
        fh.seek(FY1D_RECORD * 2)
        rec = fh.read(FY1D_RECORD)
    raw = [_i32(rec, 16 + 4 * k) for k in range(20)]
    return {
        "raw_i32": raw,
        "scale_doc": {"slope": 2.0 ** -30, "intercept": 2.0 ** -22},
        "status": "unverified",
        "note": "样本反推，文档待核对：按文档缩放不自洽，未用于 physical()",
    }


# ---------------------------------------------------------------- NOAA K/L/M/N


def _read_noaa(p: Path, *, load: bool, max_scans: int | None, geo: str) -> SatDataset:
    size = p.stat().st_size
    if size % NOAA_RECORD:
        raise ValueError(f"{p.name} 大小 {size} 不是 {NOAA_RECORD} 的整数倍，不是 NOAA 1B")
    n_records = size // NOAA_RECORD
    with open(p, "rb") as fh:
        hdr = fh.read(NOAA_RECORD)

    n_hdr = max(1, _i16(hdr, 14) or NOAA_HEADER_RECORDS)
    n_scans = n_records - n_hdr
    if max_scans is not None:
        n_scans = min(n_scans, int(max_scans))

    dataset_name = _text(hdr, 22, 64)
    plat_id = _i16(hdr, 72)
    # 星名优先取数据集名里的 NOAAxx/METOPx；数据集名不可用时只保留头里的原始编号，
    # 不去猜"编号 → NOAA 几号"的换算（文档示例 4=NOAA-15 与样本 13=NOAA-18 冲突）。
    platform = _platform_from_dataset_name(dataset_name) or (f"N{plat_id:02d}" if plat_id else "")
    meta = _name_meta(p)

    ds = SatDataset(source=p, reader="oneb")
    ds.platform = meta["platform"] or platform
    ds.instrument = meta["instrument"] or "AVHRR"
    ds.level = meta["level"] or "L1"
    ds.product = meta["product"]

    start = _dt_from(_i16(hdr, 84), _i16(hdr, 86), _u32(hdr, 88))
    end = _dt_from(_i16(hdr, 96), _i16(hdr, 98), _u32(hdr, 100))
    ds.start_time = start or meta["start_time"]
    ds.end_time = end

    wavenumbers = {
        "CH3b": _i32(hdr, 280) * 1e-2,
        "CH4": _i32(hdr, 292) * 1e-2,
        "CH5": _i32(hdr, 304) * 1e-2,
    }
    ds.attrs.update(
        {
            "variant": "noaa",
            "record_length": NOAA_RECORD,
            "n_records": n_records,
            "header_records": n_hdr,
            "n_scans": n_scans,
            "n_scans_in_file": n_records - n_hdr,
            "n_scans_declared": _i16(hdr, 128),
            "dataset_name": dataset_name,
            "b1_version": _i16(hdr, 4),
            "b1_version_year": _i16(hdr, 6),
            "b1_version_day": _i16(hdr, 8),
            "platform_id": plat_id,
            "platform_id_note": "文档示例 4=NOAA-15，但样本 13 对应 NOAA-18（以数据集名 /N18/ 为准）"
                                "→ 编号换算表口径不一致，样本反推，文档待核对",
            "instrument_id": _i16(hdr, 74),
            "data_type": _i16(hdr, 76),
            "reference_ellipsoid": _text(hdr, 328, 336),
            "orbit_epoch": {"year": _i16(hdr, 348), "day": _i16(hdr, 350),
                            "utc_s": _u32(hdr, 352)},
            "semi_major_km": _i32(hdr, 356) / 1e5,
            "eccentricity": _i32(hdr, 360) / 1e8,
            "inclination_deg": _i32(hdr, 364) / 1e5,
            "arg_perigee_deg": _i32(hdr, 368) / 1e5,
            "ascending_node_deg": _i32(hdr, 372) / 1e5,
            "mean_anomaly_deg": _i32(hdr, 376) / 1e5,
            "central_wavenumber_cm1": wavenumbers,
            "solar_irradiance": {"CH1": _i32(hdr, 256) / 10.0, "CH2": _i32(hdr, 264) / 10.0,
                                 "CH3a": _i32(hdr, 272) / 10.0},
            "equivalent_width_um": {"CH1": _i32(hdr, 260) / 1e3, "CH2": _i32(hdr, 268) / 1e3,
                                    "CH3a": _i32(hdr, 276) / 1e3},
            "bits_per_sample": 10,
            "packing": "big-endian uint16 per sample, pixel-major, 5 samples / pixel",
        }
    )

    # ---- 数据与逐扫描线字段
    # ---- 逐扫描线元数据 + 51 个定位点（跨步读取记录前 1048 字节）
    meta = _strided_block(p, NOAA_RECORD, n_hdr, n_scans, 0, 1048)
    scan_no = meta[:, 0:2].copy().view(">i2").reshape(-1).astype(np.int32)
    years = meta[:, 2:4].copy().view(">i2").reshape(-1)
    doys = meta[:, 4:6].copy().view(">i2").reshape(-1)
    millis = meta[:, 8:12].copy().view(">u4").reshape(-1)
    bitfield = meta[:, 12:14].copy().view(">u2").reshape(-1)
    ch3_select = (bitfield & 1).astype(np.int8)
    ascending = (bitfield & 0x8000) == 0
    quality = meta[:, 24:28].copy().view(">u4").reshape(-1)
    ang = meta[:, 328:634].copy().view(">i2").reshape(n_scans, NAV_POINTS, 3) / 100.0
    sun_zen, sat_zen, rel_azi = ang[:, :, 0], ang[:, :, 1], ang[:, :, 2]
    ll = meta[:, 640:1048].copy().view(">i4").reshape(n_scans, NAV_POINTS, 2) / 1e4
    lat_nav, lon_nav = ll[:, :, 0], ll[:, :, 1]
    times = [_dt_from(int(y), int(d), int(m)) for y, d, m in zip(years[:8], doys[:8], millis[:8])] \
        if n_scans else []

    # ---- 通道数据（每像元一个大端 u16，像元优先交织）
    per_ch = [np.empty((0,), dtype=np.uint16) for _ in range(NOAA_CHANNELS)]
    vis_cal: list[list[int]] = []
    ir_cal: list[list[int]] = []
    if n_scans:
        # 定标系数在**数据记录**里（@48 可见光 45×i32，@228 红外 18×i32），不是头记录；
        # 样本逐扫描线一致，取首条即可。
        cal_blk = _strided_block(p, NOAA_RECORD, n_hdr, 1, 48, 300)[0].tobytes()
        vis_cal = [[_i32(cal_blk, 4 * (c * 15 + g * 5 + j)) for j in range(5)]
                   for c in range(3) for g in range(3)]
        ir_cal = [[_i32(cal_blk, 180 + 4 * (c * 6 + g * 3 + j)) for j in range(3)]
                  for c in range(3) for g in range(2)]
    if load and n_scans:
        per_ch = [np.empty((n_scans, NOAA_PIXELS), dtype=np.uint16) for _ in range(NOAA_CHANNELS)]
        with open(p, "rb") as fh:
            for chunk_start in range(0, n_scans, 128):
                k = min(128, n_scans - chunk_start)
                fh.seek(NOAA_RECORD * (n_hdr + chunk_start))
                buf = np.frombuffer(fh.read(NOAA_RECORD * k), dtype=np.uint8).reshape(k, NOAA_RECORD)
                block = buf[:, NOAA_DATA_OFFSET:NOAA_DATA_OFFSET + NOAA_DATA_BYTES]
                cube = block.copy().view(">u2").reshape(k, NOAA_PIXELS, NOAA_CHANNELS)
                for c in range(NOAA_CHANNELS):
                    per_ch[c][chunk_start:chunk_start + k] = cube[:, :, c]

    for c, (name, band, kind) in enumerate(NOAA_BANDS):
        extra: dict[str, Any] = {}
        if c < 3:
            # 可见光：3 组（业务/测试/发射前）× 5 系数（CH3 白天为 3A，用可见光定标）
            if vis_cal:
                extra["calibration_groups"] = {
                    "operational": _vis_group(vis_cal[0:3], c),
                    "test": _vis_group(vis_cal[3:6], c),
                    "prelaunch": _vis_group(vis_cal[6:9], c),
                }
            if name == "CH3" and ir_cal:
                # 夜间 3B 用红外定标（第 1 个红外通道）
                extra["calibration_groups_ir"] = {
                    "operational": ir_cal[0],
                    "prelaunch": ir_cal[1],
                }
                extra["central_wavenumber_cm1"] = wavenumbers["CH3b"]
        else:
            if ir_cal:
                extra["calibration_groups"] = {
                    "operational": ir_cal[(c - 2) * 2],   # 3b/4/5 → 0/1/2
                    "prelaunch": ir_cal[(c - 2) * 2 + 1],
                }
            extra["central_wavenumber_cm1"] = wavenumbers[name]
        ds.variables[name] = _var(name, band, kind, per_ch[c], (n_scans, NOAA_PIXELS), extra)

    ds.attrs["calibration"] = {
        "visible": {"raw_i32": vis_cal,
                    "scaling": "slope ×1e-10, intercept ×1e-7, crossover = 计数值",
                    "method": "R% = slope1*(C/1000)*1000… 见 oneb.reflectance()",
                    "group_order": "3 组(业务/测试/发射前) × 3 通道 × 5 系数"},
        "infrared": {"raw_i32": ir_cal,
                     "scaling": "系数 ×1e-6；N = a1*(C/1000) + a2*(C/1000)^2 [mW/(m²·sr·cm⁻¹)]",
                     "method": "T = c2·νc / ln(1 + c1·νc³/N)，见 oneb.brightness_temperature()",
                     "group_order": "2 组(业务/发射前) × 3 通道 × 3 系数",
                     "central_wavenumber_cm1": wavenumbers},
    }
    ds.attrs["scan_numbers"] = scan_no
    ds.attrs["ch3_selection"] = ch3_select       # 0 = 3A（反射），1 = 3B（热红外）
    ds.attrs["scan_ascending"] = ascending
    ds.attrs["scan_quality"] = quality
    ds.attrs["scan_time_first"] = times[0] if times else None
    ds.attrs["ch3a_fraction"] = float(np.mean(ch3_select == 0)) if n_scans else 0.0

    ds.geolocation = _build_geo(lat_nav, lon_nav, geo, extra={
        "nav_points": NAV_POINTS,
        "nav_pixels": NAV_PIXELS.tolist(),
        "angle_scale": 0.01,
        "sun_zenith_deg": sun_zen,
        "satellite_zenith_deg": sat_zen,
        "relative_azimuth_deg": rel_azi,
        "note": "51 定位点位于第 25..2025 像元、每 40 像元一点（文档 §3.2 数据记录格式）",
    })

    ds.attrs["unparsed"] = [
        {"field": "data_record[1056:1262] HRPT 副帧遥测 (206 B)",
         "reason": "HRPT 副帧遥测帧格式未随该文档给出，未解析"},
        {"field": "header[161:328] 模拟遥测转换系数 / 红外目标温度系数",
         "reason": "本产品中全部为 0（样本实测），无可用信息"},
    ]
    ds.attrs["notes"] = [
        "每像元一个大端 u16（10 bit 右对齐），非 3:4 位压缩",
        "红外 Planck 反演已用样本验证：CH4 中位 297.9 K、CH5 286.5 K",
        "文档 CH4/CH5 中心波数标注 ×1e3，样本实测 ×1e2（样本反推，文档待核对）",
        "CH3 的 3A/3B 选择位（每扫描线 bit0）样本全为 0（3A），但按可见光定标得 ~100% 反射率、"
        "按红外定标得 ~339 K，两种解释都不典型 → CH3 的物理含义需人工核对（样本反推，文档待核对）",
    ]
    return ds


def _vis_group(groups: list[list[int]], channel: int) -> dict[str, Any]:
    g = groups[channel]
    return {
        "slope1": g[0] * 1e-10, "intercept1": g[1] * 1e-7,
        "slope2": g[2] * 1e-10, "intercept2": g[3] * 1e-7,
        "crossover_counts": g[4],
    }


def _platform_from_dataset_name(name: str) -> str:
    """从 "/N1BD/N18/NOAA18_AVHRR_…" 里取星名。"""
    if not name:
        return ""
    upper = name.upper()
    for token in ("NOAA18", "NOAA19", "NOAA17", "NOAA16", "NOAA15", "NOAA14",
                  "NOAA12", "NOAA11", "METOP1", "METOP2", "METOP3"):
        if token in upper:
            return token.replace("NOAA", "NOAA-").replace("METOP", "METOP-")
    for token in ("/N18/", "/N19/", "/N17/", "/N16/", "/N15/"):
        if token in upper:
            return "NOAA-" + token.strip("/").lstrip("N")
    return ""


def _build_geo(lat_nav: np.ndarray, lon_nav: np.ndarray, mode: str,
               extra: dict[str, Any], pixels: int = FY1D_PIXELS) -> Geolocation:
    """按 geo 模式构造 Geolocation。

    mode: "full"（逐像元插值，形状 (n_scan, pixels)）/ "nav"（仅 51 点）/ "none"
    """
    mode = (mode or "full").lower()
    if mode == "none" or lat_nav.size == 0:
        return Geolocation(kind="none", params=extra)
    full = mode != "nav"
    lat, lon = _nav_grid(lat_nav, lon_nav, full=full, pixels=pixels)
    params = dict(extra)
    params["interp"] = "linear" if full else "nav-only"
    return Geolocation(kind="latlon_grid", lat=lat, lon=lon, step=1, params=params)


# ---------------------------------------------------------------- 物理定标


def reflectance(ds: SatDataset, *, group: str = "operational") -> dict[str, np.ndarray]:
    """NOAA 变体的可见光通道 → 反射率（%，−999 表示无效）。

    分段线性（两段在交叉点连续，样本已验证）：R% = slope·C + intercept，
    C ≤ crossover 用第 1 段，否则用第 2 段。
    """
    out: dict[str, np.ndarray] = {}
    for c, name in enumerate(("CH1", "CH2", "CH3")):
        if name not in ds.variables:
            continue
        var = ds.variables[name]
        cal = var.attrs.get("calibration_groups", {}).get(group)
        if not cal:
            continue
        dn = var.data.astype(np.float32)
        if dn.size == 0:
            continue
        s1, o1 = np.float32(cal["slope1"]), np.float32(cal["intercept1"])
        s2, o2 = np.float32(cal["slope2"]), np.float32(cal["intercept2"])
        xo = np.float32(cal["crossover_counts"])
        out[name] = np.where(dn <= xo, s1 * dn + o1, s2 * dn + o2).astype(np.float32)
    return out


def brightness_temperature(ds: SatDataset, *, group: str = "operational") -> dict[str, np.ndarray]:
    """NOAA 变体的红外通道 → 亮温（K）。

    N = a1·(C/1000) + a2·(C/1000)^2 [mW/(m²·sr·cm⁻¹)]，
    T = c2·νc / ln(1 + c1·νc³/N)，νc 取头记录中心波数。

    多项式给出的辐射亮度 ≤ 0 的样本（只可能是 DN 极小的无效读数）返回 NaN ——
    此时 Planck 反演无解，不外推。
    """
    out: dict[str, np.ndarray] = {}
    nu_map = ds.attrs.get("central_wavenumber_cm1", {})
    for name in ("CH3b", "CH4", "CH5"):
        var_name = "CH3" if name == "CH3b" else name
        if var_name not in ds.variables:
            continue
        var = ds.variables[var_name]
        groups = var.attrs.get("calibration_groups_ir") if var_name == "CH3" \
            else var.attrs.get("calibration_groups")
        cal = (groups or {}).get(group)
        nu = nu_map.get(name)
        if not cal or not nu:
            continue
        a1, a2 = np.float64(cal[1]) * 1e-6, np.float64(cal[2]) * 1e-6   # (a0, a1, a2)
        dn = var.data.astype(np.float64) / 1000.0
        if dn.size == 0:
            continue
        rad = a1 * dn + a2 * dn * dn
        bt = np.full(rad.shape, np.nan, dtype=np.float64)
        good = rad > 0
        with np.errstate(divide="ignore", invalid="ignore"):
            bt[good] = PLANCK_C2 * nu / np.log1p(PLANCK_C1 * nu ** 3 / rad[good])
        out[name] = bt.astype(np.float32)
    return out


# ---------------------------------------------------------------- 入口


def read(path: str | Path, load: bool = True, *, variant: str | None = None,
         max_scans: int | None = None, geo: str = "full", **_: Any) -> SatDataset:
    """读取 1B 文件 → SatDataset。

    参数：
        load        True 时解出全部通道数据；False 只解析头/定位与形状（形状见
                    Variable.source_shape，dtype uint16），用于 `fysat.cli info`。
        variant     "fy1d" / "noaa"；缺省按头记录自动判别。
        max_scans   只读前 N 条扫描线（测试与预览用）。
        geo         "full"（逐像元经纬度网格）/ "nav"（仅 51 定位点）/ "none"。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    kind = (variant or detect_variant(p)).lower()
    if kind in ("fy1d", "fy1", "fy1c", "fy1d_smc"):
        return _read_fy1d(p, load=load, max_scans=max_scans, geo=geo)
    if kind in ("noaa", "noaa_klm", "n1bd"):
        return _read_noaa(p, load=load, max_scans=max_scans, geo=geo)
    raise ValueError(f"未知 1B 变体 {variant!r}（可选 fy1d / noaa）")


def load_array(path: str | Path, name: str, **kwargs: Any) -> np.ndarray:
    """按需读取单个通道（供 SatDataset.load 的按需加载分支使用）。"""
    ds = read(path, load=True, **kwargs)
    if name not in ds.variables:
        raise KeyError(f"变量不存在: {name}；可选 {list(ds.variables)[:12]}")
    return ds.variables[name].data


def list_tree(path: str | Path, max_items: int = 60) -> list[dict]:
    """列出文件结构（供 CLI `ls` / GUI 树使用，行格式与 hdf5.list_tree 一致）。"""
    ds = read(path, load=False, geo="none")
    rows: list[dict] = [
        {"path": "/", "kind": "group", "attrs": len(ds.attrs)},
        {"path": f"/{ds.attrs.get('n_records', 0)} records x "
                 f"{ds.attrs.get('record_length', 0)} B", "kind": "group", "attrs": 0},
    ]
    for var in ds.variables.values():
        rows.append({"path": "/" + var.name, "kind": "dataset", "attrs": len(var.attrs),
                     "shape": list(var.shape), "dtype": str(var.dtype)})
    return rows[:max_items]

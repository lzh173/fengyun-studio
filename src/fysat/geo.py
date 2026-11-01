"""定位与重采样：粗经纬网格插值、静止轨道标称投影反算、等经纬网格重采样。

数值全部用 numpy 向量化；只在「行分块」这一层循环（每块一两百万像元），
绝不逐像元循环，所以 8000×8192（MERSI 250m，6560 万像元）和 10992×10992
（AGRI 1km，1.2 亿像元）都能直接跑（实测见各函数 docstring）。

约定
----
* 索引 ``(row, col)`` 从 0 开始，row 向南增大、col 向东增大。
* 经纬度单位为度，lat 北正、lon 东正。
* 卫星高度 / 像元尺寸用**米**（FY-4 的 ``NOMSatHeight`` / 文件名里的 ``1000M`` 可直接传）。
* 定不了位的地方（地球圆盘外、粗网格里的缺测）一律输出 NaN，方便直接上色。

三个主力函数
------------
``sample_latlon_grid(lat, lon, shape, step)``
    文件自带粗经纬网格（FY-3 ``/GEO/``，每 ``step`` 像元一点）→ 双线性插值到全分辨率，
    图太大时自动抽稀，返回 :class:`LonLatGrid`（含 ``rows`` / ``cols`` 便于取数据子块）。

``nominal_geos_lonlat(shape, sub_lon, sub_lat, sat_height)``
    静止轨道标称投影（FY-4 / FY-2 全圆盘）→ 逐像元经纬度。

``reproject_to_grid(data, lat, lon, res=0.05)``
    散点到等经纬网格（直方图法，O(N)），返回 :class:`GeoGrid`（数据 + extent）。
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np

# WGS84 椭球（FY-4 文件里的 Semimajor / Semiminor axis of ellipsoid）
WGS84_SEMIMAJOR = 6378137.0
WGS84_SEMIMINOR = 6356752.314245
# 标称静止轨道高度（FY-4B 全局属性 NOMSatHeight = 35786000 m）
GEO_HEIGHT = 35786000.0
# 标称像元尺寸：FY-4 AGRI 1km 全圆盘 = 1000 m，4km 全圆盘 = 4000 m
NOMINAL_PIXEL_SIZE = 1000.0

__all__ = [
    "LonLatGrid",
    "GeoGrid",
    "sample_latlon_grid",
    "nominal_geos_lonlat",
    "geos_scan_to_lonlat",
    "lonlat_to_geos_scan",
    "lonlat_to_nominal_rowcol",
    "reproject_to_grid",
    "WGS84_SEMIMAJOR",
    "WGS84_SEMIMINOR",
    "GEO_HEIGHT",
    "NOMINAL_PIXEL_SIZE",
]


# ---------------------------------------------------------------- 结果容器

class LonLatGrid(NamedTuple):
    """粗网格插值结果：``lat/lon`` 与原图同尺度的子网格，``rows/cols`` 是在全分辨率图里的行/列号。

    取数据子块：``grid.take(data)`` 等价于 ``data[np.ix_(grid.rows, grid.cols)]``。
    """

    lat: np.ndarray
    lon: np.ndarray
    rows: np.ndarray
    cols: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(self.lat.shape)  # type: ignore[return-value]

    @property
    def stride(self) -> int:
        """抽稀步长（全分辨率图上相邻两点的间隔）。"""
        return int(self.rows[1] - self.rows[0]) if self.rows.size > 1 else 1

    def take(self, data: np.ndarray) -> np.ndarray:
        """从**全分辨率**数据里取出与本网格对应的子块（``rows/cols`` 是全分辨率行/列号）。

        ``data`` 必须是 ``shape`` 那个尺寸的原图，而不是自己抽稀过的子样——
        抽稀子样要自己按 ``stride`` 除一遍。
        """
        arr = np.asarray(data)
        if arr.ndim != 2 or arr.shape[0] <= int(self.rows[-1]) or arr.shape[1] <= int(self.cols[-1]):
            raise ValueError(
                f"take() 需要全分辨率数据（至少 {int(self.rows[-1]) + 1}×{int(self.cols[-1]) + 1}），"
                f"收到 {arr.shape}；若手上已是抽稀子样，请用 data[rows//stride, cols//stride]"
            )
        return arr[np.ix_(self.rows, self.cols)]


class GeoGrid(NamedTuple):
    """等经纬网格结果。

    ``data``    (nrow, ncol) float32，NaN = 该格无有效观测
    ``extent``  (lon_min, lon_max, lat_min, lat_max)，可直接给 ``imshow(extent=...)``
    ``res``     网格分辨率（度）
    ``counts``  每格参与平均的有效像元数
    """

    data: np.ndarray
    extent: tuple[float, float, float, float]
    res: float
    counts: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(self.data.shape)  # type: ignore[return-value]

    @property
    def lons(self) -> np.ndarray:
        """格心经度（1-D，西→东）。"""
        lon0, lon1 = self.extent[0], self.extent[1]
        return np.linspace(lon0 + self.res / 2, lon1 - self.res / 2, self.data.shape[1])

    @property
    def lats(self) -> np.ndarray:
        """格心纬度（1-D，北→南，与 data 的行序一致）。"""
        lat0, lat1 = self.extent[2], self.extent[3]
        return np.linspace(lat1 - self.res / 2, lat0 + self.res / 2, self.data.shape[0])


# ---------------------------------------------------------------- 粗网格插值

def _auto_stride(nrow: int, ncol: int, max_pixels: int) -> int:
    """挑一个尽量小、又不超过 max_pixels 的抽稀步长。"""
    stride = 1
    while -(-nrow // stride) * (-(-ncol // stride)) > max_pixels:
        stride += 1
    return stride


def _bilinear(field: np.ndarray, r0, r1, c0, c1, wr: np.ndarray, wc: np.ndarray) -> np.ndarray:
    """对 2-D 场做双线性插值（索引已算好，纯向量化）。"""
    wr = wr[:, None]
    wc = wc[None, :]
    top = field[np.ix_(r0, c0)] * (1.0 - wc) + field[np.ix_(r0, c1)] * wc
    bot = field[np.ix_(r1, c0)] * (1.0 - wc) + field[np.ix_(r1, c1)] * wc
    return ((1.0 - wr) * top + wr * bot).astype(np.float32, copy=False)


def sample_latlon_grid(
    lat: np.ndarray,
    lon: np.ndarray,
    shape: tuple[int, int],
    step: int = 1,
    *,
    stride: int | None = None,
    max_pixels: int = 4_000_000,
) -> LonLatGrid:
    """把「每 step 像元一点」的粗经纬网格双线性插值到全分辨率（过大时自动抽稀）。

    参数
    ----
    lat, lon : 粗网格，形状 (nrow_c, ncol_c)，例如 FY-3 MERSI 的 ``/GEO/Latitude`` (400, 410)。
    shape    : 全分辨率数据形状，例如 (8000, 8192)。
    step     : 粗网格的采样间隔（像元），FY-3 250m/1km 都是 20。
    stride   : 输出抽稀步长；``None`` 时按 ``max_pixels`` 自动挑（保证不超内存）。
    max_pixels : 输出网格的像元数上限（默认 400 万 ≈ 16 MB/张 float32 字段）。

    返回
    ----
    :class:`LonLatGrid`，``lat/lon`` 为插值结果，``rows/cols`` 为对应的全分辨率行/列号。
    粗网格之外的像元截断到最后一个粗格点（FY-3 列数 410 × 20 = 8200 > 8192 通常够用）。
    """
    lat = np.asarray(lat, dtype=np.float32)
    lon = np.asarray(lon, dtype=np.float32)
    if lat.ndim != 2 or lon.ndim != 2:
        raise ValueError("lat/lon 必须是二维粗网格")
    if lat.shape != lon.shape:
        raise ValueError(f"lat/lon 形状不一致: {lat.shape} vs {lon.shape}")
    nrow, ncol = int(shape[0]), int(shape[1])
    if step <= 0:
        raise ValueError("step 必须为正整数")
    if nrow <= 0 or ncol <= 0:
        raise ValueError(f"shape 不合法: {shape}")

    if stride is None:
        stride = _auto_stride(nrow, ncol, max_pixels)
    stride = max(1, int(stride))

    rows = np.arange(0, nrow, stride, dtype=np.int64)
    cols = np.arange(0, ncol, stride, dtype=np.int64)

    # 粗网格坐标（以「粗格点」为单位），越界截断
    u = np.minimum(rows / float(step), lat.shape[0] - 1.0)
    v = np.minimum(cols / float(step), lat.shape[1] - 1.0)

    r0 = np.floor(u).astype(np.int64)
    c0 = np.floor(v).astype(np.int64)
    r1 = np.minimum(r0 + 1, lat.shape[0] - 1)
    c1 = np.minimum(c0 + 1, lat.shape[1] - 1)
    wr = (u - r0).astype(np.float32)
    wc = (v - c0).astype(np.float32)

    out_lat = _bilinear(lat, r0, r1, c0, c1, wr, wc)
    out_lon = _bilinear(lon, r0, r1, c0, c1, wr, wc)
    return LonLatGrid(out_lat, out_lon, rows, cols)


# ---------------------------------------------------------------- 标称投影

def _sat_frame(
    sub_lon: float,
    sub_lat: float,
    sat_height: float,
    semimajor: float,
    semiminor: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """卫星位置矢量 S 与当地坐标系（shat 指向卫星、east、north），单位米。"""
    lam = np.deg2rad(float(sub_lon))
    phi = np.deg2rad(float(sub_lat))
    if abs(np.cos(phi)) < 1e-9:
        raise ValueError("sub_lat 不能取 ±90°（当地东向无定义）")
    e2 = 1.0 - (semiminor / semimajor) ** 2
    n = semimajor / np.sqrt(1.0 - e2 * np.sin(phi) ** 2)
    r = n + float(sat_height)
    s = np.array(
        [r * np.cos(phi) * np.cos(lam), r * np.cos(phi) * np.sin(lam), r * np.sin(phi)]
    )
    shat = s / r
    east = np.cross(np.array([0.0, 0.0, 1.0]), shat)
    east = east / np.linalg.norm(east)
    north = np.cross(shat, east)
    return s, shat, east, north


def geos_scan_to_lonlat(
    scan_x: np.ndarray,
    scan_y: np.ndarray,
    sub_lon: float,
    sub_lat: float = 0.0,
    sat_height: float = GEO_HEIGHT,
    *,
    semimajor: float = WGS84_SEMIMAJOR,
    semiminor: float = WGS84_SEMIMINOR,
) -> tuple[np.ndarray, np.ndarray]:
    """静止轨道扫描角 → 经纬度（向量化，椭球求交）。

    scan_x : 1-D，列方向扫描角（弧度，向东为正）
    scan_y : 1-D，行方向扫描角（弧度，向北为正）
    返回 (lat, lon)，形状 (len(scan_y), len(scan_x))，float32；地球圆盘外为 NaN。

    两个循环各占一半开销：射线与椭球求交（逐像元解析解）+ arctan2。为了压低峰值内存，
    所有能提到「一维」的量都先算成 (nx,) / (ny,)，二维中间量一律原地写回。
    整盘 1.2 亿像元请用 :func:`nominal_geos_lonlat`（它按行分块、直接给 float32）。
    """
    s, shat, east, north = _sat_frame(sub_lon, sub_lat, sat_height, semimajor, semiminor)
    sx = np.asarray(scan_x, dtype=np.float64).reshape(-1)
    sy = np.asarray(scan_y, dtype=np.float64).reshape(-1)
    # 视向量 d = (a·east + c·shat)·cos(y) + sin(y)·north，
    # c = −cos(x)、a = sin(x) 只跟列有关，cos(y)/sin(y) 只跟行有关
    cos_x, sin_x = np.cos(sx), np.sin(sx)
    kx = sin_x * east[0] - cos_x * shat[0]      # (nx,)
    ky = sin_x * east[1] - cos_x * shat[1]
    kz = sin_x * east[2] - cos_x * shat[2]
    cos_y, sin_y = np.cos(sy), np.sin(sy)       # (ny,)
    bx, by, bz = sin_y * north[0], sin_y * north[1], sin_y * north[2]

    a2, b2 = semimajor * semimajor, semiminor * semiminor
    inv_a2, inv_b2 = 1.0 / a2, 1.0 / b2
    e2 = 1.0 - b2 / a2
    cc = (s[0] * s[0] + s[1] * s[1]) * inv_a2 + s[2] * s[2] * inv_b2 - 1.0
    two_sx_a2, two_sy_a2, two_sz_b2 = 2.0 * s[0] * inv_a2, 2.0 * s[1] * inv_a2, 2.0 * s[2] * inv_b2

    cy = cos_y[:, None]                         # (ny, 1)
    dx = np.multiply(kx, cy)                    # 以下全部 (ny, nx)
    dx += bx[:, None]
    dy = np.multiply(ky, cy)
    dy += by[:, None]
    dz = np.multiply(kz, cy)
    dz += bz[:, None]

    aa = dx * dx
    aa += dy * dy
    aa *= inv_a2
    aa += dz * dz * inv_b2                  # A = |d_xy|²/a² + d_z²/b²

    bb = dx * two_sx_a2
    bb += dy * two_sy_a2
    bb += dz * two_sz_b2                    # B = 2(S·(dx,dy)/a² + S_z·dz/b²)

    disc = bb * bb
    disc -= 4.0 * cc * aa                   # 判别式；≤ 0 说明射线没有命中地球
    ok = disc > 0.0
    with np.errstate(invalid="ignore"):
        np.sqrt(disc, out=disc)             # 负值会得到 NaN，由 ok 兜底
    t = -bb - disc
    t /= 2.0 * aa                           # 近根 t = (−B − √Δ) / 2A

    px = t * dx                             # 交点 = S + t·d
    px += s[0]
    py = t * dy
    py += s[1]
    pz = t * dz
    pz += s[2]
    pxy = np.hypot(px, py)
    pxy *= 1.0 - e2
    lat = np.degrees(np.arctan2(pz, pxy))
    lon = np.degrees(np.arctan2(py, px))
    np.copyto(lat, np.nan, where=~ok)
    np.copyto(lon, np.nan, where=~ok)
    return lat.astype(np.float32), lon.astype(np.float32)


def lonlat_to_geos_scan(
    lat: np.ndarray,
    lon: np.ndarray,
    sub_lon: float,
    sub_lat: float = 0.0,
    sat_height: float = GEO_HEIGHT,
    *,
    semimajor: float = WGS84_SEMIMAJOR,
    semiminor: float = WGS84_SEMIMINOR,
) -> tuple[np.ndarray, np.ndarray]:
    """:func:`geos_scan_to_lonlat` 的逆运算：经纬度 → 扫描角（弧度）。"""
    s, shat, east, north = _sat_frame(sub_lon, sub_lat, sat_height, semimajor, semiminor)
    phi = np.deg2rad(np.asarray(lat, dtype=np.float64))
    lam = np.deg2rad(np.asarray(lon, dtype=np.float64))
    e2 = 1.0 - (semiminor / semimajor) ** 2
    n = semimajor / np.sqrt(1.0 - e2 * np.sin(phi) ** 2)
    px = n * np.cos(phi) * np.cos(lam)
    py = n * np.cos(phi) * np.sin(lam)
    pz = n * (1.0 - e2) * np.sin(phi)
    vx, vy, vz = px - s[0], py - s[1], pz - s[2]
    vn = np.sqrt(vx * vx + vy * vy + vz * vz)
    with np.errstate(invalid="ignore", divide="ignore"):
        scan_y = np.arcsin(np.clip((vx * north[0] + vy * north[1] + vz * north[2]) / vn, -1.0, 1.0))
        scan_x = np.arctan2(
            vx * east[0] + vy * east[1] + vz * east[2],
            -(vx * shat[0] + vy * shat[1] + vz * shat[2]),
        )
    return scan_x, scan_y


def nominal_geos_lonlat(
    shape: tuple[int, int],
    sub_lon: float,
    sub_lat: float = 0.0,
    sat_height: float = GEO_HEIGHT,
    *,
    pixel_size: float = NOMINAL_PIXEL_SIZE,
    semimajor: float = WGS84_SEMIMAJOR,
    semiminor: float = WGS84_SEMIMINOR,
    rows: np.ndarray | None = None,
    cols: np.ndarray | None = None,
    chunk: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    """静止轨道标称投影反算：返回逐像元 (lat, lon)，float32。

    参数
    ----
    shape     : 全圆盘网格形状，例如 FY-4B AGRI 1km 的 (10992, 10992)、FY-2 IR 的 (2288, 2288)。
    sub_lon   : 星下点经度（FY-4B 属性 ``NOMCenterLon`` = 105.0）。
    sub_lat   : 星下点纬度（``NOMCenterLat``，一般 0.0）。
    sat_height: 卫星高度，**米**（``NOMSatHeight`` = 35786000）。
    pixel_size: 标称像元尺寸，**米**（1km 产品传 1000）。
    rows/cols : 只要这些行/列的经纬度（省内存、省时间），默认全图。
    chunk     : 内部行分块大小（控制峰值内存）。

    说明：标称网格按「星下点处 pixel_size 米/像元」换算扫描角，因此地球边缘像元
    （边缘投影拉长）依旧是整数格点，这正是 FY-4 标称产品的定义；网格略大于地球圆盘，
    圆盘外的像元返回 NaN。

    规模：全盘 10992×10992 约 21 s、峰值内存约 1.3 GB（两张 float32 结果就占 0.97 GB）；
    只做预览/叠加时传 ``rows=`` / ``cols=`` 抽稀（每 4 行约省 3/4 时间）。
    """
    nrow, ncol = int(shape[0]), int(shape[1])
    idx_r = np.arange(nrow, dtype=np.int64) if rows is None else np.asarray(rows, dtype=np.int64)
    idx_c = np.arange(ncol, dtype=np.int64) if cols is None else np.asarray(cols, dtype=np.int64)
    step = float(pixel_size) / float(sat_height)     # 弧度/像元
    scan_x = (idx_c - (ncol - 1) / 2.0) * step       # 列 → 东向角
    scan_y = -(idx_r - (nrow - 1) / 2.0) * step      # 行 → 北向角（row 向南增大）

    lat = np.empty((idx_r.size, idx_c.size), dtype=np.float32)
    lon = np.empty_like(lat)
    for start in range(0, idx_r.size, max(1, int(chunk))):
        stop = min(start + max(1, int(chunk)), idx_r.size)
        la, lo = geos_scan_to_lonlat(
            scan_x,
            scan_y[start:stop],
            sub_lon,
            sub_lat,
            sat_height,
            semimajor=semimajor,
            semiminor=semiminor,
        )
        lat[start:stop] = la
        lon[start:stop] = lo
    return lat, lon


def lonlat_to_nominal_rowcol(
    lat: np.ndarray,
    lon: np.ndarray,
    shape: tuple[int, int],
    sub_lon: float,
    sub_lat: float = 0.0,
    sat_height: float = GEO_HEIGHT,
    *,
    pixel_size: float = NOMINAL_PIXEL_SIZE,
    semimajor: float = WGS84_SEMIMAJOR,
    semiminor: float = WGS84_SEMIMINOR,
) -> tuple[np.ndarray, np.ndarray]:
    """经纬度 → 标称投影网格的浮点行列号（可用来做重投影 / 检查定位）。"""
    nrow, ncol = int(shape[0]), int(shape[1])
    scan_x, scan_y = lonlat_to_geos_scan(
        lat, lon, sub_lon, sub_lat, sat_height, semimajor=semimajor, semiminor=semiminor
    )
    step = float(pixel_size) / float(sat_height)
    col = (ncol - 1) / 2.0 + scan_x / step
    row = (nrow - 1) / 2.0 - scan_y / step
    return row, col


# ---------------------------------------------------------------- 重采样到等经纬网格

def _fold_longitudes(lon: np.ndarray) -> tuple[np.ndarray, float, float]:
    """经度跨度 > 180° 时把负经度 +360 折叠到连续区间，返回 (lon, lon_min, lon_max)。

    不折叠的话，跨日界线的数据会被劈成东西两半，网格要么塌缩要么越界。
    """
    lo, hi = float(np.nanmin(lon)), float(np.nanmax(lon))
    if hi - lo > 180.0:
        lon = np.where(lon < 0.0, lon + 360.0, lon)
        lo, hi = float(np.nanmin(lon)), float(np.nanmax(lon))
    return lon, lo, hi


def _grid_geometry(
    lo_lon: float, hi_lon: float, lo_lat: float, hi_lat: float, res: float
) -> tuple[float, float, float, int, int]:
    """把经纬范围对齐到 res 的整数倍，返回 (lon0, lat1, res, nrow, ncol)。

    对齐的好处：同一区域换 res 重采样时格心坐标可复现，也便于和其它产品叠图。
    """
    eps = 1e-9            # 抵消 floor/ceil 的浮点误差（179.2/0.1 = 1791.9999）
    lon0 = np.floor(lo_lon / res + eps) * res
    lon1 = np.ceil(hi_lon / res - eps) * res
    lat0 = np.floor(lo_lat / res + eps) * res
    lat1 = np.ceil(hi_lat / res - eps) * res
    ncol = max(1, int(round((lon1 - lon0) / res)))
    nrow = max(1, int(round((lat1 - lat0) / res)))
    return float(lon0), float(lat1), float((lon1 - lon0) / ncol), nrow, ncol


def _accumulate_bins(
    lat: np.ndarray,
    lon: np.ndarray,
    data: np.ndarray,
    lon0: float,
    lat1: float,
    res: float,
    nrow: int,
    ncol: int,
) -> tuple[np.ndarray, np.ndarray]:
    """散点累加进 nrow×ncol 网格，返回 (sums, counts)，形状均为 (nrow, ncol)。

    做法：每 200 万像元一块 → 算行列号 → ``np.bincount`` 累加。对 6000 万像元的
    MERSI 全幅也只有 30 来块，峰值内存几十 MB；比 ``np.add.at`` 快一个量级。
    """
    total = nrow * ncol
    sums = np.zeros(total, dtype=np.float64)
    counts = np.zeros(total, dtype=np.int64)
    flat_lat = np.ascontiguousarray(lat).reshape(-1)
    flat_lon = np.ascontiguousarray(lon).reshape(-1)
    flat_data = np.ascontiguousarray(data).reshape(-1)
    chunk = 2_000_000

    with np.errstate(invalid="ignore"):
        for start in range(0, flat_lat.size, chunk):
            stop = min(start + chunk, flat_lat.size)
            la = flat_lat[start:stop]
            lo = flat_lon[start:stop]
            da = flat_data[start:stop]
            ok = np.isfinite(la) & np.isfinite(lo) & np.isfinite(da)
            if not ok.any():
                continue
            la, lo = la[ok], lo[ok]
            da = da[ok].astype(np.float64)
            r = np.floor((lat1 - la) / res).astype(np.int64)     # 行号：北 → 南
            c = np.floor((lo - lon0) / res).astype(np.int64)     # 列号：西 → 东
            np.clip(r, 0, nrow - 1, out=r)
            np.clip(c, 0, ncol - 1, out=c)
            idx = r * ncol + c
            sums += np.bincount(idx, weights=da, minlength=total)
            counts += np.bincount(idx, minlength=total)
    return sums.reshape(nrow, ncol), counts.reshape(nrow, ncol)


def reproject_to_grid(
    data: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    res: float = 0.05,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    agg: str = "mean",
    min_count: int = 1,
    dtype=np.float32,
) -> GeoGrid:
    """把散点 (data, lat, lon) 投到等经纬网格（直方图加权法，O(N) 向量化）。

    参数
    ----
    data       : 与 lat/lon 同形状的物理量（1-D / 2-D 均可），NaN 会被跳过。
    lat, lon   : 逐点经纬度（度）。
    res        : 网格分辨率（度），默认 0.05。
    bounds     : (lon_min, lon_max, lat_min, lat_max)，缺省按数据范围对齐到 res 的整数倍。
    agg        : 'mean'（默认，格内平均）或 'sum'（格内累加）。
    min_count  : 有效像元下界——格子里少于这么多点就算空洞（NaN），默认 1。
    dtype      : 输出 dtype。

    返回
    ----
    :class:`GeoGrid`；``data`` 为 (nrow, ncol)，北在上、东在右，NaN = 无覆盖。
    跨 180° 经线（经度跨度 > 180°）时自动折叠到连续区间，网格不会被劈开。
    """
    data = np.asarray(data)
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    if lat.shape != lon.shape:
        raise ValueError(f"lat/lon 形状不一致: {lat.shape} vs {lon.shape}")
    if data.shape != lat.shape:
        if data.size == lat.size:
            data = data.reshape(lat.shape)
        else:
            raise ValueError(f"data/lat/lon 形状不匹配: {data.shape} {lat.shape} {lon.shape}")
    if res <= 0:
        raise ValueError("res 必须为正数")
    agg_key = agg.lower()
    if agg_key not in ("mean", "sum"):
        raise ValueError(f"agg 只支持 'mean' / 'sum'，收到 {agg!r}")

    if not (np.isfinite(lat) & np.isfinite(lon)).any():
        raise ValueError("lat/lon 全是无效值，无法重采样")
    lon, lo_lon, hi_lon = _fold_longitudes(lon)
    lo_lat, hi_lat = float(np.nanmin(lat)), float(np.nanmax(lat))
    if bounds is not None:
        lo_lon, hi_lon, lo_lat, hi_lat = (float(v) for v in bounds)

    lon0, lat1, res, nrow, ncol = _grid_geometry(lo_lon, hi_lon, lo_lat, hi_lat, res)
    sums, counts = _accumulate_bins(lat, lon, data, lon0, lat1, res, nrow, ncol)

    valid = counts >= max(1, int(min_count))
    out = np.full((nrow, ncol), np.nan, dtype=np.float64)
    if agg_key == "mean":
        np.divide(sums, counts, out=out, where=valid)
    else:
        out[valid] = sums[valid]
    extent = (lon0, float(lon0 + ncol * res), float(lat1 - nrow * res), lat1)
    return GeoGrid(out.astype(dtype, copy=False), extent, res, counts.astype(np.int32, copy=False))

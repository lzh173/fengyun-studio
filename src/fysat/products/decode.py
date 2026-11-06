"""产品解码器：按 :class:`ProductDef` 把 :class:`SatDataset` 的原始 DN 变成物理量。

分工
----
* ``pipeline.py`` 负责**特定产品族**的完整出图链路（MERSI 亮温、真彩色）。
* 本模块负责**声明式**的通用解码：YAML 说方法，这里调用 ``calib.py`` 里
  已经用真实样本验证过的函数。两者不重复实现公式。

为什么定标方法名不写公式（血泪史）
----------------------------------
早期把 MERSI 发射通道的辐亮度（0.01~1.5）当亮温显示，算出来「亮温 0.01 K」。
正确链路见 ``FY-3D_L1_Data_Instruction_MERSI-II_1KM.md`` 第 204–208 行：

    TBB = TBB_Trans_Coefficient_A * Plank^-1(radiance, Effect_Center_Wavenumber)
          + TBB_Trans_Coefficient_B

这条链路在 ``pipeline.thermal_data()`` 有一份实现（针对 1KM 通道栈，实测 187–312 K），
本模块另有 ``_mersi_thermal_chain`` 以 YAML 的 ``bands`` 为通道号来源，
覆盖 250M「独立数据集 + band_name='Band 24'」这类 pipeline 解析不了的情形。
两者公式同源（都调 ``calib``），差别只在通道号怎么定。
因此这里的方法名直接映射到已验证实现，公式只有一份。

FY-3 的系数表有几处**文档与实测不一致**，解码时严格按实测（见 ``_COEFF_ROW_NOTES``）：

* ``EV_1KM_RefSB`` 的 ``band_name`` 写 "5-19"，但 ``VIS_Cal_Coeff`` 只有 19 行，
  实测按 ``coeff[band]``（即数组索引）取才得到物理合理的反射率；
  按 ``coeff[band-5]`` 会让蓝通道只剩 2.2%。这一点在 ``pipeline.visible_data()``
  的 docstring 里有实测记录（蓝通道 p90 = 38.2%）。
* ``EV_1KM_Emissive`` 的 ``band_name`` 文档写成 "20,21,22,22,23"（重复 22），
  实测文件里是 5 个通道；这里用 ``Source``/``band_name`` 解析并去重。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import calib
from ..model import SatDataset, Variable
from .loader import resolve_path
from .schema import FieldDef, ProductDef

# 逐通道系数取行方式的实测依据（写进解码结果的 notes，便于追溯）
_COEFF_ROW_NOTES = {
    "band_index": (
        "按数组索引取系数行。依据：FY-3 EV_1KM_RefSB 的 band_name 写 '5-19'，"
        "但 VIS_Cal_Coeff 只有 19 行，实测 coeff[band] 才给出物理合理反射率"
        "（蓝通道 p90=38.2%）；按 coeff[band-5] 会让蓝通道只剩 2.2%。"
        "见 pipeline.visible_data() docstring 与 tests/test_pipeline.py。"
    ),
    "band_number_minus_one": (
        "按通道号-1 取系数行。仅用于文档与实测一致的输入（如 250m 的 b1..b4 单独数据集）。"
    ),
}

# 无效 DN 的额外兜底：FY-3 约定（属性 Description 里写明）
_FY3_BAD = (65535.0, 65534.0, 65533.0)


@dataclass
class DecodedField:
    """一个字段解码结果。``data`` 为二维（单通道）或三维（通道栈，axis 0）。"""

    name: str
    data: np.ndarray
    unit: str
    kind: str
    label: str = ""
    bands: list[int] = field(default_factory=list)
    band_axis: int | None = None
    source_path: str = ""
    method: str = ""
    valid_fraction: float = 0.0
    value_min: float | None = None
    value_max: float | None = None
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self.data.shape)

    def band(self, index: int = 0) -> np.ndarray:
        """取第 index 个通道（无通道维则原样返回）。"""
        if self.data.ndim == 3:
            return self.data[min(index, self.data.shape[0] - 1)]
        return self.data

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "shape": list(self.shape),
            "unit": self.unit,
            "kind": self.kind,
            "method": self.method,
            "bands": self.bands,
            "valid_fraction": round(self.valid_fraction, 4),
            "value_range": [self.value_min, self.value_max],
            "source_path": self.source_path,
            "warnings": self.warnings,
        }


@dataclass
class DecodeResult:
    """一次解码的汇总：成功字段 + 失败字段 + 诊断。"""

    product: ProductDef
    fields: dict[str, DecodedField] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.fields)

    @property
    def primary(self) -> DecodedField | None:
        """主显示字段：优先 thermal（窗区），其次 reflective，再次 dn。"""
        for kind in ("thermal", "reflective", "dn"):
            for f in self.fields.values():
                if f.kind == kind and f.data.ndim >= 2:
                    return f
        return next(iter(self.fields.values()), None)

    def summary(self) -> dict[str, Any]:
        return {
            "product": self.product.product,
            "verified": self.product.verified,
            "n_decoded": len(self.fields),
            "n_missing": len(self.missing),
            "n_failed": len(self.failed),
            "missing": self.missing,
            "failed": self.failed,
            "fields": {k: v.summary() for k, v in self.fields.items()},
            "notes": self.notes,
        }


# ---------------------------------------------------------------- 系数与 LUT 取用

def _load_array(ds: SatDataset, path: str) -> np.ndarray | None:
    """按路径读数组；不存在返回 None（不抛，由调用方决定）。"""
    real = resolve_path(ds.variables, path)
    if real is None:
        return None
    try:
        var = ds.load(real)
    except (KeyError, OSError, ValueError):
        return None
    arr = np.asarray(var.data)
    return arr if arr.size else None


def _coeff_for_band(ds: SatDataset, fd: FieldDef, index: int,
                    band_no: int | None) -> np.ndarray | None:
    """取该通道的定标系数行；定义里没给系数表时返回 None（由调用方回退）。

    ``calib.coeff`` 支持三种写法：

    * 内联系数 ``[a0, a1]`` / ``[a0, a1, a2]``（YAML 里直接写）
    * 路径字符串 ``"Calibration/VIS_Cal_Coeff[3]"``（带显式行号）
    * **候选路径列表**，按顺序尝试——用于系数表名在不同产品间拼写不一致的情形
      （FY-3 250M 文档写 ``VIS_Cal_Ceff``，而多数文件里是 ``VIS_Cal_Coeff``）
    """
    spec = fd.calib.get("coeff")
    if spec is None:
        return None
    if isinstance(spec, (list, tuple, np.ndarray)):
        # 数值列表 = 内联系数；字符串列表 = 候选路径
        arr = np.asarray(spec)
        if arr.dtype.kind in "fiu":
            arr = np.asarray(spec, dtype=np.float64)
            if arr.ndim == 1:
                return arr
            return arr[min(index, arr.shape[0] - 1)]
        for cand in spec:
            got = _coeff_from_path(ds, str(cand), fd, index, band_no)
            if got is not None:
                return got
        return None

    return _coeff_from_path(ds, str(spec), fd, index, band_no)


def _coeff_from_path(ds: SatDataset, path: str, fd: FieldDef, index: int,
                     band_no: int | None) -> np.ndarray | None:
    """从一条系数表路径取行。"""
    # 形如 "Calibration/VIS_Cal_Coeff[3]" → 路径 + 显式行号
    row: int | None = None
    if path.endswith("]") and "[" in path:
        path, _, idx_txt = path.rpartition("[")
        try:
            row = int(idx_txt[:-1])
        except ValueError:
            row = None

    table = _load_array(ds, path)
    if table is None:
        return None
    if table.ndim == 1:
        return table                                # 单通道系数直接就是一维
    if row is not None:
        return table[min(row, table.shape[0] - 1)]

    mode = str(fd.calib.get("coeff_row") or "band_index")
    if mode == "band_number_minus_one" and band_no is not None:
        r = band_no - 1
    elif mode == "fixed":
        r = 0
    else:                                           # band_index
        r = index
    r = int(np.clip(r, 0, table.shape[0] - 1))
    return table[r]


def _bad_dn_mask(dn: np.ndarray, fd: FieldDef, raw: np.ndarray | None = None) -> np.ndarray:
    """无效 DN 掩膜：fill/dead/saturated + valid_range，再兜底 FY-3 的三个哨兵。

    **必须在原始整数数组上比较**。``np.float32(65535) == 65535`` 为 False
    （65535 超出 float32 能精确表示的整数范围，会被舍成 65536），
    若拿转换后的 float 数组去比，填充值一个都掩不掉——这正是历史上
    「-9999.9 没清掉导致画布畸变」那类事故的同款成因。

    ``raw`` 给定时用它做填充值/范围比较；否则退回用 ``dn``。
    """
    ref = dn if raw is None else raw
    bad = np.zeros(ref.shape, dtype=bool)
    fills = fd.fill_values
    for v in fills:
        bad |= ref == v
    if not fills and fd.dn.get("no_fill_value"):
        # 明示「本产品没有填充值」：不做任何哨兵兜底。
        # FY-2 CSV 容器就是这种情况（文档 Table 4.19~4.23 未定义，实测也无哨兵），
        # 无效行由 line_quality / picture_flag 标识，不能臆造填充值。
        pass
    elif not fills:
        # 兜底只用 FY-3 的三个哨兵（65535 缺测 / 65534 饱和 / 65533 失效）。
        # 注意：这是 FY-3 系列的约定，不是所有产品的通例 ——
        # FY-4B 另有 65534=地球内无效，FY-2 的 VIS 填充值是 255。
        # 因此各产品定义**都应该显式写 dn.fill**，兜底只防止定义漏写。
        for v in _FY3_BAD:
            bad |= ref == v
    vr = fd.valid_range
    if vr is not None:
        bad |= (ref < vr[0]) | (ref > vr[1])
    return bad


def _band_slice(arr: np.ndarray, fd: FieldDef, index: int) -> np.ndarray:
    """从通道栈里取第 index 个通道。

    ``band_axis`` 显式指明通道维位置：

    * ``None``   —— 无显式声明；3 维时按第 0 维（FY-3 通道栈的实测形态）
    * ``0``      —— 通道在最前（FY-3 EV_1KM_RefSB (15,2000,2048)）
    * ``2``      —— 通道在最后（FY-3D CLM Cloud_Mask 文档写 (2000,2048,6)）
    """
    if arr.ndim <= 2:
        return arr                                  # 单通道数据集，通道维不存在
    axis = 0 if fd.band_axis is None else int(fd.band_axis)
    axis = max(0, min(axis, arr.ndim - 1))
    return np.take(arr, min(index, arr.shape[axis] - 1), axis=axis)


def _n_planes(arr: np.ndarray, fd: FieldDef) -> int:
    """通道栈的通道数（非通道栈返回 1）。"""
    if arr.ndim <= 2:
        return 1
    axis = 0 if fd.band_axis is None else int(fd.band_axis)
    axis = max(0, min(axis, arr.ndim - 1))
    return int(arr.shape[axis])


def _band_number(fd: FieldDef, index: int) -> int | None:
    if fd.bands and index < len(fd.bands):
        return int(fd.bands[index])
    return None


# ---------------------------------------------------------------- 定标方法

def _decode_vis_poly(ds: SatDataset, fd: FieldDef, dn: np.ndarray,
                     index: int) -> tuple[np.ndarray, list[str]]:
    """ρ = a0 + a1·DN + a2·DN²，单位 %（FY-3 VIS_Cal_Coeff 的行格式）。"""
    notes: list[str] = []
    band_no = _band_number(fd, index)
    coeff = _coeff_for_band(ds, fd, index, band_no)
    if coeff is None:
        # 找不到系数表就**不要**退回 DN：单位会变成"假 %"，
        # 下游会把它当反射率画图，与"把亮温当辐亮度"是同一类事故。
        raise ValueError(f"找不到系数表 {fd.calib.get('coeff')}，无法得到反射率")
    mode = str(fd.calib.get("coeff_row") or "band_index")
    if mode in _COEFF_ROW_NOTES:
        notes.append(_COEFF_ROW_NOTES[mode])
    return calib.reflectance_linear(dn, coeff, fill=None), notes


def _decode_linear(ds: SatDataset, fd: FieldDef, dn: np.ndarray,
                   index: int) -> tuple[np.ndarray, list[str]]:
    """L = a0 + a1·DN。

    两种来源，优先系数表：

    * ``calib.coeff`` 指向系数表（每行 [截距, 斜率]）
    * 否则用定义里直接写的 ``calib.scale`` / ``calib.offset``

    FY-3 GEO 产品的角度字段属于后者（属性里 Slope=0.01、Intercept=0，
    把角度放大 100 倍存成 int16）。
    """
    coeff = _coeff_for_band(ds, fd, index, _band_number(fd, index))
    if coeff is not None:
        arr = np.asarray(coeff, dtype=np.float64).reshape(-1)
        a0 = float(arr[0]) if arr.size else 0.0
        a1 = float(arr[1]) if arr.size > 1 else 1.0
        return calib.radiance_linear(dn, a1, a0, fill=None), []
    scale = float(fd.calib.get("scale", 1.0))
    offset = float(fd.calib.get("offset", 0.0))
    return dn * np.float32(scale) + np.float32(offset), [
        f"按定义直接线性定标 scale={scale} offset={offset}"
    ]


def _decode_lut(ds: SatDataset, fd: FieldDef, dn: np.ndarray, *,
                percent: bool) -> tuple[np.ndarray, list[str]]:
    """查找表定标：DN → 物理量。FY-4 `CALChannelXX` / FY-2 `CALChannelIR*`。

    ``percent`` 的最终取值由字段的 ``calib.lut_percent`` 覆盖：

    * FY-4 的 CALChannel01 值域 0~1.14（反射率**小数**）→ 必须 ×100
    * FY-2 的 CALChannelVIS 值域 0~118.39（反射率**已经是 %**）→ 不能 ×100

    这两者的差异是实测确认的（tests/test_calib.py 两处断言），
    搞反了会让反射率差 100 倍。
    """
    notes: list[str] = []
    lut = _load_array(ds, str(fd.calib.get("lut") or ""))
    if lut is None:
        # 同 vis_poly：拿不到 LUT 就不能假装 DN 是物理量。
        raise ValueError(f"找不到查找表 {fd.calib.get('lut')}，无法定标")

    if "lut_percent" in fd.calib:
        want = bool(fd.calib["lut_percent"])
        if want != percent:
            notes.append(
                f"字段声明 lut_percent={want}，覆盖方法默认 {percent}"
                f"（FY-2 的 VIS LUT 已是 %，FY-4 的是 0~1.14 小数）"
            )
        percent = want

    kind = str(fd.calib.get("lut_kind") or "nearest")
    lut_fill = fd.calib.get("lut_fill")
    out = calib.lookup_table(
        dn, lut, kind=kind,
        fill=None,                                  # DN 掩膜在 decode_field 里统一做
        lut_fill=None if lut_fill is None else float(lut_fill),
    )
    if percent:
        out = out * np.float32(100.0)               # 0~1.14 的反射率 → %
        notes.append("LUT 输出为 0~1.14 的反射率小数，已 ×100 转成 %")
    else:
        notes.append("LUT 输出已经是反射率百分比，未再 ×100")
    return out, notes


def _wavenumber_table(ds: SatDataset) -> dict[int, float]:
    """通道号 → 中心波数（cm^-1），由全局属性 Effect_Center_WaveLength 换算。

    文档（FY-3D MERSI 1KM 表5）给出 25 个通道的等效中心波长，ν = 1e4/λ。
    """
    wl = ds.attrs.get("Effect_Center_WaveLength")
    if wl is None:
        return {}
    arr = np.asarray(wl, dtype=float).reshape(-1)
    return {i + 1: (1e4 / lam if lam > 0 else float("nan"))
            for i, lam in enumerate(arr)}


def _tbb_coefficients(ds: SatDataset) -> tuple[np.ndarray, np.ndarray] | None:
    """亮温转换系数 (A, B)。

    文档（FY-3D MERSI 1KM 表5 L157-158）分别给 ``TBB_Trans_Coefficient_A``
    与 ``TBB_Trans_Coefficient_B``；部分文件把它们拼在一个
    ``TBB_Trans_Coefficient`` 里（前一半 A、后一半 B），两种都认。
    """
    a = ds.attrs.get("TBB_Trans_Coefficient_A")
    b = ds.attrs.get("TBB_Trans_Coefficient_B")
    if a is not None and b is not None:
        return np.asarray(a, dtype=float).reshape(-1), np.asarray(b, dtype=float).reshape(-1)
    both = ds.attrs.get("TBB_Trans_Coefficient")
    if both is not None:
        arr = np.asarray(both, dtype=float).reshape(-1)
        n = arr.size // 2
        if n:
            return arr[:n], arr[n:]
    return None


def _mersi_thermal_chain(ds: SatDataset, fd: FieldDef, dn: np.ndarray,
                         index: int) -> tuple[np.ndarray, list[str]]:
    """FY-3 MERSI 红外通道定标链（文档 L204-208）。

    ``TBB = A · Plank⁻¹(DN·Slope, Effect_Center_Wavenumber) + B``

    为什么不直接调 ``pipeline.thermal_data``
    ----------------------------------------
    ``pipeline.thermal_data`` 靠解析数据集的 ``band_name`` 属性来推断通道号。
    MERSI 1KM 的通道栈写的是 ``"20,21,22,23"``，能解析；
    但 **250M 产品的独立数据集写的是 ``"Band 24"``**，解析器只认纯数字，
    会退回 ``ch_no = 20 + band`` = **20**，于是用 3.8 µm 的波数去反演 10.7 µm
    通道，亮温会系统性偏错。

    因此这里以 YAML 里 ``bands: [24]``（有文档与实测支撑）为准，显式给出通道号。
    公式本身仍全部来自 ``calib``，没有第二份实现。

    数据中心波长索引
    ----------------
    ``Effect_Center_WaveLength`` 是 25 个通道的完整表（文档表5），
    所以取第 ``ch_no`` 项（1 起算 → 索引 ch_no-1），**不是**取第 index 项。
    """
    notes: list[str] = []
    real = resolve_path(ds.variables, fd.path)
    if real is None:
        raise ValueError(f"字段 {fd.name}: 主数据集 {fd.paths} 不存在")

    # 复用 decode_field 已经加载好的 Variable，不要重新 ds.load（
    # MERSI 250M 一个数据集就是 8000×8192×2 = 131 MB，重复加载会翻倍占内存）。
    var = ds.variables[real]
    if var.data.size == 0:                          # load=False 打开的场合
        var = ds.load(real)
    ch_no = _band_number(fd, index)

    # 1) DN → 辐亮度：Slope 是逐通道的（EV_1KM_Emissive 为 [0.0002,0.0002,0.01,0.01]）
    #
    # Slope 数组的元素与**该数据集自己的通道**一一对应：
    #   EV_1KM_Emissive      (4,H,W)  Slope 4 个 → 用数组内序号 index
    #   EV_250_Aggr.1KM_Emissive (2,H,W) Slope 2 个 → 也用 index
    # 所以这里用 index 是对的；不能套用上面「通道号-20」的映射。
    slope_arr = var.attrs.get("Slope")
    if slope_arr is not None:
        flat = np.asarray(slope_arr, dtype=float).reshape(-1)
        slope = float(flat[min(index, flat.size - 1)])
        notes.append(f"Slope 取第 {index} 项 = {slope}（逐通道，不能统一取 0.01）")
    elif var.scale_factor is not None:
        slope = float(var.scale_factor)
        notes.append(f"Slope 取自 scale_factor = {slope}")
    else:
        slope = 1.0
        notes.append("文件未给 Slope，按 1.0 处理（待核对）")
    offset = float(var.add_offset) if var.add_offset is not None else 0.0

    radiance = np.asarray(dn, dtype=np.float64) * slope + offset
    radiance = np.where(radiance > 0, radiance, np.nan)

    # 2) 取该通道的中心波数
    wavenumbers = _wavenumber_table(ds)
    if ch_no is not None and ch_no in wavenumbers and np.isfinite(wavenumbers[ch_no]):
        lam_um = 1e4 / wavenumbers[ch_no]
        notes.append(f"通道 b{ch_no} 中心波长 {lam_um:.4f} µm（取自 Effect_Center_WaveLength）")
    else:
        # 兜底：MERSI-II 20~25 通道的标称中心波长
        fallback = {20: 3.8, 21: 4.05, 22: 7.2, 23: 8.55, 24: 10.7342, 25: 12.0}
        lam_um = fallback.get(ch_no or -1, 10.7342)
        notes.append(
            f"未能从文件取到通道 b{ch_no} 的中心波长，用标称值 {lam_um} µm（待核对）"
        )

    bt = calib.radiance_to_bt(radiance, lam_um)

    # 3) TBB 转换订正
    #
    # TBB_Trans_Coefficient_A/B 各 **6 个**，对应发射通道 20~25（文档表5 L157-158）。
    # 所以索引必须按「通道号 - 20」取，不能用数组内的序号：
    #   EV_1KM_Emissive        bands [20,21,22,23] → 序号 0..3 恰好等于 ch-20 ✓
    #   EV_250_Aggr.1KM_Emissive bands [24,25]    → 序号 0,1 ≠ ch-20（应为 4,5）✗
    # 用序号会导致 b24/b25 套用 b20/b21 的订正系数，亮温系统性偏差。
    coeffs = _tbb_coefficients(ds)
    if coeffs is not None:
        a_arr, b_arr = coeffs
        if a_arr.size and b_arr.size:
            if ch_no is not None:
                pos = ch_no - 20                    # 20 → 0, 25 → 5
            else:
                pos = index
            ai = int(np.clip(pos, 0, a_arr.size - 1))
            bi = int(np.clip(pos, 0, b_arr.size - 1))
            bt = a_arr[ai] * bt + b_arr[bi]
            notes.append(
                f"已应用 TBB 订正（通道 b{ch_no} → 系数第 {ai} 项）"
                f"A={a_arr[ai]:.6g} B={b_arr[bi]:.6g}"
            )
    else:
        notes.append("文件未提供 TBB_Trans_Coefficient，未做亮温订正（待核对）")

    return np.asarray(bt, dtype=np.float32), notes


def _decode_mersi_planck(ds: SatDataset, fd: FieldDef, dn: np.ndarray,
                         index: int) -> tuple[np.ndarray, list[str]]:
    """FY-3 MERSI 红外：DN → 辐亮度 → 普朗克反演 → TBB 订正（单位 K）。"""
    return _mersi_thermal_chain(ds, fd, dn, index)


def _decode_identity(dn: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Slope=1、Intercept=0：物理量即 DN 原值（FY-3 GNOSO 实测如此）。"""
    return calib.dn_to_float(dn, fill=None), [
        "文件属性 Slope=1、Intercept=0，DN 即物理量（GNOSO 实测，见 readers/nc3.py）"
    ]


_DECODERS: dict[str, Callable[..., tuple[np.ndarray, list[str]]]] = {
    "vis_poly": _decode_vis_poly,
    "mersi_planck": _decode_mersi_planck,
    "linear": _decode_linear,
}

_LUT_DECODERS = {
    "lut_reflectance": True,
    "lut_bt": False,
}


# ---------------------------------------------------------------- 单字段解码

def decode_field(ds: SatDataset, fd: FieldDef) -> DecodedField:
    """按字段定义解码一个字段，返回物理量（含无效值 NaN）。"""
    real = resolve_path(ds.variables, fd.path)
    if real is None:
        raise KeyError(f"字段 {fd.name}: 数据集 {fd.paths} 都不在文件里")

    var: Variable = ds.load(real)
    raw = np.asarray(var.data)
    if raw.size == 0:
        raise ValueError(f"字段 {fd.name}: 数据集 {real} 为空")

    method = str(fd.calib.get("method") or "raw_dn")
    n_planes = _n_planes(raw, fd)

    planes: list[np.ndarray] = []
    notes: list[str] = []
    warnings: list[str] = []
    for i in range(n_planes):
        dn_raw = _band_slice(raw, fd, i)
        # 掩膜在**原始整数**上做，避免 float32 把 65535 舍成 65536 后漏掩
        bad = _bad_dn_mask(dn_raw, fd, raw=dn_raw)
        dn_f = calib.dn_to_float(dn_raw, fill=None)

        if method in _DECODERS:
            out, sub = _DECODERS[method](ds, fd, dn_f, i)
            notes.extend(n for n in sub if n not in notes)
        elif method in _LUT_DECODERS:
            out, sub = _decode_lut(ds, fd, dn_f, percent=_LUT_DECODERS[method])
            notes.extend(n for n in sub if n not in notes)
        elif method == "identity":
            out, sub = _decode_identity(dn_f)
            notes.extend(n for n in sub if n not in notes)
        else:                                        # raw_dn / flag
            out = dn_f

        out = np.asarray(out, dtype=np.float32)
        bad = bad | ~np.isfinite(out)
        if bad.any():
            out = np.where(bad, np.float32("nan"), out)
        planes.append(out)

    data = planes[0] if len(planes) == 1 else np.stack(planes, axis=0)
    finite = np.isfinite(data)
    frac = float(finite.mean()) if data.size else 0.0
    vmin = float(np.nanmin(data)) if finite.any() else None
    vmax = float(np.nanmax(data)) if finite.any() else None

    if frac == 0.0:
        warnings.append("全部像元都被判为无效：可能是夜间景（反射通道全 0）或填充值设错")
    elif frac < 0.05:                               # noqa: PLR2004
        warnings.append(f"有效像元仅 {frac * 100:.1f}%")

    # 通道栈在内存里统一成 axis 0（便于 DecodedField.band() 取通道），
    # 但要把原始通道维位置记下来，便于追溯。
    if data.ndim == 3 and fd.band_axis not in (None, 0):
        notes.append(
            f"文件里通道维在第 {fd.band_axis} 维，解码后统一转成 axis 0"
        )

    return DecodedField(
        name=fd.name,
        data=data,
        unit=fd.unit or str(var.unit or ""),
        kind=fd.kind,
        label=fd.label or fd.name,
        bands=list(fd.bands),
        band_axis=0 if data.ndim == 3 else None,
        source_path=real,
        method=method,
        valid_fraction=frac,
        value_min=vmin,
        value_max=vmax,
        notes=notes + list(fd.notes),
        warnings=warnings,
    )


# ---------------------------------------------------------------- 整产品解码

def decode(ds: SatDataset, pdef: ProductDef, *,
           fields: list[str] | None = None,
           include_aux: bool = False) -> DecodeResult:
    """按产品定义解码整个数据集。

    单个字段失败**不影响**其它字段：错误进 ``failed``，缺失进 ``missing``。
    """
    res = DecodeResult(product=pdef)
    wanted = pdef.fields if fields is None else [pdef.field(f) for f in fields]

    for fd in wanted:
        if not include_aux and fd.kind in ("table",):
            continue
        real = resolve_path(ds.variables, fd.path)
        if real is None:
            if fd.required:
                res.missing.append(fd.name)
            continue
        try:
            res.fields[fd.name] = decode_field(ds, fd)
        except (KeyError, ValueError, TypeError, MemoryError) as exc:
            res.failed[fd.name] = f"{type(exc).__name__}: {exc}"

    if pdef.pending_verification:
        res.notes.append(
            f"该产品定义有 {len(pdef.pending_verification)} 项待核对："
            + "；".join(pdef.pending_verification[:3])
        )
    if not pdef.verified:
        res.notes.append("该产品定义标记为未验证（verified=false），结果需人工复核")
    return res


def describe_variables(ds: SatDataset, pdef: ProductDef | None = None) -> list[dict[str, Any]]:
    """把文件里的数据集按产品定义归类，供 CLI / GUI 使用。"""
    from .loader import guess_field_from_dataset

    rows: list[dict[str, Any]] = []
    for var in ds.variables.values():
        fd = guess_field_from_dataset(pdef, var.name) if pdef else None
        rows.append({
            "path": var.name,
            "shape": list(var.shape),
            "dtype": str(var.dtype),
            "unit": var.unit,
            "field": fd.name if fd else "",
            "kind": fd.kind if fd else "unknown",
        })
    return rows


def available_images(ds: SatDataset, pdef: ProductDef) -> list[tuple[str, int]]:
    """该产品定义下可导出的 (字段名, 通道索引) 列表。"""
    out: list[tuple[str, int]] = []
    for fd in pdef.image_fields():
        real = resolve_path(ds.variables, fd.path)
        if real is None:
            continue
        var = ds.load(real)
        arr = np.asarray(var.data)
        n = _n_planes(arr, fd)
        out.extend((fd.name, i) for i in range(max(1, n)))
    return out


__all__ = [
    "DecodedField",
    "DecodeResult",
    "decode",
    "decode_field",
    "describe_variables",
    "available_images",
]

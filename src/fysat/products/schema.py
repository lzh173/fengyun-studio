"""产品定义 schema：把「这是什么产品、取哪些字段、怎么定标、怎么显示」声明化。

设计原则
--------
1. **声明式**：产品差异全部落在 YAML，不写代码。新增一个产品 = 新增一个 ``*.yml``。
2. **可追溯**：每个产品定义必须写明 ``evidence``（文档路径 + 真实样本 + 已通过
   的测试锚点）。没有证据的字段一律进 ``pending_verification``，不许猜。
3. **与本项目既有实现对齐**：定标方法名直接对应 ``calib.py`` / ``pipeline.py``
   里**已被真实样本验证过**的函数，不另起炉灶。

为什么不让 YAML 自己写公式
--------------------------
之前踩过的坑：把 MERSI 发射通道的辐亮度（0.01~1.5）当成亮温显示，得出
「亮温 0.01 K」这种荒唐值。正确链路在
``FY-3D_L1_Data_Instruction_MERSI-II_1KM.md`` 第 204–208 行：

    TBB = TBB_Trans_Coefficient_A * Plank^-1(radiance, Effect_Center_Wavenumber)
          + TBB_Trans_Coefficient_B

这条链路在 ``pipeline.thermal_data()`` 已实现并有真实样本回归
（``tests/test_pipeline.py::test_real_brightness_temperature_is_physical``，
实测 187–312 K）。``products/decode.py`` 的 ``mersi_planck`` 复用同一条公式链
（两者都调 ``calib``），差别只在通道号来源：pipeline 解析 ``band_name``，
产品定义用 YAML 的 ``bands``（``"Band 24"`` 这类写法 pipeline 解析不出来）。
所以 YAML 只声明 **method 名**，公式留在代码里，YAML 里写公式只会引入
第二份可能写错的真相。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 字段语义类别
FIELD_KINDS: frozenset[str] = frozenset({
    "reflective",   # 太阳反射通道 → 反射率 %
    "thermal",      # 热发射通道 → 亮温 K
    "dn",           # 只有原始 DN（无法从容器内得到物理量）
    "flag",         # 质量码 / 类别 / 位标志
    "table",        # 定标表、系数表（辅助数据，不是影像）
})

# 定标方法 → 实现位置
#   vis_poly        FY-3 可见光多项式   ρ = a0 + a1·DN + a2·DN²   （单位 %）
#   mersi_planck    FY-3 红外普朗克链   DN→辐亮度→亮温→TBB 订正     （单位 K）
#   lut_reflectance FY-4 LUT → 反射率   ×100 得 %                  （单位 %）
#   lut_bt          FY-4 / FY-2 LUT → 亮温                          （单位 K）
#   linear          线性辐亮度 L = slope·DN + offset
#   identity        文件自报 Slope=1/Intercept=0，物理量即原值（GNOSO）
#   raw_dn          保持原始 DN（仅做无效值掩膜）
#   flag            类别/位标志，保持整数
CALIB_METHODS: frozenset[str] = frozenset({
    "vis_poly", "mersi_planck", "lut_reflectance", "lut_bt",
    "linear", "identity", "raw_dn", "flag",
})

# 需要额外资源路径的方法
METHODS_NEEDING_LUT: frozenset[str] = frozenset({"lut_reflectance", "lut_bt"})
# ``vis_poly`` 必须给系数表路径；``linear`` 既可以用系数表，也可以直接给
# scale/offset（FY-3 GEO 产品的角度字段就是 Slope=0.01 直接写在属性里）。
METHODS_NEEDING_COEFF: frozenset[str] = frozenset({"vis_poly"})

# 系数行解析方式
COEFF_ROW_MODES: frozenset[str] = frozenset({
    "band_index",            # 用数组里的通道索引（FY-3 栈式数据集的实测行为）
    "band_number_minus_one", # 用通道号 - 1（b1→row0 的 19 行表）
    "explicit",              # YAML 里给出显示列表
    "fixed",                 # 所有通道共用一行
})


class ProductDefError(ValueError):
    """产品定义不合法（YAML 写错、字段缺失、方法名未知）。"""


def _as_list(value: Any) -> list[Any]:
    """标量 / 列表都归一成 list（None → []）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ---------------------------------------------------------------- 匹配规则

@dataclass
class MatchRule:
    """产品匹配条件。文件名是**硬条件**，属性是**软条件**（可用于加分/否决）。"""

    filename: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    container: str = ""

    def __post_init__(self) -> None:
        import re

        if not self.filename:
            raise ProductDefError("match.filename 不能为空：没有文件名规则就无法匹配")
        try:
            re.compile(self.filename)
        except re.error as exc:                     # noqa: PERF203
            raise ProductDefError(f"match.filename 不是合法正则: {self.filename!r} ({exc})") from exc


# ---------------------------------------------------------------- 定位

@dataclass
class GeoDef:
    """定位方式。

    ``method``:
      * ``latlon_grid`` —— 文件自带粗经纬网格，插值到全分辨率
      * ``auto``        —— 交给读取器的通用探测结果（``ds.geolocation``）
      * ``nominal``     —— 静止轨道标称投影（由读取器/geo.py 处理）
      * ``none``        —— 无逐像元定位（如 CSV 容器只有稀疏映射块）
    """

    method: str = "auto"
    lat: list[str] = field(default_factory=list)     # 候选路径，按顺序尝试
    lon: list[str] = field(default_factory=list)
    step: int = 20                                   # 粗网格采样间隔（像元）
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lat = [str(v) for v in _as_list(self.lat)]
        self.lon = [str(v) for v in _as_list(self.lon)]
        self.step = int(self.step or 1)


# ---------------------------------------------------------------- 字段

@dataclass
class FieldDef:
    """一个可解码字段（一个数据集，或一个通道栈）。

    ``path`` 可以是单个字符串，也可以是**候选列表**：FY-3 的 GEO 分组在不同卫星上
    写成 ``/GEO/`` 或 ``/Geolocation/``，用候选列表 + basename 回退比硬编码更稳。
    """

    name: str
    path: Any = ""
    kind: str = "dn"
    unit: str = ""
    label: str = ""
    band_axis: int | None = None          # 通道维；None = 无通道维（数据集本身就是二维）
    bands: list[int] = field(default_factory=list)   # 物理通道号，如 [20,21,22,23]
    channel: str = ""                     # 非数字通道名，如 "IR1" / "VIS"
    dn: dict[str, Any] = field(default_factory=dict)
    calib: dict[str, Any] = field(default_factory=dict)
    display: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    required: bool = True
    auto: bool = False                    # 由 auto_fields 规则生成

    def __post_init__(self) -> None:
        if not self.name:
            raise ProductDefError("field.name 不能为空")
        if not _as_list(self.path):
            raise ProductDefError(f"字段 {self.name}: path 不能为空")
        self.bands = [int(b) for b in _as_list(self.bands)]
        if self.kind not in FIELD_KINDS:
            raise ProductDefError(
                f"字段 {self.name}: kind={self.kind!r} 未知，可选 {sorted(FIELD_KINDS)}"
            )
        # 某些 YAML 没写 calib（纯 DN 字段）→ 这里补成独立 dict，避免共享默认值
        if not isinstance(self.calib, dict):
            self.calib = dict(self.calib or {})
        method = str(self.calib.get("method") or ("flag" if self.kind == "flag" else "raw_dn"))
        self.calib["method"] = method
        if method not in CALIB_METHODS:
            raise ProductDefError(
                f"字段 {self.name}: calib.method={method!r} 未知，可选 {sorted(CALIB_METHODS)}"
            )
        if method in METHODS_NEEDING_LUT and not self.calib.get("lut"):
            raise ProductDefError(f"字段 {self.name}: 方法 {method} 需要 calib.lut")
        if method in METHODS_NEEDING_COEFF and not self.calib.get("coeff"):
            raise ProductDefError(f"字段 {self.name}: 方法 {method} 需要 calib.coeff")
        mode = str(self.calib.get("coeff_row") or "band_index")
        if mode not in COEFF_ROW_MODES:
            raise ProductDefError(
                f"字段 {self.name}: coeff_row={mode!r} 未知，可选 {sorted(COEFF_ROW_MODES)}"
            )
        self.calib["coeff_row"] = mode

    # -- 便捷访问 --------------------------------------------------

    @property
    def paths(self) -> list[str]:
        return [str(p) for p in _as_list(self.path)]

    @property
    def valid_range(self) -> tuple[float, float] | None:
        vr = self.dn.get("valid_range")
        if vr is None:
            return None
        seq = _as_list(vr)
        if len(seq) < 2:                            # noqa: PLR2004
            return None
        return float(seq[0]), float(seq[1])

    @property
    def fill_values(self) -> tuple[float, ...]:
        """所有代表「无效」的 DN。

        除常规的 fill / dead / saturated 外，还认 ``in_earth_invalid``：
        FY-4 文档（L686）明确「地球内无效像素填 65534，地球外填 65535」，
        两者都应掩成 NaN，否则圆盘内的坏像元会被当成有效值参与统计。

        若产品**确实没有填充值**，在 ``dn`` 里写 ``no_fill_value: true``：
        这样解码器既不会臆造哨兵，也不会套用 FY-3 的 65535 兜底
        （FY-2 CSV 容器就是这种情况）。
        """
        out: list[float] = []
        for key in ("fill", "dead", "saturated", "in_earth_invalid"):
            for v in _as_list(self.dn.get(key)):
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    continue
        return tuple(out)

    @property
    def is_image(self) -> bool:
        """能否作为二维影像导出。

        flag（云掩膜/质量码等二维标志平面）**算**：这类产品的主体就是掩膜，
        排除它会让 CLM 这样的产品完全无法出图。
        不可成像的是 coord（一维坐标轴）与 table（系数/查找表）。
        """
        return self.kind in ("reflective", "thermal", "dn", "flag")


# ---------------------------------------------------------------- 产品

@dataclass
class ProductDef:
    """一个产品定义。"""

    product: str
    title: str = ""
    platform: str = ""
    instrument: str = ""
    level: str = ""
    container: str = ""
    reader: str = ""
    match: MatchRule = field(default_factory=MatchRule)
    fields: list[FieldDef] = field(default_factory=list)
    geolocation: GeoDef = field(default_factory=GeoDef)
    display: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    pending_verification: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    verified: bool = False
    priority: int = 0
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.product:
            raise ProductDefError("product 标识不能为空")
        from collections import Counter

        counts = Counter(f.name for f in self.fields)
        dup = sorted(n for n, c in counts.items() if c > 1)
        if dup:
            raise ProductDefError(f"产品 {self.product}: 字段名重复 {dup}")

    # -- 查询 ------------------------------------------------------

    def field(self, name: str) -> FieldDef:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"产品 {self.product} 没有字段 {name}；可选 {[f.name for f in self.fields]}")

    def image_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.is_image]

    @property
    def specificity(self) -> int:
        """匹配优先级：条件越多越具体。用于同族定义（4000M vs 1000M）排序。

        **``priority`` 是显式的首要依据**。只靠「正则长度」并不可靠：
        FY-3 GEO 产品的正则含 ``GEO``（3 字符），而主产品含 ``1000M``（5 字符），
        按长度会把 GEO 文件判给主产品。所以需要更具体的定义显式写 ``priority: 10``。
        """
        score = 1000 * int(self.priority)
        score += len(self.match.filename)
        score += 40 * len(self.match.attrs)
        if self.match.container:
            score += 20
        if self.level:
            score += 5
        return score

    def to_summary(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "title": self.title,
            "platform": self.platform,
            "instrument": self.instrument,
            "level": self.level,
            "container": self.container,
            "verified": self.verified,
            "n_fields": len(self.fields),
            "n_image_fields": len(self.image_fields()),
            "n_pending": len(self.pending_verification),
            "filename": self.match.filename,
        }

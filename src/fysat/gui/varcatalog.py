"""变量分类：区分"可成像的数据"与"辅助表/坐标/质量码"。

这是早期版本最大的设计缺陷：把 Calibration/* 之类的校准表也列进 RGB 下拉框，
用户一选就崩（尺寸 15×2 vs 2748×2748）。分类必须在数据模型层就做掉，
而不是让 UI 到处判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# 通道维的判定：第一维较小且远小于最后一维
_MAX_BANDS = 64


@dataclass
class VarClass:
    """一个变量的分类结果。"""

    name: str
    kind: str                 # image | band_stack | coord | table | qa | other
    shape: tuple[int, ...]
    bands: int = 1
    unit: str = ""
    label: str = ""

    @property
    def is_image(self) -> bool:
        """能否直接当图像显示（二维影像 / 可拆的通道栈 / 质量码平面）。

        质量码与云掩膜本质就是二维平面，能画也能导出；
        早期把 qa 排除在外，导致 FY-3D CLM 这类"整个产品就是掩膜"
        的数据被判成"无可成像变量"，完全用不了。
        """
        return self.kind in ("image", "band_stack", "qa")

    @property
    def is_rgb_candidate(self) -> bool:
        """能否参与 RGB 合成（必须是影像，且不是坐标/表）。"""
        return self.is_image


def classify(name: str, shape: tuple[int, ...], unit: str = "",
             long_name: str = "") -> VarClass:
    """按名字与形状判定变量类别。"""
    low = name.lower()
    ndim = len(shape)

    # 明显是辅助表/坐标的
    coord_hint = ("latitude", "longitude", "lat", "lon", "x", "y")
    table_hint = ("coeff", "coef", "calchannel", "calibration", "lut", "esun",
                  "dn_average", "dn_normalized", "angle", "zenith", "azimuth",
                  "attitude", "orbit", "ephemeris", "time", "frame", "count")
    qa_hint = ("quality", "qa", "flag", "mask", "dqf", "bit")

    base = low.rsplit("/", 1)[-1]

    # 坐标轴 / 定位数据：**与维数无关**。
    # 2-D 的 Latitude/Longitude 是逐像元定位场，不是可展示影像；
    # 早期只判 ndim==1，导致"回退选一个影像来渲染"时挑到 Latitude。
    if any(base == h or base.startswith(h) for h in coord_hint):
        return VarClass(name, "coord", shape, unit=unit)
    # 行列号/扫描线号也是索引数组，同理
    if any(base.startswith(h) for h in ("columnnumber", "rownumber", "column_",
                                        "row_", "linenumber", "pixel")):
        return VarClass(name, "coord", shape, unit=unit)
    # 质量码（必须早于 table 判定：QA_Frame_Flag 同时含 "frame" 与 "flag"，
    # 而它本质是质量码，不是标定表）
    if any(h in low for h in qa_hint):
        return VarClass(name, "qa", shape, unit=unit)
    # 校准/系数表
    if any(h in low for h in table_hint):
        return VarClass(name, "table", shape, unit=unit)

    if ndim == 2:
        h, w = shape
        # 极扁/极窄的不是影像（(200,1) 这种一维质量码要归 qa，不能归 table）
        if min(h, w) < 8:
            kind = "qa" if any(hh in low for hh in qa_hint) else "table"
            return VarClass(name, kind, shape, unit=unit)
        return VarClass(name, "image", shape, unit=unit)

    if ndim == 3:
        from ..render import _band_axis

        ax = _band_axis(shape)
        if ax is not None:
            return VarClass(name, "band_stack", shape, bands=int(shape[ax]), unit=unit)
        return VarClass(name, "other", shape, unit=unit)

    return VarClass(name, "other", shape, unit=unit)


def classify_dataset(ds) -> dict[str, VarClass]:
    """对整个数据集分类。"""
    out = {}
    for name, var in ds.variables.items():
        shape = tuple(var.shape)
        out[name] = classify(name, shape, var.unit, getattr(var, "long_name", ""))
    return out


def image_names(ds, same_shape_as: tuple[int, ...] | None = None) -> list[str]:
    """返回可成像的变量名，可按形状过滤（RGB 合成需要同网格）。"""
    classes = classify_dataset(ds)
    names = [n for n, c in classes.items() if c.is_image]
    if same_shape_as is not None:
        names = [n for n in names if classes[n].shape == tuple(same_shape_as)]
    return names


def rgb_choices(ds, base_shape: tuple[int, ...] | None = None) -> list[tuple[str, str]]:
    """RGB 下拉框的选项：(显示名, 变量名)。

    只包含影像；若给了 base_shape，则只留同形状的，避免用户选出无法合成的组合。
    """
    classes = classify_dataset(ds)
    out = []
    for name, c in classes.items():
        if not c.is_rgb_candidate:
            continue
        # 只比较**空间维**（最后两维）。多通道堆栈的完整 shape 首维是通道数，
        # 用完整 shape 比较会让 (4,2000,2048) 与 (15,2000,2048) 互斥，
        # 于是"真彩色(b1-b4) + 红外(b24)"这种跨数据集组合永远选不出来。
        if base_shape is not None and tuple(c.shape[-2:]) != tuple(tuple(base_shape)[-2:]):
            continue
        label = name
        if c.kind == "band_stack":
            label = f"{name}  ({c.bands} 通道)"
        out.append((label, name))
    return out


def describe_class(c: VarClass) -> str:
    """给 UI 显示的类别标签。"""
    return {
        "image": "影像",
        "band_stack": f"多通道({c.bands})",
        "coord": "坐标",
        "table": "校准/表",
        "qa": "质量码",
        "other": "其他",
    }.get(c.kind, c.kind)

# ---------------- 物理量判定（给变量表显示） ----------------

def physical_label(ds, name: str) -> str:
    """这个变量做定标后得到什么物理量？

    返回简短标签，给界面上的变量表用：
        反射率 / 反射率% / 亮温 K / 辐亮度 / DN / DN(无定标)
    判定依据与实际定标链路一致（pipeline.visible_data / thermal_data）。
    """
    import re as _re

    var = (getattr(ds, "variables", {}) or {}).get(name)
    if var is None:
        return ""
    base = str(name).rsplit("/", 1)[-1]
    low = str(name).lower()
    attrs = getattr(var, "attrs", {}) or {}

    # AVHRR：数据集自带 band_type / physical_unit
    bt = str(attrs.get("band_type") or "").lower()
    unit = str(attrs.get("physical_unit") or "")
    if bt in ("visible", "near-infrared"):
        return "反射率%" if unit == "%" else "反射率"
    if bt == "infrared":
        return "亮温 K（待定标）"

    # MERSI：反射栈 vs 发射栈
    if "refsb" in low or "refs" in low:
        return "反射率"
    if "emissive" in low:
        return "亮温 K"

    # AGRI / GHI：NOMChannel01-06 反射，07-15 热
    m = _re.search(r"NOMChannel(\d{2})\b", base, _re.IGNORECASE)
    if m:
        ch = int(m.group(1))
        if _re.search(r"CALChannel(\d{2})", " ".join(getattr(ds, "variables", {}))):
            return "反射率" if ch <= 6 else "亮温 K"
        return "反射率" if ch <= 6 else "亮温 K"

    # FY-2：IRn / VIS
    if _re.match(r"(NOMChannel)?IR[1-4]$", base, _re.IGNORECASE):
        has_lut = any(n.endswith(f"CALChannelIR{base[-1]}") for n in getattr(ds, "variables", {}))
        return "亮温 K" if has_lut else "DN(无定标)"
    if _re.match(r"(NOMChannel)?(VIS\d*|VS\d)$", base, _re.IGNORECASE):
        has_lut = any("CALChannelVIS" in n for n in getattr(ds, "variables", {}))
        return "反射率%" if has_lut else "DN(无定标)"

    return "DN"



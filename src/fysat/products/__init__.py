"""产品定义库：把「文件 → 产品语义 → 物理量」的声明式层。

模块划分
--------
* :mod:`schema`  —— 数据结构与校验（ProductDef / FieldDef / GeoDef / MatchRule）
* :mod:`loader`  —— 读 ``products/*.yml``，按文件名+容器+属性匹配
* :mod:`decode`  —— 按定义调用 ``calib`` / ``pipeline`` 的定标链得到物理量

设计约束（来自项目踩坑记录）
----------------------------
1. **字段路径、定标方式、单位必须有真实文件或文档支撑**。每个 YAML 都带
   ``evidence``（文档路径 + 样本 + 回归测试锚点）与 ``pending_verification``
   （写不清的地方），不猜。
2. **定标公式只留一份实现**。YAML 只写方法名，公式在 ``calib.py`` 里，且必须
   有真实样本回归。曾有「把亮温当辐亮度显示、算出 0.01~1.5」的事故，
   原因就是另一份手写公式没走文档链路。
3. **单文件失败不影响整体**。定义加载与解码都是错误隔离的。
"""
from __future__ import annotations

from .decode import DecodedField, DecodeResult, available_images, decode, decode_field
from .loader import PRODUCTS_DIR, ProductRegistry, load_def, load_file, resolve_path
from .schema import CALIB_METHODS, FIELD_KINDS, FieldDef, GeoDef, MatchRule, ProductDef

__all__ = [
    "CALIB_METHODS",
    "FIELD_KINDS",
    "PRODUCTS_DIR",
    "DecodedField",
    "DecodeResult",
    "FieldDef",
    "GeoDef",
    "MatchRule",
    "ProductDef",
    "ProductRegistry",
    "available_images",
    "decode",
    "decode_field",
    "load_def",
    "load_file",
    "resolve_path",
]


def registry() -> ProductRegistry:
    """加载内置 ``products/*.yml``（带缓存）。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = ProductRegistry.from_dir(PRODUCTS_DIR)
    return _CACHE


def reload() -> ProductRegistry:
    """清缓存后重新加载（测试与热更新用）。"""
    global _CACHE
    _CACHE = None
    return registry()


_CACHE: ProductRegistry | None = None

"""产品定义加载器：把 ``products/*.yml`` 变成 :class:`ProductDef`，并按文件匹配。

匹配策略（三层，从硬到软）
--------------------------
1. **文件名正则**（硬条件，必须命中）
2. **容器类型**（有写就校验，``sniff()`` 的结果）
3. **全局属性**（软条件，用于区分同族档位；属性缺失时不算失配）

同族多定义（FY-4B 的 0500M/1000M/2000M/4000M 四个档位）靠 ``specificity``
排序：条件越具体越优先。这样 ``*.yml`` 的加载顺序不影响结果。

路径解析
--------
YAML 里写的字段路径常有三种情况，加载后统一交给 :func:`resolve_path`：

* 精确路径 ``Data/EV_1KM_Emissive``
* 含通配 ``Data/NOMChannel*``（FY-4B 15 个通道各一个数据集）
* 候选列表 + basename 回退（``/GEO/Latitude`` vs ``/Geolocation/Latitude``）

**不做模糊猜测**：解析不到就返回 ``None``，由上层决定是跳过还是报错。
"""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .schema import FieldDef, GeoDef, MatchRule, ProductDef, ProductDefError

# 内置定义目录
PRODUCTS_DIR = Path(__file__).resolve().parent

# 全局属性名的常见写法归一（不同卫星/工具写 "Dataset Name" / "Dataset_Name"）
_ATTR_NORMALISE = {
    "dataset name": ("dataset name", "dataset_name", "datasetname"),
    "satellite name": ("satellite name", "satellite_name", "satellitename"),
    "sensor name": ("sensor name", "sensor_name", "sensorname"),
    "sensor identification code": ("sensor identification code",
                                   "sensor_identification_code"),
    "data level": ("data level", "data_level", "datalevel"),
    "data name": ("data name", "data_name", "dataname"),
    "product name": ("product name", "product_name", "productname"),
}


def _attr_aliases(name: str) -> tuple[str, ...]:
    """属性名 → 可能出现在文件里的所有写法。"""
    low = name.strip().lower()
    if low in _ATTR_NORMALISE:
        return _ATTR_NORMALISE[low]
    alt = re.sub(r"[ _]", "", low)
    return (low, low.replace(" ", "_"), alt)


# ---------------------------------------------------------------- YAML → 对象

def _field_from_dict(raw: dict[str, Any], product: str) -> FieldDef:
    if not isinstance(raw, dict):
        raise ProductDefError(f"产品 {product}: fields 里出现非映射项 {raw!r}")
    known = {
        "name", "path", "kind", "unit", "label", "band_axis", "bands", "channel",
        "dn", "calib", "display", "notes", "required", "auto",
    }
    unknown = set(raw) - known
    if unknown:
        raise ProductDefError(
            f"产品 {product}: 字段 {raw.get('name')!r} 含未知键 {sorted(unknown)}"
        )
    return FieldDef(**raw)


def _geo_from_dict(raw: Any) -> GeoDef:
    if raw is None:
        return GeoDef()
    if isinstance(raw, str):
        return GeoDef(method=raw)
    if not isinstance(raw, dict):
        raise ProductDefError(f"geolocation 应为映射或字符串，收到 {type(raw).__name__}")
    known = {"method", "lat", "lon", "step", "notes"}
    unknown = set(raw) - known
    if unknown:
        raise ProductDefError(f"geolocation 含未知键 {sorted(unknown)}")
    return GeoDef(**raw)


def _match_from_dict(raw: Any) -> MatchRule:
    if raw is None:
        raise ProductDefError("缺少 match 段；至少要给 filename 正则")
    if isinstance(raw, str):
        return MatchRule(filename=raw)
    if not isinstance(raw, dict):
        raise ProductDefError(f"match 应为映射或字符串，收到 {type(raw).__name__}")
    known = {"filename", "attrs", "container"}
    unknown = set(raw) - known
    if unknown:
        raise ProductDefError(f"match 含未知键 {sorted(unknown)}")
    return MatchRule(
        filename=str(raw.get("filename") or ""),
        attrs={str(k): str(v) for k, v in (raw.get("attrs") or {}).items()},
        container=str(raw.get("container") or ""),
    )


def _expand_auto_fields(patterns: Iterable[str], template: dict[str, Any]) -> list[dict[str, Any]]:
    """按 ``auto_fields`` 规则把 dataset 名批量展开成字段定义。

    典型用途：FY-4B 的 ``Data/NOMChannel01`` … ``Data/NOMChannel15``，
    15 个通道属性完全一致，没必要在 YAML 里抄 15 遍::

        auto_fields:
          - paths: [Data/NOMChannel01, Data/NOMChannel02]
            kind: reflective
            unit: '%'
            calib: {method: lut_reflectance, lut: ...}

    ``name`` 不给时用 dataset 的 basename（如 ``NOMChannel01``）。
    ``bands`` 只给一个值时按顺序自动编号（第 1 个 paths 用 bands[0]，依此类推）。
    """
    out: list[dict[str, Any]] = []
    pats = [str(p) for p in patterns]
    band_seq = template.get("bands")
    for i, pat in enumerate(pats):
        item = {**template, "path": pat}
        if not item.get("name"):
            item["name"] = pat.rstrip("/").rsplit("/", 1)[-1]
        if isinstance(band_seq, (list, tuple)) and len(band_seq) == len(pats):
            item["bands"] = [band_seq[i]]
        elif isinstance(band_seq, int):
            item["bands"] = [band_seq + i]
        out.append(item)
    return out


_PRODUCT_KEYS = {
    "product", "title", "platform", "instrument", "level", "container", "reader",
    "match", "fields", "auto_fields", "geolocation", "display", "quality",
    "evidence", "pending_verification", "notes", "verified", "priority",
}


def load_def(data: dict[str, Any], source_path: Path | None = None) -> ProductDef:
    """从已解析的 dict 建 :class:`ProductDef`（YAML/JSON 都走这里）。"""
    if not isinstance(data, dict):
        raise ProductDefError(f"产品定义应为映射，收到 {type(data).__name__}")
    unknown = set(data) - _PRODUCT_KEYS
    if unknown:
        raise ProductDefError(
            f"产品定义 {data.get('product')!r} 含未知顶层键 {sorted(unknown)}；"
            f"已知键 {sorted(_PRODUCT_KEYS)}"
        )

    product = str(data.get("product") or "").strip()
    if not product:
        raise ProductDefError(f"{source_path or '<内存>'} 缺少 product 标识")

    raw_fields = list(data.get("fields") or [])
    for spec in data.get("auto_fields") or []:
        if not isinstance(spec, dict):
            raise ProductDefError(f"产品 {product}: auto_fields 项应为映射")
        spec = dict(spec)                        # 不改调用方的数据结构
        patterns = spec.pop("paths", None)
        if not patterns:
            raise ProductDefError(f"产品 {product}: auto_fields 缺少 paths")
        raw_fields.extend(_expand_auto_fields(patterns, template=spec))

    fields = [_field_from_dict(f, product) for f in raw_fields]
    if not fields:
        raise ProductDefError(f"产品 {product}: fields 为空，至少定义一个字段")

    pdef = ProductDef(
        product=product,
        title=str(data.get("title") or ""),
        platform=str(data.get("platform") or ""),
        instrument=str(data.get("instrument") or ""),
        level=str(data.get("level") or ""),
        container=str(data.get("container") or ""),
        reader=str(data.get("reader") or ""),
        match=_match_from_dict(data.get("match")),
        fields=fields,
        geolocation=_geo_from_dict(data.get("geolocation")),
        display=dict(data.get("display") or {}),
        quality=dict(data.get("quality") or {}),
        evidence=dict(data.get("evidence") or {}),
        pending_verification=[str(v) for v in (data.get("pending_verification") or [])],
        notes=[str(v) for v in (data.get("notes") or [])],
        verified=bool(data.get("verified", False)),
        priority=int(data.get("priority") or 0),
        source_path=source_path,
    )
    return pdef


def load_file(path: str | Path) -> ProductDef:
    """从单个 YAML 文件加载产品定义。"""
    import yaml

    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return load_def(data, source_path=p)


# ---------------------------------------------------------------- 注册表

class ProductRegistry:
    """产品定义集合，支持按文件匹配。"""

    def __init__(self, defs: Iterable[ProductDef] | None = None) -> None:
        self._defs: list[ProductDef] = list(defs or [])
        self._by_name: dict[str, ProductDef] = {}
        self.errors: list[str] = []
        for d in self._defs:
            self._by_name[d.product] = d

    # -- 构建 ------------------------------------------------------

    @classmethod
    def from_dir(cls, directory: str | Path | None = None) -> ProductRegistry:
        """加载目录下所有 ``*.yml`` / ``*.yaml``。

        单个文件写错不应让整个库不可用：跳过并记录到 ``errors``。
        """
        reg = cls()
        root = Path(directory) if directory else PRODUCTS_DIR
        if not root.exists():
            return reg
        for p in sorted(list(root.glob("*.yml")) + list(root.glob("*.yaml"))):
            try:
                reg.add(load_file(p))
            except Exception as exc:                     # noqa: BLE001
                # 单个定义写错（YAML 语法、未知键、正则非法…）只跳过该文件，
                # 不让整个产品库不可用；错误可在 reg.errors 里查。
                reg.errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
        reg._defs.sort(key=lambda d: (-d.specificity, d.product))
        return reg

    def add(self, pdef: ProductDef) -> None:
        self._defs.append(pdef)
        self._by_name[pdef.product] = pdef
        self._defs.sort(key=lambda d: (-d.specificity, d.product))

    # -- 查询 ------------------------------------------------------

    def __len__(self) -> int:
        return len(self._defs)

    def __iter__(self):
        return iter(self._defs)

    def names(self) -> list[str]:
        return [d.product for d in self._defs]

    def get(self, product: str) -> ProductDef:
        try:
            return self._by_name[product]
        except KeyError:
            raise KeyError(
                f"未注册的产品 {product!r}；已加载 {self.names()}"
            ) from None

    def match(self, path: str | Path, *,
              container: str | None = None,
              attrs: dict[str, Any] | None = None) -> ProductDef | None:
        """按文件名 / 容器 / 全局属性匹配产品定义。返回最具体的那个。"""
        name = Path(path).name
        candidates = [
            d for d in self._defs
            if re.search(d.match.filename, name, re.IGNORECASE)
        ]
        if not candidates:
            return None

        # 容器过滤：定义里写了 container 就必须相符，**不相符直接排除**。
        # 早期实现"过滤后为空就回退到未过滤集合"，会把错误的产品定义
        # 套到文件上（比不匹配更危险），必须返回 None。
        if container is not None:
            candidates = [d for d in candidates
                          if not d.match.container or d.match.container == container]
            if not candidates:
                return None

        # 属性过滤：同上，写了 attrs 就必须相符。
        # 只有"没有声明 attrs 的定义"可以兜底匹配。
        if attrs:
            matched = [d for d in candidates if _attrs_match(d.match.attrs, attrs)]
            if matched:
                candidates = matched
            else:
                candidates = [d for d in candidates if not d.match.attrs]
                if not candidates:
                    return None

        # 多个定义同时命中时，取**最具体**的那个：
        # 约束越多（container/attrs）、正则越长，越具体。
        # 否则 4000M 与 1000M 这种同族档位会随机命中先加载的那个。
        def _specificity(d):
            score = 0
            if d.match.container:
                score += 10
            if d.match.attrs:
                score += 10 * len(d.match.attrs)
            score += len(d.match.filename or "")
            prio = getattr(d, "priority", 0) or 0
            return (prio, score)

        candidates.sort(key=_specificity, reverse=True)
        return candidates[0] if candidates else None

    def expected_for(self, path: str | Path) -> ProductDef | None:
        """只要文件名能命中就返回定义（不看容器/属性，供离线校验用）。

        返回**最优先**的那个（``self._defs`` 已按 specificity 降序排好），
        与 :meth:`match` 的选取顺序保持一致。
        """
        name = Path(path).name
        for d in self._defs:
            if re.search(d.match.filename, name, re.IGNORECASE):
                return d
        return None

    # -- 诊断 ------------------------------------------------------

    def to_summary(self) -> list[dict[str, Any]]:
        return [d.to_summary() for d in self._defs]


def _attrs_match(wanted: dict[str, str], have: dict[str, Any]) -> bool:
    """全局属性子集匹配。属性缺失不算失配（不同卫星字段不全）。"""
    if not wanted:
        return True
    for key, want in wanted.items():
        got = _lookup_attr(have, key)
        if got is None:
            continue
        if str(want).lower() not in str(got).lower():
            return False
    return True


def _lookup_attr(attrs: dict[str, Any], name: str) -> Any:
    low_map = {str(k).strip().lower(): v for k, v in attrs.items()}
    for alias in _attr_aliases(name):
        if alias in low_map:
            return low_map[alias]
    return None


# ---------------------------------------------------------------- 路径解析

def resolve_path(available: Iterable[str], spec: str | list[str]) -> str | None:
    """把定义里的路径（可为候选列表 / 通配 / 无前缀 basename）解析成真实数据集名。

    解析顺序（命中即返回，**不做进一步猜测**）：

    1. 精确路径
    2. 路径出现在文件里（允许定义里省略前导 ``/``）
    3. glob 通配（``Data/NOMChannel*``）
    4. 无路径前缀时按 basename 匹配（``/GEO/Latitude`` → ``GEO/Latitude``）
    5. basename 通配（定义写 ``Latitude``，文件里是 ``Geolocation/Latitude``）
    """
    names = [str(n).lstrip("/") for n in available]
    lookup = {n.lower(): n for n in names}
    base_lookup: dict[str, list[str]] = {}
    for n in names:
        base_lookup.setdefault(n.rsplit("/", 1)[-1].lower(), []).append(n)

    specs = [spec] if isinstance(spec, str) else list(spec)
    for raw in specs:
        cand = str(raw).strip().lstrip("/")
        if not cand:
            continue
        if cand.lower() in lookup:
            return lookup[cand.lower()]

        if any(ch in cand for ch in "*?["):
            hits = [n for n in names if fnmatch.fnmatchcase(n, cand)]
            if not hits:
                hits = [n for n in names
                        if fnmatch.fnmatchcase(n.rsplit("/", 1)[-1], cand.rsplit("/", 1)[-1])]
            if hits:
                return sorted(hits, key=len)[0]

        base = cand.rsplit("/", 1)[-1].lower()
        if "/" not in cand and base in base_lookup:
            return sorted(base_lookup[base], key=len)[0]
        if any(ch in base for ch in "*?["):
            hits = sorted({n for n in names
                           if fnmatch.fnmatchcase(n.rsplit("/", 1)[-1], base)})
            if hits:
                return hits[0]
    return None


def resolve_paths(available: Iterable[str], spec: str | list[str]) -> list[str]:
    """多命名空间：返回**所有**命中（FY-4B ``Data/NOMChannel*`` → 15 个）。"""
    names = [str(n).lstrip("/") for n in available]
    specs = [spec] if isinstance(spec, str) else list(spec)
    out: list[str] = []
    for raw in specs:
        cand = str(raw).strip().lstrip("/")
        if not cand:
            continue
        if any(ch in cand for ch in "*?["):
            out.extend(n for n in names if fnmatch.fnmatchcase(n, cand))
        else:
            one = resolve_path(names, cand)
            if one:
                out.append(one)
    # 去重保序
    seen: set[str] = set()
    uniq = []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def guess_field_from_dataset(pdef: ProductDef, dataset: str) -> FieldDef | None:
    """按数据集名反查字段定义（精确路径优先，其次 basename 通配）。"""
    ds = str(dataset).lstrip("/")
    for f in pdef.fields:
        for spec in f.paths:
            cand = spec.lstrip("/")
            if cand == ds:
                return f
            if any(ch in cand for ch in "*?[") and fnmatch.fnmatchcase(ds, cand):
                return f
    base = ds.rsplit("/", 1)[-1]
    for f in pdef.fields:
        for spec in f.paths:
            cand = spec.rsplit("/", 1)[-1]
            if any(ch in cand for ch in "*?[") and fnmatch.fnmatchcase(base, cand):
                return f
    return None


__all__ = [
    "PRODUCTS_DIR",
    "ProductRegistry",
    "load_def",
    "load_file",
    "resolve_path",
    "resolve_paths",
    "guess_field_from_dataset",
]

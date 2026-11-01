"""溯源元数据：把"软件来源 / 是否修改 / 版本"写进导出文件。

为什么要做
----------
项目以 AGPL-3.0 开源，并希望分发数据时能说明来源与是否修改。
把"必须附修改后源代码"写进软件许可的附加条款会超出 AGPLv3 §7 允许范围，
但它完全可以由**技术手段**默认满足：在导出的 TIFF/PNG 里嵌入溯源字段。

这样做的额外好处：
- 数据流转到下游时，任何看图工具都能读出"这张图是哪个版本、哪个提交、哪份源文件生成的"
- 科研场景下可复现性直接提升
- 不构成对下游的额外法律限制

字段设计
--------
software / software_version / source_url / modified / commit /
generated_at / source_file / platform / instrument / product / variable
"""
from __future__ import annotations

import os
import platform as _platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOFTWARE_NAME = "FY-Sat Studio"
SOURCE_URL = os.environ.get("FYSAT_SOURCE_URL", "https://github.com/lzh173/fysat")
LICENSE_ID = "AGPL-3.0-only"


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def repo_root() -> Path | None:
    """定位源码仓库根（用于读 git 信息）。"""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def is_modified_release() -> bool:
    """判断当前运行的是否为被改动过的版本。

    依据：仓库有未提交改动，或工作区与 HEAD 不一致。
    拿不到 git 信息时保守返回 True（"可能被修改"比"谎称原版"安全）。
    """
    root = repo_root()
    if root is None:
        return True
    status = _git(["status", "--porcelain"], root)
    if status is None:
        return True
    return bool(status.strip())


def commit_hash() -> str | None:
    root = repo_root()
    if root is None:
        return None
    return _git(["rev-parse", "--short", "HEAD"], root)


def software_version() -> str:
    try:
        from . import __version__

        return str(__version__)
    except Exception:                       # noqa: BLE001
        return "unknown"


def build_provenance(
    dataset: Any = None,
    variable: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """组装溯源字段。dataset 可以是 SatDataset，也可以什么都不传。"""
    from . import __version__ as ver      # noqa: F401  (确保包已初始化)

    prov: dict[str, str] = {
        "software": SOFTWARE_NAME,
        "software_version": software_version(),
        "license": LICENSE_ID,
        "source_url": SOURCE_URL,
        "modified": "yes" if is_modified_release() else "no",
    }
    commit = commit_hash()
    if commit:
        prov["commit"] = commit

    prov["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prov["generator_platform"] = f"{_platform.system()} {_platform.release()}"

    if dataset is not None:
        for key, attr in (
            ("platform", "platform"),
            ("instrument", "instrument"),
            ("level", "level"),
            ("product", "product"),
        ):
            val = getattr(dataset, attr, "")
            if val:
                prov[key] = str(val)
        if getattr(dataset, "source", None):
            prov["source_file"] = Path(dataset.source).name
        if getattr(dataset, "start_time", None):
            prov["observation_time"] = dataset.start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        if getattr(dataset, "reader", None):
            prov["reader"] = str(dataset.reader)

    if variable:
        prov["variable"] = str(variable)

    if extra:
        for k, v in extra.items():
            if v not in (None, ""):
                prov[k] = str(v)

    return prov


def as_text(prov: dict[str, str]) -> str:
    """人类可读的单段描述（写进 TIFF ImageDescription）。"""
    order = [
        "software", "software_version", "license", "source_url", "modified",
        "commit", "generated_at", "generator_platform",
        "platform", "instrument", "level", "product",
        "observation_time", "variable", "source_file", "reader",
    ]
    lines = []
    for k in order:
        if k in prov:
            lines.append(f"{k}: {prov[k]}")
    for k, v in prov.items():            # 追加自定义字段
        if k not in order:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


# PNG tEXt 的键名有长度与字符限制，统一加前缀并转小写
PNG_KEY_PREFIX = "fysat"


def as_png_text(prov: dict[str, str]) -> dict[str, str]:
    """转成 PNG tEXt 键值对。"""
    out = {}
    for k, v in prov.items():
        key = f"{PNG_KEY_PREFIX}.{k}"[:79]          # tEXt 关键字上限 79 字节
        out[key] = str(v)
    return out


def read_tiff_provenance(path: str | Path) -> dict[str, str]:
    """从 TIFF 读回溯源字段（测试与校验用）。"""
    import tifffile

    with tifffile.TiffFile(str(path)) as tif:
        desc = tif.pages[0].tags.get("ImageDescription")
        if desc is None:
            return {}
        text = desc.value
    out = {}
    for line in str(text).splitlines():
        if ": " in line:
            k, _, v = line.partition(": ")
            out[k.strip()] = v.strip()
    return out


def read_png_provenance(path: str | Path) -> dict[str, str]:
    """从 PNG 读回溯源字段。"""
    from PIL import Image

    with Image.open(str(path)) as im:
        info = dict(im.info)
    out = {}
    for k, v in info.items():
        if isinstance(k, str) and k.startswith(f"{PNG_KEY_PREFIX}."):
            out[k[len(PNG_KEY_PREFIX) + 1:]] = str(v)
    return out

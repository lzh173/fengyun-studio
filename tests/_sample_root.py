"""测试用样本数据根目录。

开源版默认指向空路径：没有样本时相关测试会 **skip**，而不是失败。
本地开发时用环境变量指向自己的样本目录即可：

    PowerShell:  $env:FYSAT_SAMPLE_ROOT = "Y:\\download-data"
    bash:        export FYSAT_SAMPLE_ROOT=/data/fy-samples

所有需要真实卫星产品的测试都应该走这里，不要在代码里写死某台机器的路径。
"""
from __future__ import annotations

import os
from pathlib import Path

# 空字符串表示"没配置样本目录"
_ENV = os.environ.get("FYSAT_SAMPLE_ROOT", "").strip()
SAMPLE_ROOT = Path(_ENV) if _ENV else Path()


def configured() -> bool:
    """用户是否配置了样本目录且它真实存在。"""
    try:
        return bool(str(SAMPLE_ROOT)) and SAMPLE_ROOT.is_dir()
    except OSError:                      # 无法访问的网络盘等
        return False


def has(rel: str) -> bool:
    """样本根目录下是否存在某个相对路径。"""
    if not configured():
        return False
    try:
        return (SAMPLE_ROOT / rel).exists()
    except OSError:
        return False


def glob_samples(pattern: str) -> list[Path]:
    """在样本根目录下递归匹配（等价于原来的 glob(SAMPLE_ROOT/**/pattern)）。

    没有配置样本目录时返回空列表，调用方据此 skip。
    """
    if not configured():
        return []
    try:
        return sorted(p for p in SAMPLE_ROOT.rglob(pattern) if p.is_file())
    except OSError:
        return []


def first_sample(pattern: str, min_bytes: int = 0) -> Path | None:
    """取第一个满足大小要求的样本，没有则 None。"""
    for p in glob_samples(pattern):
        try:
            if p.stat().st_size >= min_bytes:
                return p
        except OSError:
            continue
    return None


def require_root():
    """在测试里用：没配样本目录就跳过整个模块。"""
    import pytest

    if not configured():
        pytest.skip(
            "未配置样本目录：设置环境变量 FYSAT_SAMPLE_ROOT 指向 NSMC 产品所在目录",
            allow_module_level=True,
        )

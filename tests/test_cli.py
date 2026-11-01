"""CLI 行为测试：变量解析、通配符、导出入口。"""
from __future__ import annotations

import numpy as np
import pytest

from fysat.cli import _numbered, _resolve_vars, build_parser
from fysat.model import SatDataset, Variable


@pytest.fixture
def ds():
    d = SatDataset(platform="FY-4B", instrument="AGRI")
    for n in ("Data/NOMChannel01", "Data/NOMChannel02", "Data/NOMChannel03"):
        d.variables[n] = Variable(name=n, data=np.zeros((8, 8), np.uint16), source_shape=(8, 8))
    d.variables["Calibration/CALChannel01"] = Variable(
        name="Calibration/CALChannel01", data=np.zeros((16,), np.float32), source_shape=(16,))
    return d


def test_parse_exact_and_wildcard_and_suffix(ds):
    assert _resolve_vars(ds, "Data/NOMChannel01") == ["Data/NOMChannel01"]
    assert len(_resolve_vars(ds, "Data/NOMChannel*")) == 3
    assert len(_resolve_vars(ds, "Data/NOMChannel0[12]")) == 2
    # 唯一后缀匹配
    assert _resolve_vars(ds, "NOMChannel03") == ["Data/NOMChannel03"]
    assert _resolve_vars(ds, "不存在") == []


def test_numbered_name_is_filesystem_safe():
    from pathlib import Path

    p = _numbered(Path("a/b.png"), "Data/NOMChannel01")
    assert p.name == "b_Data_NOMChannel01.png"
    assert "/" not in p.name


def test_subcommands_present():
    p = build_parser()
    # argparse 没有公开的子命令列表接口，改用一次解析验证
    for argv in (["info", "x.hdf"], ["ls", "x.hdf"], ["vars", "x.hdf"],
                 ["export", "x.hdf", "v", "--out", "o.png"], ["formats"]):
        ns = p.parse_args(argv)
        assert hasattr(ns, "func")


def test_export_kind_defaults():
    p = build_parser()
    ns = p.parse_args(["export", "x.hdf", "v", "--out", "o.png"])
    assert ns.kind == "png_full"          # 默认全画质
    assert ns.level == 6                  # 默认压缩强度
    assert ns.scale == 1.0                # 默认不缩放

"""本地打包脚本：一条命令产出 GUI 与 CLI 两个可执行文件。

用法（仓库根目录）：

    python packaging/build.py                # 两种都构建
    python packaging/build.py --kind gui     # 只构建图形界面版
    python packaging/build.py --kind cli     # 只构建命令行版

产物在 dist/ 下：
    dist/FY-Sat-Studio[.exe]   图形界面（Windows 下无控制台窗口）
    dist/fysat[.exe]           命令行

注意
----
* 需要先 `pip install pyinstaller`。
* 单文件体积约 100 MB（PySide6 + matplotlib + numpy + scipy + h5py 的必然结果）。
* 可选后端 satpy 被**刻意排除**：它实装约 370 MB 且需要联网资源，
  打进单文件会让体积翻倍。需要时请用 `pip install fysat[satpy]` 配源码运行。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "fysat.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build"

TARGETS = {
    "gui": ("FY-Sat-Studio.exe", "FY-Sat-Studio"),
    "cli": ("fysat.exe", "fysat"),
}


def build(kind: str) -> Path:
    """构建指定种类，返回产物路径。"""
    win_name, nix_name = TARGETS[kind]
    workpath = WORK / f"{kind}"

    env = dict(os.environ)
    env["FYSAT_BUILD_KIND"] = kind

    print(f"\n=== 构建 {kind} 版 ===", flush=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", str(SPEC),
        "--distpath", str(DIST),
        "--workpath", str(workpath),
        "--noconfirm",
    ]
    rc = subprocess.call(cmd, cwd=ROOT, env=env)
    if rc != 0:
        raise SystemExit(f"PyInstaller 失败（退出码 {rc}）")

    out = DIST / (win_name if os.name == "nt" else nix_name)
    if not out.exists():
        raise SystemExit(f"没有生成预期产物：{out}")
    print(f"  产物 {out.name}  {out.stat().st_size / 1e6:.1f} MB", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 FY-Sat Studio 可执行文件")
    ap.add_argument("--kind", choices=["gui", "cli", "all"], default="all",
                    help="构建哪种（默认两种都构建）")
    ap.add_argument("--clean", action="store_true", help="先清空 dist/ 与 build/")
    args = ap.parse_args()

    if args.clean:
        for d in (DIST, WORK):
            if d.exists():
                shutil.rmtree(d)
                print(f"已清空 {d.relative_to(ROOT)}")

    kinds = ["gui", "cli"] if args.kind == "all" else [args.kind]
    built = [build(k) for k in kinds]

    print("\n完成：")
    for p in built:
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

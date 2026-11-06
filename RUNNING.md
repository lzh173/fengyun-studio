# 启动与运行说明

## 一、先配置样本目录（可选但建议）

程序**不随包分发**卫星数据。要把界面数据树和回归测试接到你自己的产品目录：

```powershell
# PowerShell
$env:FYSAT_SAMPLE_ROOT = "D:\samples"
$env:FYSAT_SOURCE_DIRS = "E:\more-data"     # 可选，多个用分号分隔
```

```bash
# bash / zsh
export FYSAT_SAMPLE_ROOT=/data/samples
```

不配置也能启动，只是数据树为空；需要真实样本的测试会自动 skip。

---

## 二、启动方式

### 1. 图形界面

| 命令 | 用途 |
|---|---|
| `bin\fysat-gui.cmd` | Windows 正常启动，无控制台窗口 |
| `bin\fysat-gui-debug.cmd` | Windows 带控制台，启动失败时用它看 traceback |
| `python -m fysat.gui.app` | 任意平台通用 |
| `python -m fysat.cli gui` | 与上一行等价 |

带文件直接打开：

```powershell
bin\fysat-gui.cmd "D:\samples\FY4B-...4000M_V0001.HDF"
bin\fysat-gui.cmd "D:\samples"                    # 打开整个目录
```

### 2. 命令行

```powershell
bin\fysat.cmd --version
bin\fysat.cmd info   <文件>              # 卫星 / 仪器 / 变量 / 定位方式
bin\fysat.cmd ls     <文件>              # 内部结构树
bin\fysat.cmd vars   <文件> --only2d     # 可导出的二维变量
bin\fysat.cmd export <文件> <变量> --kind tiff --out a.tif
bin\fysat.cmd formats                    # 三种导出形式说明
bin\fysat.cmd products                   # 已内置的产品定义
bin\fysat.cmd product  <文件>            # 该文件匹配到哪个产品定义
bin\fysat.cmd batch    <目录> --out out\batch --kind png_compressed
```

启动脚本的解释器查找顺序：`%FYSAT_PYTHON%` → PATH 上的 `python` / `pythonw`。
用虚拟环境时把它指过去即可，不必改脚本：

```powershell
$env:FYSAT_PYTHON = "C:\venvs\fysat\Scripts\python.exe"
```

---

## 三、导出

只有三种形式（这是刻意的设计，不做更多选项）：

| `--kind` | 内容 | 适用 |
|---|---|---|
| `tiff` | 全画质无损，保留原始位深与波段数，可选 LZW/Deflate | 存档、再分析 |
| `png_full` | 全分辨率 PNG | 看图、分享 |
| `png_compressed` | 指定缩放与压缩级别 | 网页、文档 |

所有导出默认嵌入**溯源元数据**（软件名/版本/许可证/源码地址/是否修改/commit/generated_at）：

```powershell
python -c "from fysat.provenance import read_png_provenance; print(read_png_provenance('a.png'))"
```

---

## 四、无显示环境（服务器 / CI）

```bash
export QT_QPA_PLATFORM=offscreen
python -m pytest tests -q
```

---

## 五、测试

```bash
python -m pytest tests -q                     # 全量
python -m pytest tests -q -k "not gui"        # 跳过 GUI
FYSAT_SAMPLE_ROOT=/data/samples python -m pytest tests -q   # 带真实样本
```

没有 `FYSAT_SAMPLE_ROOT` 时，依赖卫星产品的用例会 skip，其余全部可跑通。

两个审查脚本用于验证"功能是否真能用"，不依赖肉眼：

```bash
python scripts/audit_gui.py            # 主界面 13 项功能探针
python scripts/audit_benches.py        # 三个工作台 9 项深度探针
python scripts/audit_all_products.py   # 对样本目录里每类产品跑完整链路
```

---

## 六、常见问题

**界面中文显示成方块**
系统缺少中文字体。程序会尝试注册 `msyh`（微软雅黑）等常见字体；
Linux 上装一个中文字体即可：`apt install fonts-noto-cjk`。

**`Cannot find font directory ... PySide6/lib/fonts`**
Qt 6 不再随包提供字体，属正常提示，不影响运行。

**启动报 `No module named fysat`**
没走启动脚本时，需要 `pip install -e .` 或把 `src` 加进 `PYTHONPATH`。

**GUI 起来但数据树为空**
没配 `FYSAT_SAMPLE_ROOT`，或该目录里没有可识别的产品文件。
用 `bin\fysat.cmd info <文件>` 先确认单个文件能被识别。

**想用 satpy 后端**
`pip install -e ".[satpy]"`。satpy 会带来约 370 MB 依赖，
且需要与数据同目录的 **GEO 定位文件**才能得到经纬度；
没有 GEO 时程序会标 `geo_missing=True` 并降级为无定位读取。
详见 [analysis/satpy_evaluation.md](analysis/satpy_evaluation.md)。

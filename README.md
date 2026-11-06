# FY-Sat Studio

风云卫星**官方数据**解码 · 分析 · 制图。
不处理射频接收链路（CADU/LRIT/Viterbi/DES），只处理 NSMC 分发产品。

> 计划与范围：[PLAN.md](PLAN.md) ｜ 当前进度见本文件「实现状态」

---

## 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.10 及以上 |
| 运行时依赖 | `numpy` `h5py` `scipy` `matplotlib` `Pillow` `tifffile` `PyYAML` `PySide6-Essentials` |
| 可选依赖 | `satpy`（可选读取后端，见下） |
| 操作系统 | Windows / Linux / macOS（GUI 需 Qt 支持，无显示环境可用 `QT_QPA_PLATFORM=offscreen`） |

```bash
pip install -e ".[gui]"          # 含图形界面（推荐）
pip install -e ".[gui,all]"      # 再加 satpy 后端
pip install -e .                 # 只要命令行
```

> `PySide6-Essentials` 是刻意的选择：完整的 `PySide6` 会拉入 GPL-only 的 Addons 模块，
> 与本项目的 AGPL-3.0-only 分发策略不匹配。详见 [LICENSES.md](LICENSES.md)。

---

## 快速开始

**图形界面**：

```powershell
bin\fysat-gui.cmd                 # Windows
```

```bash
python -m fysat.gui.app           # 任意平台
```

**命令行**：

```powershell
bin\fysat.cmd --version
bin\fysat.cmd info  "D:\samples\FY4B-...1000M_V0001.HDF"
bin\fysat.cmd batch "D:\samples" --out out\batch --kind png_compressed
```

启动脚本按以下顺序找解释器：`%FYSAT_PYTHON%`（可选）→ PATH 上的 `python` / `pythonw`。
不需要修改脚本内容；虚拟环境里把 `FYSAT_PYTHON` 指过去即可。

完整启动说明见 [RUNNING.md](RUNNING.md)。

---

## 样本数据

本项目**不随包分发**任何卫星产品数据。要用真实数据跑通界面与回归测试，
请自行从 [国家卫星气象中心（NSMC）](https://www.nsmc.org.cn/) 下载，
然后把目录告诉程序：

```powershell
# PowerShell
$env:FYSAT_SAMPLE_ROOT = "D:\samples"      # 测试与界面默认打开的位置
$env:FYSAT_SOURCE_DIRS = "E:\more-data"    # 可选：额外的数据源目录（分号分隔）
```

```bash
# bash / zsh
export FYSAT_SAMPLE_ROOT=/data/samples
```

不配置也能启动：界面照常打开（只是数据树为空），
需要真实样本的测试会自动 **skip** 而不是失败。

---

以下是直接用 Python 的方式（与启动脚本等价）：

```powershell
python -m fysat.cli info "D:\samples\FY4B-...1000M_V0001.HDF"
python -m fysat.cli ls <文件> --limit 40

# 导出（三种形式，见下节）
python -m fysat.cli export <文件> Data/NOMChannel02 --kind tiff           --out a.tif
python -m fysat.cli export <文件> Data/NOMChannel02 --kind png_full       --out a.png
python -m fysat.cli export <文件> Data/NOMChannel02 --kind png_compressed --out a.png --level 9 --scale 0.25 --cmap gray

python -m fysat.cli formats        # 全部导出形式说明
python -m fysat.cli products       # 已内置的产品定义
```

> 源码在 `src/` 下，`pip install -e .` 后可直接 `import fysat`；
> 不安装时把 `src` 加进 `PYTHONPATH` 亦可。

---

## 导出：只有三种（已定稿）

| kind | 名称 | 特点 | 实测（FY-4B 10992×10992） |
|---|---|---|---|
| `tiff` | TIFF 全画质 | 保留原始位深与波段数，Deflate 无损 | 16 位 DN → 59 MB；RGB → 167 MB |
| `png_full` | PNG 全画质 | 原始分辨率，16 位灰度无损 | 51 MB（16 位）/ 158 MB（RGB） |
| `png_compressed` | PNG 压缩强度可调 | `--level 0..9` + `--scale` | level 0 = 346 MB，level 9 = 148 MB |

**PNG 本身无损**，"压缩强度"只影响编码时间与体积；要减小体积又不想改像素，调 `--level`。

> **无损性已用真实数据验收**：FY-4B CH02（10992×10992 = 1.2 亿像素）经三种路径导出后回读，
> TIFF 与 PNG 全画质均**字节级完全一致（最大差异 0）**。
> 注意：HDF5/NetCDF 常用大端 `>u2`，早期版本会把它误当浮点重拉伸（曾实测 76.5% 像素被破坏），已修复并加回归测试。

相关代码：[src/fysat/export.py](src/fysat/export.py)，测试：[tests/test_export.py](tests/test_export.py)（8 项全绿）

---

## 目录结构

```
fysat/
├─ PLAN.md                  开发计划（范围/架构/技术栈/里程碑/样本清单）
├─ pyproject.toml
├─ src/fysat/
│  ├─ model.py              统一数据模型 SatDataset / Variable / Geolocation
│  ├─ detect.py             容器魔数识别 + 文件名解析
│  ├─ export.py             三种导出形式
│  ├─ render.py             拉伸 / 上色 / RGB 合成
│  ├─ palettes.py           业务配色（增强红外等）
│  ├─ calib.py              定标：反射率/普朗克/LUT/微波
│  ├─ geo.py                定位：粗网格插值/标称投影/重采样
│  ├─ readers/
│  │  ├─ __init__.py        按容器类型分派
│  │  ├─ hdf5.py            HDF5 + NetCDF-4 通用读取（CF 约定驱动）
│  │  ├─ nc3.py             NetCDF-3
│  │  ├─ fy2_csv.py         FY-2 CSV 容器
│  │  ├─ oneb.py            1B（FY-1D / NOAA-18）
│  │  └─ awx.py             AWX 2.1
│  └─ cli.py                info / ls / export / formats
├─ scripts/
│  ├─ demo_pipeline.py      FY-4B 真彩色 → 三格式导出
│  └─ demo_fy3h_bt.py       FY-3H 红外亮温 → 三格式导出
├─ tests/
└─ out/                     演示产物
```

---

## 实现状态

| 模块 | 状态 | 说明 |
|---|---|---|
| `model.py` | ✅ | `Variable.physical()` 处理 scale/offset/fill/valid_range；`load()` 按 reader 动态分派（支持非 HDF5 容器） |
| `detect.py` | ✅ | HDF5/HDF4/NC3/NC4/AWX/1B/JPEG/PNG/TIFF 魔数识别 + 文件名解析 |
| `readers/hdf5.py` | ✅ | 通用 CF 读取，自动识别 `GEO/Latitude` 等经纬度网格；实测 FY-4B/FY-3H/FY-2G |
| `readers/nc3.py` | ✅ | NetCDF-3 经典格式（仅用 scipy）；GNOSO 29 变量全读出 |
| `readers/fy2_csv.py` | ✅ | FY-2 CSVS V1.0 容器：2501×41260 定长记录，IR 10bit / VIS 6bit 位流解包 |
| `export.py` | ✅ | 三种形式，8 项测试全绿 |
| `render.py` | ✅ | 百分位/固定拉伸、伽马、色标、RGB 合成 |
| palettes.py | ✅ | 增强红外色表 |
| calib.py | ✅ | 反射率线性/二次、普朗克正反演、LUT 定标（FY-4/FY-2）、微波 TB |
| geo.py | ✅ | 粗网格双线性插值、标称投影正反算、等经纬重采样（全向量化） |
| `cli.py` | ✅ | info / ls / vars / export / formats，支持 glob 批量导出 |
| `readers/oneb.py` | ✅ | 1B 两种变体：FY-1D（28400B×4529，10bit 高位填零）/ NOAA-18（22016B×4538，大端 u16） |
| `readers/awx.py` | ✅ | AWX 2.1：512×512 8bit，类别 1/2、RGB、定标表、定位块 |
| GUI（PySide6） | ⬜ | 计划 M4 |
| 制图工作台（matplotlib） | ⬜ | 计划 M5 |

---

## 全样本回归

```powershell
python scripts/audit_all_products.py           # 扫描 $FYSAT_SAMPLE_ROOT 下每类产品跑完整链路
```

最近一次结果（2026-11-01）：**202 个样本全部解析通过**

| 容器 | 通过数 |
|---|---:|
| hdf5 | 126 |
| fy2_csv | 28 |
| awx | 22 |
| netcdf3 | 14 |
| oneb | 12 |

另有 3 个**下载残件**（FY-4B 两个 HDF 仅 0 MB / 0.63 MB，同批正常文件 220+ MB）
与 2 个**已知未实现**（FY-1D L2 自定义 `.DAT`），脚本会单独归类，不算解析失败。

## 已验证的真实样本

| 文件 | 结论 |
|---|---|
| `FY4B-…L1-_FDI-_…1000M_V0001.HDF` | HDF5，17 个数据集，`Data/NOMChannel01-03` (10992²) uint16，`Calibration/CALChannel01-03` (4096,) LUT |
| `FY3H_MERSI_GRAN_L1_…0250M_V0.hdf` | HDF5，`Data/EV_250_*` (8000×8192)，`GEO/Latitude,Longitude` (400,410) step=20，红外亮温 187.6–312.1 K |
| `FY2G_FDI_ALL_NOM_….hdf` | **HDF5**（非 HDF4），扁平结构，`CALChannelIR1-4` LUT |
| `FY1D_….L1B` / `NA18_….L1B` | 1B 两种头结构（空格填充 / `N1BD` 数据集树） |
| `MST2_SEC_VIS_LCN_….AWX` | AWX 2.1，`EVLD….AWX` 头 |

---

## 许可证

本项目以 **AGPL-3.0-only** 开源，另附 AGPLv3 §7 允许范围内的署名与修改标记条款。

- 软件许可证全文：[LICENSE](LICENSE)
- 依赖许可证汇总与 LGPLv3 合规清单：[LICENSES.md](LICENSES.md)
- §7 附加条款：[docs/licenses/FYSAT-ADDITIONAL-TERMS.md](docs/licenses/FYSAT-ADDITIONAL-TERMS.md)
- 导出数据署名（请求性，非软件许可条款）：[docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md)
- 第三方版权声明：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

**导出数据自带溯源**：所有 TIFF / PNG 默认写入 `software` / `software_version` /
`license` / `source_url` / `modified` / `commit` / `generated_at` 等元数据
（TIFF 写在 ImageDescription，PNG 写在 tEXt 的 `fysat.*` 键），
可用 `fysat.provenance.read_tiff_provenance / read_png_provenance` 读回。

> GUI 使用 PySide6（LGPLv3，动态链接）。**不要**把它改成裸 `PySide6` 元包依赖——
> 那会拉入含 GPL-only 模块的 PySide6-Addons。合规约束已固化为
> `tests/test_license_compliance.py` 的自动测试。

## 开发约定

- 中文界面与文档；代码注释可为中文
- 只提交能跑通的代码，随代码附测试
- 大数组一律向量化，禁止 Python 双循环遍历像素
- 新增依赖必须先确认许可证与体积（见 [LICENSES.md](LICENSES.md)）
- 不在源码里写死任何人的本地路径；需要外部目录时用环境变量

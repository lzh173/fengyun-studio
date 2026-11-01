# FY-Sat Studio

风云卫星**官方数据**解码 · 分析 · 制图。
不处理射频接收链路（CADU/LRIT/Viterbi/DES），只处理 NSMC 分发产品。

> 计划与范围：[PLAN.md](PLAN.md) ｜ 当前进度见本文件「实现状态」

---

## 快速开始

```powershell
# 解释器（已内置 numpy/h5py/matplotlib/PIL/scipy/tifffile/pyyaml）
E:\venv\fysat\Scripts\python.exe

# 查看文件概况
python -m fysat.cli info "Y:\download-data\FY4B-...1000M_V0001.HDF"

# 列出内部结构
python -m fysat.cli ls <文件> --limit 40

# 导出（三种形式）
python -m fysat.cli export <文件> Data/NOMChannel02 --kind tiff          --out a.tif
python -m fysat.cli export <文件> Data/NOMChannel02 --kind png_full      --out a.png
python -m fysat.cli export <文件> Data/NOMChannel02 --kind png_compressed --out a.png --level 9 --scale 0.25 --cmap gray

# 全部导出形式说明
python -m fysat.cli formats
```

> 源码目录已通过 `E:\venv\fysat\Lib\site-packages\fysat_src.pth` 挂到 `sys.path`，
> 因此无需安装即可 `import fysat`。

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

## 已验证的真实样本

| 文件 | 结论 |
|---|---|
| `FY4B-…L1-_FDI-_…1000M_V0001.HDF` | HDF5，17 个数据集，`Data/NOMChannel01-03` (10992²) uint16，`Calibration/CALChannel01-03` (4096,) LUT |
| `FY3H_MERSI_GRAN_L1_…0250M_V0.hdf` | HDF5，`Data/EV_250_*` (8000×8192)，`GEO/Latitude,Longitude` (400,410) step=20，红外亮温 187.6–312.1 K |
| `FY2G_FDI_ALL_NOM_….hdf` | **HDF5**（非 HDF4），扁平结构，`CALChannelIR1-4` LUT |
| `FY1D_….L1B` / `NA18_….L1B` | 1B 两种头结构（空格填充 / `N1BD` 数据集树） |
| `MST2_SEC_VIS_LCN_….AWX` | AWX 2.1，`EVLD….AWX` 头 |

---

## 开发约定

- 中文界面与文档；代码注释可为中文
- 只提交能跑通的代码，随代码附测试
- 大数组一律向量化，禁止 Python 双循环遍历像素
- 新增依赖必须先确认（磁盘 C: 已满，所有安装走 `E:\venv\fysat`）

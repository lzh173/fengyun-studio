# FY-Sat Studio 开发计划

> 通用中国气象卫星**官方数据**解码 · 分析 · 制图软件
> 文档版本 v0.1 ｜ 2026-11-01

---

## 0. 定位（一句话）

面向国家卫星气象中心（NSMC）**分发产品**的通用解析、分析与制图桌面软件。

**做**：拿到官方 HDF5 / NetCDF / HDF4 / S-VISSR / AWX / 1B 文件 → 识别 → 解析字段 → 定标定位 → 分析 → 出图。
**不做**：射频接收、CADU/LRIT 帧同步、Viterbi/RS、广播链路解密（属接收端/SatDump 范畴）。

---

## 1. 覆盖目标（依据 265 篇格式说明）

### 1.1 语料统计（已实测）

| 指标 | 数值 |
|---|---|
| 格式说明文档 | 265 篇（3,427 页 / 5,511 表） |
| 含 SDS 编号定义的文档 | 141 篇 |
| 可提取的字段条目（SDS） | **5,081 条** |
| 含字节级/偏移描述的文档 | 162 / 76 篇 |

### 1.2 支持范围判定（**样本驱动**，而非文档驱动）

判定原则：**有真实样本才承诺支持**。按用户要求，"计划下单清单之外的默认不支持"。

| 仪器 / 产品类 | 文档数 | 现有或已下单样本 | 结论 |
|---|---:|---|---|
| AGRI（FY-4A/4B） | 70 | FY-4B 全套 L1（0500/1000/2000/4000M）+ L2；FY-4A REGX L1 + L2 `.NC`（本轮下单） | ✅ v1.0 |
| MERSI（FY-3C/D/F/G/H） | 35 | FY-3F/G/H 现成；FY-3C/D 1000M + GEO1K（本轮下单） | ✅ v1.0 |
| （无仪器标识，多为 L2 产品） | 50 | 依赖同卫星 L1 样本 | 🟡 逐产品验证 |
| GNOSO · PMR · ACGS · AVHRR · AWX · FY-2 | 8 | 均已具备 | ✅ v1.0 |
| **MWRI** | 55 | 无 | ❌ 待补 |
| VIRR | 13 | 无 | ❌ 待补 |
| GIIRS | 8 | 无 | ❌ 待补 |
| MWHS + MWTS | 13 | 无 | ❌ 待补 |
| CAPIX（TanSat） | 6 | 无 | ❌ 待补 |
| IRAS | 5 | 无 | ❌ 待补 |
| ERM · SBUS · TOU · SIM（辐射/能量收支） | 7 | 无 | ❌ 待补 |
| FY-3A/B（HDF4）· EOS/GMS 1B | 5 | 无，且不在第一版订单 | 🕓 后续批次（优先级最低） |

**结论：v1.0 可验证 160 篇 / 265 篇 = 60%；其余 105 篇 = 40% 留待后续批次补齐（不是不做）。**

值得注意的是最大的缺口不是卫星而是**仪器类型**：微波成像仪 MWRI 一篇文档都没法验证，却占了 55 篇（21%）——这不影响 v1.0，但决定了 v1.1 的优先级。

### 1.3 版本路线（覆盖率随批次上升）

| 版本 | 范围 | 覆盖 |
|---|---|---|
| **v1.0** | 现有样本 + 第一版订单（AGRI / MERSI / FY-2 / 1B / AWX / GNOSO / PMR / TanSat ACGS） | 160 / 265 = **60%** |
| **v1.1** | 补 MWRI + VIRR（微波与可见红外扫描辐射计） | 219 / 265 = **83%** |
| **v1.2** | 补 MWHS / MWTS / GIIRS / IRAS / CAPIX | 244 / 265 = **92%** |
| **v1.3** | 补 ERM / SBUS / TOU / SIM（辐射收支与紫外） | **100%** |

### 1.5 v1.0 正式支持清单（按样本锁定）

| # | 卫星 | 仪器 / 产品 | 层级 | 样本来源 | 容器 |
|---:|---|---|---|---|---|
| 1 | FY-4B | AGRI（FDI 0500/1000/2000/4000M、GEO、REGX）+ L2 产品 | L1 / L2 | 现有 29 个 L1 + 206 个 L2 | HDF5 |
| 2 | FY-4A | AGRI（REGX 4000M、GEO）+ L2 FHS | L1 / L2 | 第一版订单 | HDF5 / NetCDF |
| 3 | FY-3D | MERSI L1 1000M + L2 CLM | L1 / L2 | 第一版订单 | HDF5 |
| 4 | FY-3C | MERSI L1 1000M + GEO1K | L1 | 第一版订单 | HDF5 |
| 5 | FY-3F / 3G / 3H | MERSI L1（1000M / 0250M / GEOQK）、PMR L2、GNOSO L1 | L1 / L2 | 现有 | HDF5 / NetCDF-3 |
| 6 | FY-2G | FDI L1（HDF5）、CSV L1 数据集 | L1 | 现有 | HDF5 / 自定义 |
| 7 | FY-2H / 2F | CTA、SEMXX 空间环境 | L1 | 第一版订单 | HDF5 / TXT |
| 8 | FY-1D | AVHRR L1B、L2 | L1B / L2 | 现有 | 1B / .DAT |
| 9 | NOAA-18 | AVHRR L1B | L1B | 现有 | 1B |
| 10 | FY-2 系列 | AWX 2.1 图像 | L1 | 现有 22 个 | AWX |
| 11 | TanSat | ACGS 1A/1B（SAM/CAL/SCI） | L1 | 第一版订单 | HDF5 |

**v1.0 需要实现的容器（6 种）**：HDF5、NetCDF-4、NetCDF-3、1B（2 个变体）、AWX 2.1、FY-2 CSV 自定义容器 —— 外加 TXT 与 `.h5` 的简单读取。

**v1.0 不涉及**：HDF4（FY-3A/B）、微波定标、超光谱（GIIRS/HIRAS）、广播链路（LRIT/HRIT）。

### 1.4 样本盘点（`Y:\download-data` 实测，已忽略 `.enp` 与 GK-2A）

共 **511 个文件 / 18.8 GB**（排除 ENVI 临时文件 `.enp`、缩略图库 `Thumbs.db`、以及非 NSMC 的 GK-2A 快视图）。

| 卫星 | 产品 | 文件数 | 体积 | 容器 |
|---|---|---:|---:|---|
| FY-4B | AGRI L1 0500M | 6 | 2.51 GB | HDF5 |
| FY-4B | AGRI L1 1000M | 11 | 2.37 GB | HDF5 |
| FY-4B | AGRI L1 4000M | 12 | 1.11 GB | HDF5 |
| FY-4B | AGRI L1 2000M | 1 | 0.22 GB | HDF5 |
| FY-4B | GHI L1 REGX | 44 | 0.28 GB | HDF5 |
| FY-4B | AGRI L2（火点/沙尘等） | 206 | 0.49 GB | JPEG 快视 |
| FY-3H | MERSI L1 0250M | 9 | 1.32 GB | HDF5 |
| FY-3H | MERSI L1 1000M | 19 | 0.94 GB | HDF5 |
| FY-3H | MERSI L1 GEOQK | 2 | 0.91 GB | HDF5 |
| FY-3H | GNOSO L1（掩星） | 14 | 0.01 GB | **NetCDF-3** |
| FY-3G | PMR L2 KuR（降水雷达） | 1 | 0.57 GB | HDF5 |
| FY-3F | MERSI L1 1000M | 14 | 1.07 GB | HDF5 |
| FY-2G | CSV L1 数据集 | 28 | 2.89 GB | 自定义容器（长度前缀 + 文件名头） |
| FY-2G | FDI L1 全圆盘 | 33 | 1.36 GB | **HDF5** + RAW + JPEG |
| FY-1D | AVHRR L1B | 3 | 0.33 GB | 1B（HRPT 字节记录） |
| FY-1D | AVHRR L2 | 2 | 0.01 GB | 自定义 .DAT |
| NOAA-18 | AVHRR L1B | 8 | 0.69 GB | 1B（N1BD 数据集） |
| FY-2/Meteosat | AWX 2.1 | 22 | 0.01 GB | AWX（`EVLD….AWX` 头） |

**关键结论（改变了原计划的风险判断）**

1. **FY-2 的 `.hdf` 是 HDF5，不是 HDF4** → FY-2 L1 不需要 HDF4 库，和 FY-3/4 共用读取器。
2. **FY-3H GNOSO 是 NetCDF-3（CDF 魔数）** → 必须支持 NetCDF-3，`netCDF4` 依赖保留，不能省。
3. **1B 有真样本了**（FY-1D + NOAA-18，两种不同的头结构）→ 1B 从"P3 无样本"升级为"可验证"。
4. **AWX 有真样本**（22 个，含 `EVLD` 文件名头）→ AWX 读取器可立即开发验证。
5. 6. **FY-4B 的 L2 产品只有 JPG 快视图**（ASHI/CLOD/DUST/IFOG/MCPD/MCPH/MCPN/NATR/SNOW/STOM），
   没有对应的 HDF5 原始产品 —— L2 数值解析只能用 FY-4B 的 FHS/ASHI 等少数 HDF5 件，
   其余 L2 需另下单。
7. **FY-4B 全分辨率有多档**：1000M（10992²，3 通道）、2000M、4000M（2748²，15 通道全）、
   0500M（21984²，最重）。**只有 4000M 含全部 15 个通道（含 7 个红外）**，
   1000M 仅 3 个可见光通道 —— 红外算法验证必须用 4000M 或 2000M。

**已补齐（2026-11-01 批次 `C202611011426140096`）**

| 文件 | 说明 |
|---|---|
| `FY3D_MERSI_GBAL_L1_..._1000M_MS.HDF`（206 MB） | **FY-3D 主力机型，85 篇文档**；15 变量，`EV_1KM_Emissive (4,2000,2048)`、GEO 网格 |
| `FY3D_MERSI_ORBT_L2_CLM_...`（7 个） | 云掩膜 L2，`Cloud_Mask (6,2000,2048)` / `Cirrus_Mask` / `Cloud_Mask_QA` |
| `FY3F_MERSI_GRAN_L1_..._1000M_V0.HDF`（206 MB） | 与用户示例图同源 |
| `FY2H_CTA_MLT_NOM_20261101_0000.hdf`（21 MB） | FY-2H 云顶高度 |

**仍然缺**：FY-3C（64 篇）、FY-4A 全圆盘（43 篇，只有 REGX 区域件）、FY-3A/B（HDF4）、FY-3E、TanSat CAPIX。

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────┐
│  应用层  主界面 / 分析工作台 / 解码工作台 / 制图工作台      │
├──────────────────────────────────────────────────────────┤
│  制图引擎  RGB 合成器 · 地图叠加 · 经纬网 · 标注 · 模板出图 │
├──────────────────────────────────────────────────────────┤
│  分析层   统计 · 剖面 · 直方图 · 序列/动画 · 掩膜 · 重采样   │
├──────────────────────────────────────────────────────────┤
│  物理层   定标（VIS/IR/MW） · 定位（GLT/经纬度/标称投影）    │
├──────────────────────────────────────────────────────────┤
│  语义层   产品定义库（YAML，5,081 条字段）· 单位/量纲/色标   │
├──────────────────────────────────────────────────────────┤
│  容器层   HDF5 · NetCDF-4 · NetCDF-3 · HDF4 · S-VISSR ·    │
│           AWX · 1B · GeoTIFF（输入/输出）                  │
└──────────────────────────────────────────────────────────┘
```

**核心设计原则**

1. **容器层薄**：容器只有 7 种，写一次，全卫星复用。
2. **语义层厚且声明式**：产品差异全部落在 YAML，不写代码。
3. **插件可热加载**：`readers/` 与 `products/` 两个目录即插件，放进文件立刻可用。
4. **数据模型统一**：`SatDataset`（变量 + 坐标 + 属性 + 定位 + 元数据），任何格式解析后都归一到此，分析与制图只认它。

```python
class SatDataset:
    platform: str; instrument: str; level: str; product: str
    start_time: datetime; end_time: datetime
    variables: dict[str, Variable]     # data, unit, scale, offset, valid_range, fill, long_name
    coords: dict[str, np.ndarray]      # lon, lat 或 x, y
    geolocation: Geolocation | None    # GLT / latlon 网格 / 标称投影参数
    attrs: dict[str, Any]              # 原始全局属性
    source: Path; reader: str; product_def: str
```

---

## 3. 产品定义库（最关键的资产）

### 3.1 YAML Schema

```yaml
product: FY3D_MERSI_L1_250M
match:                        # 用文件名 + 全局属性双条件匹配
  filename: '^FY3[CDEFGH]_MERSI.*_L1_.*0250M.*\.HDF$'
  attrs: {Dataset Name: 'MERSI L1 SDR 250m Data'}
container: hdf5
groups: {data: /Data, cal: /Calibration, geo: /GeO}
fields:
  - name: EV_250_RefSB_b1
    path: /Data/EV_250_RefSB_b1
    kind: reflective            # reflective | emissive | microwave | flag | coord
    unit: '1'
    dn:   {valid: [0, 4095], fill: 65535, saturated: 65534}
    calib:
      method: linear
      coeff: /Calibration/VIS_Cal_Coeff[0]     # [intercept, slope, quad]
    display: {lut: gray, stretch: [2, 98]}
  - name: EV_250_Emissive_b24
    path: /Data/EV_250_Emissive_b24
    kind: emissive
    dn:   {valid: [0, 25000], fill: 65535}
    calib:
      method: planck
      radiance: {scale: 0.01, offset: 0}       # DN → mW/(m²·cm⁻¹·sr)
      wavelength_um: 10.7
    display: {lut: bt_enhanced, range: [180, 320], unit: K}
geolocation:
  method: latlon_grid
  lat: /GEO/Latitude
  lon: /GEO/Longitude
  step: 20                     # 每 20 像元一个格点
  resample: nearest
quality:
  field: /Data/QA_Frame_Flag
  mask_bits: [26, 29, 33]      # 定标/定位失败位
```

### 3.2 从 Markdown 到 YAML 的生成流水线

```
md/数据格式说明/*.md
   │  ① 抽取：按 "SDS 名称 / 数据类型 / 维数 / 属性表" 正则与表格解析
   ▼
_table_dump.json        （每文档的字段表 + 属性表，已可自动获得）
   │  ② 归并：同族文档字段合并（FY-3D 与 FY-3C 的 MERSI 定义高度重合）
   ▼
_draft/*.yml            （骨架，字段名/类型/维度/fill/valid_range 直接落盘）
   │  ③ 补全：定标系数位置、单位、量纲、色标、定位方式（需人工或规则）
   ▼
products/*.yml          （正式定义，进版本库，带测试）
   │  ④ 校验：用真实样本跑一遍，检查维度/范围/单位是否合理
   ▼
tests/golden/*.json     （回归基线：首像元值、行列均值、BT 范围等）
```

**工作量估算**：5,081 条 SDS 中约 **60%** 可由 ② 自动生成（有完整属性表），其余需人工补定标与定位。按每条约 2 分钟计，纯人工部分约 **65 人时**，加上校对与测试，P0 阶段（FY-3C/D + FY-4A/B）约 **3–4 周**。

### 3.3 已实测的样本（真实文件 + 真实魔数）

| 样本 | 容器 | 结论 |
|---|---|---|
| `FY4B-…AGRI L1 FDI 1000M/0500M/4000M`（29 个，6.2 GB） | HDF5 | 全圆盘 L1，定标/定位主战场 |
| `FY4B-…AGRI L2 FHS/ASHI`（206 个） | HDF5 / JPEG | L2 产品，CF-1.7 属性齐全，**零硬编码可解码** |
| `FY3F_MERSI_GRAN_L1_…1000M_V0.hdf` | HDF5 | 与示例图同源，已跑通出图 |
| `FY3H_MERSI_GRAN_L1_…0250M_V0.HDF` | HDF5 | `VIS_Cal_Coeff(19,3)`、`IR_Cal_Coeff(6,4,200)`、`GEO/Latitude,Longitude(400,410)` 与文档一致，定标定位可复现 |
| `FY3G_PMR_ORBD_L2_KuR` | HDF5 | 降水雷达，L2 结构验证 |
| `FY3H_GNOSO_ORBT_L1_….NC` | **NetCDF-3** | 掩星产品，验证 NC3 通路 |
| `FY2G_FDI_ALL_NOM_….hdf` | **HDF5** | 静止轨道 L1，推翻"FY-2 = HDF4"的假设 |
| `FY2G_CSV_MLT_NUL_….DAT` | 自定义 | 4 字节长度 + ASCII 文件名头，103 MB/个 |
| `FY1D_AVHRR_HRPT_L1_….L1B` | 1B | 头以空格填充 + `SMC.HRPT` 标识 |
| `NA18_AVHRR_HRPT_L1_….L1B` | 1B | 头为 `\0\0\x07\xd5` + `/N1BD/N18/…` 数据集树 |
| `MST2_SEC_VIS_LCN_….AWX` | AWX 2.1 | 头 `EVLD0401.AWX`，尺寸 1024×1148 |

### 3.4 真实结构探针（直接驱动产品定义）

| 产品 | 顶层结构 | 关键结论 |
|---|---|---|
| FY-4B AGRI L1 FDI 4000M | `/Calibration/CALChannel01–17`（4096 点 LUT）· `/Data/NOMChannel01–15` `(2748,2748) uint16` · `/NOMObs/NOMObsTime` · `/QA/*` · `/VerSoft/*` | 定标 = **DN→查找表**，不是线性系数；`NOMObsTime` 提供逐行时间 |
| FY-4B AGRI L1 FDI 1000M | 同上，`/Data` 只有 CH01–03，`(10992,10992) uint16` | 1000M 只含 3 个可见光通道；**单幅 241 MB 内存**，需分块读取 |
| FY-3F MERSI L1 1000M | `/Data/EV_1KM_Emissive (4,2000,2048)` · `EV_1KM_RefSB (15,2000,2048)` · `EV_250_Aggr.1KM_*` · `/Calibration/*` · `/GEO/Latitude,Longitude (400,410)` · `/QA/QA_Frame_Flag` | 通道是**三维数组的第 0 维**，不是各自一个数据集 → 定义里需声明 `band_axis: 0` |
| FY-3G PMR L2 KuR | `/CSF` `/DSD` `/FRE` `/Geo_Fields` `/PRE` `/SLV` `/VER`，主维 `(3885,59,400)` | 雷达三级产品（逐 bin），与成像仪差异大，**单独一类 viewer** |
| FY-2G FDI L1 | **扁平结构无分组**：`CALChannelIR1..4 / VIS`（`(1,1024)` LUT）· `NOMChannelIR1..4 / VIS / VIS1KM` `(2288,2288) uint16` · `NOMAzimuth` 等 | FY-2 定标同样是 **LUT**；无全局属性，元数据全在**文件名**里 |

---

## 4. 定标与定位

### 4.1 定标

| 类型 | 公式 | 数据来源 |
|---|---|---|
| 可见光/近红外 | `ρ = a0 + a1·DN (+ a2·DN²)` | `VIS_Cal_Coeff` / 属性 `Slope·Intercept` |
| 热红外 | `L = 0.01·DN` → `BT = C2·ν / ln(C1·ν³/L + 1)` | `IR_Cal_Coeff` + 中心波数 |
| FY-4 AGRI | `DN → SR`（查找表 `CALChannelXX`）→ `BT` | 文件内 LUT |
| 微波 | `TB = a + b·DN + c·DN²`（逐通道逐扫描线） | `IR_Cal_Coeff` 类系数 |
| 缺测/饱和 | `65535` / `65534`（FY-3）、`FillValue` 属性 | 定义内声明 |

> 普朗克反演已验证：FY-3H CH24 实算亮温 **195–300 K**，落在大气窗区合理区间。

### 4.2 定位

| 方式 | 适用 | 实现 |
|---|---|---|
| 文件内经纬度网格 | FY-3 250m/1km（`GEO/`，每 20 像元） | 双线性插值到全分辨率 |
| GLT（地理查找表） | FY-3 部分 L2、FY-4 | 直接索引 |
| 坐标轴 + 标称投影 | FY-4 全圆盘（`x`/`y` + 星下点） | 静止轨道反算 |
| 轨道根数 | 极轨 L1（无 lat/lon 时） | 可选 SGP4，一期不做 |

### 4.3 重采样与输出网格

最近邻 / 双线性 / 面积平均；目标网格：原始条带、等经纬（0.01°–0.25°）、标称投影。输出 GeoTIFF（含 CRS）、NetCDF、PNG、CSV。

---

## 5. 可视化与制图（本轮新增需求）

### 5.1 RGB 合成器

- 三个通道槽位，可任选数据集/通道，支持逐通道拉伸、伽马、反转
- 内置组合（可扩展，全部写在 YAML）：

| 名称 | 配方 | 用途 |
|---|---|---|
| 真彩色 | R=0.65 µm, G=0.55 µm, B=0.47 µm | 白天云/地表 |
| 三明治 | R=VIS, G=IR, B=IR | 云顶纹理 + 地表 |
| 昼夜微光 | R=IR, G=VIS, B=VIS（夜间增益） | 晨昏线 |
| 火点 | R=3.7 µm, G=0.87 µm, B=11 µm | 高温目标 |
| 沙尘 | R=11−12 µm 差值, G=0.87 µm, B=11 µm | 沙尘/雾 |
| 对流 | R=6.2−10.8 差值, G=10.8, B=VIS | 深对流 |

- 支持表达式模式：`(b24-b25)/(b24+b25)`，供高级用户自定义指数

### 5.2 地图叠加

- 内置 Natural Earth 矢量：**110m（全球概览）/ 50m（区域）** 海岸线、国界、一级行政区、河流、湖泊
- 数据已下载并入库：`assets/ne_110m_coastline.geojson`（137 KB，公有领域）
- 支持导入自定义 `.geojson` / `.shp`（shp 用纯 Python 读取，不引入 GDAL）
- 样式：颜色、线宽、层级、透明度；可只显示框选范围内的要素

### 5.3 经纬网

- 间隔：0.5° / 1° / 2° / 5° / 10° / 自动
- 标注：度数符号 + N/S/E/W、十进制度、度分秒
- 样式：实线/虚线/点线、颜色、透明度、边框刻度

### 5.4 框选制图（对应你给的示例图）

```
在分析视口框选矩形/任意多边形
      ↓
生成「制图工程」：裁剪 + 定位子集
      ↓
选模板（单图 / 双图对比 / 四图 / 2×2 + 色标）
      ↓
配置：标题、副标题、页脚、色标位置与刻度、经纬网、海岸线、比例尺、指北针、DPI、尺寸
      ↓
实时预览（matplotlib 渲染到画布）
      ↓
导出 PNG / PDF / SVG / TIFF（可批量、可脚本化）
```

**出图引擎选型：matplotlib**（已装，出版级，矢量输出，字体与色标控制成熟）。已用真实 FY-3H 数据跑通一张双面板样板图：

- 左：可见光真彩色（b3/b2/b1 合成）
- 右：CH24 10.7 µm 亮温（普朗克反演，turbo 色标）
- 叠加：110m 海岸线、5°/4° 经纬网、色标、标题、时间与轨道号页脚

> 产物：`samples/fy3h_mersi_l1_figure.png`（1,500×719 @160 dpi）

### 5.5 基础图像编辑

| 类别 | 功能 |
|---|---|
| 几何 | 裁剪、旋转（任意角/90°）、翻转、缩放、重采样 |
| 光度 | 亮度、对比度、伽马、直方图均衡、自定义拉伸区间 |
| 色彩 | 色标替换、伪彩、反相、通道交换 |
| 增强 | 均值/中值/高斯平滑、USM 锐化、去噪 |
| 标注 | 文字、箭头、矩形/椭圆/折线、比例尺、指北针、图例 |
| 工程 | 图层管理、撤销/重做（命令栈）、参数可保存为预设 |

> 原则：**所有编辑都是非破坏性的**，编辑记录为图层与参数，导出时才栅格化——保证任何一步都能回溯、能复现。

---

## 6. 技术栈（最终确认）

### 6.1 主干

| 组件 | 选型 | 版本 | 说明 |
|---|---|---|---|
| 语言/运行时 | Python | 3.10（`D:\py310`，已装） | 生态最全，团队可控 |
| GUI | **PySide6** | 6.8+ | Qt6，QGraphicsView 做大幅面影像，LGPL |
| 数值 | numpy / scipy | 已装 | 全部重活 |
| HDF5 | h5py | 已装 | **HDF5 与 NetCDF-4 同一个库**，省一个依赖 |
| NetCDF-3 | netCDF4（备用 scipy.io.netcdf） | 待装 | 老产品少量 |
| 绘图 | matplotlib | 已装 | 出版级出图 |
| 图像 | Pillow / tifffile | 已装 / 待装 | 编辑与 GeoTIFF |
| 投影 | pyproj | 待装（小） | 标称投影/极射赤面 |
| 配置 | PyYAML | 待装（小） | 产品定义库 |
| 打包 | PyInstaller | 已装 | 单文件/目录包 |
| 测试 | pytest / ruff | 已装 | 回归与规范 |

### 6.2 明确不引入

| 不引入 | 原因 |
|---|---|
| GDAL / rasterio | 体积大、部署重；GeoTIFF 用 tifffile 手写即可 |
| cartopy | 依赖 PROJ/GEOS，安装复杂；海洋/海岸线自绘足够 |
| xarray（核心） | 依赖链长、启动慢；需要时作为可选导出 |
| satpy | 面向国外卫星，产品语义与我国不一致 |
| dask | 本机内存 31.7 GB，单文件最大 ~2 GB，用不上 |
| PyQt5 | 与 PySide6 二选一，选许可证更清晰的 PySide6 |

### 6.3 安装位置（磁盘约束）

C: 0 MB、D: 197 MB 可用 → **全部装 E:**：

```powershell
setx PIP_CACHE_DIR  E:\pipcache
setx TMP            E:\tmp
python -m venv E:\venv\fysat
E:\venv\fysat\Scripts\pip install PySide6 netCDF4 pyproj PyYAML tifffile
```

---

## 7. UI 设计（四屏）

| 屏 | 名称 | 主要内容 |
|---|---|---|
| ① | 主界面 | 数据目录树（卫星/仪器/产品）、单幅产品视图、属性/变量/显示设置 |
| ② | 分析工作台 | 多视口联动、RGB 合成、LUT 库、剖面/直方图、统计 |
| ③ | 解码工作台 | 批量解析流水线、文件结构树、字段定义表、校验与日志 |
| ④ | **制图工作台** | 图层与渲染参数、双面板实时预览、出图模板与导出 |

设计语言：深色、青色主色（`#22d3ee`）、中文界面、四屏共用工具条与状态栏。

> 渲染稿：`E:\CODEX-NOworkspaces\ui-mockup\01_main.png` ~ `04_figure.png`

---

## 8. 里程碑

| 阶段 | 交付 | 周期 |
|---|---|---|
| **M0 骨架** | 项目结构、`SatDataset`、插件机制、CLI、样本回归测试 | 2 周 |
| **M1 容器层** | HDF5 / NetCDF-4 / NetCDF-3 读取器 + 格式自动识别 | 3 周 |
| **M2 语义层** | 产品定义生成器 + 有样本产品（AGRI / MERSI / FY-2 / 1B / AWX / GNOSO / PMR，约 160 篇） | 4 周 |
| **M3 物理层** | 定标（VIS 线性 / IR 普朗克 / AGRI LUT / FY-2 LUT）、定位（网格/GLT/标称）、重采样、GeoTIFF 输出 | 3 周 |
| **M4 可视化** | 主界面 + 分析工作台 + RGB 合成 + 地图叠加 + 经纬网 + 编辑 | 4 周 |
| **M5 制图** | 制图工作台、模板系统、批量出图 | 3 周 |
| **M6 扩展（视样本）** | 微波仪器 MWRI/MWTS/MWHS、VIRR、GIIRS、CAPIX、IRAS（每个仪器约 1 周） | 按需 1–6 周 |
| **M7 打包发布** | PyInstaller、安装包、文档、示例工程 | 2 周 |

**合计约 24 周（6 个月）到 v1.0**；若只做 P0 的 MVP，**约 3.5 个月**可用。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **仪器缺口**：微波（MWRI/MWTS/MWHS）、VIRR、GIIRS、IRAS、CAPIX 共 105 篇无样本 | 这些仪器只能"照文档写"，无法回归验证 | v1.0 不承诺；按 §1.3 版本路线在 v1.1/v1.2 逐批补样本；无样本产品标记 `unverified`，UI 顶部显示黄色横幅 |
| 1B 头结构不统一：FY-1D 空格填充 + `SMC.HRPT`，NOAA-18 为 `N1BD` 数据集树 | 一套解析器无法通吃 | 1B 按"卫星族 + 生成系统"分派到不同子解析器，用样本做字节级回归 |
| FY-2 `CSV` 容器（长度前缀 + 文件名头）文档描述不足 | 解析规则靠样本反推 | 以真实文件为准，把反推出的结构写回 YAML，并标注"样本推断" |
| 文档缺定标公式/查找表 | 部分产品算不出物理量 | 只输出 DN + 文档已明确的定标；LUT 单独下载通道 |
| HDF4（FY-3A/B）无库无样本 | 无法验证 | 明确排在最后；需要时用 pyhdf（需 MSVC 编译） |
| 产品数量巨大（5,081 条 SDS） | 人工定义成本高 | 生成器 + 同族归并（FY-3C 与 FY-3D 定义重合度高） |
| 磁盘 C/D 几乎满 | 构建失败 | 全量迁到 E:，CI 与缓存也放 E: |
| 制图与交互渲染性能 | 大影像卡顿 | 显示用金字塔降采样，导出才用全分辨率 |

---

## 10. 待确认

1. **v1.0 范围**是否就按 §1.5 的 11 个产品族锁定（AGRI / MERSI / FY-2 / 1B / AWX / GNOSO / PMR / TanSat ACGS）？
2. 能否补齐 §11 的样本（决定 M2 的验证范围，详见该节）
3. 制图输出是否必须支持 **PDF/SVG 矢量**？（会影响字体与标注的实现方式）
4. 是否需要**批量流水线模式**（命令行/脚本，一次处理几百个文件）？
5. 交付形态：**单文件 exe** / 安装包 / 源码 + 文档？
6. 是否需要**中文/英文双语界面**？

---

## 11. 后续批次样本建议（v1.1 以后，按"补一个文件救回多少篇"排序）

现有 + 本轮下单已覆盖 AGRI、MERSI、GNOSO、PMR、ACGS、AVHRR、AWX、FY-2 系列。**其余缺口全部集中在"仪器类型"而非卫星**：

| 排序 | 缺的样本 | 救回文档 | 建议规格 | 预估体积 | 累计覆盖 |
|---:|---|---:|---|---:|---:|
| 1 | **MWRI L1** | **55 篇** | 升轨 + 降轨各 1 个 | 0.3–0.8 GB | 60% → 81% |
| 2 | **VIRR L1** | 13 篇 | 1 个（FY-3D 优先） | 0.1–0.2 GB | → 86% |
| 3 | **GIIRS L1** | 8 篇 | 1 个（FY-4A 干涉式探测仪） | 1–2 GB | → 89% |
| 4 | **MWHS L1** | 7 篇 | 1 个 | 20–60 MB | → 92% |
| 5 | **MWTS L1** | 6 篇 | 1 个 | 20–60 MB | → 94% |
| 6 | **TanSat CAPIX 1B SCI** | 6 篇 | 1 个 | 0.1–0.3 GB | → 96% |
| 7 | **IRAS L1** | 5 篇 | 1 个（FY-3C） | 0.1–0.2 GB | → 98% |
| 8 | ERM / SBUS / TOU / SIM | 7 篇 | 各 1 个（地球辐射收支/紫外） | 各 10–50 MB | → 100% |

> **前 4 项合计不到 1.5 GB，可把覆盖率从 60% 拉到 92%**，远超剩余 29 GB 配额的成本。
> 单文件即可验证，不必整轨；1 个 L1 + 1 个 L2 足够跑通定义与回归测试。

**后续批次**：上表全部为 v1.1 及以后的补充项，不需要现在下单；FY-3A/FY-3B 的 HDF4 产品（3 篇）与 EOS/GMS 1B（2 篇）优先级最低，可等前 8 项补齐后再评估。

---

## 附录 A：已产出的验证物

| 文件 | 说明 |
|---|---|
| `samples/fy3h_mersi_l1_figure.png` | 真实 FY-3H 数据、真实定标、双面板制图样板 |
| `samples/make_sample_figure.py` | 上述样板图的可复现脚本（约 130 行） |
| `analysis/corpus_inventory.json` | 265 篇文档的格式/族/层级盘点 |
| `analysis/sample_matrix.md` | `Y:\download-data` 的样本盘点表（511 文件 / 18.8 GB） |
| `analysis/inspect_formats.py` · `inspect_raw_formats.py` | 容器魔数探测脚本（HDF5/HDF4/NC3/1B/AWX） |\n| `analysis/probe_samples.py` | 真实样本结构探针（FY-4B/FY-3F/FY-3G/FY-2G） |\n| `analysis/instrument_gap.md` | 仪器维度缺口分析（补哪个文件救回多少篇） |
| `assets/ne_110m_coastline.geojson` | Natural Earth 110m 海岸线（公有领域） |
| `ui-mockup/01_main.png` … `04_figure.png` | 四屏 UI 渲染稿 |

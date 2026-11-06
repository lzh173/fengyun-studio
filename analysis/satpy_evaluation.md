# satpy 作为可选读取后端的评估（结论页）

> 评估对象：**satpy 0.59.0**（隔离安装在 `E:\tmp\satpytest`，主环境 `<venv>` 不装）
> 实测日期：2026-11-03　实测样本：<样本目录> 下的真实 NSMC 文件（见 §2）
> 落地代码：[`src/fysat/readers/satpy_adapter.py`](../src/fysat/readers/satpy_adapter.py)、
> 测试 [`tests/test_satpy_adapter.py`](../tests/test_satpy_adapter.py)（36 条：24 条零依赖 + 12 条需 satpy/真实样本）

## 0 结论

| 问题 | 结论 |
|---|---|
| 许可证能用吗 | **能**。satpy 是 GPLv3-or-later，我们 AGPL-3.0-only，GPLv3 §13 与 AGPLv3 §13 双向授权合并，合并后整体按 AGPLv3 分发——我们本来就满足（见 §1） |
| 替代我们自有读取器 | **不替代，只做叠加**。它能覆盖 FY-3 MERSI L1 定标与 FY-4 AGRI L1；AWX 2.1、FY-2 S-VISSR/CSV/1B、FY-1/NOAA 1B、绝大多数 L2 它一个都没有（见 §3、§4） |
| 进主依赖吗 | **不进**。`pip install "fysat[satpy]"` 按需装：实测依赖树 +370 MB / 13009 个文件，`import satpy` 冷启动 2.0 s（见 §5） |
| 硬约束 | **定位必须配 GEO 文件**。只有数据文件时 satpy 能定标、但 `latitude/longitude` 数据集不存在；真彩色 `true_color` 也依赖 GEO 里的太阳天顶角，无 GEO 时只有 `true_color_raw` 能出图（见 §2） |
| 建议 | 适配器给两条路径：`load=False` 惰性（GUI/CLI 该走这条）+ 自动配对 GEO；找不到 GEO 时降级为"无定位但可读"（`attrs["geo_missing"]=True`）。默认不装 satpy，`import fysat.readers` 仍是 0.33 s 且不加载它 |

## 1 许可证：GPLv3 ↔ AGPL-3.0-only 可共存

**实证**（读 `*.dist-info/METADATA`，不是凭印象）：satpy 走 **GPLv3-or-later**；随它一起装进来的 GPL 构件还有
**trollimage（GPLv3+）**、**python_geotiepoints（GPLv3+）**；`pyspectral` 是 Apache-2.0，`pyresample` 是 LGPLv3+，
`pykdtree` 是 LGPL-3.0-or-later，dask/xarray/zarr/pooch/pyproj/numcodecs 全是 BSD/MIT/Apache。

**法律依据**：

1. **GPLv3 §13「Use with the GNU Affero General Public License」**：明确允许把 GPLv3 作品与 AGPLv3 作品
   **链接或合并成一个作品**并分发。
2. **AGPLv3 §13 第二段**做反向授权：允许把 AGPL 作品与 GPLv3 作品合并，合并后的整体受 AGPLv3 约束
   （GPL 部分仍按 GPLv3 提供）。两条 §13 互为镜像，所以 **GPLv3-only 依赖与 AGPLv3-only 项目合并是许可的**。

**我们怎么做才算守住**：

- **不 vendor、不 patch satpy 源码**，只 `import`；satpy 未进 `dependencies`，只进 `optional-dependencies.satpy`，
  用户的默认安装包里没有任何 GPL 代码。
- 用户自己 `pip install` → 各自许可，我们不承担 GPL 分发义务。
- 若将来**打包随身分发** satpy：整包须按 AGPLv3 提供完整对应源码（我们本来就 AGPL-3.0-only），并把
  satpy / trollimage / python_geotiepoints 的 GPLv3 全文与版权声明放进 `docs/licenses/` 与 `THIRD_PARTY_NOTICES.md`。
- ⚠️ **待办（不属本任务文件边界，需 license-audit 收口）**：`LICENSES.md` §2 依赖表加 satpy / trollimage /
  python_geotiepoints 三行，`THIRD_PARTY_NOTICES.md` 补 GPLv3 全文。

## 2 实测结果（真实 NSMC 文件）

| 样本 | satpy reader | 结果 |
|---|---|---|
| `FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF`（196.7 MB，**无 GEO**） | `mersi2_l1b` | ✅ 25 个通道全出；band1 反射率 5.25→80.71 %（归一化 0.052→0.807），band20 亮温 242.9→317.4 K；`geo_missing=True`、`geolocation.kind="none"`，数据照读；全量 `load=True` 12.5 s / 410 MB |
| `FY3H_MERSI_GRAN_L1_20261030_0300_1000M_V0.hdf` + `..._GEO1K_V0.hdf` | `mersi3_l1b` | ✅ GEO 自动配对生效：lat 3.58→24.85°N，lon 139.46→169.80°E，另有 4 个天顶角/方位角数据集 |
| `FY3C_MERSI_GBAL_L1_20150530_0025_1000M_MS.HDF` + `..._GEO1K_MS.HDF` | `fy3c_mersi1_l1b` | ✅ 老平台（MERSI-1）同样配对成功，说明改名规则跨代通用 |
| `FY3F_MERSI_GRAN_L1_20261030_0020_1000M_V0.hdf` | `mersi3_l1b` | ✅ 25 个通道（本地无该时段 GEO，故无定位） |
| `FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_..._1000M_V0001.HDF` | `agri_fy4b_l1` | ⚠️ reader 存在、文件名模式匹配，但本地样本与现有 GEO 文件时段不重合，**未做端到端验证** |

**定位是硬约束**（复现方式见测试）：只喂数据文件时 satpy 只打 WARNING
`Required file type 'mersi2_l1b_1000_geo' not found or loaded for 'latitude'`，
而 `latitude`/`longitude` **根本不出现在 `available_dataset_names()` 里**——不是"值不对"，是"没有"。
所以适配器必须先按文件名把 GEO 文件配对进去：`_1000M_` → `_GEO1K_`、`_0250M_` → `_GEOQK_`、
`_0500M_` → `_GEOHK_`（FY-3G 专用）、AGRI 的 `L1-_FDI-` → `L1-_GEO-`。

**顺带一个坑**：MERSI-2 的 `true_color` 合成挂在 `sunz_corrected + rayleigh_corrected` 上，
两样依赖（太阳天顶角、pyspectral 的 Rayleigh LUT）一个在 GEO 里、一个要联网下载；
无 GEO 时实测 `true_color_raw` 正常（(3,2000,2048)），`true_color` 直接 KeyError。
**离线环境不要承诺 `true_color`。**

## 3 能替代我们哪些模块

| 能力 | 我们现有实现 | satpy | 结论 |
|---|---|---|---|
| FY-3 MERSI L1 反射率/亮温/辐亮度/counts 定标 | `products/decode.py` + `calib.py` + 9 个产品 YAML（系数表、波长表手工维护） | ✅ 已实测 | **可替代**，省掉逐平台维护系数/波长；但只建议作交叉校验或新平台快速接入 |
| 多平台覆盖 | 靠 YAML 逐平台声明 | A/B/C/D/E/F/G/H + MERSI-1/2/3/LL/RM | 可替代（本机只实测了 C/D/F/H） |
| FY-4A/4B AGRI L1 | `products/FY4B_*.yml` | `agri_fy4a_l1` / `agri_fy4b_l1` | 可能替代，待样本验证 |
| 真彩色合成 | `pipeline.true_color`（针对晨昏轨道调过 gamma/饱和度的参数） | `mersi-2` 有 `true_color` / `true_color_raw` | **建议保留我们的**：参数是调试成果，satpy 版本更"通用"但需要 GEO + 联网 LUT |
| 重采样/重投影 | `geo.py`（纯 numpy） | `pyresample`（pykdtree 加速，更完备） | 可选替代；换来的代价是 dask/xarray 整套 |
| 产品定义库 / 批量解码 / 四屏 GUI / 制图 / 导出 / 溯源 | 我们 | ❌ 不提供 | **必须保留** |

## 4 satpy 覆盖不到、必须保留我们自己的

| 我们的能力 | satpy 现状（逐项核过 `satpy/etc/readers/*.yaml`） |
|---|---|
| **AWX 2.1**（FY-2 定量产品） | 无任何 AWX 读取器 |
| **FY-2 S-VISSR / CSV 容器 / 1B** | 无任何 FY-2 读取器；全库唯一 VISSR reader 是日本 `gms5-vissr_l1b` |
| **FY-1 / NOAA 的 1B 容器**（`oneb.py`：CDB 定标表 + 扫描线结构） | 无 `FY1`/`1B` 相关文件名模式；AVHRR 侧只有 AAPP / EPS / GACLAC / EUM GAC / HRPT-L0 系 |
| **绝大多数 L2 产品**（如 FY-3D MERSI `ORBT_L2_CLM`） | FY 系列只覆盖 L1：全库提到 FY-3 的 reader 仅 7 个 mersi L1b。注意别被名字骗了——`li_l2_nc` 是 MTG 闪电成像仪、`vii_l2_nc` 是 EPS-SG VII，都不是风云 |
| 产品定义库 / 批处理 / GUI / 制图 / 导出 / 溯源 | 不属于 satpy 的职责范围 |

## 5 依赖代价（实测）

| 指标 | 数值 |
|---|---|
| 隔离安装体积 | **370.2 MB / 13009 个文件**（satpy + dask + xarray + zarr + pyresample + pyspectral + pyproj + pandas + pykdtree 等约 50 个包） |
| `import satpy` 冷启动 | **1.98 s** |
| `import fysat.readers`（装不装 satpy 都一样） | 0.33 s，且**不会**加载 satpy（惰性 import 实测确认） |
| 建 `Scene`（FY-3D） | 0.2–1.5 s |
| 单通道定标到 numpy（2000×2048） | 0.2–0.6 s |
| FY-3D 全 25 通道 `load=True` | 12.5 s，数据 410 MB（单通道 16.4 MB） |
| 追加运行时依赖 | pyspectral 的 Rayleigh LUT 走 `pooch` **联网下载**，离线环境 `true_color` 不可用 |

→ 结论：**默认不装**，作为 `fysat[satpy]` 可选增强；主流路径（`load=False` + 按需 `load(name)`）与我们的
HDF5 读取器保持同一套惰性语义。

## 6 用法与两条纪律

```python
from fysat.readers import satpy_adapter as satpy_backend

ds = satpy_backend.read(path)                       # 自动配对 GEO；默认 load=True
ds = satpy_backend.read(path, load=False)           # 只登记形状，之后 ds.load("1") 按需读
ds = satpy_backend.read(path, names=["1", "2", "3"])  # 只读指定通道
open_file(path, kind="satpy")                       # 走注册表（open_file 新增可选 kind 参数）
```

1. **单位**：satpy 的 MERSI 反射率是 **%**（与 `calib.reflectance_linear` 一致），适配器默认折成
   **0~1 归一化反射率**（`unit="1"`，与 `pipeline.visible_data/reflectance_toa/true_color` 同一口径），
   原生单位留在 `Variable.attrs["satpy_units"]`；要与产品解码路径（%）对齐就传 `normalize_reflectance=False`。
2. **不要把 satpy 变量喂给 `pipeline.visible_data()` / `reflectance_toa()`**：那两个函数假定输入是**原始 DN**，
   会自己查 `VIS_Cal_Coeff` 再算一遍——对已定标数据等于二次定标（本项目历史上出过同类事故）。

## 7 复跑命令（Lead 用）

```powershell
$env:TMP='E:\tmp'; $env:TEMP='E:\tmp'
cd <repo>

# 1) 有 satpy（测试自动把 E:\tmp\satpytest 加进 sys.path）：应 36 passed
<venv>\Scripts\python.exe -m pytest tests/test_satpy_adapter.py -v -rs

# 2) 模拟"没装 satpy"（拦截器让 import satpy 失败）：应 24 passed / 12 skipped
#    拦截器是 scratch 文件：E:\tmp\nosatpy\sitecustomize.py（不在仓库里）
$env:PYTHONPATH='E:\tmp\nosatpy'
<venv>\Scripts\python.exe -m pytest tests/test_satpy_adapter.py -v -rs
Remove-Item Env:PYTHONPATH

# 3) 原有读取器不回归
<venv>\Scripts\python.exe -m pytest tests/test_pipeline.py tests/test_cli.py tests/test_geo.py `
    tests/test_awx.py tests/test_oneb.py tests/test_fy2_csv.py tests/test_nc3.py tests/test_export.py tests/test_batch.py -q
```

实测记录（2026-11-03）：① **36 passed / 10.5 s**；② **24 passed / 12 skipped / 0.6 s**；③ **141 passed**。

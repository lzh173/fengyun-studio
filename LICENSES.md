# FY-Sat Studio 许可证与合规说明（LICENSES.md）

> 适用项目：**FY-Sat Studio / `fysat`**（风云气象卫星官方数据解码 · 分析 · 制图）
> 文档版本：**1.2（定稿）** ｜ 审计日期：2026-11-02（1.2 补充 2026-11-04） ｜ 审计范围：`pyproject.toml` 声明的运行时依赖 + 实际安装环境 `<venv>`（Python 3.10.6）中已安装的包 + Qt 6 / PySide6 模块授权
>
> **1.2 修订（2026-11-04）**：新增 §5.5「借鉴第三方实现（SatDump 等）的合规政策」——结论：AGPLv3 §13 ↔ GPLv3 §13 双向授权，参考/合并 GPLv3 的 SatDump 合法；仅借鉴算法/原理不触发任何 GPL 义务；**红线是 SatDump `resources/` 下的第三方 LUT/色表资产**（独立授权链）。摘要表新增第 11 条。
> 适用场景：**对外分发**（含安装包、绿色版、容器镜像、以及任何把 Python 包/二进制一并交付给第三方的形式）
> 对应文件：`LICENSE`（AGPL-3.0 全文 + 附加条款指引）、`THIRD_PARTY_NOTICES.md`（版权声明汇总）、`docs/licenses/`（许可证全文）
>
> **1.1 修订（2026-11-02，按负责人最终决策）**：① 附加条款**仅采用 AGPLv3 §7(b)(c)**；②「数据分发须附修改后源代码」经复核**不属于 §7 六类**，重构为三层结构（软件许可 / 数据使用条款 / 技术元数据，见 §1.2、§1.4）；③ 同步三项已修复风险（`pyproject` 锁定 `PySide6-Essentials==6.12.0`、`app.py` 强制 `QT_API=pyside6`、新增自动化合规测试，见 §5.2 / §5.3 / §5.5）；④ 新增根目录 `LICENSE` 与 `docs/licenses/FYSAT-ADDITIONAL-TERMS.md`，重构 `docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`（v2.0）。

---

## 0. 结论摘要（先看这里）

| # | 结论 | 依据/状态 |
|---|---|---|
| 1 | **本项目代码采用 `AGPL-3.0-only`（2026-11-02 最终决策）**；附加条款**仅采用 AGPLv3 §7(b)(c)**（保留合理署名/法律声明 + 禁止虚假来源并要求修改版合理标记）。**「数据分发须附修改后源代码」不作为软件许可条款**（超出 §7 六类，属 further restriction），改由「数据使用条款 + 导出元数据」承接（见 §1.2、§1.4）。 | `LICENSE` 已创建；`docs/licenses/FYSAT-ADDITIONAL-TERMS.md` |
| 2 | **Qt/PySide6 走 LGPLv3 动态链接路线可行**：Python wheel 形态的 PySide6 是「PySide6 运行库 + Qt 动态库（.dll）」独立文件，运行时动态加载，用户可整体替换，满足 LGPLv3 §4 的「可替换」要求。 | 实测 `PySide6\Qt6*.dll` 共 76 个独立 DLL（全部 DLL 合计 89 个） |
| 3 | **9 个运行时直接依赖中无强 copyleft**：numpy/h5py/matplotlib/pillow/scipy/tifffile/PyYAML 均为 BSD/MIT/PSF 系宽松许可；仅 PySide6/shiboken6 为 LGPLv3（弱 copyleft，仅约束 Qt 自身）。 | §2.1 表格，逐包许可证文件为证 |
| 4 | **当前源码无 GPL 污染**：全仓库无 `PyQt5/PyQt6` 导入；GUI 只导入 `PySide6.QtCore / QtGui / QtWidgets`（均 LGPLv3 可用）。 | §5.1 扫描结果 + §5.5 自动化测试 |
| 5 | ⚠️ **wheel 级 GPL-only 构件仍在**：PySide6-Essentials 6.12.0 wheel 内附带 **Qt Virtual Keyboard / Qt Lottie Animation / Qt Quick Timeline**（均 GPLv3-only）的 DLL/QML 插件，以及 14 个 GPLv3+工具例外的 Qt 可执行工具。**打包分发前必须按 §4.3 剪裁（方案 A）**，否则等于分发 GPLv3 代码。 | 实测目录清单，证据见 §4.3 |
| 6 | ✅ **已处理**：`pyproject.toml` 已从裸 `PySide6>=6.6` 改为 **`PySide6-Essentials==6.12.0`**（附注释禁止写裸 `PySide6`，否则会拉入含 GPL 模块的 Addons）。 | `pyproject.toml` L11/L27；`tests/test_license_compliance.py` 固化 |
| 7 | ✅ **已处理**：`app.py` 在导入 `matplotlib.pyplot` 前强制 `QT_API=pyside6` + `matplotlib.use("QtAgg", force=True)`，阻断 matplotlib 选中 GPL 的 PyQt。 | `src/fysat/gui/app.py::_force_pyside6_backend()` |
| 8 | **AGPL 与 LGPLv3 Qt 兼容**：AGPLv3 项目动态链接 LGPLv3 Qt 合法；AGPL 的源码公开义务只作用于「我们自己的代码」，Qt 仍按 LGPLv3 提供（可替换、附全文、附声明）。 | §1.3、§3 |
| 9 | ✅ **已处理**：根目录 `LICENSE` 已补（AGPL 全文 + 附加条款指引）；`THIRD_PARTY_NOTICES.md`、`docs/licenses/` 全套就绪。**分发前仍需**：About 声明、打包附随与 GPL-only 剪裁（§6）。 | 文件已落地（2026-11-02） |
| 10 | ✅ **已实现（技术层）**：导出 TIFF/PNG 默认写入 provenance 元数据（software / version / source_url / modified / commit / generated_at），这是「数据来源/是否修改」诉求的最强保障。 | `src/fysat/provenance.py`、`src/fysat/export.py`（§1.4） |
| 11 | **参考 SatDump（GPL-3.0-or-later）实现思路合法**：AGPLv3 §13 与 GPLv3 §13 双向授权，合并分发合法；若仅借鉴算法/物理原理，则连 GPL 义务都不触发。**唯一红线是 SatDump `resources/` 下的第三方 LUT/色表资产**（独立授权链，不受 GPL 覆盖）。 | §5.5；实测 `src/` 中 SatDump 引用 0 处 |

> 说明：第 6、7 条已由开发负责人于 2026-11-02 修复，并由 `tests/test_license_compliance.py` 固化检查（§5.6）；第 5 条（wheel 剪裁）需在发布打包时落实（检查清单 C-06）。

---

## 1. 项目自身许可证（我们自己的代码）

### 1.1 选定许可证：`AGPL-3.0-only`

| 项 | 内容 |
|---|---|
| SPDX 标识 | `AGPL-3.0-only` |
| 许可证全文 | [`docs/licenses/AGPL-3.0.txt`](docs/licenses/AGPL-3.0.txt) |
| 版权人 | FY-Sat Studio 项目作者/贡献者（`LICENSE` 头部已统一署名；源文件 SPDX 头另见检查清单 C-19） |
| 决策 | **最终决策（2026-11-02）**：`AGPL-3.0-only` 开源 + **仅 §7(b)(c) 范围内的附加条款**（见 `docs/licenses/FYSAT-ADDITIONAL-TERMS.md`）。「数据分发须附修改后源代码」**不写入软件许可**，改由数据使用条款 + 技术元数据承接（§1.2、§1.4）。 |

**AGPL-3.0 对本项目的直接影响（务必理解后再对外发布）：**

1. **必须公开源码**：向任何第三方分发程序（含可执行包）时，必须提供完整 Corresponding Source；通过网络提供服务时（AGPL §13），必须向网络用户提供获取源码的显著途径。**即「闭源分发」在本许可证下不可行。**
2. **传染范围**：`src/fysat/**` 及未来新增代码均属 AGPL 覆盖范围；第三方依赖若为宽松许可（BSD/MIT/PSF）可被 AGPL 作品包含，不冲突；LGPLv3 的 Qt 保持 LGPLv3（见 §4）。
3. **与「将来闭源/商业授权」的关系**：若未来仍希望保留闭源商业版本，需另立商业许可（要求全部版权人同意 + 依赖链允许），本 AGPL 发布不影响该计划，但**同一份代码不能既闭源分发又声称 AGPL**。此点列为待确认项（§7-Q5）。
4. **落地动作**：✅ 仓库根 `LICENSE` 已创建（AGPL 全文 + 附加条款指引，2026-11-02）；✅ `pyproject.toml` 已声明 `license = {text = "AGPL-3.0-only"}`；⬜ 源文件 SPDX 头待批量添加（`SPDX-License-Identifier: AGPL-3.0-only`，检查清单 C-19）。

### 1.2 附加条款：AGPLv3 §7 逐条对照与最终结构（本轮核心）

负责人最终要求（2026-11-02）：「分发本软件生成的数据时，需说明 **①软件来源 ②是否经过修改 ③修改后的源代码**」。

#### 1.2.1 AGPLv3 §7 允许的六类附加条款（原文摘要）

| 条款 | 内容 | 本项目是否采用 |
|---|---|---|
| (a) | 以不同于 §15/§16 的方式作免责声明或限制责任 | ❌ 不采用（保持 AGPL 原文） |
| (b) | **保留指定的合理法律声明或作者署名**（在材料中，或包含该材料的作品所展示的「适当法律声明」中） | ✅ **采用** |
| (c) | **禁止虚假陈述材料来源；或要求修改版以合理方式标记为与原版不同** | ✅ **采用** |
| (d) | 限制为宣传目的使用许可人/作者姓名 | ❌ 不采用 |
| (e) | 不授予商标/服务商标使用权 | ❌ 不采用 |
| (f) | 要求赔偿（indemnification） | ❌ 不采用 |

#### 1.2.2 三项要求的逐条结论（← 关键）

| 用户要求 | 可挂靠的 §7 类别 | 作为「软件许可附加条款」是否可行 | 结论与落点 |
|---|---|---|---|
| ① **说明软件来源** | **§7(b)**（保留合理法律声明与署名）+ **§7(c)**（禁止虚假来源，补充） | ✅ **可行**——但对象限于「程序材料」及包含程序的组合作品所展示的 Appropriate Legal Notices（About / 文档 / 版本信息 / 安装包声明）。要求第三方在**其数据**中标注，超出 §7 的对象范围（见 §1.2.3） | 写入 `LICENSE` + [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md) 第 1 条；数据场景由 §1.4 技术元数据 + 数据条款承接 |
| ② **说明是否经过修改** | **§7(c)**（要求修改版以合理方式标记为与原版不同） | ✅ **可行**——「要求标记为不同」合法；但**不能**借此要求公开修改版源码（那是 §7 之外的新义务） | `FYSAT-ADDITIONAL-TERMS.md` 第 2 条；运行时由 `provenance.modified` 自动标注（§1.4） |
| ③ **数据分发时附修改后源代码** | **❌ 不属于 §7(a)–(f) 任何一类** | ❌ **不可行**——作为软件许可条款构成 §10 意义上的 **further restriction**；§7 末段规定：若收到的程序带有超出许可的进一步限制条款，**接收者可删除该条款**；且输出数据不是 §7 所称的 "that material"，版权许可覆盖力弱 | **不写入软件许可**；改为数据条款中「注明修改后源码**获取地址**」（请求性）+ 技术层写入 `source_url` / `commit`（§1.4） |

> **§7 末段原文（关键依据）**："All other additional terms are considered 'further restrictions' within the meaning of section 10. If the Program as you received it, or any part of it, contains a notice stating that it is governed by this License along with a term that is a further restriction, **you may remove that term**."
> **§10（摘要）**：不得对许可证授予的权利施加进一步限制。

#### 1.2.3 精确边界说明（为什么「数据附源码」不能进软件许可）

1. **§7 的对象是「你添加的材料」（that material）**，不是程序输出。§7(b)(c) 均以「该材料」及「包含该材料的作品所展示的适当法律声明」为限。
2. **把「第三方分发数据必须附源码」写成软件许可条件**：既非 §7 六类之一 → 属 further restriction → 可被接收者依 §7 末段移除；同时使作品偏离标准 AGPLv3，影响与 GPLv3-only 组件的兼容性判断（本项目政策本就禁止 GPL-only 模块，§4.2）。
3. **数据通常不构成程序的衍生作品**：FSF 对 GPL/AGPL 的立场是「程序输出不因运行程序而受程序许可证约束」；用版权许可约束数据分发，效力弱、举证难。
4. **业务不可行**：气象/科研数据需要自由流转；「随数据附源码」既无对应关系（数据≠源码），也会阻碍业务采用。

#### 1.2.4 最终采用的合规替代结构（三层，互不越界）

| 层 | 载体 | 法律性质 | 覆盖对象 | 强制力 |
|---|---|---|---|---|
| **L1 软件许可层** | [`LICENSE`](LICENSE) + [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md) | `AGPL-3.0-only` + **仅 §7(b)(c)** | 本程序及修改版的分发 | **强制**（版权许可） |
| **L2 数据条款层** | [`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md) | 数据使用条款 / **请求（request）** | ① 我们分发的数据：可强制保留溯源字段；② 用户自己生成的数据：仅请求 | ① 合同/使用条款；② 无法律强制 |
| **L3 技术元数据层** | `src/fysat/provenance.py` + `src/fysat/export.py` | 技术实现（默认写元数据） | 所有导出 TIFF/PNG | **默认执行** |

#### 1.2.5 为什么把「数据附源码」降级为「请求 + 元数据」

| 理由 | 说明 |
|---|---|
| 法律 | 不属于 §7 六类；数据不是程序衍生作品；写进许可会被接收者移除 |
| 业务 | 不希望阻碍用户自由使用数据；「数据附源码」在业务上不可执行 |
| 替代 | 数据条款要求「注明**源码获取地址**」+ 元数据写入 `source_url` / `commit` / `modified`，已能回答「来源 / 是否修改 / 如何取得源码」三问 |
| 技术 | 导出即写入（§1.4），可执行性远高于条款——下游即使不读条款，看图工具也能读到溯源信息 |

#### 1.2.6 本轮产物文件

| 文件 | 作用 |
|---|---|
| [`LICENSE`](LICENSE)（根目录） | AGPL-3.0 全文 + 附加条款指引（§7(b)(c) 摘要） |
| [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md) | 附加条款正式正文（中英双语，严格限定 §7(b)(c)） |
| [`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md) | 数据条款 + 技术元数据说明（分层，v2.0） |

### 1.3 为什么选择 AGPL 与 LGPLv3 Qt 是兼容的

| 判断 | 说明 |
|---|---|
| AGPLv3 作品可动态链接 LGPLv3 库 | LGPLv3 §4 允许以「自选条款（terms of your choice）」发布组合作品，只要满足 LGPLv3 的声明、全文附随、可替换等义务；AGPLv3 即我们的自选条款。 |
| 组合后 Qt 的许可状态 | Qt 仍以 LGPLv3 授权，**不会**被「升级」为 AGPL；用户对 Qt 的权利仍来自 LGPLv3。我们的 AGPL 只覆盖我们自己的代码 + 我们创建的组合作品整体分发条款。 |
| 若使用 GPLv3-only Qt 模块（本政策禁止） | GPLv3 §13 允许 GPLv3 代码与 AGPLv3 代码组合并整体按 AGPLv3 传递，理论上可行；但会使项目被固定在 GPL/AGPL 家族、附加条款无法施加于 GPLv3 部分，且违反本项目政策（§4.2）。 |

### 1.4 技术层默认满足：导出溯源元数据（已实现）

> 位置：`src/fysat/provenance.py`（采集/序列化）+ `src/fysat/export.py`（默认写入）。这是把「数据来源 / 是否修改」诉求**用技术默认满足**的方案，不构成任何额外法律限制。

**字段设计（`build_provenance()` 产出）：**

| 字段 | 写入内容 | 来源 |
|---|---|---|
| `software` / `software_version` | `FY-Sat Studio` / 版本号 | `provenance.SOFTWARE_NAME` / `fysat.__version__` |
| `license` | `AGPL-3.0-only` | 常量 |
| `source_url` | 项目源码地址（可用 `FYSAT_SOURCE_URL` 覆盖） | `provenance.SOURCE_URL` |
| `modified` | 是否修改版（git 工作区脏 → `yes`；取不到 git → 保守 `yes`） | `provenance.is_modified_release()` |
| `commit` | 源码短提交（可得时） | `provenance.commit_hash()` |
| `generated_at` | UTC 生成时间（ISO 8601） | `provenance.build_provenance()` |
| `generator_platform` | 生成平台 | `platform` 模块 |
| `platform` / `instrument` / `level` / `product` / `observation_time` / `variable` / `source_file` / `reader` | 数据集元数据（若提供） | `SatDataset` 属性 / 调用参数 |
| `extra` | 自定义字段 | 调用方注入（如卫星/通道/产品号） |

**写入与回读：**

| 格式 | 写入位置 | 实现 |
|---|---|---|
| TIFF | `ImageDescription` tag（`key: value` 多行文本） | `as_text()` → `tifffile.imwrite(description=...)`（`export.py::_write_tiff`） |
| PNG | `tEXt` 块，键前缀 `fysat.`（如 `fysat.software`） | `as_png_text()` → Pillow `PngInfo`（`export.py::_write_png`） |
| 回读 | 测试 / 下游校验 | `read_tiff_provenance()` / `read_png_provenance()` |

- **默认开启**：`ExportOptions.provenance=None` 时自动 `build_provenance()`，用户无需任何操作。
- **可覆盖/追加**：通过 `ExportOptions.provenance` 显式传入（GUI/CLI 可加业务字段）。
- **为什么比条款强**：内嵌文件、随数据流转、任何看图工具可读、支撑科研可复现（版本 + commit + 时间 + 源文件）。
- **与软件许可的关系**：纯技术事实记录，不产生额外法律义务，也不改变 AGPLv3 赋予的任何权利。

---

## 2. 依赖许可证汇总表

### 2.1 运行时直接依赖（随软件分发）

版本取自实际安装环境 `<venv>`（`importlib.metadata` 探测，2026-11-02）；证据列为安装目录内的许可证文件或包元数据。

| 组件 | 版本 | 许可证 | Copyleft？ | 分发义务（摘要） | 证据来源（本地文件/元数据） |
|---|---|---|---|---|---|
| **NumPy** | 2.2.4 | BSD-3-Clause（含捆绑 OpenBLAS 等第三方许可） | 否 | 保留版权声明与许可文本；不得用作者名背书 | `<python>\Lib\site-packages\numpy-2.2.4.dist-info\LICENSE.txt`；`Classifier: License :: OSI Approved :: BSD License` |
| **h5py** | 3.16.0 | BSD-3-Clause（捆绑 HDF5、lzf、zlib） | 否 | 保留版权与许可文本；HDF5 单独声明 | `h5py-3.16.0.dist-info\licenses\LICENSE`；`License-Expression: BSD-3-Clause` |
| **Matplotlib** | 3.10.1 | Matplotlib License（PSF 系，BSD 兼容）+ 捆绑字体 DejaVu（Bitstream Vera）、STIX（SIL OFL 1.1） | 否 | 保留许可与字体许可文本；不得用 MDT 名背书 | `matplotlib-3.10.1.dist-info\LICENSE`；`mpl-data\fonts\ttf\LICENSE_DEJAVU`、`LICENSE_STIX` |
| **Pillow** | 11.1.0 | MIT-CMU（LICENSE 同时收录捆绑的 libjpeg-turbo、zlib、libtiff、freetype、OpenJPEG、lcms2、libwebp 等许可） | 否 | 保留版权+许可文本；捆绑库的声明见其 LICENSE | `pillow-11.1.0.dist-info\LICENSE`（56 KB 合集）；`License: MIT-CMU` |
| **SciPy** | 1.15.2 | BSD-3-Clause（含捆绑 OpenBLAS、ARPACK、Qhull、pocketfft 等） | 否 | 保留版权+许可文本 | `scipy-1.15.2.dist-info\LICENSE.txt` |
| **tifffile** | 2025.5.10 | BSD-3-Clause | 否 | 保留版权+许可文本 | `tifffile-2025.5.10.dist-info\licenses\LICENSE`；`License: BSD-3-Clause` |
| **PyYAML** | 6.0.2 | MIT | 否 | 保留版权+许可文本 | `PyYAML-6.0.2.dist-info\LICENSE`；`License: MIT` |
| **PySide6_Essentials** | 6.12.0 | **LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only** → 本项目选 **LGPLv3** | **是（弱 copyleft，仅 Qt 自身）** | 动态链接可替换；随附 LGPLv3+GPLv3 全文；显著声明使用了 Qt/LGPLv3；保留 Qt 版权声明 | `pyside6_essentials-6.12.0.dist-info\METADATA` 第 6 行 `License:`；实测 Qt 6.12.0 |
| **shiboken6** | 6.12.0 | 同上（LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only） | 是（弱） | 同 PySide6（随附声明与全文） | `shiboken6-6.12.0.dist-info\METADATA` 第 6 行 |

> 说明：以上「安装位置」中 numpy/h5py/matplotlib/pillow/scipy/pyyaml 实际位于基础解释器 `<python>\Lib\site-packages`（venv 为 system-site-packages 形态），PySide6/shiboken6/tifffile 位于 venv。分发时应以**打包产物实际包含的版本**复核一遍（检查清单 C-08）。

### 2.2 构建/开发期依赖（**不随软件分发**，但打包工具产物会进安装包）

| 组件 | 版本 | 许可证 | 是否分发 | 说明 |
|---|---|---|---|---|
| PyInstaller | 6.21.0 | **GPL-2.0-or-later with a special exception**（允许用其构建并分发非自由程序） | 打包器本身不分发；其 **bootloader 会嵌入最终 exe** | 必须在 `THIRD_PARTY_NOTICES.md` 声明并附 `docs/licenses/build/pyinstaller-GPLv2-with-exception-COPYING.txt` |
| Nuitka | 2.6.9 | Apache-2.0 | 打包器不分发（C 编译产物属用户代码） | 若采用 Nuitka 打包，随附 Apache-2.0 声明 |
| pytest / ruff | 9.1.1 / 0.12.7 | MIT | 否 | 仅开发环境 |

### 2.3 可选依赖（默认不装，启用前必须另行审计）

| 组件 | 声明位置 | 许可证 | 状态 |
|---|---|---|---|
| netCDF4 | `pyproject.toml` `[nc3]` | 待确认（上游 MIT 系；捆绑的 HDF5/netCDF-C 需逐一核对） | 未安装，未验证 → 待确认（§7-Q4） |
| pyproj | `pyproject.toml`（satpy 额外带入） | MIT（PROJ 本体 MIT/X，PROJ 数据公共领域） | 随 satpy 安装，见下 |
| **satpy** | `pyproject.toml` `[satpy]` | **GPL-3.0-or-later** | 可选后端，**默认不装**；已实测 36 项测试 |
| **pyspectral** | 同上（satpy reader 依赖） | **Apache-2.0** | 随 satpy 安装 |
| **trollimage** | satpy 依赖 | **GPL-3.0-or-later** | 随 satpy 安装 |
| **python-geotiepoints** | satpy 依赖 | **GPL-3.0-or-later** | 随 satpy 安装 |
| **pyresample** | satpy 依赖 | **LGPL-3.0-or-later** | 随 satpy 安装 |

#### 2.3.1 satpy 的许可证结论（已核实，非推测）

- **satpy 是 GPLv3+**：`satpy-0.59.0.dist-info/METADATA` 第 6 行 `License: GPLv3`，
  并有 `Classifier: License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)`。
- 本项目是 **AGPL-3.0-only**。GPLv3 §13 与 AGPLv3 §13 是**互为镜像**的条款：
  两者都明确允许把「另一个」许可证的作品链接/合并成单一作品，合并后的整体按 AGPLv3 分发。
  因此 **GPLv3 依赖可以进 AGPLv3 项目**，不构成冲突。
- 但这带来两个实际约束，必须遵守：
  1. **satpy 只能是可选依赖**，不能进主依赖。原因不是许可，而是它会把
     xarray / dask / zarr / pyresample / pyproj / pyspectral 一并拉进来
     （隔离安装实测 **370.2 MB / 13,009 个文件**，`import satpy` 冷启动 **1.98 s**）。
     实测 `import fysat.readers` 仍是 0.33 s，且**不会加载 satpy**。
  2. 一旦发布带 satpy 的构建，**LICENSE 与 THIRD_PARTY_NOTICES 必须同时列出**
     satpy / trollimage / python-geotiepoints 的 GPLv3 全文与 pyspectral 的 Apache-2.0 全文，
     并且整体仍按 AGPLv3 分发。
- 实测数据来源：`analysis/satpy_evaluation.md` §1（含 METADATA 原文行号与逐包核查表）。

### 2.4 随依赖二进制捆绑的原生库（间接依赖，随打包产物分发）

| 原生库 | 来源包 | 许可证 | 处理 |
|---|---|---|---|
| OpenBLAS（`libscipy_openblas*.dll`） | numpy 2.2.4 / scipy 1.15.2 | BSD-3-Clause | 已含于 numpy/scipy LICENSE 全文，注明即可 |
| HDF5（`hdf5.dll`、`hdf5_hl.dll`）、zlib（`z.dll`） | h5py 3.16.0 | HDF5 BSD 系 + zlib | 正文附 `docs/licenses/components/hdf5-LICENSE.txt` 与 h5py LICENSE |
| LZF filter | h5py | BSD-3（Andrew Collette） | `h5py-lzf-LICENSE.txt` |
| libjpeg-turbo / zlib / libtiff / FreeType / OpenJPEG / lcms2 / libwebp 等 | Pillow 11.1.0 | 各自宽松许可（IJG/zlib/libpng/FTL/MIT/BSD） | Pillow LICENSE 文件已完整收录，随附该文件即可 |
| DejaVu 字体 | matplotlib | Bitstream Vera License | `components/matplotlib-LICENSE_DEJAVU.txt` |
| STIX 字体 | matplotlib | SIL OFL 1.1 | `components/matplotlib-LICENSE_STIX.txt` |
| Mesa 软件 OpenGL（`opengl32sw.dll`） | PySide6 wheel | MIT（Mesa 惯例许可，随 wheel 未附文本） | ⚠️ 待确认：从 Qt 安装目录/源码补齐 Mesa 版权声明（§7-Q6） |
| libyaml（PyYAML `_yaml` 扩展） | PyYAML | MIT | PyYAML LICENSE 已覆盖（同一作者 MIT） |
| CPython 运行时（若打包解释器） | <python> | PSF-2.0 | `docs/licenses/runtime/python-PSF-LICENSE.txt` |
| OpenSSL / libffi / zlib / liblzma / SQLite 等 CPython 捆绑库 | 打包后的 Python 运行时 | Apache-2.0 / MIT / zlib / public-domain / public-domain | 打包时用 `pip-licenses` 或 PyInstaller `--collect` 清单复核并补入（检查清单 C-09） |

### 2.5 数据与底图

| 资产 | 位置 | 许可/条款 | 处理 |
|---|---|---|---|
| Natural Earth 1:110m 海岸线 | `assets/ne_110m_coastline.geojson` | **公有领域**（Natural Earth Terms of Use：可任意使用，无需署名；建议引用 "Made with Natural Earth"） | 已核实，THIRD_PARTY_NOTICES 注明来源即可 |
| FY 卫星样例/派生数据 | `samples/`、`out/` | NSMC（国家卫星气象中心）分发产品，**再分发条款待确认** | 若随包分发样例数据，须先确认 NSMC 数据使用政策（§7-Q3）；否则从发布包中剔除 |

---

## 3. PySide6 + Qt 6 的 LGPLv3 合规清单（核心）

### 3.1 先回答：为什么 Python wheel 形态天然满足「动态链接」

- PySide6 的 Python 绑定层 `PySide6/QtCore.pyd` 等是扩展模块，Qt 实现位于**独立的动态库** `PySide6/Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll` 等（实测 76 个 `Qt6*.dll`），运行时由 Windows 加载器按名加载。
- 用户/下游可以**直接替换** `PySide6\Qt6*.dll`（或用自己编译的同 ABI 版本整体替换 `PySide6` 包），无需重新编译我们的代码 → 符合 LGPLv3 §4(d)(1)「suitable shared library mechanism」的实质要求（运行时使用独立库、可与接口兼容的修改版库协同工作）。
- 所以我们**不采用**静态链接，也**不采用** `PyInstaller --onefile` 把 Qt 库塞进单一可执行体的做法作为默认发布形态（`--onedir` + 独立 DLL 可用；`--onefile` 若仍以独立文件解压到临时目录，也可解释为可替换，但审计与用户替换体验差，建议 `--onedir`）。

### 3.2 LGPLv3 义务 → 我们的落实方式（逐条）

| # | LGPLv3 义务（条款） | 我们怎么做 | 状态/证据 | 责任 |
|---|---|---|---|---|
| L-01 | 显著声明使用了 Qt 库，且该库及其使用受 LGPLv3 覆盖（§4(a)） | ① 安装包内 `THIRD_PARTY_NOTICES.md`；② 软件「关于/About」对话框增加「第三方组件」页，展示 Qt/PySide6 版本 + LGPLv3 声明 + 源码地址；③ 官网/文档页同步 | 文本模板：`docs/licenses/Qt_PySide_NOTICE.md` | 发布负责人 |
| L-02 | 随附 **LGPLv3 全文** 与 **GPLv3 全文**（§4(b)，LGPLv3 以 GPLv3 为基础） | `docs/licenses/LGPL-3.0.txt`、`docs/licenses/GPL-3.0.txt` 随包分发（另备 GPL-2.0 供 Qt 备选许可说明） | 已落地（本目录） | 发布负责人 |
| L-03 | 保留 Qt 的版权声明（§4(c)；若库运行期显示版权信息则须展示） | `THIRD_PARTY_NOTICES.md` 声明：`Copyright (C) The Qt Company Ltd. and other contributors.`（取自 Qt6Core.dll 版本信息）；About 对话框列出 | 已核实 DLL 版本信息 | 发布负责人 |
| L-04 | 允许用户替换/重新链接 Qt 库（§4(d)(1)） | ① 动态链接（独立 DLL）；② **不**做 DLL 签名校验/自校验锁死；③ **不**把 Qt 静态编译进 exe；④ 安装包不阻止用户覆盖 `PySide6\Qt6*.dll`；⑤ 发布说明中写明替换方法 | `docs/licenses/Qt_PySide_NOTICE.md` §4 提供替换步骤 | 开发+发布 |
| L-05 | 若修改 Qt 源码，须以 LGPLv3 公开修改（§4 及 §2） | **本项目不修改 Qt/PySide6 源码**（仅使用官方 PyPI wheel）→ 该条不触发；禁止私自 patch Qt DLL | 版本锁定 `PySide6-Essentials==6.12.0` | 全员 |
| L-06 | 不得对 LGPLv3 库的使用附加额外限制（§4 末段/§10） | 附加条款**仅 §7(b)(c)**，只约束本程序材料与署名，不约束 Qt；数据条款明确排除第三方组件 | 见 §1.2.4；`FYSAT-ADDITIONAL-TERMS.md` 第 3 条 | 法务 |
| L-07 | 若以「目标代码 + 用户产品（User Product）」形式分发，须提供安装信息（§4(d)(0) 备选分支 / GPLv3 §6） | 常规 Windows 桌面软件非「User Product」，不触发；**若将来做硬件一体机/锁定设备发布，须重新评估并提供 Installation Information** | 列为条件项 | 发布负责人 |
| L-08 | 提供「最小对应源码」的获取途径（若走 §4(d)(0) 分支）；无论走哪支，都应提供 PySide6/Qt 源码地址 | 我们走 §4(d)(1) 共享库分支；同时在 NOTICE 中给出 PySide6 源码仓库与 Qt 源码下载地址（含 6.12.0 tag） | `docs/licenses/Qt_PySide_NOTICE.md` §3 | 发布负责人 |
| L-09 | 不得用 GPL-only 模块（否则整体变 GPLv3，见 §4.2） | 建立模块白名单（§4.1）+ 代码评审规则 + 自动化检查 `import PySide6.Qt*` 白名单 | `pyproject` 已锁定 `PySide6-Essentials==6.12.0`；`tests/test_license_compliance.py` 已固化白名单/无 PyQt 检查 | 开发 |
| L-10 | 不得静态链接 Qt 或捆绑 GPL 组件 | 打包使用 `--onedir` 动态分发；打包脚本黑名单剔除 §4.3 所列 GPL-only 文件 | 打包脚本待实现（检查清单 C-06） | 开发 |
| L-11 | 分发时向用户提供我们的 AGPL 源码（AGPL §13 与本项目许可要求） | 安装包附「获取源码」链接/书面要约；源码仓库公开；网络服务场景（如未来有）在服务界面提供源码入口 | 检查清单 C-02/C-03 | 发布负责人 |
| L-12 | About 对话框/文档展示 **Qt 版权 + LGPLv3 + 可替换说明**（与 L-01/L-03 合并实现） | 见上 | 待实现 | 开发 |

### 3.3 用户「替换 Qt」的具体做法（写进发布说明，满足 L-04）

1. 关闭 FY-Sat Studio。
2. 自行编译/下载接口兼容的 Qt 6.12.x 动态库（or 修改版），或准备修改后的 `PySide6` 包。
3. 覆盖安装目录下 `PySide6\Qt6*.dll`（或整体替换 `PySide6` 目录）；若替换后 ABI 不兼容导致无法启动，可回滚。
4. 我们**不校验、不锁定** Qt DLL 的哈希/签名；不要求联网验证；不把 Qt 库封装进不可解包的单一文件（默认 `--onedir`）。

### 3.4 About 对话框所需声明文本（可直接使用）

> 本软件使用 **Qt 6.12.0** 与 **PySide6 6.12.0**，依据 **GNU Lesser General Public License v3 (LGPLv3)** 使用，版权归 The Qt Company Ltd. 及其他贡献者所有。LGPLv3 全文见安装目录 `docs/licenses/LGPL-3.0.txt`，Qt/PySide6 源代码可从 https://code.qt.io/cgit/pyside/pyside-setup.git/ 与 https://download.qt.io/ 获取。您有权修改并替换随附的 Qt 库（方法见发布说明）。

英文版：

> This software uses **Qt 6.12.0** and **PySide6 6.12.0** under the **GNU Lesser General Public License v3 (LGPLv3)**. Copyright (C) The Qt Company Ltd. and other contributors. The LGPLv3 text is included at `docs/licenses/LGPL-3.0.txt`. Qt/PySide6 source code is available from https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://download.qt.io/. You may modify and replace the bundled Qt libraries as described in the release notes.

---

## 4. Qt 6 模块许可：白名单与黑名单

> 依据：Qt 官方文档各模块页的 "Licenses" 小节（doc.qt.io/qt-6，2026-11-02 抓取）+ Qt 源码仓库 `LICENSES/` 目录（GitHub `qt/*`，`dev` 分支）。抽取结果见 §8 证据表。Qt 整体授权页明确：**「For open-source licensed Qt, some specific parts (modules) are not available under the GNU LGPL version 3, but under the GNU General Public License (GPL) instead.」**（https://doc.qt.io/qt-6/licensing.html）

### 4.1 白名单：LGPLv3 可用模块（可放心使用）

以下模块均为 **LGPLv3 / GPLv2 / GPLv3 / 商业** 四选一，我们按 LGPLv3 + 动态链接使用：

| 模块 | 用途 | 文档（授权见页内 Licenses 节） |
|---|---|---|
| Qt Core | 核心对象/事件/线程 | https://doc.qt.io/qt-6/qtcore-index.html |
| Qt GUI | 窗口系统/绘图/字体 | https://doc.qt.io/qt-6/qtgui-index.html |
| Qt Widgets | 桌面控件（**主 GUI 使用**） | https://doc.qt.io/qt-6/qtwidgets-index.html |
| Qt Network | 网络 | https://doc.qt.io/qt-6/qtnetwork-index.html |
| Qt OpenGL / OpenGLWidgets | OpenGL 视图 | https://doc.qt.io/qt-6/qtopengl-index.html |
| Qt Svg / SvgWidgets | SVG 图标 | https://doc.qt.io/qt-6/qtsvg-index.html |
| Qt Sql | SQLite 等 | https://doc.qt.io/qt-6/qtsql-index.html |
| Qt Xml | XML | https://doc.qt.io/qt-6/qtxml-index.html |
| Qt Test / Qt Quick Test | 单元测试 | https://doc.qt.io/qt-6/qttest-index.html |
| Qt Concurrent | 并发 | https://doc.qt.io/qt-6/qtconcurrent-index.html |
| Qt DBus | Linux 集成 | https://doc.qt.io/qt-6/qtdbus-index.html |
| Qt Help | 帮助系统 | https://doc.qt.io/qt-6/qthelp-index.html |
| Qt PrintSupport | 打印/导出 PDF | https://doc.qt.io/qt-6/qtprintsupport-index.html |
| Qt Qml / Qt Quick / Quick Controls 2 / Quick Widgets / Quick Layouts / Quick Dialogs | QML 界面（当前未用，可用） | https://doc.qt.io/qt-6/qtquick-index.html |
| Qt UI Tools | 加载 .ui 文件 | https://doc.qt.io/qt-6/qtuitools-index.html |
| Qt Widgets Designer（库部分） | 设计器集成（当前未用） | https://doc.qt.io/qt-6/qtdesigner-index.html（`qttools` 仓库含 LGPL 许可文件） |
| Qt Labs StyleKit | 主题色（当前未用） | https://doc.qt.io/qt-6/qtlabsstylekit-index.html |
| Qt PDF | PDF 渲染（当前未用） | https://doc.qt.io/qt-6/qtpdf-index.html |
| Qt Multimedia / WebSockets / WebChannel / TextToSpeech / StateMachine / Sensors / SerialPort / SerialBus / RemoteObjects / Scxml / Positioning / Location / WebView / Nfc / Bluetooth / SpatialAudio / Image Formats / TaskTree / OpenAPI | 其他 LGPL 模块（按需） | 见 §8 证据表 |

### 4.2 黑名单：GPLv3-only / 商业-only 模块（**本项目禁止使用**）

**GPLv3-only（有 GPLv3 与商业授权，没有 LGPL 选项）——用了就等于把整个软件拖入 GPLv3：**

| # | 模块 | 授权（官方原文摘要） | 官方文档 |
|---|---|---|---|
| B-01 | **Qt Charts** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtcharts-index.html |
| B-02 | **Qt Data Visualization** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtdatavisualization-index.html |
| B-03 | **Qt Graphs** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtgraphs-index.html |
| B-04 | **Qt Virtual Keyboard** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtvirtualkeyboard-index.html |
| B-05 | **Qt Quick 3D** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtquick3d-index.html |
| B-06 | **Qt Quick 3D Physics** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtquick3dphysics-index.html |
| B-07 | **Qt Quick Timeline** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtquicktimeline-index.html |
| B-08 | **Qt Lottie Animation** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtlottieanimation-index.html |
| B-09 | **Qt Network Authorization** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtnetworkauth-index.html |
| B-10 | **Qt CoAP** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtcoap-index.html |
| B-11 | **Qt MQTT** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtmqtt-index.html |
| B-12 | **Qt HTTP Server** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qthttpserver-index.html |
| B-13 | **Qt GRPC** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtgrpc-index.html |
| B-14 | **Qt Qml Compiler / QML Script Compiler** | commercial + **GNU GPLv3 with Qt GPL exception 1.0** | https://doc.qt.io/qt-6/qtqmlcompiler-index.html |
| B-15 | **Qt Canvas Painter（runtime library）** | commercial + **GNU GPLv3** | https://doc.qt.io/qt-6/qtcanvaspainter-index.html |
| B-16 | **Qt Wayland Compositor**（compositor 部分） | GPLv3；其 integration plugin 为 LGPL/GPLv2 | https://doc.qt.io/qt-6/qtwaylandcompositor-index.html |

**商业-only（不属于开源提供范围，开源构建不可用）：**

| # | 模块 | 说明 | 来源 |
|---|---|---|---|
| C-01 | Qt Commercial Modules（如 Qt Safe Renderer、Qt for Device Creation/Boot to Qt、Qt Design Studio 商业版等） | 官方原文：**"Qt Commercial Modules are available under a commercial license. They are not part of the Qt open source offering, and are not available under the Qt open source license."** | https://doc.qt.io/qt-6/qtmodules.html |

> ⚠️ 例外说明：**Qt 工具**（`moc`/`uic`/`rcc`/`designer`/`linguist`/`lupdate`/`lrelease` 等）授权为 **GPLv3 + Qt GPL Exception 1.0**（例外允许其「输出」自由使用，以及以自选条款组合插件）。工具不是库，用于构建/辅助不污染应用；但**工具本身随包分发时仍属 GPLv3 代码**，见 §4.3 剪裁建议。例外全文：`docs/licenses/Qt-GPL-exception-1.0.txt`。

### 4.3 ⚠️ 实测风险：PySide6-Essentials 6.12.0 wheel 内含 GPL-only 构件

审计中发现，虽然 `PySide6-Essentials` 的 METADATA 声明整体为 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`，但 wheel 里**实际捆绑了 GPLv3-only 模块的二进制与 QML 插件**。原样打包 = 分发 GPLv3 代码。

| 类 | 实测文件（`<venv>\Lib\site-packages\PySide6\`） | 许可证 | 是否被我们的代码使用 |
|---|---|---|---|
| Qt Lottie Animation | `Qt6Lottie.dll`、`Qt6LottieVectorImageGenerator.dll`、`Qt6LottieVectorImageHelpers.dll` | **GPLv3-only** | 否（无 Python 绑定，无 import） |
| Qt Quick Timeline | `Qt6QuickTimeline.dll`、`Qt6QuickTimelineBlendTrees.dll`、`qml\QtQuick\Timeline\qtquicktimelineplugin.dll`、`...timelineblendtreesplugin.dll` | **GPLv3-only** | 否 |
| Qt Virtual Keyboard | `qml\QtQuick\VirtualKeyboard\**`（`qtvkbplugin.dll`、`qtvkbcomponentsplugin.dll`、`qtvkblayoutsplugin.dll`、`qtvkbpluginsplugin.dll`、`qtvkbstylesplugin.dll`、`qtvkbbuiltinstylesplugin.dll`、`qtvkbhangulplugin.dll`、`qtvkbopenwnnplugin.dll`、`qtvkbpinyinplugin.dll`、`qtvkbtcimeplugin.dll`、`qtvkbthaiplugin.dll`、`qtvkbsettingsplugin.dll`、`virtualkeyboardplugin.dll` 及 QML） | **GPLv3-only** | 否 |
| Qt Qml Compiler | `Qt6QmlCompiler.dll` | **GPLv3 with Qt GPL exception 1.0** | 否（QtQml 运行期不强制依赖；但删除前须做启动自测） |
| Qt 命令行工具 | `designer.exe`、`assistant.exe`、`linguist.exe`、`lupdate.exe`、`lrelease.exe`、`uic.exe`、`rcc.exe`、`svgtoqml.exe`、`qmlcachegen.exe`、`qmlformat.exe`、`qmlimportscanner.exe`、`qmllint.exe`、`qmlls.exe`、`qmltyperegistrar.exe` | **GPLv3 + Qt GPL Exception 1.0** | 否 |

**处置方案（三选一，推荐 A）：**

| 方案 | 做法 | 优点 | 缺点/风险 |
|---|---|---|---|
| **A（推荐）** | 打包时按「GPL-only 剪裁清单」删除上表文件；保留 QtCore/QtGui/QtWidgets/QtNetwork/QtSvg/QtSql/QtXml 等 LGPL 模块 | 维持纯 LGPLv3 路线，审计清晰 | 需自测（删除 QmlCompiler 后 QtQml 功能可能受影响——我们不用 QML，可接受） |
| B | 原样分发 wheel，同时按 GPLv3 履行义务（提供 GPLv3 源码/要约） | 省事 | 安装包变成「AGPL + GPLv3 混合」，商业/合规复杂度上升，且与附加条款潜在冲突 |
| C | 不打包 PySide6，要求用户自行 `pip install PySide6-Essentials==6.12.0` | 不分发 Qt，义务最轻 | 用户体验差；仍需在文档声明 LGPL 使用 |

> 剪裁清单与自测步骤已写入检查清单 C-06。wheel 文件清单可由打包脚本/文件枚举工具重复生成；每次升级 PySide6 版本必须重新核对本表（模块归属可能变化）。

---

## 5. GPL 污染排除性检查（现状结论）

### 5.1 源码扫描结果：✅ 未发现 GPL 组件

| 检查项 | 方法 | 结果 |
|---|---|---|
| 是否有 `PyQt5 / PyQt6 / sip` 导入 | 全仓库 grep `PyQt\|pyqt\|sip` | ✅ 0 处（仅 `PLAN.md` 历史选型记录提到 PyQt5 被排除） |
| GUI 使用哪些 Qt 模块 | grep `PySide6` | ✅ 仅 `from PySide6 import QtCore, QtGui, QtWidgets`（`gui/app.py` 为延迟导入），均在 LGPLv3 白名单 |
| 是否使用 Qt Charts / Quick3D / VirtualKeyboard 等黑名单模块 | grep 模块名 | ✅ 未使用（wheel 内文件见 §4.3，属打包问题不是代码问题） |
| 是否静态链接 Qt / 自编译 Qt | 无 C++ 构建、无 qt.conf 自定义 | ✅ 纯 PyPI wheel 动态链接 |
| 是否有 GPL 代码被复制进 `src/` | 抽查读者层/算法层，无第三方源码拷贝 | ✅ 未见（建议发布前跑一次 `scancode`/`pip-licenses` 复核） |

### 5.2 matplotlib 的 Qt 后端（✅ 已处理）

- **风险原理（保留记录）**：matplotlib 3.10.1 的 `backends/qt_compat.py` 选择顺序为「已导入的 PyQt6 → PySide6 → PyQt5 → PySide2 → `QT_API` 环境变量 → rcParams」（L34–63）。若环境中存在 **PyQt6/PyQt5（GPL）** 且被优先导入，matplotlib 会选中它，导致 GUI 进程内加载 GPL 绑定 → 实质 GPL 污染。
- **已实施的硬控制（2026-11-02）**：`src/fysat/gui/app.py::_force_pyside6_backend()` 在导入 `matplotlib.pyplot` **之前**执行：
  - `os.environ.setdefault("QT_API", "pyside6")`
  - `matplotlib.use("QtAgg", force=True)`
- **剩余要求**：打包产物不得包含 PyQt5/PyQt6/PySide2（检查清单 C-05/C-07）；`tests/test_license_compliance.py::test_app_forces_pyside6_matplotlib_backend` 已固化该检查。
- **现状**：✅ 代码层已锁死（若用户自行在导入我们的 app 之前强制 import PyQt 并绕过入口，属用户自担行为，不是我们的分发义务）。

### 5.3 PySide6 安装形态风险（✅ 已处理）

- **风险原理（保留记录）**：PyPI 的 `PySide6` 元包 = `PySide6-Essentials` + **`PySide6-Addons`**；Addons 含 **Qt Charts、Qt Data Visualization、Qt Graphs、Qt Quick 3D、Qt Virtual Keyboard、Qt NetworkAuth、Qt PDF、Qt WebEngine** 等大量 GPL-only/高义务模块，直接 `pip install PySide6` 会把它们带进环境。
- **已实施的硬控制（2026-11-02）**：`pyproject.toml` 已改为 `gui = ["PySide6-Essentials==6.12.0"]`，并附注释明确「**绝不要写成 `PySide6`**」；`license = { text = "AGPL-3.0-only" }` 已声明。
- **剩余要求**：发布打包时确认未安装 `PySide6-Addons` / PyQt（`pip check` + 文件清单审计，C-05）；wheel 内 GPL-only 构件剪裁见 §4.3 / C-06。
- PySide6 6.12 还提供 **GPL-2.0-only** 备选分支（历史版本常见 LGPLv3/GPLv3/商业）；我们只主张 **LGPLv3** 分支，其他分支不使用、不依赖。

### 5.4 打包工具

| 工具 | 许可 | 结论 |
|---|---|---|
| PyInstaller 6.21.0 | GPLv2-or-later **with special exception**（允许构建并分发非自由程序） | ✅ 可用；但须随包附 `COPYING.txt`，并在 NOTICE 中声明；其 embedded bootloader 属 GPLv2 代码 |
| Nuitka 2.6.9 | Apache-2.0 | ✅ 可用（若采用） |
| cx_Freeze / 其他 | 未安装 | 采用前先审计 |

### 5.5 借鉴第三方实现（SatDump 等 GPL/其他项目）的合规政策

> 背景：本项目图像合成的实现思路需参考 **SatDump**（GPL-3.0-or-later，含 lzh173/SD-ZH 中文化 fork）。本节给出结论与操作规则，适用于所有「参考他项目实现」的场景。

**① 许可证层面：GPLv3 与我们的 AGPL-3.0-only 可以合并**
- **AGPLv3 §13 第 2 段**（`docs/licenses/AGPL-3.0.txt` L190）：`you have permission to link or combine any covered work with a work licensed under version 3 of the GNU General Public License into a single combined work, and to convey the resulting work.`
- **GPLv3 §13**（`docs/licenses/GPL-3.0.txt` L182-183）：镜像条款，同样允许合并。
- 结论：即使直接把 SatDump 的 GPLv3 代码并入本项目，也**合法**（GPL 部分保持 GPLv3，本项目部分保持 AGPL），无需闭源风险；与 `analysis/satpy_evaluation.md` §1 对 satpy（GPLv3）的结论一致。

**② 「只取思路」比「抄代码」更安全，且通常更实用**

| 维度 | 说明 |
|---|---|
| 著作权保护对象 | 保护**表达**（代码、结构、注释、脚本），**不保护**思想、算法、数学公式、操作方法。真彩色合成 = 逐通道拉伸 + 白平衡 + 饱和增强，属物理/数学范畴，不构成侵权 |
| 语言差异 | C++ → Python 本身排除逐字复制；残余风险仅为「结构/顺序组织的实质相似」 |
| 留痕建议 | 参考时记录**概念**（波段组合、拉伸区间、阈值、公式），不保留 C++ 片段；必要时在 `analysis/` 下记一份来源与学习记录，作为将来举证材料 |

**③ 三条红线（真正会出事的）**

| 级别 | 禁止事项 | 说明 |
|---|---|---|
| 🔴 P0 | **复制 SatDump `resources/` 下的第三方资产** | 这些资产**不受 GPL 覆盖**，各有独立授权链：`resources/lut/goes/abi/wxstar/`（Harry Dove-Robinson 设计，见其 README）、`resources/fy2/svissr/LUT.png`（@eswnl 的 FY-2x_CLUT，README 注明「with permission」——**该许可是给 SatDump 的，不自动延伸到我们**）、`WXtoImg-*.png`（WXtoImg 遗留色表）。要使用须**逐项取得原作者许可**并在 `docs/licenses/components/` 留存证据 |
| 🔴 P0 | **复制 `resources/scripted_compos/*.lua`、合成表达式 JSON/配置** | Lua 脚本与 muParser 表达式属**可版权表达**，不是思想 |
| 🟡 P1 | **若确实引入 GPLv3 代码却未留痕** | GPLv3 §5 要求：显著标注修改（a）、声明整体按本许可发布（b）、整体按 GPL 授权（c）；同时须在 `THIRD_PARTY_NOTICES.md` 登记 |

**④ 本项目现状（2026-11-04 核查，合规）**

| 检查项 | 结果 |
|---|---|
| `src/` 中是否含 SatDump 代码或引用 | ✅ **0 处**（全仓库仅 `PLAN.md` 一句「不做射频接收，属 SatDump 范畴」，属范围划界，非引用） |
| `composites/composites.yml`、`bands.yml` 来源 | ✅ 头部逐条标注 NSMC 说明书与 HDF5 属性（`Effect_Center_WaveLength`、`band_name`），来源可追溯 |
| `render.composite()` 架构 | ✅ 三通道合并分位数统一拉伸（`shared_range`）；SatDump 为 muParser 逐像素表达式求值 —— **架构不同**，不构成实质相似 |
| `palettes.py` 色表 | ✅ `IR_ENHANCED_STOPS` 为自研 8 段色表，非 SatDump `resources/lut/` 资产 |
| `pipeline.py` 注释「移植自参考实现 fy3f_mersi_l1.py」 | ✅ 该文件为**本项目作者自有脚本**（`2026-10-31\fy3f_mersi3_l1\fy3f_mersi_l1.py`，docstring 声明依据 NSMC《FY-3F MERSI-III L1 产品使用说明》），不涉第三方许可 |
| 是否使用 SatDump 的 LUT/Lua/配置资产 | ✅ **0 处** |

**⑤ 判据速查（团队执行用）**

> 只读**算法与物理原理**（波段组合、公式、阈值、参数）→ ✅ 安全，记录概念即可
> 复制**代码/脚本/配置文件** → 在 AGPL 项目中合法，但须按 GPLv3 §5 留痕并登记 NOTICE
> 复制 `resources/` 里的**图片/LUT/色表** → 🚫 停止，逐项核实原作者授权

---

### 5.6 自动化合规测试（已上线）

`tests/test_license_compliance.py` 已把本文件的硬约束固化为自动测试（任何一项失败即视为可能引入 GPL 污染，禁止发布）：

| 测试 | 校验内容 | 状态（2026-11-02 实测） |
|---|---|---|
| `test_no_pyqt_anywhere` | 源码无 `PyQt5/PyQt6/sip` 导入 | ✅ 通过 |
| `test_no_gpl_only_qt_modules_in_source` | 无 GPLv3-only Qt 模块导入（Charts / DataVisualization / Graphs / VirtualKeyboard / Quick3D / Quick3DPhysics / QuickTimeline / Lottie / NetworkAuth / Coap / Mqtt / HttpServer / Grpc / QmlCompiler / CanvasPainter 等） | ✅ 通过 |
| `test_only_whitelisted_qt_modules_imported` | 实际 import 的 PySide6 模块 ∈ LGPL 白名单 | ✅ 通过 |
| `test_pyproject_declares_essentials_not_full_pyside6` | `gui` 依赖必须是 `PySide6-Essentials`，禁止裸 `PySide6` | ✅ 通过（此前的正则缺陷已由 Lead 于 2026-11-02 修复） |
| `test_license_declared` | `pyproject` 声明 `AGPL-3.0-only` | ✅ 通过 |
| `test_license_files_present` | `LICENSES.md`、`THIRD_PARTY_NOTICES.md` 存在 | ✅ 通过（建议后续扩展为校验 `LICENSE` / `docs/licenses/`，非阻塞） |
| `test_runtime_has_no_gpl_qt_module_loaded` | 运行时未加载 GPL-only Qt 模块 | ✅ 通过 |
| `test_app_forces_pyside6_matplotlib_backend` | `app.py` 强制 `QT_API=pyside6` | ✅ 通过 |

> 运行方式：`<venv>\Scripts\python.exe -m pytest tests/test_license_compliance.py -q`。
> 2026-11-02 实测结果：`tests/test_license_compliance.py` + `tests/test_provenance.py` 共 **21 项全部通过**（此前的测试正则缺陷已由 Lead 修复）。

---

## 6. 分发前检查清单（Checklist，含当前状态）

> 建议复制本表到发布 PR/Release Issue，逐项确认。P0 = 不满足即不得发布。「状态」列为 2026-11-02 定的当前进展。

| ID | 级别 | 检查项 | 验收标准 | 状态（2026-11-02） | 负责人 |
|---|---|---|---|---|---|
| C-01 | P0 | 根目录 `LICENSE` 存在且含 AGPL-3.0 全文 | AGPL 全文与 `docs/licenses/AGPL-3.0.txt` 逐字一致，且含附加条款指引 | ✅ **已处理**（`LICENSE` 36.4 KB，已含全文+指引） | 发布 |
| C-02 | P0 | 安装包内包含 `LICENSE`、`LICENSES.md`、`THIRD_PARTY_NOTICES.md`、`docs/licenses/` 全套 | 文件清单核对 | ⬜ 发布时执行 | 发布 |
| C-03 | P0 | 提供 AGPL 源码获取途径（AGPL §13） | 安装包/官网/About 均有源码 URL 或书面要约；源码仓库可公开访问 | ⬜ 发布时执行 | 发布 |
| C-04 | P0 | About 对话框含 Qt/PySide6 LGPLv3 声明、AGPL 声明与 Qt 替换说明 | §3.4 文本已上屏 | ⬜ 待实现 | 开发 |
| C-05 | P0 | 打包依赖为 `PySide6-Essentials==6.12.0`，**未安装 PySide6-Addons/PyQt** | `pyproject.toml` 已锁定；发布前 `pip list` 留档 + `pip check` 通过 | ✅ **已处理**（pyproject）；发布前复核 | 开发 |
| C-06 | P0 | 按 §4.3 剪裁 wheel 内 GPL-only 文件（或书面申请方案 B） | 剪裁后 `PySide6` 目录无 Lottie/QuickTimeline/VirtualKeyboard/QmlCompiler/工具 exe；启动+打开样例自测通过 | ⬜ 打包时执行 | 开发 |
| C-07 | P0 | `QT_API=pyside6` 在导入 matplotlib 前设置；打包产物无 PyQt | `app.py::_force_pyside6_backend()` 生效 + 产物扫描 | ✅ **已处理**（代码层已锁死） | 开发 |
| C-08 | P0 | 以**打包产物实际包含的版本**重跑依赖清单（版本可能与开发环境不同） | 生成 `pip freeze` / SBOM 附在发布物中 | ⬜ 发布时执行 | 发布 |
| C-09 | P1 | 打包运行时（Python/OpenSSL/libffi/zlib 等）的许可证全文已补齐 | `docs/licenses/runtime/` 与 `build/` 更新 | ⬜ 打包时执行 | 发布 |
| C-10 | P1 | PyInstaller `COPYING.txt` 随附并在 NOTICE 声明 | 文件存在 | ⬜ 打包时执行 | 发布 |
| C-11 | P0 | 安装包**不得**包含 `out/`、`scratch/`、`.pytest_cache`、`__pycache__`、`samples/` 中的 NSMC 数据（除非已确认数据再分发条款） | 打包文件清单审计 | ⬜ 发布时执行 | 发布 |
| C-12 | P1 | 模块白名单自动化检查：`import PySide6.Qt*` 必须命中白名单 | `tests/test_license_compliance.py` 全绿 | ✅ **已上线（全绿）** | 开发 |
| C-13 | P1 | 升级任何依赖后重跑本审计（尤其 PySide6/Qt 小版本可能改变模块许可归属） | 本文件 §2/§4 更新记录 | ⬜ 持续执行 | 合规 |
| C-14 | P1 | 数据署名在导出功能中落地（元数据写入） | 导出 PNG/TIFF 带 `software/version/source_url/modified/commit/generated_at` | ✅ **技术层已实现**（`provenance.py` 默认写入）；数据条款文本待法务 | 开发+法务 |
| C-15 | P1 | 附加条款已按 §7(b)(c) 定稿；书面向法务确认 | `FYSAT-ADDITIONAL-TERMS.md` + 法务书面意见 | ✅ **已决策/正文就绪**；措辞待法务（§7-Q10） | 法务 |
| C-16 | P2 | 官网/README 增加「许可证」章节，链接 `LICENSE` / 本文件 | 页面可达 | ⬜ 待补 | 发布 |
| C-17 | P2 | 发布物附带 SBOM（CycloneDX/SPDX），供下游审计 | 生成并附 | ⬜ 发布时执行 | 发布 |
| C-18 | P2 | 开发者提交即签 DCO/CLA（保证版权可控，AGPL 双许可/维权需要） | 仓库配置 | ⬜ 待配置 | 负责人 |
| C-19 | P2 | 源文件批量添加 SPDX 头 `SPDX-License-Identifier: AGPL-3.0-only` | `grep -r "SPDX-License-Identifier" src/` 全覆盖 | ⬜ 待添加 | 开发 |
| C-20 | P1 | 附加条款正文随包分发并可从 LICENSE 链接到达 | 安装包含 `docs/licenses/FYSAT-ADDITIONAL-TERMS.md` | ✅ 文档就绪；发布时随包 | 发布 |

---

## 7. 决策记录与真·待确认项

| # | 问题 | 状态 / 影响 | 建议动作 |
|---|---|---|---|
| Q1 | **AGPL + 数据署名的条款结构**是否会被认定为 §7「进一步限制」？ | ✅ **已定（2026-11-02）**：只采用 §7(b)(c)；「数据附修改后源码」不写入软件许可，改为数据条款 + 技术元数据（结论见 §1.2） | 仅余措辞法务定稿（见 Q10） |
| Q2 | 是否真的会**打包分发 PySide6**（方案 A/B/C 选哪个）？ | 决定 LGPL 义务强度与 GPL-only 剪裁工作量 | 负责人拍板；默认建议方案 A（剪裁后随包） |
| Q3 | `samples/`、`out/` 中 NSMC 数据的**再分发条款**（NSMC 数据使用政策） | 样例数据能否随包分发 | 联系 NSMC/查阅数据政策；未确认前不随包分发 |
| Q4 | 可选依赖 `netCDF4`（以及 pyproj）的许可证与打包影响 | 启用 nc3 功能时新增义务 | 启用前单独审计；当前未安装不构成风险 |
| Q5 | 是否保留未来**闭源/商业版**计划？AGPL 发布与商业授权的关系 | 影响 Copyright 归属管理与双许可策略 | 负责人确认；需全版权人同意 + 依赖链允许 |
| Q6 | Qt wheel 内 `opengl32sw.dll`（Mesa）等未附文本的第三方库 | 严格审计时缺声明 | 从 Qt 官方源码/安装目录补齐 Mesa 版权声明，加入 `docs/licenses/components/` |
| Q7 | Qt 6.12 各模块许可是否会随小版本变化（Qt Charts/Graphs 已在 6.10 起弃用；Qt PDF 文档版本标记异常） | 升级后可能新增 GPL-only 模块 | 锁版本；每次升级重跑 §4 核实并更新本文件 |
| Q8 | FY-Sat Studio 的中文名/商标是否已注册？Qt 商标使用是否需声明「非 Qt 官方产品」 | 商标合规 | 已在 THIRD_PARTY_NOTICES 增加「与 The Qt Company 无隶属关系」声明；必要时咨询 |
| Q9 | ~~测试自身缺陷：正则误伤 `"PySide6-Essentials"`~~ | ✅ **已修复（2026-11-02）**：Lead 已将正则改为 `r'"PySide6(>=|==|>|<|~=|\")'`；`test_license_compliance` + `test_provenance` 共 21 项全绿 | 可选后续：`test_license_files_present` 扩展校验 `LICENSE` / `docs/licenses/`（非阻塞） |
| Q10 | 附加条款与数据条款的**最终措辞**法务定稿 | `FYSAT-ADDITIONAL-TERMS.md` §6、`FYSAT-OUTPUT-ATTRIBUTION-1.0.md` §7 列出具体问题 | 法务 review 后定稿；不影响当前发布路线 |
| Q11 | 数据条款的强制力形式（CC-BY 风格 / 合同条款 / 仅请求）及与 NSMC 原始数据条款的叠加 | 影响官方数据集发布方式 | 法务 + 数据负责人确认；用户自生成数据一律仅「请求」 |

---

## 8. 证据与来源（可复核）

### 8.1 本地证据（安装环境实测，2026-11-02）

| 证据 | 位置/命令 |
|---|---|
| 依赖版本与 License 元数据 | `<venv>\Scripts\python.exe` + `importlib.metadata`（`License`、`License-Expression`、`Classifier` 字段） |
| 各包许可证原文 | numpy：`numpy-2.2.4.dist-info\LICENSE.txt`；h5py：`h5py-3.16.0.dist-info\licenses\*`；matplotlib：`matplotlib-3.10.1.dist-info\LICENSE` + `mpl-data\fonts\ttf\LICENSE_*`；pillow：`pillow-11.1.0.dist-info\LICENSE`；scipy：`scipy-1.15.2.dist-info\LICENSE.txt`；tifffile：`tifffile-2025.5.10.dist-info\licenses\LICENSE`；PyYAML：`PyYAML-6.0.2.dist-info\LICENSE` |
| PySide6/shiboken6 许可元数据 | `pyside6_essentials-6.12.0.dist-info\METADATA` L6：`License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`；`shiboken6-6.12.0.dist-info\METADATA` L6 同 |
| Qt 实际版本 | `PySide6.QtCore.qVersion()` → `6.12.0`；`PySide6.__version__` → `6.12.0`；`Qt6Core.dll` VersionInfo → `6.12.0.0`，`LegalCopyright: Copyright (C) The Qt Company Ltd. and other contributors.` |
| Qt 动态库形态 | `<venv>\Lib\site-packages\PySide6\Qt6*.dll` 共 76 个独立 DLL（另含 13 个非 Qt 前缀 DLL，合计 89 个；含 Core/Gui/Widgets/Network/Svg/Sql/Xml 等） |
| GPL-only 构件 | 同上目录实测：`Qt6Lottie*.dll`、`Qt6QuickTimeline*.dll`、`qml\QtQuick\Timeline\*`、`qml\QtQuick\VirtualKeyboard\**`、`Qt6QmlCompiler.dll`、14 个 Qt 工具 exe |
| matplotlib 后端选择逻辑 | `<python>\Lib\site-packages\matplotlib\backends\qt_compat.py` L34–63 |
| 源码扫描 | 全仓库 `grep -ri "PyQt\|pyqt\|sip"` → 0；`grep "PySide6"` → 仅 QtCore/QtGui/QtWidgets |
| PyInstaller 许可 | `pyinstaller-6.21.0.dist-info\METADATA`：`License: GPLv2-or-later with a special exception...`；全文 `licenses\COPYING.txt` |
| Natural Earth 条款 | https://www.naturalearthdata.com/about/terms-of-use/ （公有领域，无需署名，建议 "Made with Natural Earth"） |
| 本项目许可文件（1.1 新增） | `LICENSE`（36,408 B；SHA-256 `a0c3b0d4…`；AGPL 全文 + 附加条款指引）；`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`；`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md` v2.0 |
| pyproject 声明（1.1 复核） | `license = { text = "AGPL-3.0-only" }`；`gui = ["PySide6-Essentials==6.12.0"]`（并含禁止裸 `PySide6` 的注释） |
| QT_API 强制（1.1 复核） | `src/fysat/gui/app.py::_force_pyside6_backend()`：`os.environ.setdefault("QT_API", "pyside6")` + `matplotlib.use("QtAgg", force=True)`（在 import pyplot 之前） |
| 溯源元数据（1.1 复核） | `src/fysat/provenance.py`（`build_provenance` / `as_text` / `as_png_text` / `read_*_provenance`）+ `src/fysat/export.py`（TIFF `description=` / PNG `PngInfo` 默认写入） |
| 自动化合规测试（1.1 复核） | `tests/test_license_compliance.py` + `tests/test_provenance.py`；2026-11-02 实测 **21 项全部通过** |
| SatDump 许可核实（1.2 新增，2026-11-04） | 本地 `D:\下载\SatDump-1.2.2`：`LICENSE` = GNU GPL v3 全文；`git remote -v` → `git@github.com:lzh173/SD-ZH.git`（本项目作者的中文化 fork，上游为 `SatDump/SatDump`）；源码头 `SPDX-License-Identifier: GPL-3.0-or-later`（`logging.h` 等）；GitHub API `SatDump/SatDump` → `license.spdx_id = GPL-3.0` |
| SatDump 第三方资产授权（1.2 新增） | `resources/lut/goes/abi/wxstar/README.md` → 作者 Harry Dove-Robinson（wx-star，独立授权）；`resources/fy2/svissr/README.md` → 作者 @eswnl / FY-2x_CLUT，「with permission」（仅授予 SatDump）；`resources/lut/WXtoImg-*.png` 为 WXtoImg 遗留色表 |
| 本项目与 SatDump 相似性核查（1.2 新增） | `grep -ri satdump src/` → 0 处（仅 `PLAN.md` 范围划界说明）；`composites.yml`/`bands.yml` 头部标注来源为 NSMC 文档与 HDF5 属性；`render.composite()` 为分位数统一拉伸架构，与 SatDump muParser 逐像素表达式不同 |

### 8.2 官方在线来源（授权结论依据）

| 主题 | URL |
|---|---|
| Qt 整体许可策略（含「部分模块仅 GPL」原文） | https://doc.qt.io/qt-6/licensing.html |
| Qt 全部模块总览（含 Commercial Modules 说明） | https://doc.qt.io/qt-6/qtmodules.html |
| Qt for Python 第三方许可 | https://doc.qt.io/qtforpython-6/licenses.html |
| 各模块授权（页内 "Licenses"/"Licenses and Attributions" 节） | §4.1/§4.2 表内各 `doc.qt.io/qt-6/*-index.html` |
| Qt 源码仓库许可目录（REUSE） | https://github.com/qt/qtbase/tree/dev/LICENSES ；https://github.com/qt/qttools/tree/dev/LICENSES ；https://github.com/qt/qtdeclarative/tree/dev/LICENSES ；**无 LGPL 文件**：https://github.com/qt/qtlottie/tree/dev/LICENSES 、https://github.com/qt/qtquicktimeline/tree/dev/LICENSES |
| Qt GPL Exception 1.0 | https://github.com/qt/qtbase/blob/dev/LICENSES/Qt-GPL-exception-1.0.txt （本地 `docs/licenses/Qt-GPL-exception-1.0.txt`） |
| AGPLv3 / GPLv3 / LGPLv3 全文 | https://www.gnu.org/licenses/ （本地 `docs/licenses/*.txt`，取自 SPDX 官方文本镜像） |

### 8.3 复核命令（可重复执行）

```powershell
# 依赖许可证元数据
& <venv>\Scripts\python.exe -c "import importlib.metadata as m; [print(n, m.version(n), (m.metadata(n).get('License-Expression') or m.metadata(n).get('License') or '')[:60]) for n in ['numpy','h5py','matplotlib','pillow','scipy','tifffile','PyYAML','PySide6','shiboken6']]"
# Qt 版本与 DLL 数量
& <venv>\Scripts\python.exe -c "from PySide6.QtCore import qVersion; print('Qt', qVersion())"
(Get-ChildItem '<venv>\Lib\site-packages\PySide6\Qt6*.dll').Count
# GPL-only 构件是否存在
Get-ChildItem '<venv>\Lib\site-packages\PySide6' -Recurse -File | Where-Object { $_.Name -match '(?i)(lottie|quicktimeline|virtualkeyboard|qtvkb|qmlcompiler)' }
# matplotlib 绑定解析
& <venv>\Scripts\python.exe -c "import matplotlib; print(matplotlib.get_backend()); from matplotlib.backends import qt_compat; print(qt_compat.QT_API)"
# 自动化合规测试（1.1 新增）
& <venv>\Scripts\python.exe -m pytest tests/test_license_compliance.py -q
# 校验 LICENSE 含 AGPL 全文（1.1 新增）
$lic = Get-Content LICENSE -Raw; $agpl = Get-Content docs/licenses/AGPL-3.0.txt -Raw; if ($lic.Contains($agpl.Trim())) { "AGPL full text OK" } else { "AGPL full text MISSING" }
# 校验 pyproject 不再声明裸 PySide6（1.1 新增）
Select-String -Path pyproject.toml -Pattern 'gui ='
```

---

*本文件为合规审计产出，不构成法律意见；涉及许可证解释与条款效力时以法务意见为准。*

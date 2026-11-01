# FY-Sat Studio 第三方组件声明（THIRD_PARTY_NOTICES.md）

> 适用项目：**FY-Sat Studio / `fysat`**
> 文档版本：1.0 ｜ 生成日期：2026-11-02 ｜ 对应环境：Python 3.10.6 · Qt 6.12.0 · PySide6_Essentials 6.12.0
> **本文件必须随软件安装包/分发物一同提供**（与 [`LICENSES.md`](LICENSES.md)、[`docs/licenses/`](docs/licenses/) 一起）。
> 许可证全文见 `docs/licenses/`；本文件只做版权声明与引用。

---

## 一、总则

1. FY-Sat Studio 自身代码以 **GNU Affero General Public License v3.0（AGPL-3.0-only）** 发布，详见 [`LICENSES.md`](LICENSES.md) 与 [`docs/licenses/AGPL-3.0.txt`](docs/licenses/AGPL-3.0.txt)。
2. 本软件包含下列第三方组件，它们分别受各自许可证约束，**不因本项目的 AGPL 许可而改变其原有许可**。
3. 若某一组件的许可证与本项目 AGPL 存在冲突，以该组件的许可证为准处理该组件；本项目选择的使用方式见 [`LICENSES.md`](LICENSES.md) §3。

---

## 二、Qt / Qt for Python（LGPLv3）—— 必须显著声明

### 2.1 使用了什么

| 组件 | 版本 | 实际使用的模块 | 许可证 |
|---|---|---|---|
| Qt（The Qt Company） | **6.12.0** | QtCore、QtGui、QtWidgets（当前 GUI 仅使用这三者；安装包可能附带其他 LGPL 模块） | **LGPL-3.0-only**（Qt 同时提供 GPLv2 / GPLv3 / 商业授权；本项目选择 LGPLv3） |
| PySide6（Qt for Python） | **6.12.0**（`PySide6_Essentials`） | Python 绑定层 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`，本项目选择 **LGPLv3** |
| shiboken6 | **6.12.0** | PySide6 绑定生成运行库 | 同上，本项目选择 **LGPLv3** |

### 2.2 版权声明

> **Copyright (C) The Qt Company Ltd. and other contributors.**
> Qt and the Qt logo are trademarks of The Qt Company Ltd. in Finland and/or other countries worldwide.
> PySide6 / Shiboken6: Copyright (C) The Qt Company Ltd. and contributors.

（上述 Qt 版权行取自随附 `Qt6Core.dll` 的版本信息 `LegalCopyright` 字段，2026-11-02 实测。）

### 2.3 必须随附的许可证全文（LGPLv3 §4(b) 要求同时提供 GPLv3 文本）

| 文件 | 说明 |
|---|---|
| [`docs/licenses/LGPL-3.0.txt`](docs/licenses/LGPL-3.0.txt) | GNU Lesser General Public License v3 全文 |
| [`docs/licenses/GPL-3.0.txt`](docs/licenses/GPL-3.0.txt) | GNU GPL v3 全文（LGPLv3 以 GPLv3 条款为基础） |
| [`docs/licenses/GPL-2.0.txt`](docs/licenses/GPL-2.0.txt) | GNU GPL v2（Qt 的备选许可分支说明用，本项目未选择） |
| [`docs/licenses/Qt-GPL-exception-1.0.txt`](docs/licenses/Qt-GPL-exception-1.0.txt) | Qt GPL Exception 1.0（适用于 Qt 工具如 `uic`/`rcc`/`designer`；**若安装包未附带 Qt 工具则无需分发**） |
| [`docs/licenses/Qt_PySide_NOTICE.md`](docs/licenses/Qt_PySide_NOTICE.md) | Qt/PySide6 使用声明、版权、替换方法与源码获取方式 |

### 2.4 用户替换 Qt 库的权利（LGPLv3 §4 摘要）

> 本软件**动态链接** Qt 6.12.0（Qt 库以 `PySide6\Qt6*.dll` 独立文件形式随附）。依据 LGPLv3，您有权修改本软件所使用的 Qt 库，并有权将随附的 Qt 库替换为接口兼容的修改版本，以便重新链接/运行。我们不会校验或锁定 Qt 库文件的签名/哈希，也不会将其封装进不可替换的单一可执行文件（默认 `--onedir` 分发）。替换步骤见 `docs/licenses/Qt_PySide_NOTICE.md` §4。

### 2.5 源码获取

| 组件 | 源码地址 |
|---|---|
| PySide6 / shiboken6 | https://code.qt.io/cgit/pyside/pyside-setup.git/ （tag：`v6.12.0`；镜像 https://github.com/qt/pyside-setup ） |
| Qt 6.12.0 | https://download.qt.io/official_releases/qt/6.12/ （源码包） |
| 各模块源码 | https://code.qt.io/cgit/qt/ （如 `qtbase`、`qtdeclarative`） |

### 2.6 不使用 GPL-only 模块的声明

本软件**未链接、未调用** Qt Charts、Qt Data Visualization、Qt Graphs、Qt Virtual Keyboard、Qt Quick 3D、Qt Quick Timeline、Qt Lottie Animation、Qt Network Authorization、Qt CoAP、Qt MQTT、Qt HTTP Server、Qt GRPC、Qt Qml Compiler 等 GPLv3-only / 商业-only 模块（黑名单详见 [`LICENSES.md`](LICENSES.md) §4.2）。
> ⚠️ 发布前须按 [`LICENSES.md`](LICENSES.md) §4.3 从安装包中**移除 wheel 自带的 GPL-only 构件**；否则本声明不成立。

### 2.7 非隶属声明

本软件为独立第三方作品，与 **The Qt Company Ltd.** 无隶属、赞助或背书关系；"Qt" 与 "Qt for Python / PySide6" 为其各自权利人的商标，此处仅为说明兼容性而使用。

---

## 三、Python 运行时（若随安装包分发解释器）

| 项 | 内容 |
|---|---|
| 组件 | CPython 3.10.6 |
| 版权 | Copyright © 2001-2023 Python Software Foundation; All Rights Reserved |
| 许可证 | PSF LICENSE AGREEMENT FOR PYTHON 3.10（PSF-2.0） |
| 全文 | [`docs/licenses/runtime/python-PSF-LICENSE.txt`](docs/licenses/runtime/python-PSF-LICENSE.txt) |
| 备注 | 若通过 PyInstaller/Nuitka 打包，安装包内还会包含 OpenSSL（Apache-2.0）、libffi（MIT）、zlib、liblzma、SQLite（public domain）等运行时库，发布时应随 SBOM 一并补齐声明（见 [`LICENSES.md`](LICENSES.md) 检查清单 C-09） |

---

## 四、运行时 Python 组件

> 版本为 2026-11-02 实测环境值；发布时以**打包产物实际版本**为准（检查清单 C-08）。

| 组件 | 版本 | 版权声明（原文摘要） | 许可证 | 全文 |
|---|---|---|---|---|
| **NumPy** | 2.2.4 | Copyright (c) 2005-2024, NumPy Developers. All rights reserved. | BSD-3-Clause | [`components/numpy-LICENSE.txt`](docs/licenses/components/numpy-LICENSE.txt) |
| **h5py** | 3.16.0 | Copyright (c) 2008 Andrew Collette and contributors. All rights reserved. | BSD-3-Clause | [`components/h5py-LICENSE.txt`](docs/licenses/components/h5py-LICENSE.txt) |
| **h5py 项目说明** | — | Copyright Notice and Statement for the h5py Project | BSD-3-Clause | [`components/h5py-project-notice.txt`](docs/licenses/components/h5py-project-notice.txt) |
| **HDF5**（h5py 捆绑 `hdf5.dll`） | h5py 内置版本 | Copyright Notice and License Terms for HDF5 (Hierarchical Data Format 5) Software Library and Utilities | HDF5 许可（BSD 系） | [`components/hdf5-LICENSE.txt`](docs/licenses/components/hdf5-LICENSE.txt) |
| **LZF filter**（h5py 捆绑） | — | Copyright (c) 2008-2009 Andrew Collette | BSD-3-Clause | [`components/h5py-lzf-LICENSE.txt`](docs/licenses/components/h5py-lzf-LICENSE.txt) |
| **Matplotlib** | 3.10.1 | Copyright (c) 2012- Matplotlib Development Team; All Rights Reserved. 早期版本 Copyright (c) 2002-2011 John D. Hunter; All Rights Reserved. | Matplotlib License（PSF 系，BSD 兼容） | [`components/matplotlib-LICENSE.txt`](docs/licenses/components/matplotlib-LICENSE.txt) |
| **DejaVu 字体**（matplotlib 捆绑） | — | Copyright (c) 2003 Bitstream, Inc. / DejaVu changes are in public domain | Bitstream Vera Fonts License | [`components/matplotlib-LICENSE_DEJAVU.txt`](docs/licenses/components/matplotlib-LICENSE_DEJAVU.txt) |
| **STIX 字体**（matplotlib 捆绑） | — | Copyright (c) 2001-2010 STI Pub Companies | SIL Open Font License 1.1 | [`components/matplotlib-LICENSE_STIX.txt`](docs/licenses/components/matplotlib-LICENSE_STIX.txt) |
| **Pillow** | 11.1.0 | Copyright © 1997-2011 Secret Labs AB；Copyright © 1995-2011 Fredrik Lundh and contributors；Copyright © 2010 Jeffrey A. Clark and contributors | MIT-CMU | [`components/pillow-LICENSE.txt`](docs/licenses/components/pillow-LICENSE.txt) |
| **SciPy** | 1.15.2 | Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers. All rights reserved. | BSD-3-Clause | [`components/scipy-LICENSE.txt`](docs/licenses/components/scipy-LICENSE.txt) |
| **tifffile** | 2025.5.10 | Copyright (c) 2008-2025, Christoph Gohlke. All rights reserved. | BSD-3-Clause | [`components/tifffile-LICENSE.txt`](docs/licenses/components/tifffile-LICENSE.txt) |
| **PyYAML** | 6.0.2 | Copyright (c) 2017-2021 Ingy döt Net；Copyright (c) 2006-2016 Kirill Simonov | MIT | [`components/pyyaml-LICENSE.txt`](docs/licenses/components/pyyaml-LICENSE.txt) |

---

## 五、随依赖二进制捆绑的原生库（间接组件）

以下原生库由上述 Python wheel 随附（不单独安装），其许可文本已收录在对应组件的 LICENSE 合集中；本节列出以便审计。

| 原生库 | 随附来源 | 许可（主要） | 声明位置 |
|---|---|---|---|
| OpenBLAS（`libscipy_openblas*.dll`） | NumPy / SciPy wheel | BSD-3-Clause（含 LAPACK 等第三方声明） | numpy/scipy LICENSE 全文 |
| HDF5、zlib（`hdf5.dll`、`hdf5_hl.dll`、`z.dll`） | h5py wheel | HDF5 许可 / zlib 许可 | `hdf5-LICENSE.txt` / h5py LICENSE |
| libjpeg-turbo、zlib、libtiff、FreeType、OpenJPEG、Little CMS（lcms2）、libwebp | Pillow wheel | IJG / zlib / libtiff / FTL / BSD / MIT | Pillow LICENSE 合集 |
| libyaml | PyYAML（`_yaml` 扩展） | MIT | PyYAML LICENSE |
| Mesa 软件 OpenGL（`opengl32sw.dll`） | PySide6 wheel | MIT（Mesa 惯例） | ⚠️ **待确认**：wheel 未附该库文本，发布前从 Qt 官方安装目录/源码补齐（[`LICENSES.md`](LICENSES.md) §7-Q6） |
| MSVC 运行库（`msvcp140*.dll`、`concrt140.dll`） | PySide6 wheel | Microsoft Visual C++ Redistributable 许可（可再分发组件） | 随安装包附带微软许可条款或引用系统已安装版本 |

---

## 六、数据与底图

| 资产 | 来源 | 许可/条款 | 引用方式 |
|---|---|---|---|
| `assets/ne_110m_coastline.geojson` | Natural Earth（1:110m 海岸线） | **公有领域**（Natural Earth Terms of Use：可任意使用、修改、商用，**无需署名**） | 建议标注："Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com." |
| `samples/`、`out/` 中的 FY 卫星样例/派生图 | 国家卫星气象中心（NSMC）分发产品 | ⚠️ **待确认**：产品再分发/二次使用条款 | 未确认前**不得随安装包分发**（[`LICENSES.md`](LICENSES.md) 检查清单 C-11 / §7-Q3） |

> **技术层（已实现）**：导出 TIFF/PNG 时默认写入溯源元数据（`software` / `software_version` / `license` / `source_url` / `modified` / `commit` / `generated_at` 等），实现见 `src/fysat/provenance.py`，说明见 [`LICENSES.md`](LICENSES.md) §1.4 与 [`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md) §4。
> 数据署名**不是**软件许可的附加条款；软件许可仅采用 AGPLv3 §7(b)(c)（见 [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md)）。

---

## 七、构建工具（发布相关）

| 工具 | 版本 | 许可 | 分发影响 |
|---|---|---|---|
| PyInstaller | 6.21.0 | **GPL-2.0-or-later with a special exception**（显式允许用于构建并分发非自由程序，包括商业程序） | 使用其打包时，安装包内嵌 PyInstaller bootloader（GPLv2 代码）→ 必须：① 随附 COPYING 全文；② 在本声明中列明；③ 不主张该 bootloader 由本项目授权。全文：[`build/pyinstaller-GPLv2-with-exception-COPYING.txt`](docs/licenses/build/pyinstaller-GPLv2-with-exception-COPYING.txt) |
| Nuitka | 2.6.9 | Apache-2.0 | 若采用，随附 Apache-2.0 声明与 NOTICE（如上游提供） |

---

## 八、许可证全文索引

| 组件 | 全文文件 | 必须随包分发？ |
|---|---|---|
| 本项目（AGPL-3.0） | 根目录 [`LICENSE`](LICENSE)（AGPL 全文 + 附加条款指引）；`docs/licenses/AGPL-3.0.txt` | ✅ 是 |
| 本项目附加条款（仅 §7(b)(c)） | [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md) | ✅ 是（构成 `LICENSE` 许可声明的一部分） |
| 输出数据条款（数据使用条款/请求，**非软件许可条款**） | [`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md) | 建议（发布数据产品时） |
| Qt / PySide6（LGPLv3） | `docs/licenses/LGPL-3.0.txt` + `docs/licenses/GPL-3.0.txt` | ✅ 是（LGPLv3 §4(b)） |
| Qt 备选许可（GPLv2 / 商业） | `docs/licenses/GPL-2.0.txt`；商业条款见 https://www.qt.io/terms-conditions | 建议 |
| Qt 工具例外 | `docs/licenses/Qt-GPL-exception-1.0.txt` | 仅当附带 Qt 工具时 |
| NumPy | `docs/licenses/components/numpy-LICENSE.txt` | ✅ 是 |
| h5py + HDF5 + LZF | `docs/licenses/components/h5py-LICENSE.txt`、`hdf5-LICENSE.txt`、`h5py-lzf-LICENSE.txt`、`h5py-project-notice.txt` | ✅ 是 |
| Matplotlib（含字体） | `docs/licenses/components/matplotlib-LICENSE.txt`、`matplotlib-LICENSE_DEJAVU.txt`、`matplotlib-LICENSE_STIX.txt` | ✅ 是 |
| Pillow | `docs/licenses/components/pillow-LICENSE.txt` | ✅ 是 |
| SciPy | `docs/licenses/components/scipy-LICENSE.txt` | ✅ 是 |
| tifffile | `docs/licenses/components/tifffile-LICENSE.txt` | ✅ 是 |
| PyYAML | `docs/licenses/components/pyyaml-LICENSE.txt` | ✅ 是 |
| CPython 运行时 | `docs/licenses/runtime/python-PSF-LICENSE.txt` | 附带解释器时 ✅ |
| PyInstaller | `docs/licenses/build/pyinstaller-GPLv2-with-exception-COPYING.txt` | 使用 PyInstaller 打包时 ✅ |

---

## 九、源代码获取方式（对应 AGPL §13 / LGPLv3 §4 / GPL §6）

> 以下为发布模板，发布时替换 `<...>` 占位内容。

1. **本项目（AGPL-3.0）**
   - 源码仓库：`<https://example.com/fysat/source>`（tag：`<vX.Y.Z>`）
   - 二进制发布页同时提供源码包：`<https://example.com/fysat/releases/tag/vX.Y.Z>`
   - 网络服务（如将来提供）：在服务页面「关于/源码」处提供同版本源码下载入口（AGPL §13）。
   - **附加条款**：随程序分发根目录 `LICENSE` 与 [`docs/licenses/FYSAT-ADDITIONAL-TERMS.md`](docs/licenses/FYSAT-ADDITIONAL-TERMS.md)（AGPLv3 §7(b)(c)：保留署名/法律声明、禁止虚假来源并要求修改版标记为不同）；数据署名不属于软件许可，见 [`docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md`](docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md)。
2. **Qt / PySide6（LGPLv3）**
   - 见 §2.5 官方地址；若您无法从官网下载，可向我们索取与安装包内版本一致的源码副本（书面请求：`<licensing@example.com>`）。
3. **书面要约模板**
   > FY-Sat Studio `<vX.Y.Z>` 二进制安装包内包含 Qt 6.12.0、PySide6 6.12.0 等第三方组件。凡本声明所列组件的对应源码，自本版本发布之日起三年内，您可向 `<licensing@example.com>` 提出书面请求获取其完整源码副本（仅收取介质/传输成本），或按本声明中各组件标注的官方地址自行下载。

---

## 十、文档维护记录

| 日期 | 版本 | 变更 | 负责人 |
|---|---|---|---|
| 2026-11-02 | 1.0 | 首次审计：核实 9 个运行时依赖许可；核实 Qt 6 模块白/黑名单；发现 PySide6-Essentials wheel 内 GPL-only 构件；确定 AGPL-3.0 + 附加条款路线（待法务确认） | 许可证合规审计（license-audit） |
| 2026-11-02 | 1.1 | 按最终决策同步：`AGPL-3.0-only` + 仅 §7(b)(c) 附加条款；新增根 `LICENSE`、`FYSAT-ADDITIONAL-TERMS.md`；数据署名改为分层（数据条款 + 导出元数据）；同步 pyproject / app.py / 自动化测试三项已修复风险 | 许可证合规审计（license-audit） |

*本文件为合规审计产出，不构成法律意见；许可证解释争议以各许可证原文与法务意见为准。*

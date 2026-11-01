# docs/licenses —— 随分发许可证全文索引

> 本目录存放 **FY-Sat Studio 对外分发时必须随包附带**的许可证全文与声明文件。
> 与项目根目录 [`LICENSE`](../../LICENSE)（AGPL-3.0 全文 + 附加条款指引）、[`LICENSES.md`](../../LICENSES.md)、[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) 配合使用。
> 基准环境：Python 3.10.6 · Qt/PySide6 6.12.0 ｜ 版本：1.1 ｜ 更新日期：2026-11-02

---

## 1. 目录结构

```
（项目根）
├── LICENSE                                      ← AGPL-3.0 全文 + §7(b)(c) 附加条款指引（分发必备）
├── LICENSES.md                                  ← 许可证与合规说明（总文档）
├── THIRD_PARTY_NOTICES.md                       ← 第三方版权声明汇总
└── docs/licenses/
    ├── README.md                                ← 本文件（索引/维护说明）
    ├── AGPL-3.0.txt                             ← 本项目主许可证全文（AGPL-3.0-only）
    ├── LGPL-3.0.txt                             ← Qt / PySide6（LGPLv3）
    ├── GPL-3.0.txt                              ← LGPLv3 §4(b) 要求随附（LGPLv3 以 GPLv3 为基础）
    ├── GPL-2.0.txt                              ← Qt 备选许可分支说明用（本项目未选）
    ├── Qt-GPL-exception-1.0.txt                 ← Qt 工具（uic/rcc/designer…）的 GPL 例外
    ├── Qt_PySide_NOTICE.md                      ← Qt/PySide6 显著声明 + 版权 + 替换方法 + 源码地址
    ├── FYSAT-ADDITIONAL-TERMS.md                ← 本项目实际采用的 AGPLv3 §7(b)(c) 附加条款（中英双语）
    ├── FYSAT-OUTPUT-ATTRIBUTION-1.0.md          ← 输出数据来源署名：分层方案（数据条款 + 技术元数据，v2.0）
    ├── components/                              ← Python 运行时依赖的许可证全文
    │   ├── numpy-LICENSE.txt
    │   ├── scipy-LICENSE.txt
    │   ├── h5py-LICENSE.txt
    │   ├── h5py-project-notice.txt
    │   ├── h5py-lzf-LICENSE.txt
    │   ├── hdf5-LICENSE.txt
    │   ├── matplotlib-LICENSE.txt
    │   ├── matplotlib-LICENSE_DEJAVU.txt
    │   ├── matplotlib-LICENSE_STIX.txt
    │   ├── pillow-LICENSE.txt
    │   ├── tifffile-LICENSE.txt
    │   └── pyyaml-LICENSE.txt
    ├── runtime/
    │   └── python-PSF-LICENSE.txt               ← 若随包分发 CPython 解释器
    └── build/
        └── pyinstaller-GPLv2-with-exception-COPYING.txt  ← 若使用 PyInstaller 打包
```

- **`LICENSE`（根目录）**：AGPL-3.0 全文 + §7(b)(c) 附加条款指引；`FYSAT-ADDITIONAL-TERMS.md` 是其许可声明的一部分，**两者必须一起分发**。
- **`FYSAT-OUTPUT-ATTRIBUTION-1.0.md`**：数据使用条款/请求，**不是**软件许可附加条款；不随软件分发强制，但发布数据产品时应附带。

---

## 2. 文件索引（含来源与 SHA-256）

> 校验值用于发布时核对文件未被篡改/替换；升级依赖或修改条款后必须同步更新本表。

| 文件 | 大小(B) | SHA-256 | 来源 | 何时随包 |
|---|---:|---|---|---|
| `../../LICENSE`（根目录） | 36408 | `a0c3b0d4401d6871c4c1f22d81dcdb06c1a0edd31baaad47e6445ea3ac478bc5` | 本项目：`docs/licenses/AGPL-3.0.txt` 全文 + §7(b)(c) 附加条款指引 | **总是** |
| `AGPL-3.0.txt` | 34020 | `d8a6cc31abc16b6748c7a21f21611f5a1ec33f67d22ca23d7da1c19b95496bee` | SPDX license-list-data（AGPL-3.0-only 官方文本） | **总是** |
| `LGPL-3.0.txt` | 7651 | `da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768` | Qt 源码仓库 `qtbase/LICENSES/LGPL-3.0-only.txt`（= FSF 官方文本） | **总是**（使用 Qt） |
| `GPL-3.0.txt` | 34674 | `fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0` | SPDX license-list-data（GPL-3.0-only） | **总是**（LGPLv3 §4(b)） |
| `GPL-2.0.txt` | 17337 | `aaf135472f81c5b4a0dca9367e5bb5e9750032b5bebe5442b36e4c0a47430df3` | SPDX license-list-data（GPL-2.0-only） | 建议（Qt 备选许可说明） |
| `Qt-GPL-exception-1.0.txt` | 965 | `40678d338ce53cd93f8b22b281a2ecbcaa3ee65ce60b25ffb0c462b0530846b2` | Qt 源码仓库 `qtbase/LICENSES/Qt-GPL-exception-1.0.txt` | 仅当附带 Qt 工具时 |
| `Qt_PySide_NOTICE.md` | 5643 | `14b01ff15c11919da34a903ff44c007359d775b213c95b8c7bd1821812294713` | 本项目编写（LGPLv3 §4 声明模板） | **总是**（使用 Qt） |
| `FYSAT-ADDITIONAL-TERMS.md` | 9470 | `d42e2b50ebebbab5e0ee8968ae437cfac1f52e713dbff8e5ebb5fce069ece28a` | 本项目编写（AGPLv3 §7(b)(c) 附加条款正文，中英双语） | **总是**（构成 LICENSE 一部分） |
| `FYSAT-OUTPUT-ATTRIBUTION-1.0.md` | 10999 | `8f87269b11fc3ad18692e18dab46efbb6416a2df253043dad85b44c4ddf5b8d9` | 本项目编写（数据条款/请求 + 技术元数据说明，v2.0） | 建议（发布数据产品时） |
| `components/numpy-LICENSE.txt` | 47709 | `14256cc3a2c9d32ac284da96b937feb44f72dd90bee2317ac3020166846ad99d` | `numpy-2.2.4.dist-info\LICENSE.txt` | 总是 |
| `components/scipy-LICENSE.txt` | 46763 | `f250e7cef15fbd99e8680093d112d7aa7579535b99995268df6c89ac926eb607` | `scipy-1.15.2.dist-info\LICENSE.txt` | 使用 SciPy 时 |
| `components/h5py-LICENSE.txt` | 1550 | `b773bc7cf038637a7fd8087648cc28e05f0f24d53770d1827147a40a1d268ab5` | `h5py-3.16.0.dist-info\licenses\LICENSE` | 总是 |
| `components/h5py-project-notice.txt` | 1773 | `9a6333afbf5c391994fe3e9f5241accb8c22a23eb50b2e7e9b00ea57dccf29d0` | `h5py-3.16.0.dist-info\licenses\licenses\license.txt` | 总是 |
| `components/h5py-lzf-LICENSE.txt` | 1589 | `d7b37a2bda245d5199b84a04cf4d91b899b4ad687076c8e0a92d792b521fd464` | `h5py-3.16.0.dist-info\licenses\lzf\LICENSE.txt` | 总是 |
| `components/hdf5-LICENSE.txt` | 5848 | `b384492d25c6e4a49f371b646d9a81bc0a4b97cf0c66c2f3ed1b35f78a148732` | HDFGroup/hdf5 仓库 `LICENSE` | 总是（h5py 捆绑 hdf5.dll） |
| `components/matplotlib-LICENSE.txt` | 4830 | `5a1a81ea301728c8bba2933da832c0cd62229daf20893a024ab3d53244468dbc` | `matplotlib-3.10.1.dist-info\LICENSE` | 总是 |
| `components/matplotlib-LICENSE_DEJAVU.txt` | 4816 | `d75938dec098f06f0ac3c00853065d94f020be1c3c62ef1dc2975ba15b4d9b0e` | `matplotlib\mpl-data\fonts\ttf\LICENSE_DEJAVU` | 总是（捆绑字体） |
| `components/matplotlib-LICENSE_STIX.txt` | 5476 | `bab3d31dfef07f483624f2f65f2711e76065b8e7273278b1c071ede1041c9959` | `matplotlib\mpl-data\fonts\ttf\LICENSE_STIX` | 总是（捆绑字体） |
| `components/pillow-LICENSE.txt` | 56662 | `63a9bb147f7b8d43d211f06000fe40606739ad93fbd5cb1f844bc740f8bc51ec` | `pillow-11.1.0.dist-info\LICENSE` | 总是 |
| `components/tifffile-LICENSE.txt` | 1559 | `c309a8540535da0e25ae5f60097d939551c8fcad7465c584353f151ac6a954e3` | `tifffile-2025.5.10.dist-info\licenses\LICENSE` | 总是 |
| `components/pyyaml-LICENSE.txt` | 1101 | `8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4` | `PyYAML-6.0.2.dist-info\LICENSE` | 总是 |
| `runtime/python-PSF-LICENSE.txt` | 32763 | `ff4591f6dec4dc7ebe86e0c1c0eef1f2c7b651ee3ba45e5b4ccb35f2607bdd43` | `D:\py310\LICENSE.txt`（CPython 3.10.6） | 附带解释器时 |
| `build/pyinstaller-GPLv2-with-exception-COPYING.txt` | 32138 | `dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245` | `pyinstaller-6.21.0.dist-info\licenses\COPYING.txt` | 使用 PyInstaller 打包时 |

> 说明：`LGPL-3.0.txt` 采用 FSF 官方短文本（LGPLv3 通过引用并入 GPLv3 条款），因此同时提供独立 `GPL-3.0.txt` 以满足 LGPLv3 §4(b)。

---

## 3. 三层许可结构速查（详见 LICENSES.md §1.2）

| 层 | 文件 | 性质 | 强制力 |
|---|---|---|---|
| L1 软件许可 | `LICENSE` + `FYSAT-ADDITIONAL-TERMS.md` | AGPL-3.0-only + **仅 §7(b)(c)** 附加条款 | 强制（版权许可） |
| L2 数据条款 | `FYSAT-OUTPUT-ATTRIBUTION-1.0.md` | 数据使用条款 / 请求 | 我们分发的数据可强制；用户自生成数据仅请求 |
| L3 技术元数据 | `src/fysat/provenance.py`（文档说明见 L2 §4） | 导出 TIFF/PNG 默认写入溯源字段 | 默认执行 |

> 注意：**不要**把 L2 的数据要求写进 L1 的 `LICENSE` 附加条款——「数据附源码」等要求超出 AGPLv3 §7 六类，会被认定为 further restriction（详见 `LICENSES.md` §1.2）。

---

## 4. 生成/复核命令（可重复执行）

```powershell
# 重新提取各依赖包内的许可证文件（版本升级后执行）
$sp = 'E:\venv\fysat\Lib\site-packages'
Copy-Item "$sp\numpy-2.2.4.dist-info\LICENSE.txt"        docs/licenses/components/numpy-LICENSE.txt
Copy-Item "$sp\h5py-3.16.0.dist-info\licenses\LICENSE"   docs/licenses/components/h5py-LICENSE.txt
# ...（其余见 LICENSES.md §8.3）

# 校验根 LICENSE 含 AGPL 全文
$lic = Get-Content LICENSE -Raw
$agpl = Get-Content docs/licenses/AGPL-3.0.txt -Raw
if ($lic.Contains($agpl.Trim())) { "AGPL full text OK" } else { "AGPL full text MISSING" }

# 核对校验值
Get-ChildItem docs/licenses -Recurse -File |
  ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.FullName }

# 合规测试
& E:\venv\fysat\Scripts\python.exe -m pytest tests/test_license_compliance.py -q
```

---

## 5. 维护规则

1. **依赖升级 = 重新审计**：任何 `pyproject.toml` 依赖版本变化，都必须重新提取 LICENSE 文件、更新本表 SHA-256、并复核 [`LICENSES.md`](../../LICENSES.md) §2/§4（Qt 小版本可能改变模块许可归属）。
2. **新增依赖 = 先审后用**：新依赖必须先在 [`LICENSES.md`](../../LICENSES.md) 依赖表中登记许可证与义务，禁止引入 GPL/AGPL/SSPL 等强 copyleft 组件（除非经负责人+法务批准并调整项目许可策略）。
3. **LICENSE 同步**：修改 `AGPL-3.0.txt`、`FYSAT-ADDITIONAL-TERMS.md` 时，必须同步根 `LICENSE` 的指引段与 SHA-256，并复核全文逐字一致。
4. **不改动原文**：本目录下 `.txt` 为第三方许可证**原文**，禁止编辑（仅允许替换为上游同版本的新文本）；如需说明，写入 `*.md`。
5. **随包分发**：打包脚本必须把根 `LICENSE`、`LICENSES.md`、`THIRD_PARTY_NOTICES.md`、`docs/licenses/` 复制进安装包（检查清单 C-02）。
6. **发布留痕**：每次发布记录本目录文件哈希（可附在 Release notes 或 SBOM 中），便于事后审计。

# Qt / Qt for Python 使用声明（LGPLv3）

> 本文件是 LGPLv3 §4(a) 要求的「显著声明」的**权威文本**，供安装包、About 对话框、发布说明、官网文档引用。
> 对应项目：FY-Sat Studio ｜ 版本基准：Qt 6.12.0 / PySide6 6.12.0 ｜ 更新日期：2026-11-02

---

## 1. 声明正文（中文）

> 本软件使用 **Qt 6.12.0** 与 **PySide6 6.12.0**（Qt for Python）。
> Qt 与 PySide6 依据 **GNU Lesser General Public License version 3（LGPLv3）** 授权使用，版权归 **The Qt Company Ltd. 及其他贡献者**所有（`Copyright (C) The Qt Company Ltd. and other contributors.`）。
> 我们**未修改** Qt/PySide6 的源代码，仅使用其官方发布的二进制包。
> 本软件以**动态链接**方式使用 Qt：Qt 库以独立动态库文件（`PySide6\Qt6*.dll`）随附，您有权替换为接口兼容的修改版本。
> LGPLv3 与 GPLv3 全文随本软件分发，位于 `docs/licenses/LGPL-3.0.txt` 与 `docs/licenses/GPL-3.0.txt`。
> Qt/PySide6 源码获取：<https://code.qt.io/cgit/pyside/pyside-setup.git/>（tag `v6.12.0`）、<https://download.qt.io/official_releases/qt/6.12/>。

## 2. 声明正文（English）

> This software uses **Qt 6.12.0** and **PySide6 6.12.0**.
> Qt and PySide6 are used under the **GNU Lesser General Public License version 3 (LGPLv3)**.
> Copyright (C) The Qt Company Ltd. and other contributors.
> We have not modified the Qt/PySide6 source code; only the official binary packages are used.
> Qt is used through **dynamic linking**: the Qt libraries are shipped as separate dynamic libraries (`PySide6\Qt6*.dll`) and may be replaced by interface-compatible modified versions.
> The full LGPLv3 and GPLv3 texts are distributed with this software at `docs/licenses/LGPL-3.0.txt` and `docs/licenses/GPL-3.0.txt`.
> Qt/PySide6 sources: <https://code.qt.io/cgit/pyside/pyside-setup.git/> (tag `v6.12.0`), <https://download.qt.io/official_releases/qt/6.12/>.

---

## 3. 随附版本与模块清单

| 组件 | 版本 | PyPI 包 | 许可证 | 选择分支 |
|---|---|---|---|---|
| Qt | 6.12.0 | （随 PySide6 wheel 提供） | LGPLv3 / GPLv2 / GPLv3 / 商业 | **LGPLv3** |
| PySide6 | 6.12.0 | `PySide6_Essentials` | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | **LGPLv3** |
| shiboken6 | 6.12.0 | `shiboken6` | 同上 | **LGPLv3** |

**本软件实际 import 的 Qt 模块（白名单，均 LGPLv3 可用）：**

| 模块 | 用途 | 证据 |
|---|---|---|
| `PySide6.QtCore` | 对象模型/信号槽/线程 | `src/fysat/gui/*.py` |
| `PySide6.QtGui` | 图像、调色板、字体 | 同上 |
| `PySide6.QtWidgets` | 主窗口与控件 | 同上 |

> 当前代码**未**使用 QtNetwork、QtSvg、QtSql、Qml、Quick 等其他模块；如未来新增模块，必须先对照 `LICENSES.md` §4 白名单。

---

## 4. 用户替换 Qt 库的步骤（满足 LGPLv3 §4(d)(1)）

1. 关闭 FY-Sat Studio。
2. 获取接口兼容的 Qt 6.12.x 动态库：可自行编译（含修改版），或下载 Qt 官方二进制（同 ABI、同大版本）。
3. 备份安装目录下 `PySide6` 文件夹。
4. 将新的 `Qt6*.dll` 覆盖到 `安装目录\PySide6\`（若整体替换，请保持 `PySide6` 的 Python 扩展模块与 Qt DLL 版本匹配）。
5. 启动软件验证；若不兼容，回滚备份即可。
6. 我们承诺：**不校验 Qt DLL 的哈希/签名，不做防替换处理，不将 Qt 库静态编译进主程序**（默认分发形态为 `--onedir`，Qt 为独立文件）。

---

## 5. LGPLv3 义务对照（本声明覆盖的部分）

| LGPLv3 条款 | 本声明/分发包的对应实现 |
|---|---|
| §4(a) 显著声明使用了库及其 LGPL 授权 | 本文件 §1/§2；安装包 `THIRD_PARTY_NOTICES.md`；About 对话框 |
| §4(b) 随附 LGPLv3 与 GPLv3 全文 | `docs/licenses/LGPL-3.0.txt`、`docs/licenses/GPL-3.0.txt` |
| §4(c) 保留版权声明 | 本文件 §1/§2 版权行；About 对话框 |
| §4(d)(1) 使用可替换的共享库机制 | §4 替换步骤 + 动态链接事实（76 个独立 `Qt6*.dll`） |
| §4 末段 不得附加限制 | 本项目的 AGPL 与数据署名条款仅约束本项目代码与输出，不对 Qt 施加额外限制 |
| §2/§4 修改须公开 | 本项目**未修改** Qt/PySide6（仅使用官方 wheel） |

---

## 6. 关于 Qt 工具与 Qt GPL Exception 1.0

Qt 的**工具**（`uic`、`rcc`、`moc`、`designer`、`linguist`、`lupdate`、`lrelease`、`qml*` 等）不是 LGPLv3 库，而是 **GPLv3 + Qt GPL Exception 1.0**（例外允许其输出/插件组合以自选条款使用）。本项目：

- 在**开发/构建期**可能调用 `pyside6-uic` / `rcc` 等工具生成代码——这属于工具正常使用，不污染应用代码（例外条款覆盖）。
- **发布包中不附带**上述 Qt 工具可执行文件（发布前按 `LICENSES.md` §4.3 剪裁）；如确需附带，须同时分发 `docs/licenses/Qt-GPL-exception-1.0.txt` 并履行 GPLv3 源码义务。

---

## 7. 禁止事项（发布前自检）

- ❌ 不得把 Qt 静态链接进主程序（除非同时购买商业许可）。
- ❌ 不得删除/替换 Qt 的版权声明后声称是自研 GUI 框架。
- ❌ 不得使用 Qt Charts / Quick 3D / Virtual Keyboard / Lottie / Quick Timeline 等 GPLv3-only 模块（见 `LICENSES.md` §4.2）。
- ❌ 不得在安装包中保留 wheel 自带的 GPL-only 构件（`Qt6Lottie*.dll`、`Qt6QuickTimeline*.dll`、`qml\QtQuick\Timeline\**`、`qml\QtQuick\VirtualKeyboard\**`、Qt 工具 exe），除非履行 GPLv3 义务并经法务批准。
- ❌ 不得对 LGPLv3 组件附加「禁止替换/禁止逆向」等额外限制。

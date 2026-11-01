# 启动说明

## 最快的方式

双击或命令行运行：

```powershell
E:\CODEX-NOworkspaces\fysat\bin\fysat-gui.cmd
```

无控制台窗口，直接弹出图形界面。

带文件直接打开：

```powershell
E:\CODEX-NOworkspaces\fysat\bin\fysat-gui.cmd "Y:\download-data\FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20261027120000_20261027121459_4000M_V0001.HDF"
```

---

## 三种启动方式

### 1. 图形界面

| 命令 | 用途 |
|---|---|
| `bin\fysat-gui.cmd` | 正常启动，无控制台窗口 |
| `bin\fysat-gui-debug.cmd` | 带控制台，出问题看日志（启动失败时用这个） |
| `bin\fysat.cmd gui` | 命令行方式启动 GUI |

### 2. 命令行

```powershell
bin\fysat.cmd --version
bin\fysat.cmd info <文件>              # 文件概况：卫星/仪器/变量/定位
bin\fysat.cmd ls <文件>                # 内部结构
bin\fysat.cmd vars <文件> --only2d     # 可导出的二维变量
bin\fysat.cmd export ...               # 导出（见下）
bin\fysat.cmd formats                  # 三种导出形式说明
```

### 3. 直接用 Python（不依赖 .cmd）

```powershell
E:\venv\fysat\Scripts\python.exe -m fysat.cli --version
E:\venv\fysat\Scripts\python.exe -m fysat.gui.app
```

> 若不用 `bin\*.cmd`，需先设 `PYTHONPATH=E:\CODEX-NOworkspaces\fysat\src`。
> 当前环境已通过 `fysat_src.pth` 把 `src` 挂进 venv，所以 `python -c "import fysat"` 直接可用。

---

## 把 `fysat` 加成全局命令（可选）

把 bin 目录加进用户 PATH，之后任意目录都能直接敲 `fysat`：

```powershell
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "User") + ";E:\CODEX-NOworkspaces\fysat\bin",
  "User"
)
```

新开一个终端生效，然后：

```powershell
fysat info "Y:\download-data\xxx.HDF"
fysat-gui
```

---

## 导出示例

```powershell
# TIFF 全画质（保留原始 16 位 DN）
bin\fysat.cmd export "Y:\...\FY4B-...1000M_V0001.HDF" Data/NOMChannel02 `
    --kind tiff --out D:\out\ch02.tif

# PNG 全画质（16 位无损，原始分辨率）
bin\fysat.cmd export "..." Data/NOMChannel02 --kind png_full --out D:\out\ch02.png

# PNG 压缩强度可调（8 位，可缩放）
bin\fysat.cmd export "..." Data/NOMChannel02 --kind png_compressed `
    --out D:\out\ch02_s.png --level 9 --scale 0.25 --cmap turbo

# 物理量（先定标再导出）
bin\fysat.cmd export "..." Data/NOMChannel02 --physical --kind png_full --out a.png

# 通配符批量
bin\fysat.cmd export "..." "Data/NOMChannel0*" --kind png_compressed --out D:\out\batch.png
```

导出的 TIFF/PNG 会自动带溯源元数据（软件名、版本、AGPL 许可、是否修改、git commit、生成时间）：

```powershell
E:\venv\fysat\Scripts\python.exe -c "import sys; sys.path.insert(0,'E:\CODEX-NOworkspaces\fysat\src'); from fysat.provenance import read_png_provenance; print(read_png_provenance(r'D:\out\ch02_s.png'))"
```

---

## GUI 操作

| 操作 | 说明 |
|---|---|
| `Ctrl+O` | 打开单个产品文件 |
| `Ctrl+Shift+O` / 左栏「打开目录」 | 打开目录，按容器类型分组列出 |
| 双击文件 / 双击变量 | 打开产品 / 显示变量 |
| 滚轮 | 缩放（0.01x – 80x） |
| 拖动 | 平移 |
| `F` 或 `0` | 适应窗口 |
| `1` | 1:1 原始像素 |
| 工具栏「框选」 | 拖拽选区，`Esc` 退出 |
| `Ctrl+E` | 导出（三种形式） |
| 鼠标移动 | 状态栏显示像素坐标、值、缩放比例、经纬度范围 |

右侧三个标签页：

- **属性** — 卫星/仪器/层级/时间/定位范围 + 完整全局属性表
- **变量** — 所有变量及形状、类型、单位
- **显示** — 色标、拉伸区间、伽马、RGB 三通道合成

---

## 常见问题

**启动没反应 / 闪退**
用 `bin\fysat-gui-debug.cmd` 启动，会保留控制台并打印错误。

**中文显示成方框**
`theme.ensure_cjk_font()` 会自动注册微软雅黑。若仍异常，检查 `C:\Windows\Fonts\msyh.ttc` 是否存在。

**`ImportError: No module named PySide6`**
```powershell
E:\venv\fysat\Scripts\python.exe -m pip install PySide6-Essentials==6.12.0
```
注意**不要**装裸 `PySide6`——会拉入含 GPL-only 模块的 Addons，违反本项目的 LGPLv3 合规约束。

**磁盘空间**
C: 已满。pip 缓存与临时目录请指向 E:：
```powershell
$env:PIP_CACHE_DIR='E:\pipcache'; $env:TMP='E:\tmp'; $env:TEMP='E:\tmp'
```

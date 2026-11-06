# 开发工作流

## Git 提交规范

仓库：`<repo>`（本地初始化，主分支 `main`）

### 提交信息格式

```
<type>: <简短摘要>

<正文：做了什么、为什么>

## 验证
<测试命令与结果>
```

`type` 取：`feat` 新功能 / `fix` 修 bug / `refactor` 重构 / `test` 测试 / `docs` 文档 / `chore` 杂项

### 签名

所有提交使用 GPG 签名（YubiKey 硬件密钥）：

```powershell
git config user.signingkey C8922CEE7E3B6239E76380AC444F3D4763360C7B
git config commit.gpgsign true
git config gpg.program "D:\Gpg4win\..\GnuPG\bin\gpg.exe"
```

**签名超时处理**：若 YubiKey 未插入或签名等待超时，本次改用
`git commit --no-gpg-sign`，并在提交信息末尾加一行：

```
Unsigned-By-Design: <原因，例如 YubiKey 不在位 / 签名超时>
```

事后补签可用：`git rebase --exec 'git commit --amend --no-edit -S' <base>`

### 校验

```powershell
git log --show-signature -1     # 查看最近一次提交的签名
git log --oneline --graph       # 查看历史
```

---

## 提交粒度

一次提交只做一件事，且**必须是可运行状态**：

- 提交前跑 `pytest tests -q`，失败的测试不许进仓库（除非测试本身标记 `xfail` 并写明原因）
- 大数据样本（`.hdf/.dat/.l1b/.nc/.awx`）与 `out/`、`scratch/` 一律不入库（见 `.gitignore`）
- 探针脚本放 `scratch/`，成熟后提炼进 `src/` 或 `tests/` 再提交

## 多人协作

多个 agent 并行开发时，按**文件边界**分工，避免同时改同一个文件：

| 成员 | 负责文件 |
|---|---|
| Lead | `model.py` `detect.py` `export.py` `render.py` `palettes.py` `cli.py` `readers/__init__.py` `readers/hdf5.py` `README.md` `PLAN.md` |
| reader-binary | `readers/oneb.py` `readers/awx.py` + 对应测试 |
| reader-container | `readers/fy2_csv.py` `readers/nc3.py` + 对应测试 |
| calib-geo | `calib.py` `geo.py` + 对应测试 |

提交时只 `git add` 自己负责且已完成的文件，不要 `git add -A`，
避免把队友写了一半的文件带进仓库。

---

## 环境

| 项 | 位置 |
|---|---|
| Python | `<venv>\Scripts\python.exe`（system-site-packages，复用 <python> 的库） |
| 源码挂载 | `<venv>\Lib\site-packages\fysat_src.pth` → `src/` |
| 临时目录 | `E:\tmp`（C: 已满，务必用 E:） |
| 依赖缓存 | `E:\pipcache` |

> C: 盘可用空间常年接近 0，任何 pip 安装、构建、临时文件都必须指向 E:。

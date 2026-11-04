# -*- coding: utf-8 -*-
"""按产品/仪器提供合成配方，并把「通道号」解析成实际的数据集+下标。

为什么单独建一套
----------------
不同仪器的通道组织方式完全不同：

* **FY-3 MERSI**：25 个通道分散在 4 个多通道堆栈里，
  靠每个数据集自带的 ``band_name`` 属性（"1,2,3,4"/"5-19"/…）定位。
* **FY-4 AGRI / GHI**：每个通道一个独立 SDS，命名 ``Data/NOMChannelNN``。
* **FY-2 FDI / AVHRR 1B**：变量名直接带通道名（``NOMChannelIR1`` / ``IR1`` / ``CH1``）。

所以 ``bands.yml`` 里每个仪器都写了 ``locate`` 策略，
由本模块按策略把「通道号」翻成「(变量名, 数组下标)」。

配方本身在 ``composites.yml``，只引用通道号，不掺和定位细节。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
BANDS_FILE = HERE / "bands.yml"
COMPOSITES_FILE = HERE / "composites.yml"


# ---------------- 表加载 ----------------

@lru_cache(maxsize=1)
def _bands() -> dict:
    with open(BANDS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _composites() -> dict:
    with open(COMPOSITES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def instruments() -> dict:
    return _bands().get("instruments", {})


def band_table(instrument: str) -> dict[int, dict]:
    inst = instruments().get(instrument) or {}
    raw = inst.get("channels") or {}
    return {int(k): v for k, v in raw.items()}


def band_wavelength(instrument: str, channel: int) -> float | None:
    """取通道中心波长（µm）；只给了 range 时取中点。"""
    c = band_table(instrument).get(channel)
    if not c:
        return None
    if "um" in c:
        return float(c["um"])
    r = c.get("range")
    if r and len(r) == 2:
        return (float(r[0]) + float(r[1])) / 2.0
    return None


# ---------------- 仪器识别 ----------------

def instrument_of(ds) -> str | None:
    """从 SatDataset 判断用哪张波段表。"""
    text = " ".join(str(x or "") for x in (
        getattr(ds, "instrument", ""),
        getattr(ds, "sensor", ""),
        getattr(ds, "product", ""),
        getattr(ds, "dataset_name", ""),
    )).upper()

    names = getattr(ds, "variables", {}) or {}
    joined = " ".join(names).upper()

    if "MERSI" in text or "EV_1KM_REFSB" in joined:
        return "mersi"
    if "GHI" in text or ("NOMCHANNEL06" in joined and "NOMCHANNEL15" not in joined):
        return "ghi"
    if "AGRI" in text or "NOMCHANNEL15" in joined:
        return "agri"
    if "AVHRR" in text:
        return "avhrr"
    if any(k in text for k in ("VISSR", "FDI", "S-VISSR")) or "NOMCHANNELIR1" in joined:
        return "vissr"
    if re.search(r"\bFY-?2", text):
        return "vissr"
    return None


# ---------------- 通道定位 ----------------

@dataclass(frozen=True)
class ChannelRef:
    channel: int
    variable: str
    index: int

    @property
    def ok(self) -> bool:
        return bool(self.variable)


_PATTERNS = {
    # 通道号 → 候选变量路径（按优先顺序，{} 为两位补零）
    "nomchannel": [
        "Data/NOMChannel{n:02d}", "NOMChannel{n:02d}",
        "Data/NOMChannel{n}", "NOMChannel{n}",
    ],
}


def _find_variable(names, candidates) -> str | None:
    lower = {n.lower(): n for n in names}
    for cand in candidates:
        hit = lower.get(cand.lower())
        if hit:
            return hit
    return None


def _locate_by_band_name(ds, channel: int) -> tuple[str, int] | None:
    from ..gui.bandindex import band_index

    ref = band_index(ds).get(channel)
    return (ref.variable, ref.index) if ref else None


def _locate_nomchannel(ds, channel: int) -> tuple[str, int] | None:
    names = list(getattr(ds, "variables", {}) or {})
    got = _find_variable(names, [p.format(n=channel) for p in _PATTERNS["nomchannel"]])
    if got:
        return (got, 0)
    # GHI 的 NOMChannel01 是"全色"，而 AGRI 的 01 是 0.47µm —— 都按编号走
    return None


def _locate_named(ds, channel: int) -> tuple[str, int] | None:
    """按变量名里的通道标识定位（IR1/VS1/CH1/…）。"""
    names = list(getattr(ds, "variables", {}) or {})
    cands: list[str] = []
    for tag in (f"IR{channel}", f"VIS{channel}", f"VS{channel}", f"CH{channel}"):
        cands += [f"Data/NOMChannel{tag}", f"NOMChannel{tag}", tag, f"Data/{tag}"]
    got = _find_variable(names, cands)
    return (got, 0) if got else None


_LOCATORS = {
    "band_name": _locate_by_band_name,
    "nomchannel": _locate_nomchannel,
    "named": _locate_named,
}


def locate_channel(ds, instrument: str, channel: int) -> ChannelRef:
    """把通道号解析成 (变量, 下标)。解析不出来时 variable 为空串。"""
    inst = instruments().get(instrument) or {}
    strategy = inst.get("locate", "named")
    fn = _LOCATORS.get(strategy)
    if fn is None:
        return ChannelRef(channel, "", 0)
    got = fn(ds, channel)
    if got is None:
        # 退一步：都试一遍（不同卫星的文件组织略有差别）
        for alt in ("band_name", "nomchannel", "named"):
            if alt == strategy:
                continue
            got = _LOCATORS[alt](ds, channel)
            if got:
                break
    if not got:
        return ChannelRef(channel, "", 0)
    return ChannelRef(channel, got[0], got[1])


# ---------------- 合成配方 ----------------

@dataclass(frozen=True)
class Composite:
    key: str
    label: str
    desc: str
    kind: str                      # rgb | single
    channels: tuple[int, ...]
    cmap: str = "gray"
    refs: tuple[ChannelRef, ...] = ()

    @property
    def ready(self) -> bool:
        return all(r.ok for r in self.refs)

    def missing(self) -> list[int]:
        return [r.channel for r in self.refs if not r.ok]

    def summary(self) -> str:
        return " ".join(f"{r.channel}→{r.variable}[{r.index}]" for r in self.refs)


def composites_for(ds, instrument: str | None = None) -> list[Composite]:
    """返回该数据集上**可执行**的合成（通道全部定位成功的）。"""
    inst = instrument or instrument_of(ds)
    if not inst:
        return []
    raw = (_composites().get("composites") or {}).get(inst) or []
    out: list[Composite] = []
    for item in raw:
        chans = tuple(int(c) for c in (item.get("channels") or []))
        if not chans:
            continue
        refs = tuple(locate_channel(ds, inst, c) for c in chans)
        comp = Composite(
            key=str(item["key"]),
            label=str(item.get("label", item["key"])),
            desc=str(item.get("desc", "")),
            kind=str(item.get("kind", "single")),
            channels=chans,
            cmap=str(item.get("cmap", "gray")),
            refs=refs,
        )
        out.append(comp)
    return out


def ready_composites(ds, instrument: str | None = None) -> list[Composite]:
    return [c for c in composites_for(ds, instrument) if c.ready]


def find(ds, key: str, instrument: str | None = None) -> Composite | None:
    for c in composites_for(ds, instrument):
        if c.key == key and c.ready:
            return c
    return None

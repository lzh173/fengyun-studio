# -*- coding: utf-8 -*-
"""从真实 FY-3H MERSI L1 文件生成"制图样板图"（与用户示例同风格）。

用于验证：定标（VIS_Cal_Coeff / 辐亮度→亮温）+ GEO 定位 + 海岸线叠加 + 经纬格 + 双面板出图。
"""
import json
import os

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

SRC = r"E:\QQ_DW\FY3H_MERSI_GRAN_L1_20261101_0405_0250M_V0.HDF"
GEOJSON = r"<repo>\assets\ne_110m_coastline.geojson"
OUT = r"<repo>\samples\fy3h_mersi_l1_figure.png"

# 普朗克反演常数（L 单位 mW/(m2 sr cm-1)）
C1 = 1.1910427e-5
C2 = 1.4387752
NU_CH24 = 1e4 / 10.7  # cm-1

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def percent_stretch(a, lo=2, hi=98):
    v = a[np.isfinite(a)]
    if v.size == 0:
        return np.zeros_like(a, dtype=float)
    p1, p2 = np.percentile(v, lo), np.percentile(v, hi)
    if p2 <= p1:
        p2 = p1 + 1e-6
    return np.clip((a - p1) / (p2 - p1), 0, 1)


def main():
    with h5py.File(SRC, "r") as f:
        cal = f["Calibration/VIS_Cal_Coeff"][:]          # (19,3) intercept, slope, quad
        lat = f["GEO/Latitude"][:]                        # (400,410)
        lon = f["GEO/Longitude"][:]                       # (400,410)
        # 抽稀到 GEO 网格（每 20 像元一个格点）
        def band(name):
            d = f["Data"][name]
            return np.asarray(d[::20, ::20], dtype=np.float64)

        b1 = band("EV_250_RefSB_b1")
        b2 = band("EV_250_RefSB_b2")
        b3 = band("EV_250_RefSB_b3")
        b24 = band("EV_250_Emissive_b24")

    def refl(dn, idx):
        c = cal[idx]
        return np.clip(c[0] + c[1] * dn, 0, 100) / 100.0

    r, g, b = refl(b3, 2), refl(b2, 1), refl(b1, 0)      # 0.65 / 0.55 / 0.47 µm
    rgb = np.dstack([percent_stretch(r), percent_stretch(g), percent_stretch(b)])
    rgb[~np.isfinite(rgb)] = 0

    # 辐亮度 → 亮温（K），再转摄氏作图
    L = np.where(b24 == 65535, np.nan, b24 * 0.01)
    with np.errstate(invalid="ignore", divide="ignore"):
        bt = (C2 * NU_CH24) / np.log(C1 * NU_CH24 ** 3 / L + 1.0)
    bt = np.where((bt > 100) & (bt < 400), bt, np.nan)
    bt_c = bt - 273.15

    # 海岸线
    coast = []
    if os.path.exists(GEOJSON):
        gj = json.load(open(GEOJSON, encoding="utf-8"))
        for feat in gj.get("features", []):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            if geom.get("type") == "LineString":
                coast.append(np.array(coords))
            elif geom.get("type") == "MultiLineString":
                coast.extend(np.array(c) for c in coords)

    cmap_bt = plt.get_cmap("turbo").copy()

    fig, axes = plt.subplots(1, 2, figsize=(14.6, 7.0), dpi=160)
    fig.patch.set_facecolor("white")

    lon0, lon1 = np.nanmin(lon), np.nanmax(lon)
    lat0, lat1 = np.nanmin(lat), np.nanmax(lat)

    # 左：真彩色
    ax = axes[0]
    ax.pcolormesh(lon, lat, rgb, shading="nearest", rasterized=True)
    for seg in coast:
        ax.plot(seg[:, 0], seg[:, 1], color="#7dd3fc", lw=0.55, alpha=0.85)
    ax.set_title("可见光真彩色", fontsize=11)

    # 右：红外亮温
    ax2 = axes[1]
    m = ax2.pcolormesh(lon, lat, bt_c, shading="nearest", cmap=cmap_bt, vmin=-100, vmax=40, rasterized=True)
    for seg in coast:
        ax2.plot(seg[:, 0], seg[:, 1], color="#0f172a", lw=0.55, alpha=0.75)
    ax2.set_title("红外亮温 CH24 10.7 μm  地表温度/SST", fontsize=11)
    cb = fig.colorbar(m, ax=ax2, fraction=0.035, pad=0.02)
    cb.set_label("BT (℃)", fontsize=9)
    cb.ax.tick_params(labelsize=8)

    for ax in axes:
        ax.set_xlim(lon0 - 0.4, lon1 + 0.4)
        ax.set_ylim(lat0 - 0.4, lat1 + 0.4)
        ax.set_aspect("equal")
        ax.tick_params(labelsize=8)
        ax.set_xticks(np.arange(np.floor(lon0 / 5) * 5, lon1 + 5, 5))
        ax.set_yticks(np.arange(np.floor(lat0 / 4) * 4, lat1 + 4, 4))
        ax.set_xticklabels([f"{int(v)}°E" for v in ax.get_xticks()], fontsize=8)
        ax.set_yticklabels([f"{int(v)}°N" if v >= 0 else f"{abs(int(v))}°S" for v in ax.get_yticks()], fontsize=8)
        ax.grid(color="#94a3b8", lw=0.35, alpha=0.6, linestyle=":")
        for s in ax.spines.values():
            s.set_color("#cbd5e1")

    fig.suptitle("FY-3H MERSI-III L1  2026-11-01 04:50z  orbit 16831  |  可见光 + 红外",
                 fontsize=12.5, y=0.985)
    fig.text(0.012, 0.975, "FY3H_MERSI_GRAN_L1_20261101_0405_0250M_V0.HDF", fontsize=8, color="#334155")
    stats = f"[Tmax, Tmin] = ({np.nanmax(bt_c):.2f}, {np.nanmin(bt_c):.2f}) °C"
    fig.text(0.988, 0.975, stats, fontsize=8, color="#334155", ha="right")
    fig.text(0.012, 0.012, "Made by FY-Sat Studio  |  FY-3H MERSI-III  2026-11-01 04:50:01Z", fontsize=8.5,
             color="#e2e8f0", bbox=dict(facecolor="#0f172a", edgecolor="none", pad=4))

    fig.subplots_adjust(left=0.045, right=0.965, top=0.90, bottom=0.07, wspace=0.10)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, facecolor="white")
    print("saved", OUT, os.path.getsize(OUT) // 1024, "KB")

    # 供 UI 稿内嵌的缩略图
    from PIL import Image
    im = Image.open(OUT).convert("RGB")
    im.thumbnail((1500, 1500), Image.LANCZOS)
    thumb = os.path.join(os.path.dirname(OUT), "figure_preview.jpg")
    im.save(thumb, quality=90)
    print("thumb", thumb, im.size)

    print("BT(C) range", float(np.nanmin(bt_c)), float(np.nanmax(bt_c)))


if __name__ == "__main__":
    main()

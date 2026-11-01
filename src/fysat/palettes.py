"""业务级红外配色：把亮温（K）映射成常用的增强红外色表。

为什么不用 turbo：turbo 在 190–320 K 这种宽区间里会把大部分晴空海面压成一片橙，
看不出层次。这里用分段色表，让对流云顶、卷云、低云、晴空各自有清晰的颜色。
"""
from __future__ import annotations

import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# 增强红外色表（从冷到暖）：深紫 → 蓝 → 青 → 绿 → 黄 → 橙 → 红 → 深红
IR_ENHANCED_STOPS = [
    (0.00, "#2b0b3f"),
    (0.12, "#3b2f8f"),
    (0.26, "#2b7bba"),
    (0.40, "#3fc0c8"),
    (0.52, "#7ede8a"),
    (0.64, "#e8e05a"),
    (0.76, "#f2a03d"),
    (0.88, "#e2562b"),
    (1.00, "#8f1d1d"),
]

# 中国气象业务常用的分段（℃）：更贴近业务习惯
IR_TEMP_BREAKS_C = [-80, -70, -60, -50, -40, -30, -20, -10, 0, 10, 20, 30]


def ir_enhanced_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("ir_enhanced", IR_ENHANCED_STOPS)


def bt_to_rgb(bt_k: np.ndarray, vmin_k: float = 190.0, vmax_k: float = 320.0) -> np.ndarray:
    """亮温（K）→ uint8 RGB，使用增强红外色表。"""
    cm = ir_enhanced_cmap()
    v = np.asarray(bt_k, dtype=np.float32)
    x = np.clip((v - vmin_k) / max(vmax_k - vmin_k, 1e-6), 0.0, 1.0)
    rgba = cm(x)
    rgb = (rgba[..., :3] * 255.0 + 0.5).astype(np.uint8)
    rgb[~np.isfinite(v)] = 0          # 无效像元压黑
    return rgb


def bt_legend(vmin_k: float = 190.0, vmax_k: float = 320.0, n: int = 5) -> list[tuple[float, str]]:
    """给制图用的色标刻度（K 与 ℃）。"""
    out = []
    for i in range(n):
        k = vmin_k + (vmax_k - vmin_k) * i / (n - 1)
        out.append((k, f"{k - 273.15:.0f}℃"))
    return out

"""GUI 层（PySide6）。

设计原则
--------
1. **UI 层薄**：所有业务逻辑留在 ``fysat.*`` 核心包里，GUI 只做展示与交互，
   这样核心可被 CLI/批处理复用，也便于无头测试。
2. **可无头测试**：用 ``QT_QPA_PLATFORM=offscreen`` 即可在 CI 里跑，不需要显示器。
3. **许可证**：PySide6 走 LGPLv3（动态链接），不引入任何 GPL-only 的 Qt 模块。
   允许使用的模块见 ``ALLOWED_QT_MODULES``，导入前请自查。

模块划分
--------
- ``app.py``        应用入口、全局样式、异常兜底
- ``mainwindow.py`` 主窗口：数据树 / 视图画布 / 属性面板 / 状态栏
- ``imageview.py``  影像画布（缩放、平移、像素取值、框选）
- ``explorer.py``   数据源树（目录 → 卫星 → 产品）
- ``inspector.py``  变量与属性面板
- ``workers.py``    后台任务（读取/渲染不阻塞 UI）
- ``theme.py``      深色样式表（与 ui-mockup 的设计稿一致）
"""
from __future__ import annotations

# LGPLv3 可用的 Qt 模块白名单（分发前由 license-audit 复核）
# 明确禁止：QtCharts / QtDataVisualization / QtVirtualKeyboard / QtQuick3D 等 GPL-only
ALLOWED_QT_MODULES = {
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtOpenGL",
    "QtOpenGLWidgets", "QtSvg", "QtPrintSupport", "QtConcurrent",
}

__all__ = ["ALLOWED_QT_MODULES"]

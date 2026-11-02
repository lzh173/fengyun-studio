"""FY-Sat Studio 核心包。"""
from __future__ import annotations

__version__ = "0.1.0"

from .model import Geolocation, SatDataset, Variable  # noqa: E402
from .readers import open_file, register  # noqa: E402

__all__ = ["SatDataset", "Variable", "Geolocation", "open_file", "register", "__version__"]
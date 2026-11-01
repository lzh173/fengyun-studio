# -*- coding: utf-8 -*-
"""探测 Y:\download-data 中每个数据族的真实容器格式（忽略 .enp）。"""
import os

import h5py

ROOT = r"Y:\download-data"
SKIP = {".enp", ".db", ".png", ".jpg", ".json", ".xml", ".txt", ".csv", ".npy", ".npz", ".cbor"}


def verdict_of(path):
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head[:4] == b"\x0e\x03\x13\x01":
        return "HDF4"
    if head[:8] == b"\x89HDF\r\n\x1a\n":
        return "HDF5"
    if head[:3] == b"CDF":
        return "NetCDF-3"
    if head[:4] == b"GRIB":
        return "GRIB"
    if head[:2] == b"\xff\xd8":
        return "JPEG"
    if head[:2] == b"AW":
        return "AWX"
    return "raw/自定义"


def main():
    seen = {}
    for dp, dn, fn in os.walk(ROOT):
        for f in fn:
            e = os.path.splitext(f)[1].lower()
            if e in SKIP:
                continue
            key = (e, f[:3].upper())
            if key not in seen:
                seen[key] = os.path.join(dp, f)

    print(f"{'ext':7s}{'head':6s}{'size':>10s}  {'magic':14s}{'h5py':6s}file")
    for (e, p), path in sorted(seen.items()):
        try:
            sz = os.path.getsize(path) / 1e6
            v = verdict_of(path)
            try:
                h5 = h5py.is_hdf5(path)
            except Exception:
                h5 = "err"
            print(f"{e:7s}{p:6s}{sz:9.1f}M  {v:14s}{h5!s:6s}{os.path.basename(path)[:70]}")
        except Exception as ex:
            print("ERR", path, ex)


if __name__ == "__main__":
    main()

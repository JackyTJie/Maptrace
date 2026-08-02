#!/usr/bin/env python3
"""Extract photo metadata (filename, timestamp, GPS) from date-named album folders.
Read-only on the source folder; writes only to the output dir.

Usage:
    python3 extract_gps.py <source_dir> [output_dir] [start_date] [end_date]
    python3 extract_gps.py ./photos/2026 gps_data 2026-01-12 2026-02-06
    python3 extract_gps.py ./photos/2026    # output gps_data, all folders
"""

import os
import sys
from datetime import datetime
from PIL import Image

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

EXIF_DATETIME = 306
EXIF_DATETIME_ORIG = 36867
EXIF_GPS = 34853


def to_decimal(ref, coord):
    if not coord:
        return None
    def val(x):
        if hasattr(x, "numerator"):
            return x.numerator / x.denominator
        return float(x)
    d = val(coord[0])
    m = val(coord[1]) if len(coord) > 1 else 0.0
    s = val(coord[2]) if len(coord) > 2 else 0.0
    v = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        v = -v
    return round(v, 6)


def fmt_ts(raw):
    try:
        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw.strip()


def extract(path):
    ts = None
    gps = None
    try:
        img = Image.open(path)
        exif = img.getexif()
        raw = exif.get(EXIF_DATETIME_ORIG) or exif.get(EXIF_DATETIME)
        if raw:
            ts = fmt_ts(raw)
        gps_ifd = exif.get_ifd(EXIF_GPS)
        lat = to_decimal(gps_ifd.get(1), gps_ifd.get(2))
        lon = to_decimal(gps_ifd.get(3), gps_ifd.get(4))
        if lat is not None and lon is not None:
            gps = f"{lat},{lon}"
    except Exception:
        pass
    if ts is None:
        ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    return ts, gps if gps else "no GPS"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "gps_data"
    start = sys.argv[3] if len(sys.argv) > 3 else None
    end = sys.argv[4] if len(sys.argv) > 4 else None

    os.makedirs(out, exist_ok=True)
    folders = sorted(d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d)))
    if start:
        folders = [d for d in folders if d >= start]
    if end:
        folders = [d for d in folders if d <= end]

    print(f"Source: {src}")
    print(f"Folders in range: {len(folders)}" + (f" ({folders[0]} .. {folders[-1]})" if folders else ""))
    total = 0
    for day in folders:
        daydir = os.path.join(src, day)
        files = sorted(
            f for f in os.listdir(daydir)
            if os.path.splitext(f)[1].lower() in IMG_EXTS
        )
        lines = []
        for f in files:
            ts, gps = extract(os.path.join(daydir, f))
            lines.append(f"{f}\t{ts}\t{gps}")
            total += 1
        out_path = os.path.join(out, f"{day}.txt")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"  {day}.txt  {len(lines)} photos")
    print(f"TOTAL photos: {total}, files written to {out}/")


if __name__ == "__main__":
    sys.exit(main())

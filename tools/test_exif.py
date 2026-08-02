from PIL import Image
import sys

path = sys.argv[1]
img = Image.open(path)
exif = img.getexif()
print("DateTimeOriginal:", exif.get(36867))
print("DateTime:", exif.get(306))
gps = exif.get_ifd(34853)
for k, v in gps.items():
    print(f"GPS tag {k}: {v}")

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

lat = to_decimal(gps.get(1), gps.get(2))
lon = to_decimal(gps.get(3), gps.get(4))
print("GPS decimal:", lat, lon)

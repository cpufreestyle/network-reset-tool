"""Generate ICO with CORRECT 16-byte directory entries (BMP format)."""
from PIL import Image
import os, struct

BASE = r"D:\qclaw-workspace\network-reset-tool"
src = Image.open(os.path.join(BASE, "icon_preview.png")).convert("RGBA")
sizes = [16, 24, 32, 48, 64, 128, 256]

def make_bmp_data(img):
    """RGBA -> ICO BMP (BGRA + AND mask)."""
    w, h = img.size
    # BITMAPINFOHEADER: 40 bytes
    # BITMAPINFOHEADER (40 bytes):
    # biSize(4) biWidth(4) biHeight(4) biPlanes(2) biBitCount(2)
    # biCompression(4) biSizeImage(4) biXPelsPerMeter(4) biYPelsPerMeter(4) biClrUsed(4) biClrImportant(4)
    info = struct.pack('<I  i  i  H H  I  I  i  i  I  I',
        40, w, h*2, 1, 32, 0, 0, 0, 0, 0, 0)
    # BGRA pixels
    bgra = img.tobytes('raw', 'BGRA')
    # AND mask
    row_size = ((w + 31) // 32) * 4
    and_mask = bytes(row_size * h)
    return info + bgra + and_mask

# Generate all image data first
bmp_datas = [make_bmp_data(src.resize((s,s), Image.LANCZOS)) for s in sizes]

# Directory entry is exactly 16 bytes: BBBBhhII (or bbbbhhiin PyInstaller terms)
# bWidth(1) bHeight(1) bColorCount(1) bReserved(1) wPlanes(2) wBitCount(2) dwBytesInRes(4) dwImageOffset(4)
dir_size = 6 + 16 * len(sizes)  # header + entries
offsets = []
cur = dir_size
for bd in bmp_datas:
    offsets.append(cur)
    cur += len(bd)

ico_path = os.path.join(BASE, "icon.ico")
with open(ico_path, 'wb') as f:
    # ICONDIR header (6 bytes): reserved(2) type(2) count(2)
    f.write(struct.pack('<HHH', 0, 1, len(sizes)))
    
    # ICONDIRENTRY (16 bytes each) - MUST match 'bbbbhhii'
    for i, s in enumerate(sizes):
        bw = s if s < 256 else 0
        bh = s if s < 256 else 0
        f.write(struct.pack('<BBBBhhII',
            bw, bh,       # width, height
            0, 0,         # color count, reserved
            1, 32,        # planes, bpp
            len(bmp_datas[i]),  # dwBytesInRes
            offsets[i]))       # dwImageOffset
    
    # Image data
    for bd in bmp_datas:
        f.write(bd)

fsize = os.path.getsize(ico_path)
print(f"ICO: {ico_path} ({fsize} bytes)")

# Verify with PyInstaller's exact format
with open(ico_path, 'rb') as f:
    v = f.read()
rsv, typ, cnt = struct.unpack_from('hhh', v, 0)
print(f"Verify: type={typ} count={cnt} filesize={len(v)}")
assert cnt == len(sizes), "count mismatch"
for i in range(cnt):
    off = 6 + i * 16
    w, h, cc, res, planes, bpp, sz, imgoff = struct.unpack_from('bbbbhhii', v, off)
    assert sz > 0, f"[{i}] dwBytesInRes negative or zero!"
    end = imgoff + sz
    assert end <= len(v), f"[{i}] data exceeds file! ({end} > {len(v)})"
    print(f"  [{i}] {w or 256}x{h or 256} planes={planes} bpp={bpp} size={sz} offset={imgoff} OK")
print("\nAll checks passed!")

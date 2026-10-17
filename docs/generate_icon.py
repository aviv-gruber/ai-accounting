#!/usr/bin/env python3
"""Generate simple PWA icons for SmartBooks AI."""
import struct, zlib, os

def create_png(width, height, pixels):
    """Create a minimal PNG from RGBA pixel data."""
    def chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))

    raw = b''
    for y in range(height):
        raw += b'\x00'  # filter byte
        for x in range(width):
            raw += pixels[y * width + x]
    idat = chunk(b'IDAT', zlib.compress(raw))
    iend = chunk(b'IEND', b'')
    return header + ihdr + idat + iend


def make_icon(size, filename):
    """Create a SmartBooks AI icon — blue gradient with ₪ symbol feel."""
    pixels = []
    for y in range(size):
        for x in range(size):
            # Gradient from dark blue to bright blue
            t = y / size
            r = int(30 + t * 7)      # 30 → 37
            g = int(58 + t * 41)     # 58 → 99
            b = int(95 + t * 140)    # 95 → 235

            # Rounded corners (radius = size/6)
            radius = size // 6
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            if dx < radius and dy < radius:
                dist = ((radius - dx)**2 + (radius - dy)**2) ** 0.5
                if dist > radius:
                    pixels.append(struct.pack('BBBB', 0, 0, 0, 0))
                    continue

            # Draw "SB" text area — a simple white rectangle block as logo mark
            cx, cy = size // 2, size // 2
            # Three horizontal bars (like a chart icon)
            bar_h = size // 14
            bar_gap = size // 8
            bars = [
                (cx - size//4, cy - bar_gap - bar_h, size//2, bar_h),
                (cx - size//5, cy - bar_h//2, size*2//5, bar_h),
                (cx - size//3, cy + bar_gap, size*2//3, bar_h),
            ]
            in_bar = False
            for bx, by, bw, bh in bars:
                if bx <= x < bx + bw and by <= y < by + bh:
                    in_bar = True
                    break

            if in_bar:
                pixels.append(struct.pack('BBBB', 255, 255, 255, 230))
            else:
                pixels.append(struct.pack('BBBB', r, g, b, 255))

    png = create_png(size, size, pixels)
    with open(filename, 'wb') as f:
        f.write(png)
    print(f"Created {filename} ({len(png)} bytes)")


if __name__ == '__main__':
    d = os.path.dirname(os.path.abspath(__file__))
    make_icon(192, os.path.join(d, 'icon-192.png'))
    make_icon(512, os.path.join(d, 'icon-512.png'))

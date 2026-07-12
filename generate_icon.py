"""
generate_icon.py

Builds the app icon from scratch with Pillow -- a simple, original paw-print
mark on a rounded gradient badge. Not a reproduction of any game's mascot
or logo; just a generic "pet/companion server" motif befitting a Palworld
tool. Run once to (re)generate assets/icon.png and assets/icon.ico.
"""

from pathlib import Path
from PIL import Image, ImageDraw

SIZE = 512
OUT_DIR = Path(__file__).parent / "assets"
OUT_DIR.mkdir(exist_ok=True)


def make_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square badge with a vertical gradient (deep teal -> amber-ish
    # slate), giving it a distinct identity from the default blue theme.
    pad = 8
    radius = 110
    top_color = (25, 58, 66)      # deep teal-slate
    bottom_color = (16, 38, 46)   # darker teal-slate

    grad = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for y in range(SIZE):
        t = y / SIZE
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        grad_draw.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))

    mask = Image.new("L", (SIZE, SIZE), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # Subtle inner border for polish
    draw.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=radius,
                            outline=(255, 255, 255, 35), width=4)

    # Paw print: one large pad + four toes, in a warm amber accent.
    accent = (240, 165, 60, 255)
    cx, cy = SIZE // 2, SIZE // 2 + 55

    pad_w, pad_h = 210, 170
    draw.ellipse([cx - pad_w // 2, cy - pad_h // 2, cx + pad_w // 2, cy + pad_h // 2], fill=accent)

    toe_r = 54
    toe_positions = [
        (cx - 108, cy - 128),
        (cx - 42, cy - 168),
        (cx + 42, cy - 168),
        (cx + 108, cy - 128),
    ]
    for (tx, ty) in toe_positions:
        draw.ellipse([tx - toe_r, ty - toe_r, tx + toe_r, ty + toe_r], fill=accent)

    return img


def main():
    icon = make_icon()
    png_path = OUT_DIR / "icon.png"
    icon.save(png_path)
    print(f"Wrote {png_path}")

    ico_path = OUT_DIR / "icon.ico"
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(ico_path, format="ICO", sizes=sizes)
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()

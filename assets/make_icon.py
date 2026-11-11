import math, random
from PIL import Image, ImageDraw, ImageFilter, ImageChops
random.seed(7)
N = 1024; K = 4; W = N * K

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))

# ── fond : squircle (superellipse) aux proportions macOS (corps 824/1024)
body = int(W * 824 / 1024); m0 = (W - body) // 2
pts = []
for i in range(720):
    a = 2 * math.pi * i / 720
    c, s = math.cos(a), math.sin(a)
    x = math.copysign(abs(c) ** (2 / 5), c); y = math.copysign(abs(s) ** (2 / 5), s)
    pts.append((W / 2 + x * body / 2, W / 2 + y * body / 2))
mask = Image.new("L", (W, W), 0); ImageDraw.Draw(mask).polygon(pts, fill=255)

# dégradé diagonal indigo → nuit
bg = Image.new("RGB", (W, W)); bd = ImageDraw.Draw(bg)
c0, c1 = (112, 78, 255), (18, 14, 60)
for k in range(2 * W):
    t = k / (2 * W)
    bd.line([(k, 0), (0, k)], fill=lerp(c0, c1, min(1, t * 1.15) ** 1.1), width=2)
bg = bg.convert("RGBA")
glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([W * .05, -W * .35, W * .75, W * .35], fill=(170, 140, 255, 120))
bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(W * .08)))

icon = Image.new("RGBA", (W, W), (0, 0, 0, 0))
shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(shadow).polygon(pts, fill=(10, 6, 40, 150))
icon.alpha_composite(ImageChops.offset(shadow.filter(ImageFilter.GaussianBlur(W * .018)), 0, int(W * .016)))
icon.paste(bg, (0, 0), mask)

# ── document qui se dissout en pixels
x0, x1 = int(W * .285), int(W * .715); y0, y1 = int(W * .205), int(W * .775)
fold = int(W * .11); cell = W // 76; gap = int(cell * .07)
doc = Image.new("RGBA", (W, W), (0, 0, 0, 0)); dd = ImageDraw.Draw(doc)
cols = (x1 - x0) // cell; rows = (y1 - y0) // cell
X0 = x0; Y0 = y0
def square(cx, cy, size, col):
    dd.rectangle([cx + gap, cy + gap, cx + size - gap, cy + size - gap], fill=col)
for r in range(rows):
    t = r / rows
    for c in range(cols):
        cx, cy = X0 + c * cell, Y0 + r * cell
        if (cx + cell / 2) - (x1 - fold) > (cy + cell / 2) - y0 and cy < y0 + fold:
            continue  # coin plié
        u = c / cols
        if t < .56:
            continue  # zone pleine dessinée d'un seul bloc
        else:
            keep = 1 - ((t - .56) / .44) ** .7 * (.7 + .5 * u)
            keep = min(keep, .97)
        if random.random() < keep:
            shade = 250 - int(10 * t)
            square(cx, cy, cell, (shade, shade, 255, 255))
        elif random.random() < .55 * (1 - t * .5):
            # pixels qui s'échappent vers le bas / la droite, de plus en plus pâles
            dx = int(cell * random.uniform(0.5, 4.5) * (0.4 + u)); dy = int(cell * random.uniform(0.3, 3.2))
            a = int(random.uniform(60, 190) * (1 - t * .55))
            sz = int(cell * random.choice([1, 1, .75, .55]))
            square(cx + dx, cy + dy, sz, (235, 232, 255, a))
solid_b = Y0 + int(.56 * rows) * cell
dd.polygon([(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, solid_b), (x0, solid_b)], fill=(251, 250, 255, 255))
dsh = Image.new("RGBA", (W, W), (0, 0, 0, 0)); dsh.paste((8, 4, 40, 120), (0, 0), doc.split()[3])
icon.alpha_composite(ImageChops.offset(dsh.filter(ImageFilter.GaussianBlur(W * .014)), 0, int(W * .014)))
icon.alpha_composite(doc)
d = ImageDraw.Draw(icon)
# pli
d.polygon([(x1 - fold, y0), (x1, y0 + fold), (x1 - fold, y0 + fold)], fill=(196, 186, 255, 255))
# lignes de texte (zone encore solide) + barre d'accent
ix = x0 + int(W * .045); iw = (x1 - x0) - int(W * .09)
d.rounded_rectangle([ix, y0 + int(W * .07), ix + int(iw * .46), y0 + int(W * .105)], radius=int(W * .018), fill=(70, 232, 170, 255))
for i, wf in enumerate([.9, .72, .82]):
    yy = y0 + int(W * (.15 + i * .06))
    d.rounded_rectangle([ix, yy, ix + int(iw * wf), yy + int(W * .02)], radius=int(W * .01), fill=(150, 138, 214, 255))

# ── reflet verre en haut + liseré
gl = Image.new("RGBA", (W, W), (0, 0, 0, 0)); gd = ImageDraw.Draw(gl)
for y in range(int(W * .55)):
    gd.line([(0, y + m0), (W, y + m0)], fill=(255, 255, 255, int(46 * (1 - y / (W * .55)) ** 1.6)))
clip = Image.new("RGBA", (W, W), (0, 0, 0, 0)); clip.paste(gl, (0, 0), mask); icon.alpha_composite(clip)
rim = Image.new("RGBA", (W, W), (0, 0, 0, 0)); ImageDraw.Draw(rim).polygon(pts, outline=(255, 255, 255, 70), width=K * 2)
icon.alpha_composite(rim)

icon.resize((N, N), Image.LANCZOS).save(__import__("sys").argv[1])

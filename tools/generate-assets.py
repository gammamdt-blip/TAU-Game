#!/usr/bin/env python3
"""
generate-assets.py - builds every image and sound used by TAU.

    python3 tools/generate-assets.py            # everything (images + audio + audio-data.js)
    python3 tools/generate-assets.py images     # only the artwork in assets/images/
    python3 tools/generate-assets.py audio      # only the sounds in assets/audio/ (+ audio-data.js)
    python3 tools/generate-assets.py bundle     # only rebuild assets/audio/audio-data.js from the .wav files
    python3 tools/generate-assets.py images skyline player   # only artwork whose name contains these words

Needs Python 3 with Pillow, NumPy and SciPy. Nothing here is needed to PLAY the game: the generated
files are committed in assets/. Run it when you want to re-theme or tweak the art/audio.

Sections (search for the banner comments):
    1. TOOLKIT            palette, noise, a supersampled drawing surface, small helpers
    2. SKY AND FOG        sky backdrop, fog bank
    3. SKYLINE LAYERS     the four parallax city layers (atmospheric -> near mid-ground)
    4. WALLS AND ROOFS    tileable textures for the playable buildings
    5. PROPS              antennas, vents, tanks, fences, obstacles, cranes, doors ...
    6. PLAYER             the runner sprite sheet (skeleton driven, 48 frames)
    7. ACTORS             mech, airship, gunship, drone, missile, particles, foreground, icons
    8. AUDIO              every sound effect, the ambience loops and the music
    9. MAIN

Every generator uses fixed random seeds, so the same files come out each time. Units: the game works in
"units" (the original game's pixels). Each image is drawn at PPU pixels per unit - the numbers in
assets.js (`ppu`) must match the PPU used here.
Original work, CC0.
"""
import base64
import io
import math
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage as ndi
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "assets" / "images"
AUDIO_DIR = ROOT / "assets" / "audio"

# ============================================================================
# 1. TOOLKIT
# ============================================================================
# ---- palette -------------------------------------------------------------------------------------
# Roughly 95% monochrome. The only chroma is a faint cold blue and the warning red / dim white lights.
PAL = {
    "black":      (7, 8, 10),
    "charcoal":   (14, 16, 19),
    "concrete_d": (26, 29, 33),
    "concrete":   (44, 49, 55),
    "concrete_l": (72, 79, 88),
    "steel":      (96, 105, 116),
    "steel_cold": (128, 140, 154),
    "fog":        (142, 150, 160),
    "fog_white":  (200, 206, 213),
    "light":      (222, 229, 235),
    "light_dim":  (190, 200, 210),
    "red":        (196, 38, 34),
    "red_dim":    (140, 28, 26),
}


def rgb(name):
    return np.array(PAL[name], dtype=np.float32)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rng(seed):
    return np.random.default_rng(seed)


def save_png(img, name, optimize=True):
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    path = IMG_DIR / name
    if name.endswith(".jpg"):
        img.convert("RGB").save(path, quality=92, subsampling=0, optimize=True)
    else:
        img.save(path, optimize=optimize)
    print("  %-34s %5dx%-5d %7.0f KB" % (name, img.width, img.height, path.stat().st_size / 1024))


def want(filters, name):
    """True when no filter words were given on the command line, or `name` contains one."""
    return not filters or any(f in name for f in filters)


# ---- noise ----------------------------------------------------------------------------------------
def fnoise(h, w, seed, beta=2.2, sx=1.0, sy=1.0):
    """Fractal (1/f^beta) noise in 0..1. Periodic in both axes, so it tiles. sx>1 stretches along x."""
    white = rng(seed).standard_normal((h, w)).astype(np.float32)
    fy = np.fft.fftfreq(h)[:, None].astype(np.float32) * sy
    fx = np.fft.rfftfreq(w)[None, :].astype(np.float32) * sx
    f = np.sqrt(fx * fx + fy * fy)
    f[0, 0] = 1.0
    spec = np.fft.rfft2(white) * (f ** (-beta / 2.0))
    spec[0, 0] = 0
    n = np.fft.irfft2(spec, s=(h, w)).astype(np.float32)
    lo, hi = np.percentile(n, [1, 99])
    return np.clip((n - lo) / (hi - lo + 1e-9), 0, 1)


def vgrad(h, w, stops):
    """Vertical colour gradient. stops = [(0..1, (r,g,b)), ...] -> float32 (h, w, 3)."""
    ys = np.linspace(0, 1, h, dtype=np.float32)
    cols = np.stack([np.interp(ys, [s[0] for s in stops], [s[1][c] for s in stops]) for c in range(3)], -1)
    return np.repeat(cols[:, None, :], w, axis=1).astype(np.float32)


def to_img(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def rgba_img(rgb_arr, alpha):
    a = np.clip(alpha, 0, 1)[..., None] * 255
    return Image.fromarray(np.clip(np.concatenate([rgb_arr, a], -1), 0, 255).astype(np.uint8), "RGBA")


def grain(arr, amount, seed):
    """Fine monochrome film grain."""
    h, w = arr.shape[:2]
    g = rng(seed).standard_normal((h, w)).astype(np.float32) * amount
    return arr + (g[..., None] if arr.ndim == 3 else g)


def font(size, weight="Regular"):
    """A UI font for text baked into billboards. Falls back to PIL's built-in font."""
    for p in ("/usr/share/fonts/opentype/inter/Inter-%s.otf" % weight,
              str(ROOT / "assets" / "fonts" / ("Inter-%s.otf" % weight)),
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ---- supersampled drawing surface -------------------------------------------------------------------
class Art:
    """RGBA surface addressed in game units. Draws at `ss`x resolution, then downsamples = anti-aliasing.
    wrap=(w_u, h_u) makes every primitive repeat across the edges, so the result tiles seamlessly."""

    def __init__(self, w_u, h_u, ppu, ss=3, bg=(0, 0, 0, 0), wrap=None):
        self.ppu, self.ss = ppu, ss
        self.k = ppu * ss
        self.W = int(round(w_u * self.k))
        self.H = int(round(h_u * self.k))
        self.im = Image.new("RGBA", (self.W, self.H), bg)
        self.d = ImageDraw.Draw(self.im)
        wx, wy = wrap if wrap else (0, 0)
        self.offs = [(ox * wx, oy * wy) for ox in ((-1, 0, 1) if wx else (0,)) for oy in ((-1, 0, 1) if wy else (0,))]

    def P(self, pts, o=(0, 0)):
        return [((x + o[0]) * self.k, (y + o[1]) * self.k) for x, y in pts]

    def poly(self, pts, fill):
        for o in self.offs:
            self.d.polygon(self.P(pts, o), fill=fill)

    def rect(self, x0, y0, x1, y1, fill):
        for o in self.offs:
            xa, ya = (x0 + o[0]) * self.k, (y0 + o[1]) * self.k
            self.d.rectangle([xa, ya, max(xa, (x1 + o[0]) * self.k - 1), max(ya, (y1 + o[1]) * self.k - 1)], fill=fill)

    def rrect(self, x0, y0, x1, y1, r, fill):
        for o in self.offs:
            xa, ya = (x0 + o[0]) * self.k, (y0 + o[1]) * self.k
            self.d.rounded_rectangle([xa, ya, max(xa + 1, (x1 + o[0]) * self.k - 1), max(ya + 1, (y1 + o[1]) * self.k - 1)],
                                     max(0, r * self.k), fill=fill)

    def ellipse(self, cx, cy, rx, ry, fill):
        for o in self.offs:
            self.d.ellipse([(cx + o[0] - rx) * self.k, (cy + o[1] - ry) * self.k,
                            (cx + o[0] + rx) * self.k, (cy + o[1] + ry) * self.k], fill=fill)

    def line(self, pts, fill, w=0.3):
        for o in self.offs:
            self.d.line(self.P(pts, o), fill=fill, width=max(1, int(round(w * self.k))), joint="curve")

    def capsule(self, p0, p1, r0, r1, fill):
        """A tapered limb with round ends from p0 (radius r0) to p1 (radius r1)."""
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1e-6
        nx, ny = -dy / L, dx / L
        self.poly([(x0 + nx * r0, y0 + ny * r0), (x1 + nx * r1, y1 + ny * r1),
                   (x1 - nx * r1, y1 - ny * r1), (x0 - nx * r0, y0 - ny * r0)], fill)
        self.ellipse(x0, y0, r0, r0, fill)
        self.ellipse(x1, y1, r1, r1, fill)

    def paste(self, im, x, y):
        """Alpha-composite another PIL image (already at this surface's ss*ppu scale) at unit coords."""
        self.im.alpha_composite(im, (int(round(x * self.k)), int(round(y * self.k))))

    def finish(self):
        if self.ss == 1:
            return self.im
        return self.im.resize((self.W // self.ss, self.H // self.ss), Image.LANCZOS)


def glow_dot(r_px, color, strength=1.0):
    """A soft radial light as an RGBA image (r_px radius)."""
    n = int(r_px * 2)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.sqrt((xx - r_px + .5) ** 2 + (yy - r_px + .5) ** 2) / r_px
    a = np.clip(1 - d, 0, 1) ** 2.2 * strength
    rgbv = np.zeros((n, n, 3), np.float32) + np.array(color, np.float32)
    return rgba_img(rgbv, a)


def add_glow(img, cx_px, cy_px, r_px, color, strength=1.0):
    g = glow_dot(r_px, color, strength)
    img.alpha_composite(g, (int(cx_px - r_px), int(cy_px - r_px)))


# ============================================================================
# 2. SKY AND FOG
# ============================================================================
def make_sky():
    """Overcast storm sky, 1920x1080 (cover-fitted by the renderer)."""
    W, H = 1920, 1080
    base = vgrad(H, W, [(0, (36, 40, 46)), (0.28, (66, 72, 80)), (0.55, (102, 109, 118)),
                        (0.80, (146, 154, 164)), (1, (126, 134, 144))])
    big = fnoise(H, W, 11, beta=3.2, sx=2.4, sy=1.0)
    mid = fnoise(H, W, 12, beta=2.6, sx=1.8, sy=1.0)
    fine = fnoise(H, W, 13, beta=2.0, sx=1.3, sy=1.0)
    mod = (big - .5) * .7 + (mid - .5) * .42 + (fine - .5) * .18
    ys = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    strength = 0.55 + 0.9 * (1 - ys)                      # clouds are more contrasty high up
    rgbv = base * (1 + mod[..., None] * strength[..., None])
    # a diffuse pale break in the clouds behind the central megastructure
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = ((xx - W * .54) / (W * .30)) ** 2 + ((yy - H * .40) / (H * .30)) ** 2
    rgbv += np.exp(-d * 1.6)[..., None] * np.array([62, 66, 72], np.float32) * (0.7 + 0.5 * mid[..., None])
    # corner vignette and grain
    vd = ((xx / W - .5) ** 2 + (yy / H - .5) ** 2) * 1.5
    rgbv *= (1 - vd[..., None] * 0.55)
    rgbv = grain(rgbv, 1.6, 14)
    save_png(to_img(rgbv), "sky.jpg")


def make_fog_bank():
    """A wide, soft, horizontally tiling fog wisp used by the runtime fog layers (drifts and scrolls)."""
    W, H = 2048, 384
    n = fnoise(H, W, 21, beta=3.4, sx=5.0, sy=1.0)
    n2 = fnoise(H, W, 22, beta=2.4, sx=3.0, sy=1.0)
    ys = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    window = np.clip(np.sin(np.pi * ys), 0, 1) ** 1.6
    a = smoothstep(0.30, 0.88, n * .78 + n2 * .22) * window * 0.92
    col = np.zeros((H, W, 3), np.float32) + np.array([204, 211, 218], np.float32)
    col += (n2[..., None] - .5) * 24
    save_png(rgba_img(col, a), "fog_bank.png")


# ============================================================================
# 3. SKYLINE LAYERS  (the five parallax depth layers behind the playable rooftops)
#    sky.jpg            L0  static backdrop             (section 2)
#    skyline_atmos.png  L5  atmospheric megastructures  fx 0.03
#    skyline_far.png    L4  distant skyscrapers         fx 0.07
#    skyline_mid.png    L3  mid-distance, bridges, ads  fx 0.16
#    skyline_near.png   L2  near mid-ground, gantries   fx 0.34
# Each strip tiles seamlessly in x. Haze, rim light, mist and a fog-coloured base are baked in.
# ============================================================================
def text_spaced(draw, xy, text, fnt, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing
    return x


def draw_eye(art, cx, cy, w, h, tone=1.0):
    """A stylised, unblinking surveillance eye (grey scale) centred at (cx, cy) with width w, height h."""
    pts_t = [(cx + (t / 20.0 - 1) * w / 2, cy - h / 2 * (1 - (t / 20.0 - 1) ** 2) ** 0.9) for t in range(41)]
    pts_b = [(cx + (1 - t / 20.0) * w / 2, cy + h / 2 * (1 - (1 - t / 20.0) ** 2) ** 0.9) for t in range(41)]
    sc = (196 * tone, 202 * tone, 208 * tone)
    art.poly(pts_t + pts_b, tuple(int(v) for v in sc) + (255,))
    ir = h * 0.46
    art.ellipse(cx, cy, ir, ir, (96, 104, 114, 255))
    r = rng(5)
    for i in range(46):                                   # iris streaks
        a = r.uniform(0, 2 * math.pi)
        r0, r1 = ir * r.uniform(.25, .5), ir * r.uniform(.85, 1.0)
        art.line([(cx + math.cos(a) * r0, cy + math.sin(a) * r0), (cx + math.cos(a) * r1, cy + math.sin(a) * r1)],
                 (int(r.uniform(40, 150)),) * 3 + (150,), w * .006)
    art.ellipse(cx, cy, ir * .34, ir * .34, (6, 7, 9, 255))
    art.ellipse(cx - ir * .22, cy - ir * .24, ir * .12, ir * .12, (235, 240, 245, 255))
    art.line(pts_t, (22, 25, 29, 255), w * .018)          # lids
    art.line(pts_b + [pts_b[0]], (22, 25, 29, 255), w * .014)


def make_billboard(w_u, h_u, ppu, kind):
    """An emissive wall display (RGBA, with its own soft halo). kind: 'eye' | 'tau' | 'notice'."""
    pad = 6
    art = Art(w_u + pad * 2, h_u + pad * 2, ppu, ss=3)
    art.rect(pad, pad, pad + w_u, pad + h_u, (14, 16, 19, 255))
    art.rect(pad + .8, pad + .8, pad + w_u - .8, pad + h_u - .8, (30, 34, 39, 255))
    art.rect(pad + 1.4, pad + 1.4, pad + w_u - 1.4, pad + h_u - 1.4, (58, 64, 72, 255))
    x0, y0, ww, hh = pad + 1.4, pad + 1.4, w_u - 2.8, h_u - 2.8
    if kind == "eye":
        draw_eye(art, x0 + ww * .30, y0 + hh * .5, ww * .50, hh * .66)
        fnt = font(int(hh * .15 * art.k), "SemiBold")
        d = ImageDraw.Draw(art.im)
        for i, word in enumerate(("BETTER", "TOMORROW", "TOGETHER")):
            text_spaced(d, ((x0 + ww * .62) * art.k, (y0 + hh * (.26 + i * .20)) * art.k), word, fnt, (218, 224, 230, 255), art.k * .12)
    elif kind == "tau":
        cx, cy = x0 + ww * .5, y0 + hh * .46
        bar, stem = ww * .30, hh * .30
        art.rect(cx - bar, cy - stem, cx + bar, cy - stem + hh * .075, (214, 220, 226, 255))
        art.rect(cx - hh * .04, cy - stem, cx + hh * .04, cy + stem, (214, 220, 226, 255))
        fnt = font(int(hh * .10 * art.k), "Medium")
        d = ImageDraw.Draw(art.im)
        text_spaced(d, ((x0 + ww * .30) * art.k, (y0 + hh * .84) * art.k), "STAY COUNTED", fnt, (170, 178, 186, 255), art.k * .14)
    else:
        fnt = font(int(hh * .17 * art.k), "SemiBold")
        d = ImageDraw.Draw(art.im)
        for i, word in enumerate(("ORDER", "IS", "SAFETY")):
            text_spaced(d, ((x0 + ww * .12) * art.k, (y0 + hh * (.14 + i * .26)) * art.k), word, fnt, (214, 220, 226, 255), art.k * .2)
        art.rect(x0 + ww * .12, y0 + hh * .90, x0 + ww * .88, y0 + hh * .92, (190, 40, 36, 255))
    im = art.finish()
    a = np.array(im).astype(np.float32)
    a[::2, :, :3] *= 0.86                                # scan lines
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    halo = im.filter(ImageFilter.GaussianBlur(ppu * 3.2))
    ha = np.array(halo).astype(np.float32)
    ha[..., 3] *= 0.55
    out = Image.fromarray(ha.astype(np.uint8), "RGBA")
    out.alpha_composite(im)
    return out


def make_skyline(name, spec, ss=2):
    W_u, H_u, ppu = spec["W"], spec["H"], spec["ppu"]
    r = rng(spec["seed"])
    S = ss * ppu
    Wp, Hp = int(round(W_u * S)), int(round(H_u * S))
    sil = Image.new("LA", (Wp, Hp), (0, 0))
    dk = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))     # dark surface detail (ribs, bands, recesses)
    lt = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))     # lit windows (emissive)
    sd, dkd, ltd = ImageDraw.Draw(sil), ImageDraw.Draw(dk), ImageDraw.Draw(lt)
    reds = []

    def poly(pts, tint):
        for ox in (0, -W_u, W_u):
            sd.polygon([((x + ox) * S, y * S) for x, y in pts], fill=(int(tint), 255))

    def line(pts, tint, w):
        for ox in (0, -W_u, W_u):
            sd.line([((x + ox) * S, y * S) for x, y in pts], fill=(int(tint), 255), width=max(1, int(w * S)))

    def box(d, x0, y0, x1, y1, fill):
        for ox in (0, -W_u, W_u):
            xa, ya = (x0 + ox) * S, y0 * S
            d.rectangle([xa, ya, max(xa, (x1 + ox) * S - 1), max(ya, y1 * S - 1)], fill=fill)

    ground = H_u
    win = spec["window"]

    def faces_detail(x0, x1, yt, yb, style):
        cw, ch = win["cell"]
        yb = min(yb, H_u * .93)
        cols, rows = max(1, int((x1 - x0 - 1.0) / cw)), max(1, int((yb - yt - 2) / ch))
        if "bands" in style:
            for j in range(rows):
                y = yt + 1.6 + j * ch
                box(dkd, x0 + .5, y, x1 - .5, y + ch * .36, (0, 0, 0, win.get("band_a", 70)))
                if r.random() < win.get("band_lit", .0):
                    xa = x0 + .5 + r.uniform(0, (x1 - x0) * .5)
                    box(ltd, xa, y + ch * .06, xa + r.uniform(2, (x1 - x0) * .5), y + ch * .3, PAL["light_dim"] + (int(r.uniform(*win["lit_a"])),))
        if "ribs" in style:
            for i in range(cols + 1):
                x = x0 + .5 + i * cw
                box(dkd, x, yt + 1, x + cw * .28, yb, (0, 0, 0, win.get("rib_a", 60)))
                box(ltd, x + cw * .28, yt + 1, x + cw * .36, yb, (255, 255, 255, win.get("rib_hi", 10)))
        if "recess" in style:
            for i in range(0, cols, 2):
                for j in range(0, rows, 2):
                    if r.random() < .6:
                        box(dkd, x0 + 1 + i * cw, yt + 2 + j * ch, x0 + 1 + (i + 1.7) * cw, yt + 2 + (j + 1.5) * ch, (0, 0, 0, 80))
        if "dots" in style and win["lit"] > 0:
            for i in range(cols):
                for j in range(rows):
                    if r.random() < win["lit"]:
                        a = int(r.uniform(*win["lit_a"]))
                        wx, wy = x0 + .5 + i * cw + cw * .3, yt + 1.5 + j * ch + ch * .3
                        box(ltd, wx, wy, wx + cw * .38, wy + ch * .34, PAL["light_dim"] + (a,))

    def shape(x0, x1, yt, style, tint, with_detail=True, hero=None):
        w = x1 - x0
        yb = ground + 4
        tiers = [(x0, x1, yt)]
        if style == "flat":
            poly([(x0, yb), (x0, yt), (x1, yt), (x1, yb)], tint)
        elif style == "step":
            n = int(r.integers(2, 4))
            tiers = []
            for k in range(n):
                inset = w * (0.16 * k) * r.uniform(.8, 1.2)
                y_k = yt + k * r.uniform(8, 26) if k else yt
                a, b = x0 + inset * (1 if r.random() < .5 else .4), x1 - inset * (1 if r.random() < .5 else .4)
                if k == 0:
                    a, b = x0 + w * .2, x1 - w * .2
                    tiers.append((a, b, yt))
                else:
                    tiers.append((x0 + inset * .5 if k == n - 1 else x0, x1 - inset * .5 if k == n - 1 else x1, yt + k * r.uniform(14, 34)))
                poly([(tiers[-1][0], yb), (tiers[-1][0], tiers[-1][2]), (tiers[-1][1], tiers[-1][2]), (tiers[-1][1], yb)], tint)
        elif style == "slant":
            d = r.uniform(.12, .5) * min(w, 40) * (1 if r.random() < .5 else -1)
            poly([(x0, yb), (x0, yt + max(0, -d)), (x1, yt + max(0, d)), (x1, yb)], tint)
        elif style == "chamfer":
            c = w * r.uniform(.16, .3)
            poly([(x0, yb), (x0, yt + c), (x0 + c, yt), (x1 - c, yt), (x1, yt + c), (x1, yb)], tint)
        elif style == "taper":
            t = w * r.uniform(.12, .22)
            poly([(x0 - t * .5, yb), (x0 + t, yt), (x1 - t, yt), (x1 + t * .5, yb)], tint)
        elif style == "monument":                           # slab with a notched crown, the "hero" shape
            t = w * .08
            poly([(x0 - t, yb), (x0 + t * .4, yt + w * .10), (x0 + w * .2, yt + w * .10), (x0 + w * .2, yt),
                  (x1 - w * .2, yt), (x1 - w * .2, yt + w * .10), (x1 - t * .4, yt + w * .10), (x1 + t, yb)], tint)
        elif style == "twin":
            g = w * r.uniform(.1, .2)
            m = (x0 + x1) / 2
            poly([(x0, yb), (x0, yt), (m - g / 2, yt), (m - g / 2, yb)], tint)
            poly([(m + g / 2, yb), (m + g / 2, yt + r.uniform(4, 22)), (x1, yt + r.uniform(4, 22)), (x1, yb)], tint)
            poly([(m - g, yb), (m - g, yt + w * .35), (m + g, yt + w * .35), (m + g, yb)], tint)
        elif style == "spire":
            poly([(x0, yb), (x0, yt), (x1, yt), (x1, yb)], tint)
        elif style == "stack":                              # chimney / exhaust stack
            poly([(x0, yb), (x0 + w * .1, yt), (x1 - w * .1, yt), (x1, yb)], tint)
            poly([(x0 - w * .12, yt + 1), (x0 - w * .12, yt - 1.5), (x1 + w * .12, yt - 1.5), (x1 + w * .12, yt + 1)], tint)
            reds.append(((x0 + x1) / 2, yt - 2.4))
            for k in range(3):                              # hazard banding
                box(dkd, x0 + w * .1, yt + 3 + k * 7, x1 - w * .1, yt + 5 + k * 7, (0, 0, 0, 110))
            return
        if style in ("flat", "step", "chamfer", "taper") and r.random() < .7:
            for _ in range(int(r.integers(1, 4))):            # rooftop plant: boxes, tanks, housings
                bw_, bh_ = r.uniform(1.4, max(2.0, w * .22)), r.uniform(1.0, 4.2)
                bx_ = r.uniform(tiers[0][0] + w * .05, max(tiers[0][0] + w * .06, tiers[0][1] - bw_ - w * .05))
                poly([(bx_, tiers[0][2] + 1), (bx_, tiers[0][2] - bh_), (bx_ + bw_, tiers[0][2] - bh_), (bx_ + bw_, tiers[0][2] + 1)], tint * .96)
        if style in ("spire", "flat", "step", "chamfer", "slant", "taper") and r.random() < spec.get("antenna", .35):
            cx = (tiers[0][0] + tiers[0][1]) / 2 + r.uniform(-w * .15, w * .15)
            top = tiers[0][2]
            sh = r.uniform(10, 34) if style == "spire" else r.uniform(5, 18)
            sw = max(.35, w * .02) if style != "spire" else w * .09
            poly([(cx - sw, top + 1), (cx, top - sh), (cx + sw, top + 1)], tint)
            if r.random() < .75:
                reds.append((cx, top - sh))
        if with_detail:
            style_d = hero.get("detail") if hero and hero.get("detail") else win["style"][int(r.integers(len(win["style"])))]
            for (a, b, y) in tiers:
                faces_detail(a, b, y, yb, style_d)

    # ---- layout --------------------------------------------------------------------------------
    blds, x = [], float(r.uniform(0, 6))
    while x < W_u:
        bw = r.uniform(*spec["w"])
        blds.append(dict(x0=x, x1=x + bw, h=r.uniform(*spec["h"]), style=str(r.choice(spec["crowns"])), tint=r.uniform(.84, 1.1)))
        x += bw + r.uniform(*spec["gap"])
    blds.sort(key=lambda b: -b["h"])                       # tall ones first, short ones in front
    for b in blds:
        shape(b["x0"], b["x1"], ground - b["h"], b["style"], 255 * b["tint"])

    for st in range(spec.get("stacks", 0)):                  # industrial chimneys
        w = r.uniform(3, 5.5)
        x0 = r.uniform(0, W_u)
        shape(x0, x0 + w, ground - r.uniform(*spec.get("stack_h", (60, 120))), "stack", 255 * r.uniform(.85, 1.0), False)

    for hh in spec.get("heroes", []):                       # monumental structures
        yt = ground - hh["h"]
        shape(hh["x"] - hh["w"] / 2, hh["x"] + hh["w"] / 2, yt, hh["style"], 255 * hh.get("tint", 1.0), True, hh)
        if hh.get("slit"):
            box(ltd, hh["x"] + hh["w"] * .05, yt + hh["w"] * .30, hh["x"] + hh["w"] * .05 + max(.7, hh["w"] * .014), yt + hh["h"] * .78, PAL["light"] + (225,))
        if hh.get("emblem"):                                # the TAU glyph, inset into the tower
            cx, cy, s = hh["x"] - hh["w"] * .12, yt + hh["w"] * .34, hh["w"] * .26
            box(ltd, cx - s, cy - s * .75, cx + s, cy - s * .75 + s * .22, PAL["light_dim"] + (150,))
            box(ltd, cx - s * .12, cy - s * .75, cx + s * .12, cy + s * .8, PAL["light_dim"] + (150,))

    for br in range(spec.get("bridges", 0)):                 # truss bridges between neighbouring towers
        i = int(r.integers(0, len(blds) - 1))
        order = sorted(blds, key=lambda b: b["x0"])
        a, b = order[i], order[i + 1]
        if b["x0"] - a["x1"] > 70:
            continue
        xa, xb = a["x1"] - 2, b["x0"] + 2
        if xb - xa < 5:
            continue
        top = ground - min(a["h"], b["h"]) * r.uniform(.35, .85)
        th = r.uniform(2.6, 5.0)
        line([(xa, top), (xb, top)], 190, .8)
        line([(xa, top + th), (xb, top + th)], 190, .8)
        k = max(2, int((xb - xa) / (th * 1.3)))
        zz = []
        for q in range(k + 1):
            zz.append((xa + (xb - xa) * q / k, top + (th if q % 2 else 0)))
        line(zz, 190, .5)

    # ---- composite at final resolution ---------------------------------------------------------
    Wf, Hf = int(round(W_u * ppu)), int(round(H_u * ppu))
    la = np.array(sil.resize((Wf, Hf), Image.LANCZOS)).astype(np.float32)
    tint, cov = la[..., 0] / 255.0, la[..., 1] / 255.0
    dkf = np.array(dk.resize((Wf, Hf), Image.LANCZOS)).astype(np.float32)
    ltf = np.array(lt.resize((Wf, Hf), Image.LANCZOS)).astype(np.float32)
    ys = np.linspace(0, 1, Hf, dtype=np.float32)[:, None]
    top, bottom, fog = (np.array(spec[k], np.float32) for k in ("top", "bottom", "fog"))
    col = lerp(top, bottom, np.clip(ys * 1.15, 0, 1)[..., None]) * np.clip(tint, 0, 1.3)[..., None]
    streak = fnoise(Hf, Wf, spec["seed"] + 5, beta=2.4, sx=1.0, sy=6.0)
    patch = fnoise(Hf, Wf, spec["seed"] + 6, beta=3.0, sx=2.0, sy=2.0)
    col = col * (1 + (streak[..., None] - .5) * spec.get("streak", .30) + (patch[..., None] - .5) * .22)
    col = col + (fnoise(Hf, Wf, spec["seed"] + 7, beta=2.0, sx=1.0, sy=1.0)[..., None] - .5) * spec.get("texture", 8)
    da = (dkf[..., 3] / 255.0)[..., None]
    col = col * (1 - da * cov[..., None])                    # dark detail darkens the face
    # rim light on top/left edges (back-lit by the sky glow)
    rs = max(1, int(round(spec.get("rim_px", 1.2) * ppu / 2)))
    rim = ndi.gaussian_filter(np.clip(cov - np.roll(np.roll(cov, rs, 1), rs, 0), 0, 1), max(.6, ppu * .35))
    col = col + rim[..., None] * np.array(spec.get("rim_col", (150, 158, 168)), np.float32) * spec.get("rim", .4)
    vfog = smoothstep(0.30, 1.0, ys)[..., None] * spec.get("vfog", .55)
    col = lerp(col, fog, np.clip(spec["haze"] + vfog, 0, 1))
    la_ = (ltf[..., 3] / 255.0) * (1 - vfog[..., 0] * .85)
    litc = ltf[..., :3]
    col = col * (1 - (la_ * cov)[..., None]) + litc * (la_ * cov)[..., None]
    bloom = ndi.gaussian_filter(litc * la_[..., None], (1.6 * ppu, 1.6 * ppu, 0), mode="wrap") * spec.get("bloom", .8)
    col = col + bloom * cov[..., None] * 0.6 + bloom * (1 - cov[..., None]) * .25
    # distant hazard lights (static dim red points)
    for (rx, ry) in reds:
        for ox in (0, -W_u, W_u):
            cx, cy = (rx + ox) * ppu, ry * ppu
            if -20 < cx < Wf + 20:
                yy0, yy1, xx0, xx1 = int(max(0, cy - 8)), int(min(Hf, cy + 9)), int(max(0, cx - 8)), int(min(Wf, cx + 9))
                if yy1 <= yy0 or xx1 <= xx0:
                    continue
                gy, gx = np.mgrid[yy0:yy1, xx0:xx1].astype(np.float32)
                dd = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2) / max(2.5, ppu * 1.6)
                g = np.clip(1 - dd, 0, 1) ** 2.0
                core = np.clip(1.4 - dd * 2.2, 0, 1)
                col[yy0:yy1, xx0:xx1] += g[..., None] * np.array(PAL["red"], np.float32) * (0.9 - spec["haze"]) \
                    + core[..., None] * np.array([255, 120, 110], np.float32) * .6
    alpha = cov.copy()
    # billboards are pasted last (emissive, with halo), slightly hazed
    emit = Image.new("RGBA", (Wf, Hf), (0, 0, 0, 0))
    for bb in spec.get("billboards", []):
        panel = make_billboard(bb["w"], bb["h"], ppu, bb["kind"])
        px, py = int((bb["x"]) * ppu), int((ground - bb["y"]) * ppu)
        for ox in (0, -Wf, Wf):
            emit.alpha_composite(panel, (px + ox, py)) if -panel.width < px + ox < Wf else None
    ef = np.array(emit).astype(np.float32)
    ea = (ef[..., 3] / 255.0)
    ec = lerp(ef[..., :3], fog, spec["haze"] * .6)
    col = col * (1 - ea[..., None]) + ec * ea[..., None]
    alpha = np.maximum(alpha, ea)
    # mist: soft horizontal fog banks between and in front of the towers, solid fog at the base
    mist = fnoise(Hf, Wf, spec["seed"] + 3, beta=3.0, sx=3.2, sy=1.0)
    mist_a = smoothstep(.42, .85, mist) * (0.10 + 0.9 * smoothstep(.25, 1.0, ys)) * spec.get("mist", .5)
    solid = smoothstep(.80, .97, ys)
    mist_a = np.clip(np.maximum(mist_a, solid), 0, 1)
    mcol = fog
    prem = col * alpha[..., None]
    out_prem = mcol * mist_a[..., None] + prem * (1 - mist_a[..., None])
    out_a = mist_a + alpha * (1 - mist_a)
    out_rgb = np.where(out_a[..., None] > 1e-4, out_prem / np.maximum(out_a[..., None], 1e-4), 0)
    if spec.get("blur", 0) > 0:
        pr = out_rgb * out_a[..., None]
        s = spec["blur"]
        pr = ndi.gaussian_filter(pr, (s, s, 0), mode=("nearest", "wrap", "nearest"))
        out_a = ndi.gaussian_filter(out_a, s, mode=("nearest", "wrap"))
        out_rgb = pr / np.maximum(out_a[..., None], 1e-4)
    out_rgb = grain(out_rgb, spec.get("grain", 1.0), spec["seed"] + 9)
    save_png(rgba_img(out_rgb, out_a), name)


SKYLINES = {
    "skyline_atmos.png": dict(
        W=1280, H=300, ppu=1.5, seed=101, w=(18, 62), gap=(-10, 2), h=(60, 205),
        crowns=["flat", "step", "slant", "chamfer", "taper", "spire", "twin"],
        window=dict(style=[["ribs"], ["bands"], ["ribs", "bands"]], cell=(4.0, 6.0), lit=0.0, rib_a=40, band_a=46),
        top=(70, 77, 87), bottom=(134, 142, 152), fog=(138, 146, 156), haze=0.22, vfog=.7, blur=1.3, rim=.22, mist=.55, antenna=.4,
        heroes=[dict(x=520, w=118, h=262, style="monument", emblem=True, slit=True, detail=["ribs"], tint=.98),
                dict(x=980, w=74, h=238, style="step", detail=["bands"]),
                dict(x=170, w=92, h=226, style="chamfer", detail=["ribs", "bands"])]),
    "skyline_far.png": dict(
        W=1280, H=290, ppu=2, seed=202, w=(9, 34), gap=(-6, 1), h=(45, 192),
        crowns=["flat", "step", "slant", "chamfer", "taper", "spire", "twin"],
        window=dict(style=[["dots"], ["dots", "bands"], ["ribs", "dots"], ["bands"]], cell=(2.6, 3.8), lit=0.045, lit_a=(40, 100), band_a=52, rib_a=44),
        top=(52, 58, 66), bottom=(122, 130, 140), fog=(124, 132, 142), haze=0.16, vfog=.65, blur=.85, rim=.2, mist=.5, antenna=.5, stacks=3,
        heroes=[dict(x=330, w=62, h=214, style="step", detail=["dots", "bands"]),
                dict(x=880, w=54, h=204, style="spire", detail=["ribs", "dots"]),
                dict(x=1130, w=70, h=188, style="taper", detail=["recess"])]),
    "skyline_mid.png": dict(
        W=1280, H=270, ppu=3, seed=303, w=(9, 38), gap=(-6, 2), h=(50, 176),
        crowns=["flat", "step", "slant", "chamfer", "taper", "spire", "twin"],
        window=dict(style=[["dots"], ["dots", "bands"], ["ribs", "dots"], ["recess", "dots"]], cell=(2.4, 3.4), lit=0.07, lit_a=(50, 140), band_a=60, rib_a=50, band_lit=.1),
        top=(34, 38, 44), bottom=(100, 107, 117), fog=(106, 113, 123), haze=0.10, vfog=.6, blur=.5, rim=.22, mist=.45, antenna=.45, stacks=4,
        bridges=6, bloom=.9,
        billboards=[dict(x=222, y=128, w=62, h=34, kind="eye"), dict(x=870, y=104, w=40, h=48, kind="tau")],
        heroes=[dict(x=250, w=84, h=186, style="step", detail=["recess", "dots"]),
                dict(x=720, w=60, h=170, style="chamfer", detail=["dots", "bands"]),
                dict(x=1060, w=76, h=180, style="taper", detail=["ribs", "dots"])]),
    "skyline_near.png": dict(
        W=1024, H=280, ppu=4, seed=404, w=(22, 70), gap=(-4, 10), h=(80, 224),
        crowns=["flat", "step", "chamfer", "taper", "slant", "twin"],
        window=dict(style=[["recess", "ribs"], ["bands", "ribs"], ["recess", "dots"], ["bands"]], cell=(3.4, 4.8), lit=0.05, lit_a=(60, 150), band_a=82, rib_a=70, band_lit=.12, rib_hi=14),
        top=(16, 18, 22), bottom=(70, 76, 86), fog=(76, 82, 92), haze=0.04, vfog=.7, blur=.28, rim=.25, mist=.40, antenna=.5, stacks=2,
        bridges=3, bloom=1.0, texture=10,
        billboards=[dict(x=560, y=148, w=70, h=36, kind="notice")]),
}


def make_skylines(filters):
    for name, spec in SKYLINES.items():
        if want(filters, name):
            make_skyline(name, spec)
# ============================================================================
# 4. WALLS AND ROOFS  (tileable textures; the game repeats them as patterns)
# ============================================================================
WALL_DARK = (8, 10, 12, 255)
WALL_HI = (74, 82, 93, 130)


def concrete(h, w, seed, base, var=8.0, grit=3.0):
    n1 = fnoise(h, w, seed, beta=2.4)
    n2 = fnoise(h, w, seed + 1, beta=1.1)
    return np.array(base, np.float32) + (n1[..., None] - .5) * var * 2 + (n2[..., None] - .5) * grit * 2


def overlay(base_rgb, art):
    ov = np.array(art.finish()).astype(np.float32)
    a = ov[..., 3:4] / 255.0
    return base_rgb * (1 - a) + ov[..., :3] * a


def make_wall(i):
    names = ["wall_slit", "wall_grid", "wall_panel", "wall_rib"]
    ppu, T = 8, 64
    N = T * ppu
    seed = 500 + i * 7
    base = concrete(N, N, seed, (31, 35, 41), 9, 3)
    streak = fnoise(N, N, seed + 2, beta=2.2, sx=1.0, sy=7.0)
    base *= 1 + (streak[..., None] - .5) * .34
    ov = Art(T, T, ppu, ss=2, wrap=(T, T))
    if i == 0:      # slit windows in staggered precast panels
        for y in (0, 32):
            ov.rect(0, y - .3, T, y + .3, WALL_DARK)
            ov.rect(0, y + .3, T, y + .65, WALL_HI)
        for (x, y0) in ((0, 0), (32, 32)):
            ov.rect(x - .3, y0, x + .3, y0 + 32, WALL_DARK)
            ov.rect(x + .3, y0, x + .65, y0 + 32, WALL_HI)
        for k, (cx, cy) in enumerate(((16, 7), (48, 39), (16, 39), (48, 7))):
            ov.rect(cx - 1.7, cy, cx + 1.7, cy + 19, (60, 68, 78, 255))
            ov.rect(cx - 1.3, cy + .4, cx + 1.3, cy + 18.8, (5, 7, 9, 255))
            ov.rect(cx - 1.0, cy + .6, cx - .5, cy + 18.5, (18, 23, 30, 255))
            if k == 0:
                ov.rect(cx - 1.0, cy + 6, cx + 1.0, cy + 11, (206, 214, 224, 150))
    elif i == 1:    # office window grid
        for y in (0, 32):
            ov.rect(0, y - .5, T, y + .5, WALL_DARK)
        for c in range(4):
            for r in range(3):
                x0, y0 = 3 + c * 16, 3 + r * 21
                ov.rect(x0 - .4, y0 - .4, x0 + 10.4, y0 + 8.4, (60, 68, 78, 255))
                ov.rect(x0, y0, x0 + 10, y0 + 8, (9, 13, 18, 255))
                ov.rect(x0, y0, x0 + 10, y0 + 2.6, (20, 28, 38, 255))
                ov.poly([(x0 + 1, y0 + 8), (x0 + 4.5, y0), (x0 + 6.5, y0), (x0 + 3, y0 + 8)], (255, 255, 255, 14))
                if (c, r) in ((1, 0), (3, 2)):
                    ov.rect(x0 + .5, y0 + .5, x0 + 9.5, y0 + 7.5, (204, 213, 224, 150))
    elif i == 2:    # tie-hole precast panels with a louvre block
        for y in (0, 32):
            ov.rect(0, y - .4, T, y + .4, WALL_DARK)
            ov.rect(0, y + .4, T, y + .8, WALL_HI)
        for (x, y0) in ((0, 0), (32, 32)):
            ov.rect(x - .4, y0, x + .4, y0 + 32, WALL_DARK)
            ov.rect(x + .4, y0, x + .8, y0 + 32, WALL_HI)
        for xx in range(8, 64, 16):
            for yy in (4, 28, 36, 60):
                ov.ellipse(xx, yy, .6, .6, WALL_DARK)
        ov.rect(36, 6, 56, 20, (7, 9, 11, 255))
        for k in range(7):
            ov.rect(36.6, 6.8 + k * 1.9, 55.4, 7.6 + k * 1.9, (46, 52, 60, 255))
    else:           # vertical fins
        for x in range(0, 64, 8):
            ov.rect(x, 0, x + 3, 64, (40, 46, 54, 255))
            ov.rect(x, 0, x + .6, 64, (66, 74, 85, 255))
            ov.rect(x + 3, 0, x + 8, 64, (17, 20, 25, 255))
            ov.rect(x + 3, 0, x + 4.6, 64, (24, 28, 34, 255))
        for y in (0, 32):
            ov.rect(0, y - 1.4, T, y + 1.4, (34, 39, 46, 255))
            ov.rect(0, y - 1.4, T, y - .8, (70, 78, 90, 255))
            ov.rect(0, y + 1.0, T, y + 1.4, WALL_DARK)
    out = overlay(base, ov)
    out = grain(out, 1.4, seed + 9)
    save_png(to_img(out), names[i] + ".png")


def make_roof(i):
    """Roof-edge strip (64 x 14 units): wet top surface, coping lip, parapet face. Tiles in x."""
    names = ["roof_a", "roof_b", "roof_c"]
    ppu, Tw, Th = 8, 64, 14
    W, H = Tw * ppu, Th * ppu
    seed = 600 + i * 11
    arr = np.zeros((H, W, 3), np.float32)
    ys = (np.arange(H, dtype=np.float32) / ppu)[:, None]
    face = concrete(H, W, seed, (33, 37, 43), 6, 2.5)
    face *= (1 - np.clip((ys - 4.4) / 9.6, 0, 1) * .45)[..., None]
    surf = concrete(H, W, seed + 3, (36, 41, 48), 4, 2)
    puddle = smoothstep(.60, .80, fnoise(H, W, seed + 5, beta=2.8, sx=6.0, sy=1.0))
    sheen = np.array([86, 96, 108], np.float32)
    surf = surf * (1 - puddle[..., None] * .8) + sheen * puddle[..., None] * .8
    streaks = smoothstep(.7, .95, fnoise(H, W, seed + 6, beta=1.6, sx=9.0, sy=1.0))
    surf += streaks[..., None] * 22
    arr[:] = face
    sm = (ys < 3.6)
    arr = np.where(sm[..., None], surf, arr)
    far = (ys < .6)
    arr = np.where(far[..., None], np.array([110, 120, 132], np.float32) * (.75 + .25 * puddle[..., None]) , arr)
    lip = (ys >= 3.6) & (ys < 4.1)
    arr = np.where(lip[..., None], np.array([92, 100, 112], np.float32), arr)
    shadow = (ys >= 4.1) & (ys < 4.7)
    arr = np.where(shadow[..., None], np.array([5, 6, 8], np.float32), arr)
    ov = Art(Tw, Th, ppu, ss=2, wrap=(Tw, 0))
    for x in (0, 16, 32, 48):                              # parapet joints
        ov.rect(x - .25, 4.7, x + .25, Th, WALL_DARK)
        ov.rect(x + .25, 4.7, x + .5, Th, (70, 78, 88, 90))
    if i == 1:
        ov.rect(20, 4.7, 26, 9, (8, 10, 12, 255))          # scupper
        ov.rect(20.4, 5.0, 25.6, 8.6, (20, 24, 29, 255))
    if i == 2:
        ov.rect(40, 1.0, 43, 3.3, (10, 12, 14, 255))        # drain grate
        for k in range(4):
            ov.rect(40.3 + k * .7, 1.2, 40.6 + k * .7, 3.1, (60, 68, 78, 255))
    arr = overlay(arr, ov)
    arr = grain(arr, 1.3, seed + 9)
    save_png(to_img(arr), names[i] + ".png")


def make_floor(i):
    """Corridor floor strip (64 x 14 units): steel plate / grating."""
    names = ["floor_plate", "floor_grate"]
    ppu, Tw, Th = 8, 64, 14
    W, H = Tw * ppu, Th * ppu
    seed = 700 + i * 13
    arr = concrete(H, W, seed, (30, 34, 40), 5, 2)
    ys = (np.arange(H, dtype=np.float32) / ppu)[:, None]
    arr = np.where((ys < 3.6)[..., None], concrete(H, W, seed + 2, (46, 52, 60), 4, 2), arr)
    arr = np.where((ys < .6)[..., None], np.array([116, 126, 138], np.float32), arr)
    arr = np.where(((ys >= 3.6) & (ys < 4.1))[..., None], np.array([96, 104, 116], np.float32), arr)
    arr = np.where(((ys >= 4.1) & (ys < 4.7))[..., None], np.array([5, 6, 8], np.float32), arr)
    ov = Art(Tw, Th, ppu, ss=2, wrap=(Tw, 0))
    if i == 0:
        for x in (0, 32):
            ov.rect(x - .2, .6, x + .2, 3.6, (12, 14, 17, 255))
        for x in range(4, 64, 8):                           # diamond plate ticks
            ov.rect(x, 1.4, x + 2.2, 1.8, (88, 98, 110, 255))
            ov.rect(x + 3, 2.4, x + 5.2, 2.8, (88, 98, 110, 255))
    else:
        for x in range(0, 64, 2):
            ov.rect(x, .6, x + .7, 3.6, (6, 7, 9, 255))
    for x in (0, 16, 32, 48):
        ov.rect(x - .25, 4.7, x + .25, Th, WALL_DARK)
    ov.rect(0, 7.5, Tw, 8.1, (150, 158, 168, 90))
    arr = overlay(arr, ov)
    arr = grain(arr, 1.3, seed + 9)
    save_png(to_img(arr), names[i] + ".png")


def make_hall_wall():
    """Interior corridor wall (32 x 32): dark panels with a skirting rail and cable run."""
    ppu, T = 8, 32
    N = T * ppu
    base = concrete(N, N, 800, (15, 18, 23), 4, 1.5)
    ov = Art(T, T, ppu, ss=2, wrap=(T, 0))
    for x in (0, 16):
        ov.rect(x - .3, 0, x + .3, T, (5, 6, 8, 255))
        ov.rect(x + .3, 0, x + .6, T, (50, 57, 66, 120))
    ov.rect(0, 26, T, 32, (24, 28, 34, 255))
    ov.rect(0, 26, T, 26.6, (74, 82, 94, 255))
    ov.rect(0, 22, T, 23.1, (34, 38, 45, 255))
    ov.rect(0, 22, T, 22.35, (78, 86, 98, 255))
    ov.rect(0, 5, T, 5.5, (6, 7, 9, 255))
    out = grain(overlay(base, ov), 1.0, 801)
    save_png(to_img(out), "hall_wall.png")


# ============================================================================
# 5. PROPS  (bottom-aligned sprites; positions of their warning lights are printed for assets.js)
# ============================================================================
BASE, BASE2 = (38, 43, 50), (26, 30, 35)
HI, DK, RED = (112, 122, 135), (11, 13, 16), (214, 44, 38)
LIGHTS = {}


def finish_prop(im, grain_amt=2.0, vshade=.20, seed=0):
    a = np.array(im).astype(np.float32)
    h, w = a.shape[:2]
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    a[..., :3] *= (1 - vshade * ys)[..., None]
    n = rng(seed).standard_normal((h, w)).astype(np.float32) * grain_amt
    a[..., :3] += n[..., None] * (a[..., 3:4] > 8)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def bevel(a, x0, y0, x1, y1, base=BASE, hi=HI, dk=DK, t=.4):
    a.rect(x0, y0, x1, y1, base + (255,))
    a.rect(x0, y0, x1, y0 + t, hi + (255,))
    a.rect(x0, y0, x0 + t * .7, y1, tuple(int(v * .65) for v in hi) + (255,))
    a.rect(x0, y1 - t, x1, y1, dk + (255,))
    a.rect(x1 - t * .7, y0, x1, y1, dk + (255,))


def led(art, x, y, r=.55, color=RED):
    art.ellipse(x, y, r, r, color + (255,))
    art.ellipse(x, y, r * .45, r * .45, (255, 190, 180, 255))


def save_prop(name, art, lights=None, seed=0, **kw):
    img = finish_prop(art.finish(), seed=seed, **kw)
    if lights:
        px = art.ppu
        for (lx, ly, col) in lights:
            add_glow(img, lx * px, ly * px, px * 2.4, col, .55)
        LIGHTS[name] = [(round(lx, 2), round(ly, 2), "red" if col[0] > 150 and col[1] < 100 else "white") for lx, ly, col in lights]
    save_png(img, name + ".png")


def lattice(art, xl0, xl1, xr0, xr1, ytop, ybot, step, w=.5, col=(70, 78, 90, 255)):
    """Zig-zag lattice between two (possibly sloped) legs."""
    n = max(2, int((ybot - ytop) / step))
    for k in range(n):
        y0, y1 = ytop + (ybot - ytop) * k / n, ytop + (ybot - ytop) * (k + 1) / n
        f0, f1 = k / n, (k + 1) / n
        l0, l1 = xl0 + (xl1 - xl0) * f0, xl0 + (xl1 - xl0) * f1
        r0, r1 = xr0 + (xr1 - xr0) * f0, xr0 + (xr1 - xr0) * f1
        art.line([(l0, y0), (r1, y1)] if k % 2 == 0 else [(r0, y0), (l1, y1)], col, w)
        art.line([(l0, y0), (r0, y0)], col, w)


def prop_antenna_a():
    a = Art(22, 104, 8, ss=3)
    c = (60, 68, 80, 255)
    a.line([(3, 104), (10, 7)], c, 1.0)
    a.line([(19, 104), (12, 7)], c, 1.0)
    lattice(a, 10, 3, 12, 19, 7, 104, 7.0, .55)
    for y in (34, 58):
        a.rect(1, y - .6, 21, y + .6, (74, 84, 96, 255))
    a.rrect(0, 30, 4, 40, .8, BASE + (255,))
    a.rrect(18, 52, 22, 62, .8, BASE + (255,))
    a.ellipse(11, 44, 3.6, 3.6, BASE2 + (255,))
    a.ellipse(11, 44, 2.7, 2.7, (50, 57, 66, 255))
    a.line([(11, 7), (11, 1)], (86, 96, 108, 255), .45)
    led(a, 11, 1.2)
    save_prop("antenna_a", a, [(11, 1.2, RED)], 1)


def prop_antenna_b():
    a = Art(18, 84, 8, ss=3)
    a.rect(7.3, 2, 8.7, 84, (66, 74, 86, 255))
    for y in (12, 28, 44):
        a.rrect(3.0, y, 6.0, y + 9, .5, (88, 98, 110, 255))
        a.rrect(10.0, y, 13.0, y + 9, .5, (88, 98, 110, 255))
        a.rect(6, y + 2, 10, y + 2.6, (66, 74, 86, 255))
    bevel(a, 3, 76, 13, 84)
    a.line([(8, 2), (8, 0)], (96, 106, 118, 255), .4)
    led(a, 8, 1, .5)
    save_prop("antenna_b", a, [(8, 1, RED)], 2)


def prop_antenna_c():
    a = Art(28, 60, 8, ss=3)
    a.rect(13.2, 12, 14.8, 60, (66, 74, 86, 255))
    for (cx, cy, r, ang) in ((8, 20, 6.5, -0.4), (20, 36, 5.2, .3)):
        pts = [(cx + math.cos(ang + t / 14 * math.pi - math.pi / 2) * r * .45, cy + math.sin(ang + t / 14 * math.pi - math.pi / 2) * r) for t in range(15)]
        a.poly(pts, (80, 90, 102, 255))
        a.line(pts, (128, 138, 150, 255), .5)
        a.line([(cx, cy), (cx + math.cos(ang) * 4, cy + math.sin(ang) * 4)], (56, 63, 73, 255), .5)
    bevel(a, 9, 54, 19, 60)
    led(a, 14, 12, .5)
    save_prop("antenna_c", a, [(14, 12, RED)], 3)


def prop_antenna_d():
    a = Art(40, 128, 8, ss=3)
    a.rect(19.4, 3, 20.6, 128, (70, 78, 90, 255))
    for (y, ex) in ((30, 18), (70, 14), (104, 10)):
        a.line([(20, y), (20 - ex - 2, 128)], (46, 52, 61, 255), .25)
        a.line([(20, y), (20 + ex + 2, 128)], (46, 52, 61, 255), .25)
    for y in (28, 68, 100):
        a.rect(17, y, 23, y + .7, (96, 106, 118, 255))
    a.line([(20, 3), (20, 0)], (96, 106, 118, 255), .4)
    led(a, 20, 1.2, .6)
    led(a, 20, 66, .5)
    bevel(a, 16, 122, 24, 128)
    save_prop("antenna_d", a, [(20, 1.2, RED), (20, 66, RED)], 4)


def prop_antenna_e():
    a = Art(28, 74, 8, ss=3)
    bevel(a, 5, 66, 23, 74)
    for (x, top) in ((8, 14), (12, 4), (16, 24), (20, 10), (24, 30)):
        a.line([(x, 66), (x + (x - 14) * .04, top)], (84, 94, 106, 255), .4)
    a.ellipse(12, 4, .5, .5, RED + (255,))
    a.ellipse(20, 10, .45, .45, (230, 236, 240, 255))
    save_prop("antenna_e", a, [(12, 4, RED), (20, 10, (214, 222, 230))], 5)


def prop_tower_surveillance():
    a = Art(18, 66, 8, ss=3)
    a.rect(7.4, 14, 10.6, 66, (46, 52, 61, 255))
    lattice(a, 7.4, 7.4, 10.6, 10.6, 14, 66, 6.0, .45)
    a.ellipse(9, 12, 6.5, 6.5, (0, 0, 0, 0))
    a.rrect(2.5, 6, 15.5, 14, 2.2, BASE + (255,))                  # camera pod
    a.rect(2.5, 6, 15.5, 6.5, HI + (255,))
    a.rect(11.5, 8, 14.5, 12, (6, 8, 10, 255))                      # lens
    a.rect(12.0, 9, 13.0, 10.2, (150, 160, 172, 255))
    a.rect(8.7, 2, 9.3, 6, (84, 94, 106, 255))
    led(a, 9, 2.2, .55)
    bevel(a, 4, 62, 14, 66)
    save_prop("tower_surveillance", a, [(9, 2.2, RED)], 6)


def prop_cctv_pole():
    a = Art(14, 36, 8, ss=3)
    a.rect(2.5, 4, 3.8, 36, (62, 70, 82, 255))
    a.rect(2.5, 4, 11, 5.2, (62, 70, 82, 255))
    a.poly([(8, 5), (13, 6.2), (13, 9.8), (8, 8.6)], BASE + (255,))
    a.rect(12.2, 6.8, 13, 8.2, (150, 160, 172, 255))
    led(a, 9.2, 8.8, .45)
    save_prop("cctv_pole", a, [(9.2, 8.8, RED)], 7)


def prop_vent_a():
    a = Art(40, 18, 8, ss=3)
    bevel(a, 1, 6, 39, 18)
    for cx in (10, 30):
        a.ellipse(cx, 12.5, 4.2, 4.2, (9, 11, 14, 255))
        a.ellipse(cx, 12.5, 3.6, 3.6, (28, 32, 38, 255))
        for k in range(8):
            ang = k * math.pi / 8
            a.line([(cx - math.cos(ang) * 3.4, 12.5 - math.sin(ang) * 3.4), (cx + math.cos(ang) * 3.4, 12.5 + math.sin(ang) * 3.4)], (56, 63, 73, 255), .35)
    bevel(a, 5, 1, 15, 6, BASE2)
    bevel(a, 25, 3, 35, 6, BASE2)
    a.rect(18.5, 6, 21.5, 18, (22, 26, 31, 255))
    save_prop("vent_a", a, None, 8)


def prop_vent_b():
    a = Art(24, 26, 8, ss=3)
    bevel(a, 1, 18, 23, 26)
    for (cx, top) in ((7, 3), (17, 7)):
        a.rect(cx - 2.6, top + 1, cx + 2.6, 18, BASE + (255,))
        a.rect(cx - 2.6, top + 1, cx - 1.6, 18, (74, 82, 94, 255))
        a.rrect(cx - 3.8, top - 1, cx + 3.8, top + 2, .6, (60, 68, 80, 255))
        a.rect(cx - 3.8, top - 1, cx + 3.8, top - .5, HI + (255,))
    save_prop("vent_b", a, None, 9)


def prop_pipes_a():
    a = Art(56, 14, 8, ss=3)
    for x in (5, 20, 36, 51):
        a.rect(x, 8, x + 1.8, 14, (30, 34, 40, 255))
    for (y, r, col) in ((5.2, 1.7, (46, 52, 61, 255)), (9.2, 1.3, (38, 43, 50, 255))):
        a.rect(0, y - r, 56, y + r, col)
        a.rect(0, y - r, 56, y - r + .4, HI + (255,))
        for x in (10, 28, 44):
            a.rect(x, y - r - .5, x + .8, y + r + .5, (70, 78, 90, 255))
    a.rect(50, 0, 52.6, 6, (46, 52, 61, 255))
    a.ellipse(30, 2.2, 2.6, 2.6, (20, 23, 28, 255))
    a.ellipse(30, 2.2, 2.0, 2.0, (58, 66, 78, 255))
    a.line([(28, 2.2), (32, 2.2)], (20, 23, 28, 255), .35)
    a.line([(30, 0.2), (30, 4.2)], (20, 23, 28, 255), .35)
    a.rect(29.8, 2.5, 30.6, 5, (46, 52, 61, 255))
    save_prop("pipes_a", a, None, 10)


def prop_pipes_b():
    a = Art(44, 30, 8, ss=3)
    for (x, top, r) in ((8, 4, 1.8), (18, 12, 1.4), (31, 2, 2.1)):
        a.rect(x - r, top, x + r, 30, (44, 50, 58, 255))
        a.rect(x - r, top, x - r + .5, 30, HI + (255,))
        a.rect(x - r - .5, top, x + r + .5, top + 1.2, (66, 74, 86, 255))
    a.rect(6, 17, 34, 19, (38, 43, 50, 255))
    a.ellipse(25, 8, 3.3, 3.3, (14, 16, 19, 255))
    a.ellipse(25, 8, 2.7, 2.7, (180, 188, 198, 255))
    a.line([(25, 8), (26.6, 6.6)], (10, 12, 14, 255), .3)
    bevel(a, 36, 22, 44, 30, BASE2)
    save_prop("pipes_b", a, None, 11)


def prop_skylight():
    a = Art(40, 9, 8, ss=3)
    a.poly([(1, 9), (5, 2), (35, 2), (39, 9)], (34, 39, 46, 255))
    a.poly([(3, 9), (6, 3.4), (34, 3.4), (37, 9)], (10, 14, 19, 255))
    for x in (13, 20, 27):
        a.line([(x - 2, 9), (x, 3.4)], (44, 50, 59, 255), .35)
    a.poly([(9, 8.5), (12, 3.6), (17, 3.6), (14, 8.5)], (188, 200, 214, 60))
    a.rect(5, 1.6, 35, 2.3, HI + (255,))
    save_prop("skylight", a, None, 12)


def prop_access_hut():
    a = Art(38, 32, 8, ss=3)
    bevel(a, 1, 4, 37, 32, (30, 34, 40))
    a.rect(0, 2, 38, 4, (50, 57, 66, 255))
    a.rect(0, 2, 38, 2.5, HI + (255,))
    a.rect(6, 12, 15, 32, (8, 10, 12, 255))                       # door
    a.rect(6.6, 12.6, 14.4, 32, (24, 28, 34, 255))
    a.rect(7.4, 14, 13.6, 18, (150, 164, 180, 255))
    a.ellipse(13, 24, .5, .5, (150, 160, 172, 255))
    a.rect(5, 8, 16, 9, (226, 232, 238, 255))                     # light strip over the door
    a.rect(22, 12, 34, 20, (9, 12, 15, 255))                      # louvres
    for k in range(5):
        a.rect(22.4, 12.6 + k * 1.5, 33.6, 13.2 + k * 1.5, (48, 54, 62, 255))
    a.rect(24, 0, 28, 2, (60, 68, 80, 255))
    led(a, 31, 7, .5)
    save_prop("access_hut", a, [(10.5, 8.5, (226, 232, 238)), (31, 7, RED)], 13)


def prop_tank():
    a = Art(34, 72, 8, ss=3)
    for x in (5, 12, 22, 29):
        a.rect(x, 44, x + 1.2, 72, (40, 46, 54, 255))
    lattice(a, 5, 5, 29, 29, 44, 72, 7.5, .5)
    a.rect(2, 14, 32, 46, (44, 50, 59, 255))
    a.rect(2, 14, 4, 46, (84, 94, 106, 255))
    a.rect(30, 14, 32, 46, (16, 18, 22, 255))
    for y in (22, 30, 38):
        a.rect(2, y, 32, y + .6, (22, 26, 31, 255))
    a.poly([(2, 14), (17, 3), (32, 14)], (56, 63, 74, 255))
    a.poly([(2, 14), (17, 3), (17, 14)], (78, 88, 100, 255))
    a.rect(16.4, 0, 17.6, 3.5, (70, 78, 90, 255))
    a.rect(33, 14, 34, 72, (66, 74, 86, 255))
    save_prop("tank", a, None, 14)


def prop_crates():
    a = Art(26, 18, 8, ss=3)
    bevel(a, 1, 8, 13, 18, (46, 50, 56))
    bevel(a, 13, 10, 25, 18, (40, 44, 50))
    bevel(a, 5, 1, 17, 8, (52, 57, 64))
    for (x0, y0, x1, y1) in ((1, 8, 13, 18), (13, 10, 25, 18), (5, 1, 17, 8)):
        a.line([(x0, y0), (x1, y1)], (16, 18, 22, 255), .35)
        a.line([(x1, y0), (x0, y1)], (16, 18, 22, 255), .35)
    save_prop("crates", a, None, 15)


def prop_floodlight():
    a = Art(18, 44, 8, ss=3)
    a.rect(8, 8, 9.6, 44, (60, 68, 80, 255))
    a.poly([(2, 3), (14, 1), (15, 8), (3, 9)], BASE + (255,))
    a.poly([(2, 3), (14, 1), (14.3, 2.6), (2.2, 4.4)], HI + (255,))
    a.poly([(2.6, 4.6), (13.6, 3), (14.2, 7), (3.2, 8.2)], (226, 232, 238, 255))
    bevel(a, 5, 40, 13, 44)
    save_prop("floodlight", a, [(8.5, 6, (226, 232, 238))], 16)


# ---- tiles and strips ----------------------------------------------------------------------------
def make_fence():
    a = Art(32, 32, 8, ss=3, wrap=(32, 0))
    a.rect(0, 0, 32, .9, (70, 78, 90, 255))
    a.rect(0, 31, 32, 32, (60, 68, 80, 255))
    for k in range(-16, 32):
        a.line([(k * 2.0, 1), (k * 2.0 + 30, 31)], (84, 94, 106, 150), .17)
        a.line([(k * 2.0 + 30, 1), (k * 2.0, 31)], (84, 94, 106, 150), .17)
    a.rect(-.7, 0, .7, 32, (52, 58, 68, 255))
    a.rect(-.7, 0, -.2, 32, (110, 120, 132, 255))
    save_png(finish_prop(a.finish(), 1.0, .1, 17), "fence.png")


def make_railing():
    a = Art(32, 10, 8, ss=3, wrap=(32, 0))
    a.rect(0, .6, 32, 1.4, (80, 90, 102, 255))
    a.rect(0, 5, 32, 5.5, (56, 63, 73, 255))
    a.rect(0, 9, 32, 10, (40, 45, 52, 255))
    for x in (0, 16):
        a.rect(x - .5, .6, x + .5, 10, (62, 70, 82, 255))
    save_png(finish_prop(a.finish(), 1.0, .1, 18), "railing.png")


def make_escape():
    """4 frames of 32 x 32 units: ladder, landing, caged ladder, pipe run. Hung on building sides."""
    a = Art(128, 32, 8, ss=3)
    c, c2 = (62, 70, 82, 255), (34, 39, 46, 255)
    a.rect(10, 0, 11.2, 32, c); a.rect(21, 0, 22.2, 32, c)               # 0 ladder
    for y in range(2, 32, 3):
        a.rect(10, y, 22.2, y + .6, c2)
    a.rect(32, 24, 64, 26.5, c); a.rect(32, 26.5, 64, 27.3, c2)          # 1 landing
    for x in range(33, 63, 2):
        a.rect(x, 24.6, x + .5, 26.3, (10, 12, 14, 255))
    a.rect(32, 14, 33, 24, c); a.rect(63, 14, 64, 24, c); a.rect(32, 14, 64, 15, c)
    a.rect(74, 0, 75.2, 32, c); a.rect(85, 0, 86.2, 32, c)               # 2 caged
    for y in range(2, 32, 4):
        a.rect(74, y + 1.5, 86.2, y + 2.1, c2)
    for y in range(3, 32, 9):
        a.line([(72, y), (77, y - 3), (83, y - 3), (88, y)], c, .5)
        a.line([(72, y), (77, y + 3), (83, y + 3), (88, y)], c, .5)
    for (x, r) in ((107, 1.4), (112, 1.1), (118, 1.6)):                  # 3 pipes
        a.rect(x - r, 0, x + r, 32, c2)
        a.rect(x - r, 0, x - r + .4, 32, (84, 94, 106, 255))
        for y in range(5, 32, 9):
            a.rect(x - r - .4, y, x + r + .4, y + .7, c)
    save_png(finish_prop(a.finish(), 1.0, .05, 19), "escape.png")


def make_obstacles():
    """Low clutter, 4 frames of 14 x 14 units each (floor line at y = 12). Hit box stays ankle-high."""
    for nm, variant in (("obstacles", 0), ("obstacles2", 1)):
        a = Art(56, 14, 8, ss=3)
        o = 0
        if variant == 0:                      # corridor: spool, bag, barrier, crate shards
            a.rrect(1, 4, 13, 12, 2, (54, 60, 69, 255)); a.ellipse(3, 8, 1.8, 4, (36, 41, 48, 255)); a.ellipse(3, 8, .7, 1.5, (12, 14, 17, 255))
            a.rect(1, 4, 13, 4.5, HI + (255,))
            a.ellipse(21, 9, 5.5, 3.2, (24, 27, 32, 255)); a.ellipse(20, 8, 3.2, 1.6, (48, 54, 62, 255))
            a.poly([(16, 12), (17, 8), (25, 8), (27, 12)], (30, 34, 40, 255))
            a.rect(29, 6, 41, 8, (66, 74, 86, 255)); a.rect(29, 8, 41, 9, (16, 18, 22, 255))
            a.rect(30, 9, 31.4, 12, (46, 52, 61, 255)); a.rect(39, 9, 40.4, 12, (46, 52, 61, 255))
            a.rect(33, 6, 35, 8, (206, 212, 218, 255)); a.rect(37, 6, 38.6, 8, (206, 212, 218, 255))
            a.poly([(43, 12), (45, 8), (49, 9), (50, 12)], (60, 66, 76, 255))
            a.poly([(50, 12), (51, 9), (55, 10), (55.5, 12)], (42, 47, 55, 255))
            a.rect(44, 6, 47, 8, (74, 82, 94, 255))
        else:                                 # roof: sandbags, cable coil, pallet, rubble
            for (x, y, w) in ((1.5, 9, 6), (7.5, 9, 6), (4.5, 5.6, 6)):
                a.rrect(x, y, x + w, y + 3.4, 1.4, (58, 62, 68, 255)); a.rect(x + 1, y + .4, x + w - 1, y + .8, (96, 102, 112, 200))
            a.ellipse(21, 8.5, 5.6, 3.6, (24, 27, 32, 255)); a.ellipse(21, 8, 4.0, 2.4, (50, 56, 64, 255)); a.ellipse(21, 7.8, 1.6, 1.0, (12, 14, 17, 255))
            a.rect(29, 10, 41, 11.4, (58, 64, 74, 255)); a.rect(29, 11.4, 41, 12, (14, 16, 19, 255))
            for x in (30, 34.5, 38.8):
                a.rect(x, 8.4, x + 1.6, 10, (48, 54, 62, 255))
            a.rect(31, 6.2, 39, 8.2, (70, 78, 90, 255))
            for (x, y, s) in ((44, 9, 3.2), (48, 10, 2.4), (51.4, 8.6, 3.2), (46.5, 6.4, 2.4)):
                a.poly([(x, y + s), (x + s * .3, y), (x + s, y + s * .35), (x + s * 1.1, y + s)], (50, 56, 65, 255))
        save_png(finish_prop(a.finish(), 1.6, .12, 20 + variant), nm + ".png")


def make_doors():
    """4 corridor doors, 12 x 19 units each."""
    a = Art(48, 19, 8, ss=3)
    for k in range(4):
        x = k * 12
        bevel(a, x + 1, 3, x + 11, 19, (34, 39, 46))
        a.rect(x + 2, 4, x + 10, 19, (22, 26, 31, 255))
        if k in (0, 2):
            a.rect(x + 3.4, 6, x + 8.6, 10, (150, 164, 180, 255) if k == 0 else (22, 28, 36, 255))
        if k == 1:
            a.rect(x + 2, 4, x + 10, 19, (30, 34, 40, 255))
            a.poly([(x + 6, 7), (x + 9, 13), (x + 3, 13)], (186, 36, 32, 255))
        if k == 3:
            a.rect(x + 4.2, 4, x + 7.8, 19, (4, 5, 6, 255))
        a.rect(x + 2, 0.5, x + 10, 1.3, (226, 232, 238, 255))
        a.ellipse(x + 9, 12.5, .45, .45, (150, 160, 172, 255))
        led(a, x + 3, 2.4, .4)
    save_png(finish_prop(a.finish(), 1.2, .1, 22), "doors.png")


def make_cracks():
    a = Art(96, 24, 8, ss=3)
    r = rng(30)
    for k in range(4):
        cx, cy = k * 24 + 12, 12
        for b in range(5):
            ang, pts, x, y = r.uniform(0, 2 * math.pi), [], cx, cy
            for s in range(int(r.integers(4, 7))):
                pts.append((x, y))
                ang += r.uniform(-.7, .7)
                L = r.uniform(1.5, 4.0)
                x, y = x + math.cos(ang) * L, y + math.sin(ang) * L
            a.line(pts, (150, 160, 172, 70), .55)
            a.line(pts, (2, 3, 4, 230), .32)
    save_png(a.finish(), "cracks.png")


def make_crane_parts():
    d = Art(32, 32, 8, ss=3, wrap=(32, 0))           # deck truss tile
    c, c2 = (58, 66, 78, 255), (36, 41, 48, 255)
    d.rect(0, 0, 32, 2.6, (40, 46, 54, 255)); d.rect(0, 0, 32, .6, (112, 122, 134, 255))
    d.rect(0, 29.4, 32, 32, c2)
    for x in (0, 16):
        d.rect(x - .5, 2.6, x + .5, 29.4, c)
    for k in range(2):
        d.line([(k * 16, 2.6), (k * 16 + 16, 29.4)], c, .7)
        d.line([(k * 16 + 16, 2.6), (k * 16, 29.4)], (46, 52, 61, 255), .7)
    save_png(finish_prop(d.finish(), 1.0, .1, 23), "crane_deck.png")
    col = Art(32, 32, 8, ss=3, wrap=(0, 32))         # support column tile (tiles in y)
    col.rect(3, 0, 5, 32, c); col.rect(27, 0, 29, 32, c)
    col.line([(5, 0), (27, 16), (5, 32)], c, .7)
    col.line([(27, 0), (5, 16), (27, 32)], (46, 52, 61, 255), .7)
    col.rect(3, 15.5, 29, 16.5, (46, 52, 61, 255))
    save_png(finish_prop(col.finish(), 1.0, .05, 24), "crane_column.png")
    cab = Art(56, 30, 8, ss=3)
    bevel(cab, 2, 6, 40, 30, (32, 37, 44))
    cab.poly([(40, 6), (54, 12), (54, 30), (40, 30)], (28, 32, 38, 255))
    cab.poly([(41, 9), (51, 13.5), (51, 20), (41, 20)], (150, 164, 180, 255))
    cab.rect(8, 11, 30, 19, (12, 15, 19, 255))
    cab.rect(0, 3, 42, 6, (50, 57, 66, 255)); cab.rect(0, 3, 42, 3.6, HI + (255,))
    cab.rect(20, 0, 21, 3, (86, 96, 108, 255))
    led(cab, 20.5, .8, .5)
    save_prop("crane_cab", cab, [(20.5, .8, RED)], 25)
    wn = Art(40, 16, 8, ss=3)
    bevel(wn, 1, 4, 39, 16, (36, 41, 48))
    wn.ellipse(10, 10, 4.5, 4.5, (14, 16, 19, 255)); wn.ellipse(10, 10, 3.6, 3.6, (56, 63, 73, 255))
    wn.rect(18, 1, 38, 4, (70, 78, 90, 255))
    save_prop("crane_winch", wn, None, 26)
    hk = Art(14, 46, 8, ss=3)
    hk.rect(6.4, 0, 7.6, 24, (60, 68, 80, 255))
    bevel(hk, 3, 24, 11, 31, (44, 50, 58))
    hk.line([(7, 31), (7, 38), (10, 41), (7, 44), (4, 41)], (96, 106, 118, 255), 1.0)
    save_prop("crane_hook", hk, None, 27)


def make_world(filters):
    steps = [("wall", lambda: [make_wall(i) for i in range(4)]),
             ("roof", lambda: [make_roof(i) for i in range(3)]),
             ("floor", lambda: [make_floor(i) for i in range(2)]),
             ("hall_wall", make_hall_wall),
             ("antenna", lambda: [f() for f in (prop_antenna_a, prop_antenna_b, prop_antenna_c, prop_antenna_d, prop_antenna_e)]),
             ("tower_cctv", lambda: [prop_tower_surveillance(), prop_cctv_pole()]),
             ("vent_pipes", lambda: [prop_vent_a(), prop_vent_b(), prop_pipes_a(), prop_pipes_b()]),
             ("roofprops", lambda: [prop_skylight(), prop_access_hut(), prop_tank(), prop_crates(), prop_floodlight()]),
             ("fence_railing_escape", lambda: [make_fence(), make_railing(), make_escape()]),
             ("obstacles_doors_cracks", lambda: [make_obstacles(), make_doors(), make_cracks()]),
             ("crane", make_crane_parts)]
    for name, fn in steps:
        if want(filters, name):
            fn()
# ============================================================================
# 6. PLAYER  - the runner, a small dark silhouette. Skeleton driven: every frame is a pose, drawn with
#    tapered capsules at 4x supersampling, rim-lit and downsampled to 8 px per unit.
#    Frames 24 x 24 units (192 px), 8 per row. Frame map (also listed in config.js -> PLAYER.animations):
#      0-15 run   16-19 jump   20-26 fall   27-37 tumble   38-41 land   42-47 die
#    Feet rest on the frame's bottom edge (y = 24); the game aligns it with the 12 x 14 hit box.
# ============================================================================
GROUND = 24.0
L_THIGH, L_SHIN, L_FOOT, L_TORSO, L_NECK, R_HEAD, L_UARM, L_FARM = 4.7, 4.7, 2.3, 6.0, .9, 1.5, 3.1, 3.1
C_NEAR, C_FAR, C_PACK, C_SCARF = (8, 9, 11, 255), (24, 27, 33, 255), (15, 17, 21, 255), (27, 31, 37, 255)


def _fk_leg(hip, th, bend, fa):
    k = (hip[0] + math.sin(th) * L_THIGH, hip[1] + math.cos(th) * L_THIGH)
    a = (k[0] + math.sin(th - bend) * L_SHIN, k[1] + math.cos(th - bend) * L_SHIN)
    t = (a[0] + math.cos(fa) * L_FOOT, a[1] + math.sin(fa) * L_FOOT)
    return k, a, t


def _ik_leg(hip, ankle, fa):
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    d = min(max(math.hypot(dx, dy), abs(L_THIGH - L_SHIN) + .05), L_THIGH + L_SHIN - .05)
    a = (L_THIGH ** 2 - L_SHIN ** 2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, L_THIGH ** 2 - a * a))
    ux, uy = dx / (math.hypot(dx, dy) or 1), dy / (math.hypot(dx, dy) or 1)
    c = (hip[0] + ux * a, hip[1] + uy * a)
    k1, k2 = (c[0] - uy * h, c[1] + ux * h), (c[0] + uy * h, c[1] - ux * h)
    k = k1 if k1[0] > k2[0] else k2                          # knees always bend forward
    t = (ankle[0] + math.cos(fa) * L_FOOT, ankle[1] + math.sin(fa) * L_FOOT)
    return k, ankle, t


def _fk_arm(sh, a, b):
    e = (sh[0] + math.sin(a) * L_UARM, sh[1] + math.cos(a) * L_UARM)
    h = (e[0] + math.sin(a + b) * L_FARM, e[1] + math.cos(a + b) * L_FARM)
    return e, h


def joints(hip, lean, legs, arms, scarf_mode="run", scarf_phase=0.0, head_lean=.12):
    """legs = ((near joints), (far joints)) each (knee, ankle, toe); arms = ((e, h), (e, h))."""
    sh = (hip[0] + math.sin(lean) * L_TORSO, hip[1] - math.cos(lean) * L_TORSO)
    hl = lean + head_lean
    head = (sh[0] + math.sin(hl) * (L_NECK + R_HEAD), sh[1] - math.cos(hl) * (L_NECK + R_HEAD))
    return dict(hip=hip, sh=sh, head=head, lean=lean, legs=legs,
                arms=(_fk_arm(sh, *arms[0]), _fk_arm(sh, *arms[1])), scarf=(scarf_mode, scarf_phase))


def pose_fk(hip, lean, nl, fl, na, fa, **kw):
    return joints(hip, lean, (_fk_leg(hip, *nl), _fk_leg(hip, *fl)), (na, fa), **kw)


def pose_run(t, hip_h=8.7, step=3.5, lift=3.6, lean=.38, bob=.36, xoff=11.4):
    hip = (xoff, GROUND - hip_h - bob * math.cos(4 * math.pi * t))
    legs, arms = [], []
    for k in (0, 1):
        tt = (t + .5 * k) % 1.0
        if tt < .5:
            u = tt / .5
            fa = -.12 + .8 * u ** 3
            fx, fy = hip[0] + step * .9 - step * 2.0 * u, GROUND - .55 - L_FOOT * max(0.0, math.sin(fa))
        else:
            u = (tt - .5) / .5
            e = u * u * (3 - 2 * u)
            fx, fy, fa = hip[0] - step * 1.1 + step * 2.0 * e, GROUND - .75 - lift * math.sin(math.pi * u) ** .9, .75 - .55 * e
        legs.append(_ik_leg(hip, (fx, fy), fa))
        arms.append((-.95 * math.cos(2 * math.pi * tt) + .15, 1.45 - .35 * math.cos(2 * math.pi * tt)))
    return joints(hip, lean + .03 * math.sin(4 * math.pi * t), tuple(legs), tuple(arms), "run", t * 2 * math.pi)


def lerp_list(a, b, t):
    return [lerp(x, y, t) if not isinstance(x, (list, tuple)) else lerp_list(x, y, t) for x, y in zip(a, b)]


def fkp(hx, hy, lean, nl, fl, na, fa, **kw):
    return dict(hip=(hx, hy), lean=lean, nl=nl, fl=fl, na=na, fa=fa, **kw)


def build_fk(p):
    return pose_fk(p["hip"], p["lean"], p["nl"], p["fl"], p["na"], p["fa"],
                   scarf_mode=p.get("sm", "run"), scarf_phase=p.get("sp", 0.0))


def mix(p, q, t):
    o = dict(p)
    o["hip"] = tuple(lerp_list(p["hip"], q["hip"], t))
    o["lean"] = lerp(p["lean"], q["lean"], t)
    for k in ("nl", "fl", "na", "fa"):
        o[k] = tuple(lerp_list(p[k], q[k], t))
    return o


def rot_pt(p, c, th):
    s, co = math.sin(th), math.cos(th)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (c[0] + dx * co - dy * s, c[1] + dx * s + dy * co)


def rotate_joints(J, c, th):
    R = lambda p: rot_pt(p, c, th)
    o = dict(J)
    for k in ("hip", "sh", "head"):
        o[k] = R(J[k])
    o["legs"] = tuple(tuple(R(p) for p in leg) for leg in J["legs"])
    o["arms"] = tuple(tuple(R(p) for p in arm) for arm in J["arms"])
    o["rot"] = th
    return o


def scarf_points(J):
    mode, ph = J["scarf"]
    neck = (J["sh"][0] + math.sin(J["lean"]) * .6, J["sh"][1] - math.cos(J["lean"]) * .6)
    rot = J.get("rot", 0.0)
    pts = []
    for i in range(8):
        f = i / 7
        if mode == "run":
            p = (-i * .85, -.05 * i * 1.0 + math.sin(ph * 2 + i * .85) * .55 * f)
        elif mode == "up":
            p = (-i * .25 + math.sin(ph + i) * .5 * f, -i * .8)
        else:
            p = (-i * .6 + math.sin(ph + i) * .7 * f, i * .15 + math.cos(ph + i * .8) * .6 * f)
        q = rot_pt((neck[0] + p[0], neck[1] + p[1]), neck, rot)
        pts.append(q)
    return pts, neck


def draw_figure(a, J):
    def leg(hip, kn, an, toe, col):
        a.capsule(hip, kn, 1.25, .95, col)
        a.capsule(kn, an, .95, .64, col)
        a.capsule(an, toe, .62, .46, col)
        a.ellipse(an[0], an[1], .75, .75, col)

    def arm(sh, el, ha, col):
        a.capsule(sh, el, .85, .68, col)
        a.capsule(el, ha, .66, .5, col)
        a.ellipse(ha[0], ha[1], .58, .58, col)

    hip, sh, head = J["hip"], J["sh"], J["head"]
    (kn_n, an_n, to_n), (kn_f, an_f, to_f) = J["legs"]
    (el_n, ha_n), (el_f, ha_f) = J["arms"]
    leg(hip, kn_f, an_f, to_f, C_FAR)
    arm(sh, el_f, ha_f, C_FAR)
    pts, neck = scarf_points(J)
    for i in range(len(pts) - 1):
        a.capsule(pts[i], pts[i + 1], 1.15 * (1 - i / 8) + .12, 1.15 * (1 - (i + 1) / 8) + .1, C_SCARF)
    # backpack: sits on the upper back, along the torso axis
    tx, ty = sh[0] - hip[0], sh[1] - hip[1]
    L = math.hypot(tx, ty) or 1
    ux, uy = tx / L, ty / L                        # up the torso
    bx, by = -uy, ux                               # towards the back
    if bx > 0:
        bx, by = -bx, -by
    c = (hip[0] + ux * L * .62 + bx * 1.85, hip[1] + uy * L * .62 + by * 1.85)
    pk = [(c[0] + ux * 2.1 + bx * 1.3, c[1] + uy * 2.1 + by * 1.3), (c[0] + ux * 2.1 - bx * 1.3, c[1] + uy * 2.1 - by * 1.3),
          (c[0] - ux * 1.9 - bx * 1.3, c[1] - uy * 1.9 - by * 1.3), (c[0] - ux * 1.9 + bx * 1.3, c[1] - uy * 1.9 + by * 1.3)]
    a.poly(pk, C_PACK)
    a.capsule(hip, sh, 1.35, 1.72, C_NEAR)         # torso
    a.capsule((sh[0] - ux * .2, sh[1] - uy * .2), (sh[0] + ux * .7, sh[1] + uy * .7), 1.0, 1.3, C_NEAR)   # neck
    hx, hy = head
    a.ellipse(hx + bx * .45, hy + by * .45 + .05, 1.62, 1.72, C_NEAR)         # hood bump
    a.ellipse(hx, hy, 1.6, 1.7, C_NEAR)
    leg(hip, kn_n, an_n, to_n, C_NEAR)
    arm(sh, el_n, ha_n, C_NEAR)
    return (c[0] + bx * 1.35 + ux * 1.4, c[1] + by * 1.35 + uy * 1.4)        # where the pack LED goes


def render_player_frame(J):
    a = Art(24, 24, 8, ss=4)
    led_pos = draw_figure(a, J)
    im = a.finish()
    arr = np.array(im).astype(np.float32)
    A = arr[..., 3] / 255.0
    rp = 2
    rim = np.clip(A - np.roll(np.roll(A, rp, 1), rp, 0), 0, 1)               # light from upper-left
    rim = ndi.gaussian_filter(rim, .7)
    col = np.array([104, 118, 136], np.float32)
    arr[..., :3] = arr[..., :3] * (1 - rim[..., None] * .75) + col * rim[..., None] * .75
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    add_glow(out, led_pos[0] * 8, led_pos[1] * 8, 7, PAL["red"], .8)
    d = ImageDraw.Draw(out)
    d.ellipse([led_pos[0] * 8 - 1.6, led_pos[1] * 8 - 1.6, led_pos[0] * 8 + 1.6, led_pos[1] * 8 + 1.6], fill=(255, 120, 110, 255))
    return out


def player_poses():
    P = []
    for i in range(16):                                                    # 0-15 run
        P.append(pose_run(i / 16.0))
    crouch = fkp(11.5, 17.4, .5, (.5, 1.2, .2), (-.3, 1.0, .2), (-1.0, .7), (-.8, .6))      # 16-19 jump
    P.append(build_fk(crouch))
    P.append(build_fk(fkp(11.5, 14.7, .22, (.9, .6, .6), (-.5, .2, .9), (1.6, .5), (1.1, .5))))
    P.append(build_fk(fkp(11.5, 13.7, .25, (1.4, 1.9, .3), (-.35, .7, .9), (1.3, .9), (-.3, .9))))
    P.append(build_fk(fkp(11.5, 13.3, .2, (1.25, 1.55, .2), (.2, 1.2, .5), (1.0, 1.0), (1.7, .7))))
    for i in range(7):                                                     # 20-26 fall (loops)
        ph = 2 * math.pi * i / 7
        P.append(build_fk(fkp(11.5, 12.8, .1 + .06 * math.sin(ph),
                              (.8 + .5 * math.sin(ph), 1.1 + .5 * math.cos(ph), .5), (.2 - .5 * math.sin(ph), 1.0 - .4 * math.cos(ph), .6),
                              (1.95 + .3 * math.sin(ph + 1), .75), (2.2 - .25 * math.sin(ph), .6), sm="up", sp=ph)))
    stumble = fkp(11.5, 16.5, .75, (1.0, 1.4, .3), (.5, 1.2, .3), (1.0, .8), (1.6, .8), sm="tumble")      # 27-37 tumble (roll)
    curled = fkp(12, 14.2, .85, (1.7, 2.4, .4), (1.5, 2.3, .4), (.5, 2.3), (.3, 2.2), sm="tumble")
    ready = fkp(11.5, 17.0, .55, (.7, 1.3, .3), (-.2, 1.0, .3), (-.5, 1.2), (.4, 1.2), sm="run")
    for i in range(11):
        t = i / 10.0
        curl = smoothstep(0.0, .22, t) * (1 - smoothstep(.72, .95, t))
        base = mix(stumble, ready, smoothstep(.65, 1.0, t))
        J = build_fk(mix(base, curled, curl))
        J["scarf"] = ("tumble", t * 9)
        th = 2 * math.pi * smoothstep(.08, .92, t)
        P.append(rotate_joints(J, (12, 14.5), th) if 0 < i < 10 else J)
    for hy, ln, nl, fl, na, fa in ((18.0, .55, (.9, 1.4, .3), (-.2, 1.0, .3), (.7, 1.0), (.5, 1.0)),      # 38-41 land
                                   (19.4, .70, (1.15, 1.9, .2), (.1, 1.5, .3), (.5, 1.3), (.2, 1.3)),
                                   (18.4, .55, (.95, 1.5, .3), (-.1, 1.1, .3), (-.1, 1.3), (.3, 1.3)),
                                   (17.2, .42, (.55, 1.2, .3), (-.3, 1.0, .3), (-.8, 1.0), (-.5, 1.1))):
        P.append(build_fk(fkp(11.5, hy, ln, nl, fl, na, fa)))
    die = [(0.0, fkp(11.5, 16.8, -.15, (.8, 1.0, .3), (.3, .9, .3), (1.9, .5), (1.6, .5), sm="up")),       # 42-47 die
           (-.14, fkp(11.0, 15.2, -.5, (.4, .5, .4), (.1, .6, .4), (2.4, .4), (2.2, .4), sm="up")),
           (-.38, fkp(10.4, 14.6, -.8, (.1, .4, .5), (-.3, .5, .5), (2.7, .3), (2.5, .3), sm="up")),
           (-.70, fkp(10.0, 14.2, -1.0, (-.1, .5, .6), (-.5, .4, .6), (2.8, .2), (2.3, .2), sm="up")),
           (-1.05, fkp(9.8, 14.0, -1.1, (-.3, .3, .6), (-.7, .3, .7), (2.7, .3), (2.1, .3), sm="up")),
           (-1.45, fkp(9.6, 13.8, -1.1, (-.4, .3, .7), (-.8, .2, .7), (2.5, .4), (1.9, .4), sm="up"))]
    for th, p in die:
        J = build_fk(p)
        J["scarf"] = ("up", 1.0)
        P.append(rotate_joints(J, (11.5, 15.0), th) if th else J)
    return P


def make_player():
    poses = player_poses()
    cols = 8
    rows = (len(poses) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * 192, rows * 192), (0, 0, 0, 0))
    for i, J in enumerate(poses):
        sheet.alpha_composite(render_player_frame(J), ((i % cols) * 192, (i // cols) * 192))
    save_png(sheet, "player.png")
    return len(poses)
# ============================================================================
# 7. ACTORS  - mech, airship, gunship, drone, missile, particles, foreground silhouettes, icons
# ============================================================================
def haze_rgba(im, fog, top=.25, bottom=.8, start=.3):
    """Fade an RGBA sprite towards fog colour from `start` (0..1 of its height) downwards."""
    a = np.array(im).astype(np.float32)
    h = a.shape[0]
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    t = lerp(top, bottom, smoothstep(start, 1.0, ys))
    a[..., :3] = lerp(a[..., :3], np.array(fog, np.float32), t)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def rim_light(im, col=(150, 160, 174), amt=.5, rp=2, blur=.8):
    arr = np.array(im).astype(np.float32)
    A = arr[..., 3] / 255.0
    rim = ndi.gaussian_filter(np.clip(A - np.roll(np.roll(A, rp, 1), rp, 0), 0, 1), blur)
    arr[..., :3] = arr[..., :3] * (1 - rim[..., None] * amt) + np.array(col, np.float32) * rim[..., None] * amt
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


# ---- mech ("walker") -------------------------------------------------------------------------------
def _mech_leg(a, hip, foot, col, hi):
    L1, L2 = 15.0, 16.5
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = min(max(math.hypot(dx, dy), 4.0), L1 + L2 - .1)
    q = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, L1 * L1 - q * q))
    ux, uy = dx / (math.hypot(dx, dy) or 1), dy / (math.hypot(dx, dy) or 1)
    c = (hip[0] + ux * q, hip[1] + uy * q)
    k1, k2 = (c[0] - uy * h, c[1] + ux * h), (c[0] + uy * h, c[1] - ux * h)
    knee = k1 if k1[0] < k2[0] else k2                    # facing left: knees point left
    ank = (hip[0] + ux * d, hip[1] + uy * d)
    a.capsule(hip, knee, 4.2, 3.2, col)
    a.capsule(knee, ank, 3.2, 2.2, col)
    a.poly([(ank[0] - 7, ank[1] + 3.2), (ank[0] - 5, ank[1] - 1), (ank[0] + 4, ank[1] - 1.5), (ank[0] + 5.5, ank[1] + 3.2)], col)
    a.line([hip, knee], hi, .5)
    return knee


def mech_frame(phase, fire):
    """phase 0..1 walk cycle; fire = None or 0..5 firing stage."""
    a = Art(96, 64, 2, ss=4)
    near, far, hi = (44, 50, 58, 255), (30, 35, 42, 255), (92, 102, 116, 255)
    bob = 1.3 * math.cos(4 * math.pi * phase) if phase is not None else 0
    gy = 62.0
    legs = []
    for k, hx in ((0, 46), (1, 60)):
        tt = ((phase or 0) + .5 * k) % 1.0
        if phase is None:
            fx, fy = hx + (-5 if k == 0 else 5), gy - 3.5
        elif tt < .5:
            u = tt / .5
            fx, fy = hx + 9 - 18 * u, gy - 3.5
        else:
            u = (tt - .5) / .5
            e = u * u * (3 - 2 * u)
            fx, fy = hx - 9 + 18 * e, gy - 3.5 - 8 * math.sin(math.pi * u)
        legs.append(((hx, 36 + bob), (fx, fy)))
    _mech_leg(a, legs[1][0], legs[1][1], far, hi)
    # cannon arm (far side, hangs)
    a.capsule((52, 24 + bob), (46, 40 + bob), 3, 2.4, far)
    # torso
    ty = bob
    a.poly([(34, 24 + ty), (40, 12 + ty), (58, 8 + ty), (74, 14 + ty), (76, 30 + ty), (66, 40 + ty), (42, 40 + ty), (36, 34 + ty)], near)
    a.poly([(34, 24 + ty), (40, 12 + ty), (58, 8 + ty), (60, 11 + ty), (42, 16 + ty), (38, 26 + ty)], (62, 70, 82, 255))
    a.rect(64, 16 + ty, 78, 34 + ty, far)                          # back radiator
    for k in range(5):
        a.rect(65, 18 + ty + k * 3, 77, 19 + ty + k * 3, (12, 14, 17, 255))
    a.poly([(28, 20 + ty), (38, 17 + ty), (40, 27 + ty), (30, 28 + ty)], near)                    # head
    a.rect(29.4, 22 + ty, 35, 23.4 + ty, (12, 14, 17, 255))
    a.rect(29.8, 22.3 + ty, 33, 23.1 + ty, (190, 38, 34, 255))                                     # eye slit
    a.line([(56, 8 + ty), (58, -2 + ty)], hi, .5)
    a.ellipse(58, -2 + ty, .7, .7, (210, 44, 38, 255))
    a.capsule((44, 20 + ty), (36, 14 + ty), 5.5, 4.0, near)        # shoulder pauldron
    for x in (46, 54, 62):
        a.rect(x, 33 + ty, x + 5, 34 + ty, (16, 19, 23, 255))
    _mech_leg(a, legs[0][0], legs[0][1], near, hi)
    # near arm + cannon
    sh = (42, 24 + ty)
    ang = 0.35 if fire is None else [0.9, 1.45, 1.75, 1.7, 1.5, .9][fire]    # 0 = straight down, ~1.6 = level forward(left)
    el = (sh[0] - math.sin(ang * .8) * 9, sh[1] + math.cos(ang * .8) * 9)
    tip = (el[0] - math.sin(ang) * 16, el[1] + math.cos(ang) * 16)
    a.capsule(sh, el, 3.4, 3.0, near)
    a.capsule(el, tip, 3.0, 2.2, near)
    a.capsule(el, (el[0] - math.sin(ang) * 6, el[1] + math.cos(ang) * 6), 3.9, 3.9, (36, 41, 48, 255))
    im = a.finish()
    im = rim_light(im, amt=.45)
    if fire in (2, 3):
        add_glow(im, tip[0] * 2 - 4, tip[1] * 2, 18, (236, 240, 246), 1.0)
    return haze_rgba(im, (118, 126, 136), .12, .72, .38)


def make_mech():
    frames = [mech_frame(i / 6.0, None) for i in range(6)] + [mech_frame(None, s) for s in range(6)]
    cols = 4
    sheet = Image.new("RGBA", (cols * 192, 3 * 128), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f, ((i % cols) * 192, (i // cols) * 128))
    save_png(sheet, "mech_walker.png")


# ---- airship ----------------------------------------------------------------------------------------
def make_airship():
    a = Art(240, 66, 2, ss=4)
    hull, hi = (66, 73, 83, 255), (112, 122, 136, 255)
    a.poly([(8, 30), (28, 12), (40, 22)], (50, 56, 65, 255))                # tail fins
    a.poly([(8, 32), (28, 52), (40, 40)], (50, 56, 65, 255))
    a.ellipse(124, 31, 112, 24, hull)
    a.ellipse(124, 27, 104, 15, (84, 93, 105, 255))
    for x in range(26, 224, 12):
        a.line([(x, 31 - 23 * math.sqrt(max(0, 1 - ((x - 124) / 112) ** 2))), (x, 31 + 23 * math.sqrt(max(0, 1 - ((x - 124) / 112) ** 2)))], (34, 39, 46, 150), .5)
    a.rrect(92, 52, 150, 62, 3, (34, 38, 45, 255))                           # gondola
    for k in range(7):
        a.rect(98 + k * 7, 55, 102.5 + k * 7, 58, (200, 210, 222, 255) if k not in (2, 5) else (40, 46, 54, 255))
    a.rrect(158, 24, 206, 42, 2, (16, 18, 22, 255))                          # LED screen
    a.rect(159.2, 25.2, 204.8, 40.8, (146, 154, 164, 255))
    draw_eye(a, 182, 33, 24, 11, .8)
    a.ellipse(238, 30, 1.2, 1.2, (214, 44, 38, 255))
    a.ellipse(18, 32, 1.1, 1.1, (230, 236, 240, 255))
    im = a.finish().filter(ImageFilter.GaussianBlur(.5))
    add_glow(im, 477, 60, 8, PAL["red"], .8)
    add_glow(im, 36, 64, 7, (230, 236, 240), .7)
    im = rim_light(im, (160, 170, 184), .5, 2, 1.0)
    im = haze_rgba(im, (122, 130, 140), .2, .5, .2)
    save_png(im, "airship.png")


# ---- gunship (the fly-by that rattles the screen; faces left) --------------------------------------------
def make_gunship():
    a = Art(100, 36, 4, ss=3)
    body, dark = (22, 25, 30, 255), (12, 14, 17, 255)
    a.poly([(2, 20), (14, 14), (46, 11), (80, 12), (96, 15), (98, 21), (80, 25), (40, 27), (14, 25)], body)       # fuselage
    a.poly([(8, 19), (16, 14.5), (28, 13.5), (28, 20)], (60, 72, 86, 255))                                        # canopy
    a.poly([(10, 18.4), (17, 15), (24, 14.4), (22, 18.4)], (150, 165, 184, 255))
    a.poly([(72, 12), (96, 6), (99, 10), (82, 14)], body)                                                         # tail fin
    a.poly([(44, 12), (62, 4), (70, 4), (60, 13)], dark)                                                          # upper wing
    a.rrect(46, 24, 70, 29, 2, dark)                                                                              # missile pod
    for k in range(4):
        a.ellipse(48 + k * 5.5, 26.5, 1.3, 1.3, (60, 66, 76, 255))
    for cx in (58, 84):                                                                                           # nacelles
        a.rrect(cx - 7, 3, cx + 7, 11, 3, (30, 34, 40, 255))
        a.ellipse(cx + 6.5, 7, 2.4, 3.5, (220, 232, 244, 255))
    a.ellipse(46, 27, 1, 1, (214, 44, 38, 255))
    im = a.finish()
    for cx in (64.5, 90.5):
        add_glow(im, cx * 4, 28, 26, (200, 220, 245), .9)
    add_glow(im, 46 * 4, 108, 10, PAL["red"], .9)
    sharp = np.array(im).astype(np.float32)
    mb = ndi.uniform_filter1d(sharp, 14, axis=1)
    out = np.clip(sharp * .72 + mb * .55, 0, 255)
    im = Image.fromarray(out.astype(np.uint8), "RGBA")
    im = rim_light(im, (120, 134, 152), .5, 2, .8)
    save_png(im, "gunship.png")


# ---- drones (4 frames of 14 x 10 units: 3 hovering/flying, 1 perched) ---------------------------------
def make_drone():
    cols, fw, fh, ppu = 4, 14, 10, 8
    sheet = Image.new("RGBA", (cols * fw * ppu, fh * ppu), (0, 0, 0, 0))
    for f in range(4):
        a = Art(fw, fh, ppu, ss=4)
        perched = f == 3
        by = 6.2 if perched else 4.6
        body, dk = (20, 23, 28, 255), (10, 12, 15, 255)
        a.rrect(3.2, by - 1.4, 10.6, by + 1.5, 1.4, body)
        a.ellipse(10.4, by + .1, 1.7, 1.5, (14, 16, 20, 255))
        a.rect(4, by - 1.4, 10, by - 1.0, (84, 94, 108, 255))
        a.line([(4.5, by - 1.2), (3.0, by - 2.5)], dk, .5); a.line([(9.5, by - 1.2), (11.2, by - 2.6)], dk, .5)
        if perched:
            a.line([(4.5, by + 1.4), (3.6, 8.9)], dk, .45); a.line([(9.2, by + 1.4), (10.2, 8.9)], dk, .45)
            a.line([(2.0, 8.9), (5.0, 8.9)], dk, .45); a.line([(8.6, 8.9), (11.6, 8.9)], dk, .45)
            a.line([(1.2, by - 2.4), (4.8, by - 2.9)], dk, .6); a.line([(9.4, by - 2.9), (12.6, by - 2.3)], dk, .6)
        else:
            tilt = (f - 1) * .35
            for cx in (3.0, 11.3):
                a.ellipse(cx, by - 2.7, 3.0, .45 + .18 * abs(tilt), (120, 132, 148, 90))
                a.line([(cx - 2.8, by - 2.7 + tilt * .6), (cx + 2.8, by - 2.7 - tilt * .6)], (30, 34, 40, 255), .35)
            a.line([(4.5, by + 1.4), (4.2, by + 2.6)], dk, .4); a.line([(9.2, by + 1.4), (9.6, by + 2.6)], dk, .4)
        eye = (214, 44, 38, 255) if f != 1 else (110, 24, 22, 255)
        if perched:
            eye = (120, 26, 24, 255)
        a.ellipse(11.4, by - .1, .55, .55, eye)
        im = rim_light(a.finish(), (130, 144, 162), .5, 1, .6)
        add_glow(im, 11.4 * ppu, (by - .1) * ppu, 9, PAL["red"], .55 if f != 3 else .25)
        sheet.alpha_composite(im, (f * fw * ppu, 0))
    save_png(sheet, "drone.png")


# ---- missile (24 x 64 units, nose down; the strike hazard) -----------------------------------------------
def make_missile():
    a = Art(24, 64, 8, ss=3)
    body, band = (54, 60, 69, 255), (176, 36, 32, 255)
    a.poly([(6, 14), (0, 20), (1, 8), (6, 5)], (34, 38, 45, 255))             # fins (side + back)
    a.poly([(18, 14), (24, 20), (23, 8), (18, 5)], (28, 32, 38, 255))
    a.rect(7, 3, 17, 46, body)
    a.poly([(7, 46), (7.6, 52), (12, 64), (16.4, 52), (17, 46)], body)       # ogive
    a.rect(7, 3, 9.2, 46, (92, 102, 116, 255))
    a.rect(14.8, 3, 17, 46, (26, 30, 36, 255))
    a.rect(7, 24, 17, 27, band)
    for y in (12, 36, 42):
        a.rect(7, y, 17, y + .5, (18, 21, 25, 255))
    a.poly([(6.5, 3), (7.5, 0), (16.5, 0), (17.5, 3)], (20, 23, 28, 255))      # nozzle
    a.rect(9.5, 29, 14.5, 30, (200, 208, 216, 255)); a.rect(9.5, 31.5, 13, 32.4, (200, 208, 216, 255))
    im = finish_prop(a.finish(), 1.5, .12, 40)
    add_glow(im, 12 * 8, 3, 46, (255, 150, 120), .8)
    add_glow(im, 12 * 8, 3, 16, (255, 235, 220), 1.0)
    save_png(im, "missile.png")


# ---- particles ----------------------------------------------------------------------------------------
def make_smoke():
    sheet = Image.new("RGBA", (3 * 128, 128), (0, 0, 0, 0))
    for f in range(3):
        r = rng(60 + f)
        n = fnoise(128, 128, 60 + f, beta=3.0)
        yy, xx = np.mgrid[0:128, 0:128].astype(np.float32)
        d = np.sqrt((xx - 64) ** 2 + (yy - 64) ** 2) / 60
        blob = np.clip(1 - d, 0, 1) ** 1.3 * (0.55 + 0.9 * n)
        col = np.zeros((128, 128, 3), np.float32) + np.array([160, 166, 174], np.float32) + (n[..., None] - .5) * 30
        sheet.alpha_composite(rgba_img(col, np.clip(blob * .8, 0, .85)), (f * 128, 0))
    save_png(sheet, "smoke.png")


def make_gibs():
    sheet = Image.new("RGBA", (6 * 48, 48), (0, 0, 0, 0))
    for f in range(6):
        a = Art(6, 6, 8, ss=4)
        r = rng(70 + f)
        n = int(r.integers(5, 8))
        pts = []
        for k in range(n):
            ang = 2 * math.pi * k / n + r.uniform(-.25, .25)
            rad = r.uniform(1.4, 2.7)
            pts.append((3 + math.cos(ang) * rad, 3 + math.sin(ang) * rad))
        shade = int(r.integers(46, 78))
        a.poly(pts, (shade, shade + 4, shade + 10, 255))
        a.poly([pts[0], pts[1], (3, 3)], (shade + 28, shade + 32, shade + 38, 255))
        sheet.alpha_composite(a.finish(), (f * 48, 0))
    save_png(sheet, "gibs.png")


# ---- foreground silhouettes (whip past at 3-5x speed; slightly out of focus) -------------------------------
def make_foreground():
    a = Art(26, 320, 4, ss=3)
    a.rect(2, 0, 24, 5, (6, 7, 9, 255)); a.rect(2, 315, 24, 320, (6, 7, 9, 255))      # flanges
    a.rect(2, 0, 7, 320, (8, 9, 11, 255)); a.rect(19, 0, 24, 320, (8, 9, 11, 255))
    a.rect(7, 0, 19, 320, (5, 6, 7, 255))
    a.rect(2, 0, 3, 320, (40, 46, 54, 255))
    for y in range(8, 320, 36):
        a.rect(1, y, 25, y + 3, (10, 11, 14, 255))
        a.ellipse(4.5, y + 1.5, .8, .8, (30, 34, 40, 255)); a.ellipse(21.5, y + 1.5, .8, .8, (30, 34, 40, 255))
    im = a.finish().filter(ImageFilter.GaussianBlur(1.6))
    save_png(im, "fg_column.png")
    b = Art(84, 320, 3, ss=3)
    c = (7, 8, 10, 255)
    b.line([(10, 320), (26, 0)], c, 3.2); b.line([(74, 320), (58, 0)], c, 3.2)
    for k in range(0, 40):
        y0, y1 = 320 - k * 8, 320 - (k + 1) * 8
        f0, f1 = k / 40.0, (k + 1) / 40.0
        l0, l1 = 10 + 16 * f0, 10 + 16 * f1
        r0, r1 = 74 - 16 * f0, 74 - 16 * f1
        b.line([(l0, y0), (r1, y1)] if k % 2 == 0 else [(r0, y0), (l1, y1)], c, 1.3)
        b.line([(l0, y0), (r0, y0)], c, 1.1)
    b.rect(18, 0, 66, 6, c)
    im = b.finish().filter(ImageFilter.GaussianBlur(1.4))
    save_png(im, "fg_truss.png")


# ---- interface icons (white on transparent, 96 x 96) and the favicon -----------------------------------------
def make_icons():
    def icon(name, fn):
        a = Art(96, 96, 1, ss=4)
        fn(a)
        save_png(a.finish(), name)
    W = (240, 244, 248, 255)
    icon("ui_pause.png", lambda a: (a.rrect(26, 20, 40, 76, 3, W), a.rrect(56, 20, 70, 76, 3, W)))

    def spk(a, on):
        a.poly([(14, 38), (30, 38), (50, 20), (50, 76), (30, 58), (14, 58)], W)
        if on:
            for r in (14, 26):
                pts = [(52 + math.cos(t) * r, 48 + math.sin(t) * r * 1.1) for t in np.linspace(-.9, .9, 14)]
                a.line(pts, W, 5)
        else:
            a.line([(60, 36), (84, 60)], W, 6); a.line([(84, 36), (60, 60)], W, 6)
    icon("ui_sound_on.png", lambda a: spk(a, True))
    icon("ui_sound_off.png", lambda a: spk(a, False))

    def fs(a):
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 48 + sx * 32, 48 + sy * 32
            a.line([(cx, cy - sy * 18), (cx, cy), (cx - sx * 18, cy)], W, 6)
    icon("ui_fullscreen.png", fs)
    a = Art(256, 256, 1, ss=3, bg=(10, 12, 15, 255))
    a.rect(0, 0, 256, 6, (30, 34, 40, 255))
    a.rect(46, 66, 210, 94, (226, 232, 238, 255))
    a.rect(114, 66, 142, 196, (226, 232, 238, 255))
    a.ellipse(200, 196, 7, 7, (196, 38, 34, 255))
    save_png(a.finish(), "icon.png")


def make_grain():
    n = rng(90).standard_normal((256, 256)).astype(np.float32)
    n = ndi.gaussian_filter(n, .6, mode="wrap")
    a = np.clip(.5 + n * .5, 0, 1)
    col = np.zeros((256, 256, 3), np.float32) + np.where(n[..., None] > 0, 255, 0)
    save_png(rgba_img(col, np.abs(n) * .28 * (a > 0)), "grain.png")


def make_actors(filters):
    steps = [("mech", make_mech), ("airship", make_airship), ("gunship", make_gunship), ("drone", make_drone),
             ("missile", make_missile), ("smoke", make_smoke), ("gibs", make_gibs), ("fg_", make_foreground),
             ("ui_icon", make_icons), ("grain", make_grain)]
    for name, fn in steps:
        if want(filters, name):
            fn()
# ============================================================================
# 8. AUDIO  - everything is synthesised (oscillators + filtered noise), 22.05 kHz mono 16-bit WAV.
#    Sound design: wet concrete, wind, rain, distant machinery, heavy aircraft, mechanical impacts,
#    slow electronic drones. File names are the ids used by the game (see assets.js).
# ============================================================================
SR = 22050


def t_axis(dur):
    return np.arange(int(SR * dur)) / SR


def noise(dur, seed=0):
    return rng(seed).uniform(-1, 1, int(SR * dur))


def lowpass(x, fc, order=2):
    return sosfilt(butter(order, min(fc, SR / 2 - 100) / (SR / 2), btype="low", output="sos"), x)


def highpass(x, fc, order=2):
    return sosfilt(butter(order, max(fc, 20) / (SR / 2), btype="high", output="sos"), x)


def bandpass(x, lo, hi, order=2):
    return sosfilt(butter(order, [max(lo, 20) / (SR / 2), min(hi, SR / 2 - 100) / (SR / 2)], btype="band", output="sos"), x)


def env_ad(n, attack, decay_tau):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / decay_tau)


def sine(f, dur, phase=0.0):
    return np.sin(2 * np.pi * f * t_axis(dur) + phase)


def sweep(f0, f1, dur, shape="exp"):
    t = t_axis(dur)
    f = f0 * (f1 / f0) ** (t / dur) if shape == "exp" else f0 + (f1 - f0) * t / dur
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def square(f, dur, duty=0.5):
    return np.where((t_axis(dur) * f) % 1.0 < duty, 1.0, -1.0)


def saw(f, dur):
    return 2 * ((t_axis(dur) * f) % 1.0) - 1


def fade_edges(x, ms=4):
    n = min(int(SR * ms / 1000), len(x) // 2)
    if n > 0:
        x = x.copy()
        x[:n] *= np.linspace(0, 1, n)
        x[-n:] *= np.linspace(1, 0, n)
    return x


def norm(x, peak=0.9):
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def mixdown(*parts, length=None):
    n = length or max(len(p) for p in parts)
    out = np.zeros(n)
    for p in parts:
        out[: len(p)] += p[:n]
    return out


def echo(x, secs, gain, taps=3):
    d = int(SR * secs)
    out = np.zeros(len(x) + d * taps)
    for k in range(taps + 1):
        out[k * d: k * d + len(x)] += x * (gain ** k)
    return out


def loopify(x, n, xf):
    """Seamless loop: x has n + xf samples; the tail is cross-faded onto the head."""
    body = x[:n].copy()
    f = np.linspace(0, 1, xf)
    body[:xf] = body[:xf] * np.sqrt(f) + x[n:n + xf] * np.sqrt(1 - f)
    return body


# ---- footsteps, movement ------------------------------------------------------------------------------
def sfx_foot(i, metal=False):
    seed = 100 + i + (50 if metal else 0)
    dur = 0.14 if not metal else 0.2
    n = int(SR * dur)
    base = 120 + 18 * i
    thump = sweep(base * 1.5, base * .55, dur) * env_ad(n, .001, .03)
    if not metal:                                       # wet concrete: dull thud + splashy hiss
        slap = bandpass(noise(dur, seed), 700, 3200) * env_ad(n, .001, .02) * .6
        splash = highpass(noise(dur, seed + 9), 2500) * env_ad(n, .004, .022) * .22
        out = thump * .95 + slap + splash
    else:                                               # steel gantry: dull clank
        ring = (sine(620 + 70 * i, dur) + .6 * sine(1130 + 60 * i, dur) + .35 * sine(1930, dur)) * env_ad(n, .0005, .06)
        out = thump * .6 + ring * .35 + highpass(noise(dur, seed), 1500) * env_ad(n, .0005, .012) * .35
    return fade_edges(norm(out, .7))


def sfx_jump(i):
    dur = .22 + .03 * i
    n = int(SR * dur)
    cloth = bandpass(noise(dur, 200 + i), 400 + 150 * i, 2600 + 500 * i) * (np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5)
    breath = lowpass(noise(dur, 230 + i), 900) * env_ad(n, .02, .07) * .6
    push = sweep(110 + 12 * i, 70, dur) * env_ad(n, .004, .05) * .5
    return fade_edges(norm(cloth * .6 + breath + push, .65))


def sfx_land():
    dur = .22
    n = int(SR * dur)
    thump = sweep(100, 48, dur) * env_ad(n, .001, .05)
    slap = bandpass(noise(dur, 960), 500, 2600) * env_ad(n, .001, .03) * .5
    return fade_edges(norm(thump + slap, .7))


def sfx_tumble():
    dur = .6
    n = int(SR * dur)
    out = np.zeros(n)
    for k, (t0, g) in enumerate(((0.0, 1.0), (.15, .7), (.3, .55), (.43, .35))):
        i0 = int(SR * t0)
        seg = sweep(190 - 22 * k, 60, .13) * env_ad(int(SR * .13), .001, .035)
        seg = seg + bandpass(noise(.13, 300 + k), 500, 2400) * env_ad(int(SR * .13), .001, .025) * .8
        out[i0: i0 + len(seg)] += seg * g
    return fade_edges(norm(out, .75))


def sfx_obstacle(i):
    dur = .32
    n = int(SR * dur)
    clatter = bandpass(noise(dur, 400 + i), 250 + 150 * i, 2600) * env_ad(n, .001, .07)
    thud = sweep(160, 55, dur) * env_ad(n, .001, .05)
    rattle = np.zeros(n)
    r = rng(410 + i)
    for _ in range(6):
        t0 = int(r.uniform(.04, .24) * SR)
        seg = bandpass(noise(.03, int(r.integers(0, 9999))), 700, 3300) * env_ad(int(SR * .03), .0005, .008)
        rattle[t0: t0 + len(seg)] += seg * r.uniform(.2, .5)
    return fade_edges(norm(clatter * .8 + thud * .7 + rattle, .75))


def sfx_wall():
    dur = .6
    n = int(SR * dur)
    boom = sweep(115, 32, dur) * env_ad(n, .002, .14)
    crack = lowpass(noise(dur, 500), 1400) * env_ad(n, .0005, .045)
    rumble = lowpass(noise(dur, 501), 260) * env_ad(n, .01, .2) * .7
    return fade_edges(norm(boom * .9 + crack * .7 + rumble, .88))


def sfx_glass(i):
    dur = .24
    n = int(SR * dur)
    out = np.zeros(n)
    r = rng(600 + i)
    for _ in range(7):
        f, t0 = r.uniform(2800, 6500), int(r.uniform(0, .12) * SR)
        seg = sine(f, .09) * env_ad(int(SR * .09), .0005, .02)
        out[t0: t0 + len(seg)] += seg * r.uniform(.25, .6)
    out += highpass(noise(dur, 610 + i), 3500) * env_ad(n, .0005, .02) * .4
    return fade_edges(norm(out, .6))


def sfx_window(i):
    dur = .9
    n = int(SR * dur)
    crash = highpass(noise(dur, 700 + i), 1100) * env_ad(n, .001, .13)
    body = lowpass(noise(dur, 710 + i), 800) * env_ad(n, .001, .08) * .9
    out = crash * .85 + body
    r = rng(720 + i)
    for _ in range(18):
        f, t0 = r.uniform(2500, 7000), int(r.uniform(.02, .65) * SR)
        seg = sine(f, .08) * env_ad(int(SR * .08), .0004, .018)
        out[t0: t0 + len(seg)] += seg * r.uniform(.05, .25)
    return fade_edges(norm(out, .8))


def sfx_crumble():
    dur = 3.4
    n = int(SR * dur)
    rumble = lowpass(noise(dur, 800), 200, 3)
    rumble *= (.4 + .6 * lowpass(noise(dur, 801), 6, 1) * 6)
    rumble *= np.minimum(1, np.linspace(0, 3, n)) * np.minimum(1, np.linspace(3.5, 0, n))
    grit = lowpass(noise(dur, 802), 2000) * .35
    r = rng(803)
    for _ in range(46):
        t0 = int(r.uniform(0, dur - .2) * SR)
        seg = bandpass(noise(.08, int(r.integers(0, 9999))), 280, 2400) * env_ad(int(SR * .08), .001, .02)
        grit[t0: t0 + len(seg)] += seg * r.uniform(.3, 1.0)
    grit *= np.minimum(1, np.linspace(0, 4, n)) * np.minimum(1, np.linspace(3.4, 0, n))
    return fade_edges(norm(rumble * 1.3 + grit * .7, .82), 20)


def sfx_missile_pre():
    dur = 1.3
    t = t_axis(dur)
    f = 2000 - 1650 * (t / dur) ** .7
    whistle = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / dur) ** 1.2
    air = bandpass(noise(dur, 910), 900, 4200) * (t / dur) ** 1.5 * .45
    rumble = lowpass(noise(dur, 911), 180) * (t / dur) ** 2 * .6
    return fade_edges(norm(whistle * .5 + air + rumble, .68), 10)


def sfx_missile_hit():
    dur = 1.3
    n = int(SR * dur)
    boom = sweep(85, 24, dur) * env_ad(n, .002, .32)
    crack = lowpass(noise(dur, 920), 2600) * env_ad(n, .0005, .07)
    debris = lowpass(noise(dur, 921), 1100) * env_ad(n, .04, .38) * .5
    return fade_edges(norm(boom + crack * .8 + debris, .9), 8)


def sfx_missile_explode():
    dur = 2.4
    n = int(SR * dur)
    boom = sweep(70, 20, dur) * env_ad(n, .002, .5)
    blast = lowpass(noise(dur, 930), 3200, 3) * env_ad(n, .0005, .24)
    tail = lowpass(noise(dur, 931), 450, 2) * env_ad(n, .1, .9) * .75
    return fade_edges(norm(boom * 1.15 + blast + tail, .95), 10)


def sfx_flyby():
    dur = 2.8
    n = int(SR * dur)
    t = t_axis(dur)
    sw = np.exp(-((t - 1.1) ** 2) / (2 * .45 ** 2))
    roar = bandpass(noise(dur, 940), 200, 2800, 2) * sw
    low = lowpass(noise(dur, 941), 420) * sw * 1.1
    whine = np.sin(2 * np.pi * np.cumsum(900 - 420 * (t / dur)) / SR) * sw * .12
    throb = (.75 + .25 * np.sin(2 * np.pi * 26 * t)) * sw
    return fade_edges(norm((roar * .8 + low) * throb + whine, .8), 25)


def sfx_drone(i):
    dur = .55
    n = int(SR * dur)
    t = t_axis(dur)
    f = 150 + 70 * i + 140 * (t / dur)
    buzz = (2 * ((np.cumsum(f) / SR) % 1.0) - 1) * (.6 + .4 * np.sin(2 * np.pi * 38 * t))
    air = bandpass(noise(dur, 950 + i), 600, 2800) * .5
    env = np.minimum(1, t / .06) * np.exp(-t / .35)
    return fade_edges(norm(lowpass(buzz, 1400) * env * .8 + air * env * .6, .4), 6)


def sfx_fall():
    dur = 1.0
    n = int(SR * dur)
    w = sweep(780, 120, dur) * env_ad(n, .02, .6)
    air = bandpass(noise(dur, 960), 300, 2000) * env_ad(n, .05, .65) * .35
    return fade_edges(norm(w * .4 + air, .55), 12)


def sfx_start():
    dur = .9
    n = int(SR * dur)
    swell = sweep(46, 92, dur, "lin") * env_ad(n, .12, .5)
    tone = (sine(220, dur) + .5 * sine(330, dur)) * env_ad(n, .18, .3) * .25
    click = highpass(noise(.04, 970), 2500) * env_ad(int(SR * .04), .0005, .01)
    out = swell * .9 + tone
    out[:len(click)] += click * .5
    return fade_edges(norm(out, .6), 8)


def sfx_ui(kind):
    if kind == "move":
        dur = .06
        return fade_edges(norm(sine(1500, dur) * env_ad(int(SR * dur), .0005, .012) + highpass(noise(dur, 981), 3000) * env_ad(int(SR * dur), .0003, .006) * .4, .28), 2)
    if kind == "select":
        dur = .3
        n = int(SR * dur)
        return fade_edges(norm((sine(210, dur) + .6 * sine(420, dur)) * env_ad(n, .003, .09) + sweep(90, 60, dur) * env_ad(n, .002, .08) * .6, .42), 4)
    dur = .22
    n = int(SR * dur)
    return fade_edges(norm(sweep(260, 120, dur) * env_ad(n, .002, .06), .4), 4)


# ---- ambience and music ---------------------------------------------------------------------------------
def make_ambience():
    """16 s loop: deep industrial drone, heavy wind with gusts, distant machinery, a faint beacon."""
    dur, xf = 16.0, 1.6
    tot = dur + xf
    n = int(SR * tot)
    t = t_axis(tot)
    drone = (np.sin(2 * np.pi * 36.7 * t) * .8 + np.sin(2 * np.pi * 36.7 * 1.5 * t + 1) * .25 + np.sin(2 * np.pi * 55.2 * t + 2) * .3)
    drone *= (.75 + .25 * np.sin(2 * np.pi * (1 / 8.0) * t))
    hum = lowpass(sum(np.sin(2 * np.pi * 100 * k * t + k) / k for k in (1, 2, 3, 5)), 420) * .12 * (.8 + .2 * np.sin(2 * np.pi * (1 / 5.3) * t))
    gust = lowpass(noise(tot, 1001), 2, 1) * 8 + lowpass(noise(tot, 1002), .5, 1) * 14
    gust = np.clip(gust * .5 + .45, .12, 1.2)
    wind_a = bandpass(noise(tot, 1003), 180, 900, 2) * gust
    wind_b = bandpass(noise(tot, 1004), 700, 2200, 2) * gust ** 2 * .45
    machinery = np.zeros(n)
    for k, step in enumerate(np.arange(.7, tot, 1.4)):
        i0 = int(SR * step)
        thud = sweep(78, 40, .5) * env_ad(int(SR * .5), .004, .13)
        thud += lowpass(noise(.5, 1010 + k), 300) * env_ad(int(SR * .5), .002, .07) * .5
        if i0 + len(thud) < n:
            machinery[i0: i0 + len(thud)] += thud * (.35 + .25 * ((k % 4) == 0))
    r = rng(1020)
    for _ in range(3):                                  # distant clangs
        i0 = int(r.uniform(1, tot - 2) * SR)
        ring = (sine(430 + r.uniform(0, 160), 1.0) + .5 * sine(830 + r.uniform(0, 200), 1.0)) * env_ad(SR, .001, .22)
        machinery[i0: i0 + len(ring)] += ring[: n - i0] * .035
    beacon = np.zeros(n)
    for step in (3.2, 9.6, 13.9):
        i0 = int(SR * step)
        ping = sine(1480, 1.4) * env_ad(int(SR * 1.4), .004, .35)
        ping = echo(ping, .31, .45, 3)
        beacon[i0: i0 + len(ping)] += ping[: n - i0] * .03
    x = drone * .55 + hum + wind_a * .5 + wind_b * .5 + machinery * .35 + beacon
    return norm(loopify(x, int(SR * dur), int(SR * xf)), .6)


def make_rain():
    dur, xf = 8.0, 1.0
    tot = dur + xf
    n = int(SR * tot)
    base = highpass(noise(tot, 1101), 1400) * .5
    base = lowpass(base, 7800)
    patter = np.zeros(n)
    r = rng(1102)
    for _ in range(int(tot * 220)):
        i0 = int(r.uniform(0, n - 400))
        seg = highpass(noise(.012, int(r.integers(0, 99999))), 2500) * env_ad(int(SR * .012), .0004, .003)
        patter[i0: i0 + len(seg)] += seg * r.uniform(.15, .8)
    swell = .8 + .2 * lowpass(noise(tot, 1103), 1.2, 1) * 6
    drum = lowpass(noise(tot, 1104), 500) * .15
    x = (base * .6 + patter * .5 + drum) * np.clip(swell, .5, 1.2)
    return norm(loopify(x, int(SR * dur), int(SR * xf)), .55)


def note_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def make_music():
    """24 s dark-ambient loop (80 BPM, D minor): sub pulse, slow pad, sparse echoing plucks, metal hits."""
    bpm = 80
    beat = 60.0 / bpm
    bars = 8
    total = bars * 4 * beat
    n = int(SR * total)
    out = np.zeros(n + int(SR * 3))

    def place(sig, at, gain=1.0):
        i0 = int(SR * at)
        out[i0: i0 + len(sig)] += sig[: len(out) - i0] * gain

    roots = [38, 38, 34, 34, 36, 36, 33, 33]          # D D Bb Bb C C A A  (two bars each pair)
    chords = [[50, 53, 57], [50, 53, 57], [46, 50, 53], [46, 50, 53], [48, 52, 55], [48, 52, 55], [45, 48, 52], [45, 48, 52]]
    for b in range(bars):
        d = 4 * beat
        nn = int(SR * d)
        pad = np.zeros(nn)
        for m in chords[b]:
            pad += saw(note_hz(m), d) * .22 + saw(note_hz(m) * 1.006, d) * .22 + saw(note_hz(m) * .994, d) * .18
        pad = lowpass(pad, 650 + 250 * (b % 2))
        pad *= np.minimum(1, np.linspace(0, 5, nn)) * np.minimum(1, np.linspace(5, 0, nn))
        place(pad, b * d, .20)
        for k in range(4):                              # sub pulse
            f = note_hz(roots[b])
            sub = sine(f, 1.1) * env_ad(int(SR * 1.1), .01, .3)
            place(sub, b * d + k * beat, .55 if k == 0 else .32)
        for k in (0, 2):                                # soft kick
            kick = sweep(110, 38, .3) * env_ad(int(SR * .3), .002, .09)
            place(kick, b * d + k * beat, .5)
        if b % 2 == 1:                                  # metal hit
            hit = bandpass(noise(.5, 1200 + b), 700, 3400) * env_ad(int(SR * .5), .001, .09)
            hit += (sine(510, .5) + .6 * sine(1190, .5)) * env_ad(int(SR * .5), .001, .14) * .3
            place(hit, b * d + 3.5 * beat, .14)
    r = rng(1300)
    scale = [62, 65, 67, 69, 72, 74, 77]
    for b in range(bars):
        for s in range(8):
            if r.random() < .38:
                m = scale[int(r.integers(0, len(scale)))]
                pl = sine(note_hz(m), .8) * env_ad(int(SR * .8), .004, .12) + sine(note_hz(m) * 2, .8) * env_ad(int(SR * .8), .004, .06) * .25
                pl = echo(pl, beat * .75, .5, 3)
                place(pl, b * 4 * beat + s * beat * .5, .075)
    wind = bandpass(noise(total + 3, 1310), 300, 1800) * (.5 + .5 * np.sin(2 * np.pi * t_axis(total + 3) / 12.0))
    out[: len(wind)] += wind[: len(out)] * .06
    return norm(np.tanh(loopify(out, n, int(SR * 3)) * 1.2), .8)


def to_wav_bytes(x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return bio.getvalue()


def sound_table():
    s = {}
    for i in range(1, 5):
        s["foot%d" % i] = lambda i=i: sfx_foot(i)
        s["footc%d" % i] = lambda i=i: sfx_foot(i, True)
    for i in range(1, 4):
        s["jump%d" % i] = lambda i=i: sfx_jump(i)
        s["obstacle%d" % i] = lambda i=i: sfx_obstacle(i)
        s["drone%d" % i] = lambda i=i: sfx_drone(i)
    for i in range(1, 3):
        s["glass%d" % i] = lambda i=i: sfx_glass(i)
        s["window%d" % i] = lambda i=i: sfx_window(i)
    s.update(land=sfx_land, tumble=sfx_tumble, wall=sfx_wall, crumble=sfx_crumble, bomb_pre=sfx_missile_pre,
             bomb_hit=sfx_missile_hit, bomb_explode=sfx_missile_explode, flyby=sfx_flyby, fall=sfx_fall, start=sfx_start,
             ui_move=lambda: sfx_ui("move"), ui_select=lambda: sfx_ui("select"), ui_back=lambda: sfx_ui("back"),
             ambience=make_ambience, rain=make_rain, music=make_music)
    return s


def make_audio(filters):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, fn in sound_table().items():
        if not want(filters, name):
            continue
        sig = fn()
        assert np.isfinite(sig).all(), name
        raw = to_wav_bytes(sig)
        (AUDIO_DIR / (name + ".wav")).write_bytes(raw)
        total += len(raw)
        print("  %-14s %5.2fs %6.0f KB" % (name, len(sig) / SR, len(raw) / 1024))
    print("  wav total: %.0f KB" % (total / 1024))
    bundle_audio()


def bundle_audio():
    """audio-data.js = every .wav in assets/audio/ as base64, so the game can play when opened from disk."""
    lines = ["/* Generated by tools/generate-assets.py (python3 tools/generate-assets.py bundle) - do not edit by hand.",
             "   Base64 copies of the .wav files in this folder. Browsers refuse fetch() on file:// pages, so the game",
             "   decodes these with Web Audio when index.html is opened straight from disk. When served over http(s)",
             "   it loads the .wav files directly instead, so you can swap a .wav without re-bundling. */",
             "window.AUDIO_DATA = {"]
    for p in sorted(AUDIO_DIR.glob("*.wav")):
        lines.append('  "%s": "%s",' % (p.stem, base64.b64encode(p.read_bytes()).decode("ascii")))
    lines.append("};")
    (AUDIO_DIR / "audio-data.js").write_text("\n".join(lines) + "\n")
    print("  audio-data.js        %6.0f KB" % ((AUDIO_DIR / "audio-data.js").stat().st_size / 1024))


# ============================================================================
# 9. MAIN
# ============================================================================
def make_images(filters):
    print("images ->", IMG_DIR)
    if want(filters, "sky"):
        make_sky()
    if want(filters, "fog_bank"):
        make_fog_bank()
    make_skylines(filters)
    make_world(filters)
    if want(filters, "player"):
        make_player()
    make_actors(filters)
    if LIGHTS:
        print("\nLight positions (units, relative to each prop's top-left) - paste into assets.js `lights` when a prop changes:")
        for k in sorted(LIGHTS):
            print("  %-20s %s" % (k, LIGHTS[k]))


def main(argv):
    modes = ("images", "audio", "bundle", "all")
    mode = argv[0] if argv and argv[0] in modes else "all"
    filters = argv[1:] if argv and argv[0] in modes else argv
    if mode in ("images", "all"):
        make_images(filters)
    if mode in ("audio", "all"):
        print("audio ->", AUDIO_DIR)
        make_audio(filters)
    if mode == "bundle":
        bundle_audio()


if __name__ == "__main__":
    main(sys.argv[1:])

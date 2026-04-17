"""
overlay_generator.py — Génère les images d'overlay à incruster sur la vidéo.

Produit :
    - intro.png          : logo dropzone + "NOM CLIENT" + date saut
    - outro.png          : logo + site web + CTA
    - hud_stats.png      : panneau HUD altitude/vitesse/durée chute (fin de montage)
    - (à terme) frames animées pour HUD live pendant la chute libre

Utilise Pillow — pas de dépendance GPU.

Usage :
    from core.overlay_generator import build_intro, build_outro, build_stats_panel
    path = build_intro("Marie Dubois", "2026-04-17", Path("assets/branding/logo.png"))
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Configuration par défaut
# ══════════════════════════════════════════════════════════════
@dataclass
class OverlayStyle:
    width: int = 1920
    height: int = 1080
    color_primary: tuple = (255, 107, 0, 255)       # orange SkyDive
    color_secondary: tuple = (26, 26, 46, 255)      # bleu nuit
    color_text: tuple = (255, 255, 255, 255)
    color_shadow: tuple = (0, 0, 0, 180)
    bg_dim_alpha: int = 140                         # 0-255 : intensité de l'assombrissement


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════
_FONT_WARNED = False


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Charge une police de fallback cross-platform."""
    global _FONT_WARNED
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError as e:
                log.debug("Font %s illisible: %s", p, e)
                continue
    if not _FONT_WARNED:
        log.warning("Aucune police TrueType trouvée — fallback bitmap moche")
        _FONT_WARNED = True
    return ImageFont.load_default()


def _draw_text_shadow(draw: ImageDraw.ImageDraw, pos: tuple[int, int],
                      text: str, font: ImageFont.FreeTypeFont,
                      fill=(255, 255, 255, 255),
                      shadow=(0, 0, 0, 180), offset: int = 3):
    x, y = pos
    for dx, dy in [(offset, offset), (offset, -offset),
                   (-offset, offset), (-offset, -offset)]:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text(pos, text, font=font, fill=fill)


def _paste_logo(img: Image.Image, logo_path: Optional[Path], pos: tuple[int, int],
                max_size: int = 200) -> None:
    if not logo_path or not logo_path.exists():
        return
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        log.warning("Logo %s illisible (%s) — overlay sans branding", logo_path, e)
        return
    logo.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    img.paste(logo, pos, logo)


# ══════════════════════════════════════════════════════════════
#  Builders
# ══════════════════════════════════════════════════════════════
def build_intro(nom_passager: str,
                 date_saut: str,
                 logo_path: Optional[Path] = None,
                 dropzone_nom: str = "",
                 style: Optional[OverlayStyle] = None,
                 output_dir: Optional[Path] = None) -> Path:
    """Crée une image d'intro avec logo + nom passager + date."""
    style = style or OverlayStyle()
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))

    # Overlay semi-transparent gradient bottom
    gradient = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gradient)
    for y in range(style.height):
        alpha = int(style.bg_dim_alpha * (y / style.height) ** 2)
        gdraw.line([(0, y), (style.width, y)], fill=(*style.color_secondary[:3], alpha))
    img = Image.alpha_composite(img, gradient)

    draw = ImageDraw.Draw(img)

    # Logo en haut à gauche
    if logo_path and logo_path.exists():
        _paste_logo(img, logo_path, (60, 50), max_size=180)

    # Nom passager (grand, centré bas)
    f_title = _load_font(110, bold=True)
    f_sub = _load_font(42, bold=False)

    nom_up = nom_passager.upper()
    bbox = draw.textbbox((0, 0), nom_up, font=f_title)
    nom_w = bbox[2] - bbox[0]
    y_nom = style.height - 280
    _draw_text_shadow(draw, ((style.width - nom_w) // 2, y_nom),
                       nom_up, f_title, fill=style.color_text)

    # Ligne primaire (accent)
    line_y = y_nom + 125
    line_w = 120
    draw.rectangle([
        ((style.width - line_w) // 2, line_y),
        ((style.width + line_w) // 2, line_y + 6),
    ], fill=style.color_primary)

    # Date + dropzone
    sub_text = f"Saut tandem · {date_saut}"
    if dropzone_nom:
        sub_text += f" · {dropzone_nom}"
    bbox = draw.textbbox((0, 0), sub_text, font=f_sub)
    sub_w = bbox[2] - bbox[0]
    _draw_text_shadow(draw, ((style.width - sub_w) // 2, line_y + 30),
                       sub_text, f_sub, fill=(220, 220, 230, 255))

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="overlay_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "intro.png"
    img.save(out, "PNG")
    return out


def build_outro(dropzone_nom: str = "",
                 site_web: str = "",
                 logo_path: Optional[Path] = None,
                 style: Optional[OverlayStyle] = None,
                 output_dir: Optional[Path] = None) -> Path:
    """Image d'outro : logo + CTA."""
    style = style or OverlayStyle()
    img = Image.new("RGBA", (style.width, style.height),
                     (*style.color_secondary[:3], 255))
    draw = ImageDraw.Draw(img)

    # Logo centré
    if logo_path and logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((400, 400), Image.Resampling.LANCZOS)
        lw, lh = logo.size
        img.paste(logo, ((style.width - lw) // 2, style.height // 2 - lh - 20), logo)

    f_big = _load_font(68, bold=True)
    f_med = _load_font(36)

    title = dropzone_nom.upper() if dropzone_nom else "SKYDIVE PRO"
    bbox = draw.textbbox((0, 0), title, font=f_big)
    tw = bbox[2] - bbox[0]
    _draw_text_shadow(draw, ((style.width - tw) // 2, style.height // 2 + 40),
                       title, f_big, fill=style.color_text)

    if site_web:
        bbox = draw.textbbox((0, 0), site_web, font=f_med)
        sw = bbox[2] - bbox[0]
        draw.text(((style.width - sw) // 2, style.height // 2 + 140),
                   site_web, font=f_med, fill=style.color_primary)

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="overlay_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "outro.png"
    img.save(out, "PNG")
    return out


def build_stats_panel(altitude_max_m: Optional[float],
                       vitesse_max_kmh: Optional[float],
                       duree_chute_s: Optional[float],
                       style: Optional[OverlayStyle] = None,
                       output_dir: Optional[Path] = None) -> Path:
    """Panneau stats à afficher en fin de montage."""
    style = style or OverlayStyle()
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))

    # Dim background
    dim = Image.new("RGBA", (style.width, style.height),
                     (*style.color_secondary[:3], 200))
    img = Image.alpha_composite(img, dim)

    draw = ImageDraw.Draw(img)

    f_label = _load_font(32)
    f_value = _load_font(140, bold=True)
    f_unit = _load_font(42)
    f_title = _load_font(50, bold=True)

    # Titre
    title = "TON SAUT EN CHIFFRES"
    bbox = draw.textbbox((0, 0), title, font=f_title)
    tw = bbox[2] - bbox[0]
    draw.text(((style.width - tw) // 2, 120), title, font=f_title,
               fill=style.color_primary)

    # 3 blocs de stats
    stats = []
    if altitude_max_m is not None:
        stats.append(("ALTITUDE", f"{int(altitude_max_m):,}".replace(",", " "), "mètres"))
    if vitesse_max_kmh is not None:
        stats.append(("VITESSE MAX", f"{int(vitesse_max_kmh)}", "km/h"))
    if duree_chute_s is not None:
        stats.append(("CHUTE LIBRE", f"{int(duree_chute_s)}", "secondes"))

    if not stats:
        draw.text((style.width // 2 - 200, style.height // 2),
                   "Télémétrie indisponible", font=f_label, fill=style.color_text)
    else:
        col_width = style.width // len(stats)
        for i, (label, value, unit) in enumerate(stats):
            cx = col_width * i + col_width // 2
            # label
            bbox = draw.textbbox((0, 0), label, font=f_label)
            lw = bbox[2] - bbox[0]
            draw.text((cx - lw // 2, 320), label, font=f_label,
                       fill=(200, 200, 210, 255))
            # value
            bbox = draw.textbbox((0, 0), value, font=f_value)
            vw = bbox[2] - bbox[0]
            _draw_text_shadow(draw, (cx - vw // 2, 380), value, f_value,
                               fill=style.color_text)
            # unit
            bbox = draw.textbbox((0, 0), unit, font=f_unit)
            uw = bbox[2] - bbox[0]
            draw.text((cx - uw // 2, 560), unit, font=f_unit,
                       fill=style.color_primary)

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="overlay_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "stats.png"
    img.save(out, "PNG")
    return out


if __name__ == "__main__":
    import sys
    intro = build_intro("Marie Dubois", "17/04/2026",
                          logo_path=None, dropzone_nom="Skydive Adventure")
    outro = build_outro("Skydive Adventure", "skydive-adventure.fr")
    stats = build_stats_panel(altitude_max_m=4050, vitesse_max_kmh=212,
                                duree_chute_s=58)
    print(f"Intro : {intro}")
    print(f"Outro : {outro}")
    print(f"Stats : {stats}")

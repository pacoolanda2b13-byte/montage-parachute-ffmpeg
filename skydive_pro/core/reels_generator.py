"""
reels_generator.py — Génération de Reels Instagram verticaux (9:16) pour SkyDive Pro.

Produit 2-3 Reels à partir des mêmes segments source que le montage long :
  - "adrenaline"  30-45s  : sortie avion + chute libre + ouverture parachute
  - "emotion"     15-30s  : atterrissage + réaction
  - "paysage"     15-30s  : vues avion + sous voile (pur visuel, pas de texte)

Usage :
    from core.reels_generator import generate_reels
    reels = generate_reels(
        segments=timeline,
        output_dir=Path("output/reels"),
        nom_passager="Marie Dupont",
        date_saut="14 juin 2026",
        lieu="Skydive Lyon",
        vitesse_max_kmh=210.0,
        music_path=Path("assets/music/default.mp3"),
    )
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from core.ffmpeg_engine import (
    _concat_clips,
    _find_ffmpeg,
    _mix_music,
    _pick_encoder,
)
from core.logger import get_logger

log = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Constantes templates
# ══════════════════════════════════════════════════════════════

# Scènes requises et durées cibles (min, max) par template
REEL_TEMPLATES: dict[str, dict] = {
    "adrenaline": {
        "required_scenes": ["sortie_avion", "chute_libre", "sous_voile"],
        "scene_targets_s": {
            "sortie_avion": 5.0,
            "chute_libre": 25.0,
            "sous_voile": 5.0,
        },
        "duration_min_s": 30.0,
        "duration_max_s": 45.0,
        "music_style": "energy",
    },
    "emotion": {
        "required_scenes": ["atterrissage", "reaction_emotion"],
        "scene_targets_s": {
            "atterrissage": 5.0,
            "reaction_emotion": 18.0,
        },
        "duration_min_s": 15.0,
        "duration_max_s": 30.0,
        "music_style": "emotional",
    },
    "paysage": {
        "required_scenes": ["paysage_avion", "sous_voile"],
        "scene_targets_s": {
            "paysage_avion": 10.0,
            "sous_voile": 15.0,
        },
        "duration_min_s": 15.0,
        "duration_max_s": 30.0,
        "music_style": "ambient",
    },
}

# Filtre crop + scale pour passer de 16:9 source à 9:16 vertical
VERTICAL_CROP_FILTER = (
    "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
    "scale=1080:1920"
)


# ══════════════════════════════════════════════════════════════
#  Helpers internes
# ══════════════════════════════════════════════════════════════

def _cut_clip_vertical(
    video: str | Path,
    start: float,
    end: float,
    out_path: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    encoder: str = "libx264",
) -> Path:
    """Coupe un sous-clip, recadre en 9:16 vertical et normalise la résolution."""
    ffmpeg, _ = _find_ffmpeg()
    duration = max(0.1, end - start)
    vf = f"{VERTICAL_CROP_FILTER},fps={fps}"
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-ss", str(start), "-i", str(video),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", encoder, "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _build_drawtext_filter(text: str) -> str:
    """Construit un filtre drawtext pour texte blanc gras avec ombre portée.

    Le texte est centré horizontalement, positionné à 88% de la hauteur
    (bas d'écran, au-dessus de la zone sécurisée Instagram).
    """
    # Échappe les apostrophes et les deux-points pour le filtre drawtext
    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace("'", "\u2019")   # apostrophe courbe → pas de conflit ffmpeg
        .replace(":", r"\:")
    )
    return (
        f"drawtext="
        f"text='{safe_text}':"
        f"fontsize=52:"
        f"fontcolor=white:"
        f"fontfile='':"          # utilise la police par défaut ffmpeg
        f"x=(w-text_w)/2:"
        f"y=h*0.88:"
        f"shadowcolor=black:"
        f"shadowx=3:"
        f"shadowy=3:"
        f"box=1:"
        f"boxcolor=black@0.35:"
        f"boxborderw=12"
    )


def _add_text_overlay(
    video_path: Path,
    out_path: Path,
    text: str,
    encoder: str = "libx264",
) -> Path:
    """Applique un overlay texte sur une vidéo déjà encodée (re-encode vidéo)."""
    ffmpeg, _ = _find_ffmpeg()
    drawtext = _build_drawtext_filter(text)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-i", str(video_path),
        "-vf", drawtext,
        "-c:v", encoder, "-preset", "ultrafast", "-crf", "18",
        "-c:a", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _select_segments_for_scene(
    segments: list[dict],
    scene: str,
    target_duration_s: float,
) -> list[dict]:
    """Sélectionne les segments d'une scène pour atteindre la durée cible.

    Stratégie :
      - Filtre les segments de la scène demandée.
      - Prend le (ou les) meilleur(s) segment(s) pour couvrir target_duration_s.
      - Pour "chute_libre" : prend la portion centrale du premier segment long.
      - Pour "atterrissage" : prend la fin du segment.
      - Pour les autres : prend le début.

    Retourne une liste de dicts avec les clés :
        source_file, local_start_s, local_end_s, scene
    """
    matching = [s for s in segments if s.get("scene") == scene]
    if not matching:
        return []

    # Trier par position temporelle
    matching_sorted = sorted(matching, key=lambda s: s.get("local_start_s", s.get("start_s", 0)))

    # Calculer la durée disponible par segment
    def seg_duration(s: dict) -> float:
        start = s.get("local_start_s", s.get("start_s", 0.0))
        end = s.get("local_end_s", s.get("end_s", 0.0))
        return max(0.0, end - start)

    total_available = sum(seg_duration(s) for s in matching_sorted)
    if total_available <= 0:
        return []

    result: list[dict] = []
    remaining = target_duration_s

    for seg in matching_sorted:
        if remaining <= 0:
            break
        src = seg.get("source_file", "")
        start = seg.get("local_start_s", seg.get("start_s", 0.0))
        end = seg.get("local_end_s", seg.get("end_s", 0.0))
        dur = max(0.0, end - start)
        if dur < 0.5:
            continue

        take = min(remaining, dur)

        # Positionnement selon la scène
        if scene == "atterrissage":
            # Prendre la fin du segment (touch down)
            clip_start = end - take
            clip_end = end
        elif scene in ("chute_libre", "sous_voile"):
            # Prendre le milieu
            mid = (start + end) / 2
            clip_start = mid - take / 2
            clip_end = mid + take / 2
            # Clamper dans le segment
            if clip_start < start:
                clip_start = start
                clip_end = start + take
            if clip_end > end:
                clip_end = end
                clip_start = end - take
        else:
            # Prendre le début
            clip_start = start
            clip_end = start + take

        result.append({
            "source_file": src,
            "local_start_s": clip_start,
            "local_end_s": clip_end,
            "scene": scene,
        })
        remaining -= take

    return result


# ══════════════════════════════════════════════════════════════
#  Génération d'un Reel unique
# ══════════════════════════════════════════════════════════════

def _generate_single_reel(
    reel_type: str,
    segments: list[dict],
    tmpdir: Path,
    output_path: Path,
    text_overlay: Optional[str],
    music_path: Optional[Path],
    width: int,
    height: int,
    fps: int,
    encoder: str,
) -> dict:
    """Génère un seul Reel. Retourne un dict résultat."""
    template = REEL_TEMPLATES[reel_type]
    required_scenes = template["required_scenes"]
    scene_targets = template["scene_targets_s"]

    # ── 1. Vérifier que toutes les scènes requises sont présentes ──
    available_scenes = {s.get("scene") for s in segments}
    missing = [sc for sc in required_scenes if sc not in available_scenes]
    if missing:
        log.warning(
            "Reel '%s' ignoré : scènes manquantes %s (disponibles : %s)",
            reel_type, missing, sorted(available_scenes),
        )
        return {"type": reel_type, "path": None, "duree_s": 0.0, "ok": False}

    # ── 2. Couper les clips verticaux ──
    clips_files: list[Path] = []
    total_dur = 0.0

    for scene in required_scenes:
        target_s = scene_targets.get(scene, 5.0)
        scene_segs = _select_segments_for_scene(segments, scene, target_s)

        if not scene_segs:
            log.warning(
                "Reel '%s' : aucun segment utilisable pour la scène '%s' — abandon.",
                reel_type, scene,
            )
            return {"type": reel_type, "path": None, "duree_s": 0.0, "ok": False}

        for i, seg in enumerate(scene_segs):
            src = seg["source_file"]
            s_start = seg["local_start_s"]
            s_end = seg["local_end_s"]
            dur = s_end - s_start

            if dur < 0.5:
                log.warning(
                    "Reel '%s' : sous-clip %s[%d] trop court (%.2fs) — ignoré.",
                    reel_type, scene, i, dur,
                )
                continue

            clip_out = tmpdir / f"{reel_type}_{scene}_{i:02d}.mp4"
            try:
                _cut_clip_vertical(
                    src, s_start, s_end,
                    clip_out, width, height, fps, encoder,
                )
                clips_files.append(clip_out)
                total_dur += dur
            except subprocess.CalledProcessError as e:
                err = (e.stderr or b"").decode("utf-8", errors="replace")[:400]
                log.error(
                    "Reel '%s' : échec découpe %s [%.1f-%.1f] : %s",
                    reel_type, scene, s_start, s_end, err,
                )
                return {"type": reel_type, "path": None, "duree_s": 0.0, "ok": False}

    if not clips_files:
        log.warning("Reel '%s' : aucun clip produit — abandon.", reel_type)
        return {"type": reel_type, "path": None, "duree_s": 0.0, "ok": False}

    # ── 3. Concaténer ──
    concat_out = tmpdir / f"{reel_type}_concat.mp4"
    try:
        _concat_clips(clips_files, concat_out, encoder)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[:400]
        log.error("Reel '%s' : échec concat : %s", reel_type, err)
        return {"type": reel_type, "path": None, "duree_s": 0.0, "ok": False}

    current = concat_out

    # ── 4. Overlay texte (si applicable) ──
    if text_overlay:
        text_out = tmpdir / f"{reel_type}_text.mp4"
        try:
            _add_text_overlay(current, text_out, text_overlay, encoder)
            current = text_out
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace")[:400]
            log.warning(
                "Reel '%s' : overlay texte échoué (%s) — on continue sans texte.",
                reel_type, err,
            )
            # Non fatal : on continue avec la vidéo sans texte

    # ── 5. Mixer la musique ──
    if music_path and music_path.exists():
        mixed_out = tmpdir / f"{reel_type}_mixed.mp4"
        try:
            _mix_music(current, music_path, mixed_out,
                       music_volume=0.9, encoder=encoder)
            current = mixed_out
        except Exception as e:
            log.warning(
                "Reel '%s' : mix musique échoué (%s) — Reel sans musique.",
                reel_type, e,
            )

    # ── 6. Re-mux faststart final ──
    ffmpeg, _ = _find_ffmpeg()
    try:
        subprocess.run([
            ffmpeg, "-y", "-v", "error",
            "-i", str(current),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        log.warning(
            "Reel '%s' : re-mux faststart échoué (%s) — copie directe.",
            reel_type,
            (e.stderr or b"").decode("utf-8", errors="replace")[:200],
        )
        shutil.copy(str(current), str(output_path))

    if not output_path.exists() or output_path.stat().st_size == 0:
        log.error("Reel '%s' : fichier final absent ou vide.", reel_type)
        return {"type": reel_type, "path": output_path, "duree_s": 0.0, "ok": False}

    log.info(
        "Reel '%s' généré : %s (%.1fs)",
        reel_type, output_path.name, total_dur,
    )
    return {
        "type": reel_type,
        "path": output_path,
        "duree_s": round(total_dur, 2),
        "ok": True,
    }


# ══════════════════════════════════════════════════════════════
#  Fonction principale publique
# ══════════════════════════════════════════════════════════════

def generate_reels(
    segments: list[dict],
    output_dir: Path,
    nom_passager: str = "",
    date_saut: str = "",
    lieu: str = "",
    vitesse_max_kmh: Optional[float] = None,
    music_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    job_id: str = "reel",
) -> list[dict]:
    """Génère 2-3 Reels Instagram verticaux (9:16) depuis les segments du montage.

    Args:
        segments        : timeline avec source_file, local_start_s, local_end_s, scene.
                          Accepte aussi les champs start_s/end_s si local_* absents.
        output_dir      : dossier de sortie (créé si absent).
        nom_passager    : prénom + nom du passager (overlay texte).
        date_saut       : date du saut, ex. "14 juin 2026" (overlay texte reel emotion).
        lieu            : dropzone / lieu, ex. "Skydive Lyon" (overlay texte reel emotion).
        vitesse_max_kmh : vitesse max en km/h (overlay texte reel adrenaline).
        music_path      : chemin vers le fichier audio à mixer (optionnel).
        width           : largeur du Reel (défaut 1080 — vertical Instagram).
        height          : hauteur du Reel (défaut 1920 — vertical Instagram).
        fps             : images par seconde (défaut 30).
        job_id          : préfixe pour les noms de fichiers de sortie.

    Returns:
        Liste de dicts : [{"type": str, "path": Path|None, "duree_s": float, "ok": bool}]
        Les Reels ignorés (matière insuffisante) ont ok=False et path=None.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not segments:
        log.warning("generate_reels : liste de segments vide — aucun Reel produit.")
        return []

    encoder = _pick_encoder()
    log.info(
        "generate_reels : %d segments, encoder=%s, job_id=%s",
        len(segments), encoder, job_id,
    )

    # Construire les overlays texte par type
    def _vitesse_str() -> str:
        if vitesse_max_kmh is not None:
            return f"{vitesse_max_kmh:.0f}"
        return "?"

    text_overlays: dict[str, Optional[str]] = {
        "adrenaline": (
            f"{nom_passager} · CHUTE LIBRE · {_vitesse_str()} km/h"
            if nom_passager else f"CHUTE LIBRE · {_vitesse_str()} km/h"
        ),
        "emotion": " · ".join(filter(None, [nom_passager, date_saut, lieu])) or None,
        "paysage": None,  # pas de texte — pur visuel
    }

    results: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix=f"reels_{job_id}_"))

    try:
        for reel_type in ("adrenaline", "emotion", "paysage"):
            out_file = output_dir / f"{job_id}_{reel_type}.mp4"
            result = _generate_single_reel(
                reel_type=reel_type,
                segments=segments,
                tmpdir=tmpdir,
                output_path=out_file,
                text_overlay=text_overlays[reel_type],
                music_path=music_path,
                width=width,
                height=height,
                fps=fps,
                encoder=encoder,
            )
            results.append(result)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    ok_count = sum(1 for r in results if r["ok"])
    log.info(
        "generate_reels terminé : %d/%d Reels produits.",
        ok_count, len(results),
    )
    return results

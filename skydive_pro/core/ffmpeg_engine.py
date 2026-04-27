"""
ffmpeg_engine.py — Moteur FFmpeg de génération du montage final.

Prend une liste de segments vidéo (avec start/end/label) + des overlays +
une musique et produit le MP4 final.

Usage :
    from core.ffmpeg_engine import build_montage
    build_montage(
        video_source="sources/saut.mp4",
        segments=[{"start_s": 10, "end_s": 18, "scene": "briefing"}, ...],
        overlays={"intro": Path("..."), "outro": Path("...")},
        music="assets/music/default.mp3",
        output="output/saut_final.mp4",
        nom_passager="Marie Dubois",
    )
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════
def _find_ffmpeg() -> tuple[str, str]:
    return (shutil.which("ffmpeg") or "ffmpeg",
            shutil.which("ffprobe") or "ffprobe")


def _pick_encoder(preferred: Optional[str] = None) -> str:
    """Choisit le meilleur encodeur : AMF > NVENC > VideoToolbox > QSV > x264.

    Lève RuntimeError si ffmpeg absent (plus utile qu'un fallback silencieux).
    """
    preferred = preferred or os.environ.get("ENCODEUR_VIDEO")
    ffmpeg, _ = _find_ffmpeg()
    try:
        res = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=10)
        available = res.stdout
    except FileNotFoundError as e:
        log.error("ffmpeg introuvable dans PATH")
        raise RuntimeError("ffmpeg introuvable — installe FFmpeg") from e
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg -encoders timeout — fallback libx264")
        available = ""
    except subprocess.CalledProcessError as e:
        log.warning("ffmpeg -encoders échoué: %s", e)
        available = ""

    if preferred and preferred in available:
        log.info("Encodeur sélectionné (preferred) : %s", preferred)
        return preferred
    for enc in ("h264_amf", "h264_nvenc", "h264_videotoolbox", "h264_qsv"):
        if enc in available:
            log.info("Encodeur sélectionné : %s", enc)
            return enc
    log.info("Encodeur sélectionné : libx264 (CPU fallback)")
    return "libx264"


def _cut_clip(video: str | Path, start: float, end: float,
               out_path: Path, width: int = 1920, height: int = 1080,
               fps: int = 30) -> Path:
    """Coupe un sous-clip normalisé (résolution/fps unifiés)."""
    ffmpeg, _ = _find_ffmpeg()
    duration = max(0.1, end - start)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-ss", str(start), "-i", str(video),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _still_to_clip(still_img: Path, duration: float, out_path: Path,
                   width: int = 1920, height: int = 1080,
                   fps: int = 30) -> Path:
    """Transforme une image fixe en clip vidéo silencieux."""
    ffmpeg, _ = _find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-loop", "1", "-t", str(duration), "-i", str(still_img),
        "-f", "lavfi", "-t", str(duration), "-i",
           f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _concat_clips(clips: list[Path], out_path: Path, encoder: str) -> Path:
    """Concatène des clips déjà normalisés via le demuxer concat.

    Échappe les apostrophes dans les chemins pour éviter de casser le format.
    """
    ffmpeg, _ = _find_ffmpeg()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                        encoding="utf-8") as f:
        list_path = Path(f.name)
        for c in clips:
            # Échappe les apostrophes selon le format concat FFmpeg
            path_str = c.as_posix().replace("'", "'\\''")
            f.write(f"file '{path_str}'\n")

    try:
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c:v", encoder,
        ]
        if encoder == "libx264":
            cmd += ["-preset", "fast", "-crf", "20"]
        else:
            cmd += ["-b:v", "8M"]
        cmd += ["-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        list_path.unlink(missing_ok=True)
    return out_path


def _has_audio_stream(video_path: Path) -> bool:
    """Vrai si la vidéo contient au moins une piste audio."""
    _, ffprobe = _find_ffmpeg()
    cmd = [ffprobe, "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0",
           str(video_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return "audio" in r.stdout
    except subprocess.CalledProcessError:
        return False


def _mix_music(video_path: Path, music_path: Path, out_path: Path,
                music_volume: float = 0.35, encoder: str = "libx264") -> Path:
    """Mixe une piste musicale par-dessus le son original de la vidéo.

    Si la vidéo source n'a pas d'audio (cas des montages composés uniquement
    de stills), la musique est simplement collée sans amix → évite le crash
    « Invalid stream specifier » de FFmpeg.
    """
    ffmpeg, _ = _find_ffmpeg()
    has_audio = _has_audio_stream(video_path)

    if has_audio:
        filter_complex = (
            f"[1:a]volume={music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        )
        map_audio = ["-map", "[aout]"]
    else:
        # Pas de piste audio dans la vidéo : on prend juste la musique
        filter_complex = f"[1:a]volume=1.0[aout]"
        map_audio = ["-map", "[aout]"]

    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v", *map_audio,
        "-c:v", "copy",  # re-copie la vidéo (pas besoin de ré-encoder)
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # Fallback ultime : copier la vidéo sans musique
        import shutil as _sh
        _sh.copy(str(video_path), str(out_path))
    return out_path


# ══════════════════════════════════════════════════════════════
#  Sélection des meilleurs moments par scène
# ══════════════════════════════════════════════════════════════
# Durée cible par scène (en secondes) — total ≈ 3m
# Priorité client : plus de chute libre, ouverture du parachute visible,
# vraie sortie d'avion et vrai atterrissage.
SCENE_DURATIONS_CIBLE = {
    "briefing": 6,
    "vehicule_embarquement": 3,
    "montee_avion": 8,
    "sortie_avion": 12,       # +7s : bien voir le saut hors avion
    "chute_libre": 75,        # +25s : le moment phare
    "sous_voile": 12,         # -8s : moins de plané, on prend le DEBUT
    "atterrissage": 18,       # +8s : voir l'arrive au sol
    "reaction_emotion": 15,
    "interaction_moniteur": 12,
}

# Ou extraire le clip dans le segment source :
#   "start"  -> prendre les premieres secondes (capture le debut du moment)
#   "middle" -> prendre le milieu (moment moyen)
#   "end"    -> prendre la fin (capture la conclusion du moment)
SCENE_CLIP_POSITION = {
    "sortie_avion":   "start",  # saut hors avion = debut du segment
    "sous_voile":     "start",  # ouverture du parachute = debut du segment
    "atterrissage":   "end",    # touche du sol = fin du segment
    "chute_libre":    "middle",
    "briefing":       "middle",
    "vehicule_embarquement": "middle",
    "montee_avion":   "middle",
    "reaction_emotion": "middle",
    "interaction_moniteur": "middle",
}


def select_best_clips(segments: list[dict],
                       max_total_duration_s: int = 210) -> list[dict]:
    """Sélectionne et trim les clips pour respecter la durée cible.

    Stratégie simple :
        - Pour chaque scène, on prend au plus SCENE_DURATIONS_CIBLE[scene]
        - On prend le milieu du segment (meilleur moment en général)
        - On garde l'ordre narratif (briefing → ... → interaction_moniteur)
    """
    # Order narratif
    order = ["briefing", "vehicule_embarquement", "montee_avion",
             "sortie_avion", "chute_libre", "sous_voile",
             "atterrissage", "reaction_emotion", "interaction_moniteur"]

    by_scene = {}
    for seg in segments:
        scene = seg.get("scene")
        if scene in order:
            by_scene.setdefault(scene, []).append(seg)

    out = []
    for scene in order:
        segs = by_scene.get(scene, [])
        if not segs:
            continue
        # Garder le plus long segment de la scène
        best = max(segs, key=lambda s: s["end_s"] - s["start_s"])
        target = SCENE_DURATIONS_CIBLE.get(scene, 8)
        seg_start = max(0.0, best["start_s"])
        seg_end = max(seg_start, best["end_s"])
        seg_dur = seg_end - seg_start
        if seg_dur <= target:
            out.append({"start_s": seg_start,
                        "end_s": seg_end, "scene": scene})
        else:
            pos = SCENE_CLIP_POSITION.get(scene, "middle")
            if pos == "start":
                new_start = seg_start
                new_end = seg_start + target
            elif pos == "end":
                new_end = seg_end
                new_start = max(seg_start, seg_end - target)
            else:  # middle
                mid = (seg_start + seg_end) / 2
                half = target / 2
                new_start = max(0.0, mid - half)
                new_end = min(seg_end, new_start + target)
                # Si on a rogné à gauche, décale à gauche pour garder target secs
                if new_end - new_start < target:
                    new_start = max(0.0, new_end - target)
            out.append({"start_s": new_start, "end_s": new_end, "scene": scene})
    return out


# ══════════════════════════════════════════════════════════════
#  Pipeline principal
# ══════════════════════════════════════════════════════════════
def build_montage(video_source: str | Path,
                   segments: list[dict],
                   output_path: str | Path,
                   intro_overlay: Optional[Path] = None,
                   outro_overlay: Optional[Path] = None,
                   stats_overlay: Optional[Path] = None,
                   music_path: Optional[Path] = None,
                   music_volume: float = 0.35,
                   max_duration_s: int = 210,
                   encoder: Optional[str] = None,
                   width: int = 1920, height: int = 1080, fps: int = 30,
                   ) -> Path:
    """Construit le montage final à partir des segments sélectionnés.

    Returns: chemin du MP4 final.
    """
    video_source = Path(video_source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = encoder or _pick_encoder()

    # 1. Sélectionner les meilleurs clips
    best = select_best_clips(segments, max_total_duration_s=max_duration_s)

    # 2. Couper chaque clip + intro/stats/outro
    tmpdir = Path(tempfile.mkdtemp(prefix="montage_"))
    clips_files: list[Path] = []

    try:
        # Intro (2.5s)
        if intro_overlay:
            intro_clip = tmpdir / "00_intro.mp4"
            _still_to_clip(intro_overlay, 2.5, intro_clip, width, height, fps)
            clips_files.append(intro_clip)

        # Clips
        clips_perdus = []
        for i, seg in enumerate(best):
            out = tmpdir / f"clip_{i:02d}_{seg['scene']}.mp4"
            try:
                _cut_clip(video_source, seg["start_s"], seg["end_s"], out,
                           width, height, fps)
                clips_files.append(out)
            except subprocess.CalledProcessError as e:
                err = (e.stderr or b"").decode("utf-8", errors="replace")[:300]
                log.error("Clip %s [%.1f-%.1f] échec: %s",
                           seg["scene"], seg["start_s"], seg["end_s"], err)
                clips_perdus.append(seg["scene"])
                continue
        if clips_perdus:
            log.warning("Scènes perdues dans le montage: %s",
                         ", ".join(clips_perdus))

        # Stats overlay (4s)
        if stats_overlay:
            stats_clip = tmpdir / "98_stats.mp4"
            _still_to_clip(stats_overlay, 4.0, stats_clip, width, height, fps)
            clips_files.append(stats_clip)

        # Outro (3s)
        if outro_overlay:
            outro_clip = tmpdir / "99_outro.mp4"
            _still_to_clip(outro_overlay, 3.0, outro_clip, width, height, fps)
            clips_files.append(outro_clip)

        if not clips_files:
            raise RuntimeError("Aucun clip à monter — segments vides ?")

        # 3. Concat
        concat_out = tmpdir / "concat.mp4"
        _concat_clips(clips_files, concat_out, encoder)

        # 4. Mixer la musique si fournie
        if music_path and Path(music_path).exists():
            _mix_music(concat_out, Path(music_path), output_path,
                       music_volume=music_volume, encoder=encoder)
        else:
            shutil.copy(concat_out, output_path)

        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("Encodeur choisi :", _pick_encoder())

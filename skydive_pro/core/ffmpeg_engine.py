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
               fps: int = 30,
               fade_in: float = 0.0, fade_out: float = 0.0) -> Path:
    """Coupe un sous-clip normalisé (résolution/fps unifiés).

    Args:
        fade_in/fade_out : durée du fondu (s). 0 = cut sec (transition net sur beat).
                           > 0 = fondu vidéo+audio progressif (style smooth).
    """
    ffmpeg, _ = _find_ffmpeg()
    duration = max(0.1, end - start)

    # Filtres vidéo : scale + pad + fps + (fades optionnels)
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}")
    if fade_in > 0:
        vf += f",fade=t=in:st=0:d={fade_in:.2f}"
    if fade_out > 0:
        fo_start = max(0.0, duration - fade_out)
        vf += f",fade=t=out:st={fo_start:.2f}:d={fade_out:.2f}"

    # Filtres audio : fades optionnels (sinon copie directe)
    af_parts = []
    if fade_in > 0:
        af_parts.append(f"afade=t=in:st=0:d={fade_in:.2f}")
    if fade_out > 0:
        fo_start = max(0.0, duration - fade_out)
        af_parts.append(f"afade=t=out:st={fo_start:.2f}:d={fade_out:.2f}")

    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-ss", str(start), "-i", str(video),
        "-t", str(duration),
        "-vf", vf,
    ]
    if af_parts:
        cmd += ["-af", ",".join(af_parts)]
    cmd += [
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
    "briefing": 8,            # +2s
    "vehicule_embarquement": 5,  # +2s
    "montee_avion": 10,       # +2s
    "sortie_avion": 30,       # +18s : sequence COMPLETE de la sortie
    "chute_libre": 90,        # +15s : le moment phare, bien etale
    "sous_voile": 30,         # +18s : ouverture parachute + plane (validee user)
    "atterrissage": 35,       # +17s : approche + flare + arret au sol
    "reaction_emotion": 20,   # +5s
    "interaction_moniteur": 15,  # +3s
}
# Total cible : 243s = 4 min 03

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

# Subdivision : pour rendre les scenes longues plus dynamiques, on les
# decoupe en N sous-clips repartis sur la duree du segment source.
# Chaque sous-clip est ~ duree_cible/N et place dans le segment a
# intervalles reguliers (debut, milieu, fin).
# 1 = pas de subdivision (clip unique)
SCENE_SUBDIVIDE = {
    "sous_voile": 3,       # 3 sous-clips de ~10s = ouverture / plane / approche
    "chute_libre": 1,      # garde un plan continu pour le climax central
    "atterrissage": 1,
}


def select_best_clips(segments: list[dict],
                       max_total_duration_s: int = 210,
                       scene_durations: Optional[dict] = None) -> list[dict]:
    """Sélectionne et trim les clips pour respecter la durée cible.

    Stratégie simple :
        - Pour chaque scène, on prend au plus scene_durations[scene]
          (ou SCENE_DURATIONS_CIBLE par défaut, possiblement snappé sur beats)
        - On prend le milieu du segment (meilleur moment en général)
        - On garde l'ordre narratif (briefing → ... → interaction_moniteur)
    """
    durations = scene_durations or SCENE_DURATIONS_CIBLE
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
        target = durations.get(scene, 8)
        seg_start = max(0.0, best["start_s"])
        seg_end = max(seg_start, best["end_s"])
        seg_dur = seg_end - seg_start

        # Subdivision : decouper en N sous-clips pour plus de dynamisme
        n_sub = SCENE_SUBDIVIDE.get(scene, 1)
        if n_sub > 1 and seg_dur >= n_sub * 2:  # au moins 2s par sous-clip
            sub_target = target / n_sub
            # Repartir N points equi-distribues sur le segment source
            # (debut + (N-1) * pas)
            usable_dur = max(0.0, seg_dur - sub_target)
            for k in range(n_sub):
                if n_sub == 1:
                    sub_offset = 0.0
                else:
                    sub_offset = (usable_dur * k) / (n_sub - 1)
                sub_start = seg_start + sub_offset
                sub_end = min(seg_end, sub_start + sub_target)
                out.append({"start_s": sub_start, "end_s": sub_end,
                            "scene": scene})
            continue  # passe a la scene suivante

        # Pas de subdivision : 1 seul clip
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
                   beat_sync: bool = True,
                   fade_duration_s: float = 0.4,
                   ) -> Path:
    """Construit le montage final à partir des segments sélectionnés.

    Args:
        beat_sync       : si True et music_path fournie, snap les durées scènes
                          sur les beats de la musique (cuts en rythme).
        fade_duration_s : durée du fondu pour les scènes "calm" (style C).

    Returns: chemin du MP4 final.
    """
    video_source = Path(video_source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = encoder or _pick_encoder()

    # 0. Beat-sync : si musique fournie, on ajuste les durées cibles sur le tempo
    durations = dict(SCENE_DURATIONS_CIBLE)
    beat_period = None
    if beat_sync and music_path and Path(music_path).exists():
        try:
            from core.music_sync import analyze_beats, quantize_durations
            info = analyze_beats(music_path)
            if info.get("available"):
                beat_period = info["beat_period"]
                durations = quantize_durations(durations, beat_period)
                log.info(
                    "Beat-sync ON : %.1f BPM, durées snappées au beat (%.2fs)",
                    info["tempo"], beat_period,
                )
        except Exception as e:
            log.warning("Beat-sync indisponible (%s) — durées brutes", e)

    # 1. Sélectionner les meilleurs clips (avec durées éventuellement snappées)
    best = select_best_clips(segments, max_total_duration_s=max_duration_s,
                              scene_durations=durations)

    # 2. Couper chaque clip + intro/stats/outro
    tmpdir = Path(tempfile.mkdtemp(prefix="montage_"))
    clips_files: list[Path] = []

    # Style C de transitions : 'cut' = pas de fondu (transition nette sur beat),
    # 'fade' = fondu in/out de fade_duration_s (transition smooth).
    try:
        from core.music_sync import transition_style_for
    except ImportError:
        def transition_style_for(_):  # fallback minimal
            return "fade"

    try:
        # Intro (2.5s) — toujours en fondu
        if intro_overlay:
            intro_clip = tmpdir / "00_intro.mp4"
            _still_to_clip(intro_overlay, 2.5, intro_clip, width, height, fps)
            clips_files.append(intro_clip)

        # Clips — fade par scène selon SCENE_TRANSITION_STYLE
        clips_perdus = []
        for i, seg in enumerate(best):
            out = tmpdir / f"clip_{i:02d}_{seg['scene']}.mp4"
            style = transition_style_for(seg["scene"])
            # Cut sec (climax) = 0, fade = fade_duration_s
            fd = 0.0 if style == "cut" else fade_duration_s
            try:
                _cut_clip(video_source, seg["start_s"], seg["end_s"], out,
                           width, height, fps,
                           fade_in=fd, fade_out=fd)
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

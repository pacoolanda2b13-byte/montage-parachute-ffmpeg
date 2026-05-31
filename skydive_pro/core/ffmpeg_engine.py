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

import json as _json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Validation post-montage
# ══════════════════════════════════════════════════════════════
def validate_montage(output_path: str | Path,
                     expected_dur: Optional[float] = None,
                     duration_tolerance_s: float = 3.0) -> dict:
    """Vérifie l'intégrité d'un montage produit (ffprobe).

    Contrôle : présence vidéo + audio, codec h264, durée cohérente avec
    la durée attendue. Retourne un rapport structuré exploitable par le
    pipeline pour décider du statut (succes / partiel) — au lieu de
    "soft fail" silencieux qui faisait croire à un succès (cf postmortem
    bug #6).

    Returns:
        dict {ok: bool, issues: list[str], duration_s, has_video,
              has_audio, video_codec}
    """
    _, ffprobe = _find_ffmpeg()
    rapport = {"ok": False, "issues": [], "duration_s": None,
               "has_video": False, "has_audio": False, "video_codec": None}

    output_path = Path(output_path)
    if not output_path.exists() or output_path.stat().st_size == 0:
        rapport["issues"].append("FICHIER ABSENT OU VIDE")
        return rapport

    try:
        r = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "format=duration",
             "-show_streams", "-of", "json", str(output_path)],
            capture_output=True, text=True, check=True,
        )
        data = _json.loads(r.stdout)
    except Exception as e:
        rapport["issues"].append(f"ffprobe illisible : {e}")
        return rapport

    streams = data.get("streams", [])
    rapport["has_video"] = any(s.get("codec_type") == "video" for s in streams)
    rapport["has_audio"] = any(s.get("codec_type") == "audio" for s in streams)
    rapport["video_codec"] = next(
        (s.get("codec_name") for s in streams
         if s.get("codec_type") == "video"), None)
    try:
        rapport["duration_s"] = float(data["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        rapport["duration_s"] = None

    if not rapport["has_video"]:
        rapport["issues"].append("PAS DE VIDEO")
    if not rapport["has_audio"]:
        rapport["issues"].append("PAS D'AUDIO")
    if rapport["video_codec"] != "h264":
        rapport["issues"].append(
            f"codec video={rapport['video_codec']} (attendu h264)")
    if expected_dur is not None and rapport["duration_s"] is not None:
        delta = rapport["duration_s"] - expected_dur
        if abs(delta) > duration_tolerance_s:
            rapport["issues"].append(
                f"duree {rapport['duration_s']:.1f}s vs attendu "
                f"{expected_dur:.1f}s (delta {delta:+.1f}s)")

    rapport["ok"] = not rapport["issues"]
    return rapport


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
    except subprocess.CalledProcessError as e:
        # Fallback : copier la video sans musique. ATTENTION : silencieux
        # pour le user, donc on log MAXIMUM pour permettre le diag posteriori.
        err_str = (e.stderr or b"").decode("utf-8", errors="replace")[:1000]
        log.error("_mix_music ECHEC : video=%s music=%s -> output COPIE "
                   "SANS MUSIQUE. Stderr ffmpeg: %s",
                   video_path.name, music_path.name, err_str)
        log.error("_mix_music: cmd qui a echoue : %s", " ".join(cmd))
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
    "briefing": 10,
    "vehicule_embarquement": 5,
    "dans_avion": 10,         # NEW : interieur cabine
    "paysage_avion": 30,      # NEW : vues mer/montagne par hublot
    "montee_avion": 5,        # legacy, on garde minimal au cas ou Gemini renvoie ca
    "sortie_avion": 30,
    "chute_libre": 90,
    "sous_voile": 30,
    "atterrissage": 35,
    "reaction_emotion": 30,
    "interaction_moniteur": 15,
}
# Total cible avec toutes les scenes : ~290s = 4 min 50
# Sans interaction (videos courtes) : ~275s = 4 min 35

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
    "dans_avion":     "middle",
    "paysage_avion":  "middle",
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
                       max_total_duration_s: int = 320,
                       scene_durations: Optional[dict] = None,
                       video_duration_s: Optional[float] = None,
                       telemetry_chute_start_s: Optional[float] = None,
                       telemetry_atter_start_s: Optional[float] = None,
                       ) -> list[dict]:
    """Selection POSITIONNELLE garantissant l'ordre temporel narratif.

    Strategie :
        - Identifier 2 marqueurs cles via Gemini : 1ere chute_libre +
          1ere atterrissage
        - Decouper la video sequentiellement en respectant l'ordre
          temporel (briefing -> ... -> atterrissage)
        - Plus de melange entre fallback positionnel et segments Gemini
          qui creait des sauts narratifs (l'utilisateur voyait la video
          sauter entre des moments differents).

    Args:
        segments        : segments classifies par Gemini (juste utilises
                          pour reperer les positions de chute/atterrissage)
        scene_durations : durees cibles par scene
        video_duration_s: duree totale de la video source (None -> deduit
                          du max end_s des segments)
    """
    durations = scene_durations or SCENE_DURATIONS_CIBLE

    # ─── 1. Detecter la duree totale de la video ───
    if video_duration_s is None:
        video_duration_s = max((s.get("end_s", 0) for s in segments),
                                default=0.0)
    if video_duration_s <= 0:
        log.warning("select_best_clips: video_duration_s inconnue")
        return []

    # Guard : video trop courte (< 90s) -> mode degrade simple
    # On ne peut pas faire un montage narratif structure sur si peu.
    if video_duration_s < 90:
        log.warning("Video tres courte (%.1fs) : mode degrade simple "
                     "(pas de structure narrative).", video_duration_s)
        # Decoupe simple : briefing au debut, climax au milieu, atterrissage fin
        third = video_duration_s / 3
        return [
            {"start_s": 0.0, "end_s": min(third, 10),
             "scene": "briefing"},
            {"start_s": third, "end_s": min(2 * third, third + 60),
             "scene": "chute_libre"},
            {"start_s": 2 * third, "end_s": video_duration_s - 0.5,
             "scene": "atterrissage"},
        ]

    # ─── 2. Identifier les marqueurs cles ───
    # Priorite : telemetrie (precis ±0.1s) > Gemini (approximatif ±15s)
    chute_segs = [s for s in segments if s.get("scene") == "chute_libre"]
    atter_segs = [s for s in segments if s.get("scene") == "atterrissage"]

    if telemetry_chute_start_s is not None:
        chute_start = telemetry_chute_start_s
        log.info("chute_start depuis TELEMETRIE : %.1fs (precis)",
                  chute_start)
    elif chute_segs:
        chute_start = min(s["start_s"] for s in chute_segs)
        log.info("chute_start depuis Gemini : %.1fs (approximatif)",
                  chute_start)
    else:
        chute_start = video_duration_s * 0.30
        log.warning("Pas de chute_libre detectee — fallback chute_start=%.1fs",
                     chute_start)

    if telemetry_atter_start_s is not None:
        atter_start = telemetry_atter_start_s
        log.info("atter_start depuis TELEMETRIE : %.1fs (precis)",
                  atter_start)
    elif atter_segs:
        atter_start = min(s["start_s"] for s in atter_segs)
        log.info("atter_start depuis Gemini : %.1fs", atter_start)
    else:
        atter_start = max(chute_start + 90, video_duration_s - 35)
        log.warning("Pas d'atterrissage detecte — fallback atter_start=%.1fs",
                     atter_start)

    # Securites : chute_start >= 60s (pour avoir du pre-saut),
    # atter_start >= chute_start + 90s
    chute_start = max(60.0, chute_start)
    atter_start = max(chute_start + 60.0, atter_start)
    atter_start = min(atter_start, video_duration_s - 5.0)

    log.info("Marqueurs : chute=%.1fs, atter=%.1fs, video=%.1fs",
              chute_start, atter_start, video_duration_s)

    # ─── 3. Decoupage sequentiel garanti dans l'ordre temporel ───
    out = []
    briefing_d = durations.get("briefing", 10)
    embarq_d = durations.get("vehicule_embarquement", 5)
    dans_avion_d = durations.get("dans_avion", 10)
    paysage_d = durations.get("paysage_avion", 30)
    montee_d = durations.get("montee_avion", 5)
    sortie_d = durations.get("sortie_avion", 30)
    chute_d = durations.get("chute_libre", 90)
    sous_voile_d = durations.get("sous_voile", 30)
    atter_d = durations.get("atterrissage", 35)
    reaction_d = durations.get("reaction_emotion", 30)
    interaction_d = durations.get("interaction_moniteur", 15)

    # Pre-saut : [0, chute_start - sortie_d]
    pre_saut_end = chute_start - sortie_d
    pre_saut_duration = pre_saut_end
    cible_pre_saut = briefing_d + embarq_d + dans_avion_d + paysage_d + montee_d

    if pre_saut_duration < cible_pre_saut:
        # Compresser paysage_avion en priorite (le moins critique)
        deficit = cible_pre_saut - pre_saut_duration
        paysage_d = max(8.0, paysage_d - deficit)
        cible_pre_saut = briefing_d + embarq_d + dans_avion_d + paysage_d + montee_d
        if pre_saut_duration < cible_pre_saut:
            # Encore trop court : reduire dans_avion + briefing proportionnellement
            scale = pre_saut_duration / cible_pre_saut
            briefing_d *= scale
            embarq_d *= scale
            dans_avion_d *= scale
            paysage_d *= scale
            montee_d *= scale

    # POSITIONNEMENT INTELLIGENT du pre-saut :
    # briefing + embarquement = DEBUT de la video (zones briefing au sol)
    # dans_avion + paysage_avion = JUSTE AVANT la montee finale
    # (le paysage par hublot et les passagers en vol arrivent
    # naturellement vers la fin du pre-saut, pas au debut)
    # montee = les 5s juste avant la sortie

    sortie_start = chute_start - sortie_d
    # Calculer les positions en remontant depuis la sortie
    montee_end = sortie_start
    montee_start = montee_end - montee_d
    paysage_end = montee_start
    paysage_start = paysage_end - paysage_d
    dans_avion_end = paysage_start
    dans_avion_start = dans_avion_end - dans_avion_d

    # Si pre-saut trop court, on commence dans_avion juste apres
    # l'embarquement (cas video courte)
    embarq_end = briefing_d + embarq_d
    if dans_avion_start < embarq_end:
        # Compresser : positionner dans_avion juste apres embarquement
        dans_avion_start = embarq_end
        dans_avion_end = dans_avion_start + dans_avion_d
        paysage_start = dans_avion_end
        paysage_end = paysage_start + paysage_d
        montee_start = max(paysage_end, sortie_start - montee_d)
        montee_end = sortie_start

    # Briefing : tout debut de video
    out.append({"start_s": 0.0, "end_s": briefing_d,
                "scene": "briefing"})
    # Embarquement : centre dans la zone [briefing_d, dans_avion_start]
    # (cette zone correspond au "trou" entre briefing et avion, qui
    # contient typiquement la marche vers le vehicule + le trajet vers
    # l'avion)
    embarq_zone_start = briefing_d
    embarq_zone_end = max(briefing_d + embarq_d, dans_avion_start)
    embarq_zone_dur = embarq_zone_end - embarq_zone_start
    if embarq_zone_dur > embarq_d * 2:
        # Zone large : centre l'embarquement dans la zone
        emb_offset = (embarq_zone_dur - embarq_d) / 2
        emb_start = embarq_zone_start + emb_offset
    else:
        # Zone serree : juste apres briefing
        emb_start = embarq_zone_start
    out.append({"start_s": emb_start, "end_s": emb_start + embarq_d,
                "scene": "vehicule_embarquement"})
    # Dans avion : interieur cabine (positionne en remontant depuis sortie)
    out.append({"start_s": dans_avion_start, "end_s": dans_avion_end,
                "scene": "dans_avion"})
    # Paysage : vue hublot, juste avant la montee finale
    out.append({"start_s": paysage_start, "end_s": paysage_end,
                "scene": "paysage_avion"})
    # Montee : les 5s juste avant la sortie
    out.append({"start_s": montee_start, "end_s": montee_end,
                "scene": "montee_avion"})

    # Sortie d'avion
    out.append({"start_s": sortie_start, "end_s": chute_start,
                "scene": "sortie_avion"})

    # Chute libre : [chute_start, chute_end]
    # Garder au moins sous_voile_d secondes avant l'atterrissage
    max_chute_end = atter_start - sous_voile_d
    chute_end = min(chute_start + chute_d, max_chute_end)
    if chute_end - chute_start < 30:  # securite : pas de chute < 30s
        chute_end = chute_start + 30
    out.append({"start_s": chute_start, "end_s": chute_end,
                "scene": "chute_libre"})

    # Sous voile : zone [chute_end, atter_start]
    sv_zone_start = chute_end
    sv_zone_end = atter_start
    sv_zone_dur = sv_zone_end - sv_zone_start
    n_sub = SCENE_SUBDIVIDE.get("sous_voile", 3)
    if sv_zone_dur >= 30 and n_sub > 1:
        # 3 sous-clips espaces dans la zone sous-voile
        sub_target = sous_voile_d / n_sub
        usable = max(0.0, sv_zone_dur - sub_target)
        for k in range(n_sub):
            if n_sub == 1:
                off = 0.0
            else:
                off = (usable * k) / (n_sub - 1)
            ss = sv_zone_start + off
            out.append({"start_s": ss, "end_s": ss + sub_target,
                        "scene": "sous_voile"})
    else:
        # Petit zone : un seul clip
        out.append({"start_s": sv_zone_start,
                    "end_s": min(sv_zone_end, sv_zone_start + sous_voile_d),
                    "scene": "sous_voile"})

    # Atterrissage : si la video ne va pas assez loin pour avoir
    # atter_d secondes apres atter_start, on etend en ARRIERE
    # (l'approche d'atterrissage est aussi importante que le touchdown).
    atter_end = min(atter_start + atter_d, video_duration_s - 0.5)
    actual_dur = atter_end - atter_start
    if actual_dur < atter_d:
        # Pas assez de matiere apres : decale atter_start en arriere
        atter_start = max(chute_end, atter_end - atter_d)
    out.append({"start_s": atter_start, "end_s": atter_end,
                "scene": "atterrissage"})

    # Reaction emotion + interaction moniteur (si video continue apres)
    remaining = video_duration_s - atter_end
    if remaining > 5:
        r_dur = min(reaction_d, remaining - 1)
        out.append({"start_s": atter_end, "end_s": atter_end + r_dur,
                    "scene": "reaction_emotion"})
        rest = remaining - r_dur
        if rest > 5:
            i_dur = min(interaction_d, rest - 1)
            out.append({
                "start_s": atter_end + r_dur,
                "end_s": atter_end + r_dur + i_dur,
                "scene": "interaction_moniteur",
            })

    # ─── 4. Clamping final : garantir 0 <= start < end <= video_duration ───
    clamped = []
    for c in out:
        s = max(0.0, c["start_s"])
        e = min(video_duration_s, c["end_s"])
        if e - s >= 0.5:  # rejette les clips < 0.5s
            clamped.append({"start_s": s, "end_s": e, "scene": c["scene"]})
        else:
            log.warning("Clip rejete (trop court ou hors video) : "
                         "scene=%s [%.1f-%.1f]", c["scene"],
                         c["start_s"], c["end_s"])
    out = clamped

    # ─── 5. Respect strict de max_total_duration_s ───
    # Si la somme des clips depasse le budget, on tronque par scene
    # selon priorite (climax > calme), en commencant par les scenes
    # bonus (interaction, reaction) puis les paysages.
    total_dur = sum(c["end_s"] - c["start_s"] for c in out)
    if total_dur > max_total_duration_s:
        excess = total_dur - max_total_duration_s
        log.info("Depassement budget : %.1fs > %ds -> trim de %.1fs",
                  total_dur, max_total_duration_s, excess)
        # Priorite de trim : interaction > reaction > paysage > briefing > montee
        trim_priority = ["interaction_moniteur", "reaction_emotion",
                          "paysage_avion", "briefing", "vehicule_embarquement",
                          "dans_avion", "montee_avion"]
        for trim_scene in trim_priority:
            if excess <= 0:
                break
            for c in out:
                if c["scene"] == trim_scene and excess > 0:
                    clip_dur = c["end_s"] - c["start_s"]
                    can_trim = max(0, clip_dur - 2.0)  # garde au moins 2s
                    actual = min(can_trim, excess)
                    c["end_s"] -= actual
                    excess -= actual
        # Re-filter : enleve les clips qui sont devenus < 1s
        out = [c for c in out if (c["end_s"] - c["start_s"]) >= 1.0]

    log.info("select_best_clips POSITIONAL : %d clips, %.1fs total",
              len(out),
              sum(c["end_s"] - c["start_s"] for c in out))
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
                   telemetry_chute_start_s: Optional[float] = None,
                   telemetry_atter_start_s: Optional[float] = None,
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

    # 1. Detecter la duree de la video source (necessaire pour la
    # strategie positionnelle de select_best_clips)
    _, ffprobe = _find_ffmpeg()
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_source)],
            capture_output=True, text=True, check=True,
        )
        video_duration_s = float(r.stdout.strip())
    except Exception:
        video_duration_s = None

    # 2. Selection POSITIONNELLE : decoupage sequentiel garanti dans
    #    l'ordre temporel de la video source. Priorite : marqueurs
    #    telemetrie (precis) > marqueurs Gemini (approximatifs).
    best = select_best_clips(
        segments,
        max_total_duration_s=max_duration_s,
        scene_durations=durations,
        video_duration_s=video_duration_s,
        telemetry_chute_start_s=telemetry_chute_start_s,
        telemetry_atter_start_s=telemetry_atter_start_s,
    )

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

        # Clips — fade UNIQUEMENT aux FRONTIERES de scenes :
        # - fade_in si scene differente de la precedente (ou 1er clip)
        # - fade_out si scene differente de la suivante (ou dernier clip)
        # → Entre 2 sous-clips de la MEME scene (ex: 3 cuts sous_voile),
        #   pas de mini-fondu parasite.
        clips_perdus = []
        for i, seg in enumerate(best):
            out = tmpdir / f"clip_{i:02d}_{seg['scene']}.mp4"
            style = transition_style_for(seg["scene"])
            scene = seg["scene"]
            prev_scene = best[i - 1]["scene"] if i > 0 else None
            next_scene = best[i + 1]["scene"] if i < len(best) - 1 else None
            is_first_of_scene = (scene != prev_scene)
            is_last_of_scene = (scene != next_scene)

            if style == "cut":
                # Climax : aucun fade nulle part (cut sec)
                fade_in = 0.0
                fade_out = 0.0
            else:
                # Scenes calmes : fade SEULEMENT aux frontieres de scene
                fade_in = fade_duration_s if is_first_of_scene else 0.0
                fade_out = fade_duration_s if is_last_of_scene else 0.0
            try:
                _cut_clip(video_source, seg["start_s"], seg["end_s"], out,
                           width, height, fps,
                           fade_in=fade_in, fade_out=fade_out)
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
            mix_target = tmpdir / "mixed.mp4"
            _mix_music(concat_out, Path(music_path), mix_target,
                       music_volume=music_volume, encoder=encoder)
            source_for_final = mix_target
        else:
            source_for_final = concat_out

        # 5. Re-mux final avec faststart explicite — l'encodeur AMD AMF
        # n'applique pas toujours faststart correctement, le moov atom
        # peut se retrouver en fin de fichier -> certains lecteurs (Movies
        # & TV Windows, lecteurs mobiles) refusent de jouer. Ce remux
        # rapide (sans re-encodage) garantit un fichier lisible partout.
        ffmpeg, ffprobe = _find_ffmpeg()
        try:
            subprocess.run([
                ffmpeg, "-y", "-v", "error",
                "-i", str(source_for_final),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            log.warning("Re-mux faststart échoué (%s) — fallback copy",
                         (e.stderr or b"").decode("utf-8", errors="replace")[:200])
            shutil.copy(source_for_final, output_path)

        # 6. VALIDATION POST-MONTAGE : ffprobe sur le fichier final.
        # Le rapport est écrit dans un fichier .validation.json à côté du
        # montage pour que le pipeline puisse décider du statut (succes /
        # partiel) au lieu d'un "soft fail" silencieux (cf postmortem #6).
        expected_dur = sum(c["end_s"] - c["start_s"] for c in best)
        if intro_overlay:
            expected_dur += 2.5
        if stats_overlay:
            expected_dur += 4.0
        if outro_overlay:
            expected_dur += 3.0

        rapport = validate_montage(output_path, expected_dur=expected_dur)
        if rapport["ok"]:
            log.info("Validation OK : duree=%.1fs (attendu %.1fs), "
                      "video=%s, audio=%s",
                      rapport["duration_s"] or -1, expected_dur,
                      rapport["video_codec"],
                      "OK" if rapport["has_audio"] else "ABSENT")
        else:
            log.warning("VALIDATION POST-MONTAGE : problemes detectes — %s",
                         "; ".join(rapport["issues"]))
        try:
            (output_path.with_suffix(output_path.suffix + ".validation.json")
             ).write_text(_json.dumps(rapport, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("Ecriture rapport validation echouee : %s", e)

        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("Encodeur choisi :", _pick_encoder())

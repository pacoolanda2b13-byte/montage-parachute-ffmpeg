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


def _resolve_overlaps(clips: list[dict], overlap_threshold: float = 5.0
                       ) -> list[dict]:
    """Resout les chevauchements temporels MAJEURS entre clips.

    Ne coupe que si l'overlap est >= overlap_threshold secondes.
    Sinon, on accepte les petits chevauchements (transitions cinema OK).

    Cette logique evite que `_resolve_overlaps` ne mange des scenes
    entieres a cause d'un chevauchement de quelques secondes.
    """
    if len(clips) < 2:
        return clips
    # Conserver l'ordre narratif d'origine (selon SCENE order)
    # On ne tri PAS par start_s pour preserver l'ordre de scene.
    resolved = [dict(clips[0])]
    for c in clips[1:]:
        prev = resolved[-1]
        # Chevauchement detecte uniquement si c.start < prev.end
        # ET overlap est consequent (>= overlap_threshold secs)
        overlap = prev["end_s"] - c["start_s"]
        if overlap >= overlap_threshold:
            # Tronquer le precedent juste avant le suivant
            new_prev_end = c["start_s"]
            if new_prev_end > prev["start_s"] + 1.0:  # garde >= 1s
                prev["end_s"] = new_prev_end
        # Sinon : on accepte le petit chevauchement (= transition fluide)
        resolved.append(dict(c))
    # Filter out clips trop courts
    return [c for c in resolved if (c["end_s"] - c["start_s"]) >= 1.0]


def _merge_adjacent(segments: list[dict], gap_s: float = 5.0) -> list[dict]:
    """Fusionne les segments adjacents portant le même label scene.

    Deux segments sont considérés adjacents si l'écart entre la fin du
    premier et le début du second est <= gap_s.
    """
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda s: s.get("start_s", 0))
    merged = [dict(sorted_segs[0])]
    for seg in sorted_segs[1:]:
        last = merged[-1]
        same_scene = seg.get("scene") == last.get("scene")
        gap = seg.get("start_s", 0) - last.get("end_s", 0)
        if same_scene and gap <= gap_s:
            last["end_s"] = max(last["end_s"], seg.get("end_s", 0))
        else:
            merged.append(dict(seg))
    return merged


def _take_target_from_scene(segs_for_scene: list[dict], target: float,
                             pos: str = "middle") -> list[dict]:
    """Prend autant de segments que nécessaire pour cumuler `target` secondes.

    Stratégie :
        - Trier les segments par durée décroissante
        - En prendre un par un jusqu'à atteindre target
        - Si le dernier segment dépasse, le tronquer (selon `pos`)
        - Retourner les clips dans l'ordre temporel d'origine
    """
    if not segs_for_scene:
        return []
    by_dur = sorted(segs_for_scene,
                     key=lambda s: s["end_s"] - s["start_s"], reverse=True)
    picked = []
    cumul = 0.0
    for seg in by_dur:
        if cumul >= target:
            break
        seg_dur = seg["end_s"] - seg["start_s"]
        remaining = target - cumul
        if seg_dur <= remaining:
            picked.append({"start_s": seg["start_s"],
                            "end_s": seg["end_s"],
                            "scene": seg["scene"]})
            cumul += seg_dur
        else:
            # Tronquer ce segment selon la position
            seg_start = seg["start_s"]
            seg_end = seg["end_s"]
            if pos == "start":
                new_start = seg_start
                new_end = seg_start + remaining
            elif pos == "end":
                new_end = seg_end
                new_start = seg_end - remaining
            else:  # middle
                mid = (seg_start + seg_end) / 2
                half = remaining / 2
                new_start = max(seg_start, mid - half)
                new_end = new_start + remaining
            picked.append({"start_s": new_start, "end_s": new_end,
                            "scene": seg["scene"]})
            cumul += remaining
    # Re-trier dans l'ordre temporel pour la narration
    picked.sort(key=lambda s: s["start_s"])
    return picked


def select_best_clips(segments: list[dict],
                       max_total_duration_s: int = 210,
                       scene_durations: Optional[dict] = None) -> list[dict]:
    """Sélectionne et trim les clips pour respecter la durée cible.

    Stratégie multi-segment :
        - Fusionne les segments adjacents de même scène
        - Pour chaque scène, cumule plusieurs segments si nécessaire pour
          atteindre la durée cible (au lieu d'un seul "best")
        - Fallback positionnel : si "briefing"/"vehicule_embarquement"
          manquent mais qu'un segment "montee_avion" couvre tout le début
          de la vidéo, on subdivise ce gros segment en briefing/embarquement
          /montée pour une vraie structure narrative.
    """
    durations = scene_durations or SCENE_DURATIONS_CIBLE
    segments = _merge_adjacent(segments)
    # Order narratif (briefing -> embarquement -> dans_avion ->
    # paysage_avion -> sortie -> chute -> sous_voile -> atterrissage ->
    # reaction -> interaction). "montee_avion" garde sa place legacy
    # mais la valeur de duree sert de fallback uniquement.
    order = ["briefing", "vehicule_embarquement",
             "dans_avion", "paysage_avion", "montee_avion",
             "sortie_avion", "chute_libre", "sous_voile",
             "atterrissage", "reaction_emotion", "interaction_moniteur"]

    by_scene = {}
    for seg in segments:
        scene = seg.get("scene")
        if scene in order:
            by_scene.setdefault(scene, []).append(seg)

    # ─── Fallback positionnel intelligent ───
    # Probleme observe : Gemini (surtout flash-lite) classifie souvent
    # les 100+ premieres secondes en "montee_avion" alors qu'il y a
    # briefing + embarquement + interieur cabine + paysages.
    # Si on detecte un GROS segment "montee_avion" au debut, on le
    # subdivise en proportion en utilisant les durees cibles.
    if "montee_avion" in by_scene:
        big_montee = max(by_scene["montee_avion"],
                          key=lambda s: s["end_s"] - s["start_s"])
        big_dur = big_montee["end_s"] - big_montee["start_s"]
        # Seuil : segment >= 60s au debut de la video
        if big_dur >= 60 and big_montee["start_s"] < 30:
            seg_start = big_montee["start_s"]
            seg_end = big_montee["end_s"]
            cursor = seg_start

            # Briefing : tout debut (target 10s)
            if not by_scene.get("briefing"):
                d = durations.get("briefing", 10)
                by_scene["briefing"] = [{
                    "start_s": cursor, "end_s": cursor + d,
                    "scene": "briefing",
                }]
            cursor += durations.get("briefing", 10)

            # Embarquement (target 5s)
            if not by_scene.get("vehicule_embarquement"):
                d = durations.get("vehicule_embarquement", 5)
                by_scene["vehicule_embarquement"] = [{
                    "start_s": cursor, "end_s": cursor + d,
                    "scene": "vehicule_embarquement",
                }]
            cursor += durations.get("vehicule_embarquement", 5)

            # Dans l'avion : interieur cabine (target 10s)
            if not by_scene.get("dans_avion"):
                d = durations.get("dans_avion", 10)
                by_scene["dans_avion"] = [{
                    "start_s": cursor, "end_s": cursor + d,
                    "scene": "dans_avion",
                }]
            cursor += durations.get("dans_avion", 10)

            # Paysage avion : vue hublot (target 30s) — la VRAIE valeur
            # ajoutee de SkyDive Pro pour ce client
            if not by_scene.get("paysage_avion"):
                d = durations.get("paysage_avion", 30)
                # On reserve la fin du gros segment pour la "montee" finale
                paysage_end = min(seg_end - 5, cursor + d)
                if paysage_end > cursor + 5:  # au moins 5s de paysage
                    by_scene["paysage_avion"] = [{
                        "start_s": cursor, "end_s": paysage_end,
                        "scene": "paysage_avion",
                    }]
                    cursor = paysage_end

            # Montee avion : derniers 5s avant la sortie
            montee_dur = durations.get("montee_avion", 5)
            new_montee_start = max(cursor, seg_end - montee_dur)
            by_scene["montee_avion"] = [{
                "start_s": new_montee_start, "end_s": seg_end,
                "scene": "montee_avion",
            }]

    # ─── Fallback : extraire sortie_avion depuis le debut de chute_libre ───
    # Probleme observe : Gemini fusionne souvent "sortie_avion" avec
    # "chute_libre" (la sortie est tres breve visuellement).
    if not by_scene.get("sortie_avion") and by_scene.get("chute_libre"):
        first_chute = min(by_scene["chute_libre"],
                           key=lambda s: s["start_s"])
        sortie_dur = durations.get("sortie_avion", 30)
        sortie_start = max(0.0, first_chute["start_s"] - sortie_dur)
        by_scene["sortie_avion"] = [{
            "start_s": sortie_start,
            "end_s": first_chute["start_s"],
            "scene": "sortie_avion",
        }]

    # ─── Fallback : sous_voile -> chute_libre + atterrissage ───
    # Probleme observe : Gemini-flash-lite classifie 70%+ de la video en
    # sous_voile (de la fin de chute libre jusqu'a l'atterrissage).
    # Si chute_libre est tres courte (<30s) mais sous_voile gigantesque
    # (>120s), on suspecte cette confusion et on reattribue le 1er tiers
    # de sous_voile a chute_libre.
    sous_voile_segs = by_scene.get("sous_voile", [])
    chute_segs = by_scene.get("chute_libre", [])
    chute_total = sum(s["end_s"] - s["start_s"] for s in chute_segs)
    sous_total = sum(s["end_s"] - s["start_s"] for s in sous_voile_segs)
    if sous_total > 120 and chute_total < 40 and sous_voile_segs:
        # Recuperer les 1ers segments sous_voile contigus pour augmenter chute
        sv_sorted = sorted(sous_voile_segs, key=lambda s: s["start_s"])
        recover_dur = min(60.0, sous_total / 3)
        recovered = []
        accumulated = 0
        for sv in sv_sorted:
            if accumulated >= recover_dur:
                break
            sv_dur = sv["end_s"] - sv["start_s"]
            recovered.append({**sv, "scene": "chute_libre"})
            accumulated += sv_dur
        # Mettre a jour les listes
        by_scene["chute_libre"] = chute_segs + recovered
        by_scene["sous_voile"] = [s for s in sv_sorted
                                    if s not in [r for r in recovered]]
        log.info("Fallback sous_voile->chute_libre : %d segs, %.1fs recuperes",
                  len(recovered), accumulated)

    out = []
    for scene in order:
        segs = by_scene.get(scene, [])
        if not segs:
            continue
        target = durations.get(scene, 8)
        pos = SCENE_CLIP_POSITION.get(scene, "middle")
        n_sub = SCENE_SUBDIVIDE.get(scene, 1)

        # ─── Cas 1 : Subdivision avec PLUSIEURS segments distincts ───
        # Ex: sous_voile detecte sur 9 segments differents -> on en prend 3
        # qui sont espaces dans le temps (debut, milieu, fin) au lieu de
        # decouper artificiellement un seul segment court.
        if n_sub > 1 and len(segs) >= n_sub:
            segs_sorted = sorted(segs, key=lambda s: s["start_s"])
            sub_target = target / n_sub
            # Picker N segments equi-repartis sur la liste
            indices = [int(i * (len(segs_sorted) - 1) / (n_sub - 1))
                        for i in range(n_sub)]
            for idx in indices:
                seg = segs_sorted[idx]
                seg_dur = seg["end_s"] - seg["start_s"]
                # Tronquer ce segment a sub_target depuis le debut
                clip_dur = min(seg_dur, sub_target)
                out.append({
                    "start_s": seg["start_s"],
                    "end_s": seg["start_s"] + clip_dur,
                    "scene": scene,
                })
            continue

        # ─── Cas 2 : Multi-segment cumule pour atteindre target ───
        # On essaie de cumuler plusieurs segments de la meme scene si
        # le plus long ne suffit pas a remplir target.
        total_avail = sum(s["end_s"] - s["start_s"] for s in segs)
        if total_avail >= target * 0.9:
            # Assez de matiere : prendre plusieurs segments
            picked = _take_target_from_scene(segs, target, pos)
            out.extend(picked)
            continue

        # ─── Cas 3 : Pas assez de matiere -> extension contextuelle ───
        # On etend le segment dans le voisinage temporel pour atteindre target.
        # Direction d'extension selon la position narrative de la scene :
        #   sortie_avion / atterrissage : extend en ARRIERE (avant le moment)
        #   sous_voile : extend en AVANT
        #   autres : extend symetrique
        biggest = max(segs, key=lambda s: s["end_s"] - s["start_s"])
        seg_start = biggest["start_s"]
        seg_end = biggest["end_s"]
        seg_dur = seg_end - seg_start
        deficit = target - seg_dur

        if deficit > 0:
            extend_dir = {
                "sortie_avion":   "backward",
                "atterrissage":   "backward",
                "sous_voile":     "forward",
                "chute_libre":    "symmetric",
                "reaction_emotion": "forward",
                "interaction_moniteur": "forward",
            }.get(scene, "symmetric")

            if extend_dir == "backward":
                seg_start = max(0.0, seg_start - deficit)
            elif extend_dir == "forward":
                seg_end = seg_end + deficit  # NB: pourra etre clamp par cut_clip
            else:  # symmetric
                seg_start = max(0.0, seg_start - deficit / 2)
                seg_end = seg_end + deficit / 2

        out.append({
            "start_s": seg_start,
            "end_s": seg_end,
            "scene": scene,
        })

    # Resoudre les chevauchements MAJEURS uniquement (>= 15s)
    # Les petits chevauchements sont en fait des transitions fluides
    # entre scenes adjacentes (ex: fin de sortie -> debut chute_libre).
    out = _resolve_overlaps(out, overlap_threshold=15.0)
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
        ffmpeg, _ = _find_ffmpeg()
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

        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("Encodeur choisi :", _pick_encoder())

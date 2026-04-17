"""
scene_detector.py — Détection hybride des scènes d'un saut tandem.

Combine 3 sources de signal :
    1. Télémétrie GoPro (altitude, vitesse, accéléro) → phases objectives
    2. Audio (Librosa) → moteur avion / vent / silence / voix
    3. Vision IA (Gemini Vision) → briefing / véhicule / atterrissage

Sortie : timeline JSON des 9 scènes du saut tandem :
    briefing, vehicule_embarquement, montee_avion, sortie_avion,
    chute_libre, sous_voile, atterrissage, reaction_emotion, interaction_moniteur

Usage :
    from core.scene_detector import detect_scenes
    timeline = detect_scenes("sources/saut.mp4")
"""

from __future__ import annotations

import os
import base64
import json
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from core.telemetry_gopro import extract_telemetry, TelemetrySample


# ══════════════════════════════════════════════════════════════
#  Modèles
# ══════════════════════════════════════════════════════════════
SCENE_NAMES = [
    "briefing", "vehicule_embarquement", "montee_avion",
    "sortie_avion", "chute_libre", "sous_voile",
    "atterrissage", "reaction_emotion", "interaction_moniteur",
]


@dataclass
class SceneSegment:
    scene: str
    start_s: float
    end_s: float
    confiance: float = 1.0
    source: str = "telemetrie"  # telemetrie | audio | vision | fusion

    @property
    def duree_s(self) -> float:
        return self.end_s - self.start_s


# ══════════════════════════════════════════════════════════════
#  1. Couche télémétrie
# ══════════════════════════════════════════════════════════════
def detect_phases_from_telemetry(samples: list[TelemetrySample]) -> list[SceneSegment]:
    """Détecte chute libre, sous voile, atterrissage à partir des samples."""
    if not samples:
        return []

    segments = []

    # Chute libre : accel_g < 0.5 pendant >= 5 s
    accels = [(s.time_s, s.accel_g) for s in samples if s.accel_g is not None]
    in_ff = False
    ff_start = 0.0
    for t, g in accels:
        if g < 0.5:
            if not in_ff:
                in_ff, ff_start = True, t
        else:
            if in_ff and (t - ff_start) >= 5:
                segments.append(SceneSegment("chute_libre", ff_start, t, 0.9))
            in_ff = False
    if in_ff and accels and (accels[-1][0] - ff_start) >= 5:
        segments.append(SceneSegment("chute_libre", ff_start, accels[-1][0], 0.9))

    # Altitude → détecter descente sous voile + atterrissage
    gps = [s for s in samples if s.altitude_m is not None]
    if len(gps) >= 5:
        # Atterrissage : 5 derniers % du temps avec altitude stable
        last_t = gps[-1].time_s
        end_window = [s for s in gps if s.time_s >= last_t - 10]
        if len(end_window) >= 3:
            alt_range = max(s.altitude_m for s in end_window) - min(s.altitude_m for s in end_window)
            if alt_range < 5:  # < 5m de variation sur 10s = au sol
                segments.append(SceneSegment("atterrissage",
                                              end_window[0].time_s,
                                              last_t, 0.85))

        # Sous voile : entre fin chute libre et début atterrissage
        chute = next((s for s in segments if s.scene == "chute_libre"), None)
        atter = next((s for s in segments if s.scene == "atterrissage"), None)
        if chute and atter and chute.end_s < atter.start_s:
            segments.append(SceneSegment("sous_voile",
                                          chute.end_s, atter.start_s, 0.85))

        # Montée avion : altitude augmente du début à max altitude
        alt_max_idx = max(range(len(gps)), key=lambda i: gps[i].altitude_m)
        if alt_max_idx > 0:
            segments.append(SceneSegment("montee_avion",
                                          gps[0].time_s, gps[alt_max_idx].time_s,
                                          0.7))

    return segments


# ══════════════════════════════════════════════════════════════
#  2. Couche audio (librosa)
# ══════════════════════════════════════════════════════════════
def analyze_audio(video_path: str | Path, sample_rate: int = 22050) -> dict:
    """Analyse audio via Librosa — retourne des labels par fenêtre de 1s.

    Labels possibles :
        - "moteur"   : spectre rich, basse fréquence dominante (avion)
        - "vent"     : bruit blanc, haute énergie (chute libre)
        - "silence"  : faible énergie
        - "voix"     : bande 300-3000 Hz dominante (briefing, interaction)
        - "ambiant"  : non classifié
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        return {"disponible": False, "labels": []}

    video_path = Path(video_path)
    # Extraire l'audio en WAV mono 22050 Hz via ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
             "-ac", "1", "-ar", str(sample_rate), tmp_wav],
            capture_output=True, check=True,
        )
        y, sr = librosa.load(tmp_wav, sr=sample_rate, mono=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"disponible": False, "labels": []}
    finally:
        Path(tmp_wav).unlink(missing_ok=True)

    hop = sr  # 1 seconde par fenêtre
    labels = []
    for i in range(0, len(y), hop):
        chunk = y[i:i + hop]
        if len(chunk) < sr // 2:
            break
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        # Énergie spectrale
        S = np.abs(librosa.stft(chunk, n_fft=1024, hop_length=512))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)

        # Ratios par bande
        low = S[(freqs >= 20) & (freqs < 300)].sum()
        mid = S[(freqs >= 300) & (freqs < 3000)].sum()
        high = S[(freqs >= 3000)].sum()
        total = low + mid + high + 1e-9

        if rms < 0.005:
            label = "silence"
        elif high / total > 0.55 and rms > 0.02:
            label = "vent"         # spectre plat + énergie → chute libre
        elif low / total > 0.5 and rms > 0.01:
            label = "moteur"       # basses dominantes → avion
        elif mid / total > 0.5 and rms > 0.01:
            label = "voix"         # voix humaine
        else:
            label = "ambiant"

        labels.append({
            "start_s": i / sr,
            "end_s": min((i + hop) / sr, len(y) / sr),
            "label": label,
            "rms": rms,
        })

    return {"disponible": True, "labels": labels}


def phases_from_audio(audio_result: dict) -> list[SceneSegment]:
    """Convertit les labels audio en segments de scènes probables."""
    if not audio_result.get("disponible"):
        return []

    segments = []
    labels = audio_result["labels"]

    # Regrouper les séquences consécutives du même label
    if not labels:
        return segments

    current_label = labels[0]["label"]
    current_start = labels[0]["start_s"]
    for lab in labels[1:]:
        if lab["label"] != current_label:
            segments.append((current_label, current_start, lab["start_s"]))
            current_label = lab["label"]
            current_start = lab["start_s"]
    segments.append((current_label, current_start, labels[-1]["end_s"]))

    # Mapper les labels audio → scènes
    mapping = {
        "moteur": "montee_avion",
        "vent": "chute_libre",
        # voix + silence ne mappent pas directement sur une seule scène
    }
    out = []
    for label, start, end in segments:
        scene = mapping.get(label)
        if scene and (end - start) >= 3:
            out.append(SceneSegment(scene, start, end, 0.65, source="audio"))
    return out


# ══════════════════════════════════════════════════════════════
#  3. Couche vision IA (Gemini)
# ══════════════════════════════════════════════════════════════
def extract_keyframes(video_path: str | Path,
                      every_n_sec: int = 30,
                      output_dir: Optional[Path] = None) -> list[tuple[float, Path]]:
    """Extrait des keyframes tous les N secondes. Retourne (time_s, path)."""
    video_path = Path(video_path)
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="keyframes_"))
    output_dir.mkdir(exist_ok=True)

    # Durée de la vidéo via ffprobe
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "json", str(video_path)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(json.loads(res.stdout)["format"]["duration"])
    except Exception:
        return []

    timestamps = [t for t in range(0, int(duration), every_n_sec)]
    frames = []
    for i, t in enumerate(timestamps):
        out = output_dir / f"frame_{i:04d}_t{t}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", str(t),
             "-i", str(video_path), "-frames:v", "1",
             "-vf", "scale=640:-1", "-q:v", "5", str(out)],
            capture_output=True,
        )
        if out.exists():
            frames.append((float(t), out))

    return frames


def classify_keyframes_with_gemini(frames: list[tuple[float, Path]],
                                    api_key: Optional[str] = None) -> list[dict]:
    """Classifie chaque keyframe via Gemini Flash (gratuit)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not frames:
        return []

    try:
        import google.generativeai as genai
    except ImportError:
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"))

    prompt = """Tu analyses une photo extraite d'une vidéo de saut en parachute tandem.
Classifie UNE seule scène parmi cette liste exacte :
- briefing (passager et moniteur au sol, équipement, gestes d'explication)
- vehicule_embarquement (voiture/minibus, personne qui monte ou descend)
- montee_avion (intérieur avion, passagers assis, hublot, moteur)
- sortie_avion (porte ouverte, sortie, parachute attaché)
- chute_libre (ciel, visage du passager visible en vol, vent)
- sous_voile (voile ouverte visible, ciel dégagé, descente calme)
- atterrissage (sol proche, pieds touchant le sol, voile derrière)
- reaction_emotion (passager au sol après saut, visage plein cadre, émotion forte)
- interaction_moniteur (moniteur et passager ensemble, geste : check, high-five, câlin)
- autre (si aucune ne correspond)

Réponds UNIQUEMENT avec un JSON compact :
{"scene": "nom_scene", "confiance": 0.0-1.0}"""

    results = []
    for t, fpath in frames:
        try:
            with open(fpath, "rb") as f:
                img_data = f.read()
            response = model.generate_content([
                {"mime_type": "image/jpeg", "data": img_data},
                prompt,
            ])
            text = response.text.strip()
            # Nettoyer markdown si présent
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
                if text.startswith("json"):
                    text = text[4:].strip()
            parsed = json.loads(text)
            results.append({
                "time_s": t,
                "scene": parsed.get("scene", "autre"),
                "confiance": float(parsed.get("confiance", 0.5)),
            })
        except Exception as e:
            results.append({"time_s": t, "scene": "autre", "confiance": 0.0, "erreur": str(e)})
    return results


def phases_from_vision(gemini_results: list[dict],
                        total_duration_s: float) -> list[SceneSegment]:
    """Convertit les classifications Gemini en segments de scènes."""
    segments = []
    for i, r in enumerate(gemini_results):
        if r["scene"] == "autre":
            continue
        start = r["time_s"]
        # durée jusqu'au prochain keyframe
        end = gemini_results[i + 1]["time_s"] if i + 1 < len(gemini_results) else total_duration_s
        segments.append(SceneSegment(
            r["scene"], start, end, r["confiance"], source="vision"
        ))
    return segments


# ══════════════════════════════════════════════════════════════
#  4. Fusion des signaux
# ══════════════════════════════════════════════════════════════
def merge_signals(telemetry_segs: list[SceneSegment],
                   audio_segs: list[SceneSegment],
                   vision_segs: list[SceneSegment]) -> list[SceneSegment]:
    """Fusionne les segments des 3 sources en privilégiant la télémétrie."""
    # Priorité : télémétrie > vision > audio
    # On garde télémétrie en premier, puis on remplit les trous avec vision puis audio
    all_segs = list(telemetry_segs)

    for seg in vision_segs:
        # Pas de recouvrement avec télémétrie
        overlap = any(
            not (seg.end_s <= t.start_s or seg.start_s >= t.end_s)
            for t in telemetry_segs
        )
        if not overlap:
            all_segs.append(seg)

    for seg in audio_segs:
        overlap = any(
            not (seg.end_s <= s.start_s or seg.start_s >= s.end_s)
            for s in all_segs
        )
        if not overlap:
            all_segs.append(seg)

    all_segs.sort(key=lambda s: s.start_s)
    return all_segs


# ══════════════════════════════════════════════════════════════
#  Point d'entrée principal
# ══════════════════════════════════════════════════════════════
def detect_scenes(video_path: str | Path,
                   use_vision: bool = True,
                   keyframe_interval: int = 30) -> dict:
    """Pipeline complet de détection de scènes sur une vidéo.

    Retourne un dict avec :
        - segments : liste de SceneSegment
        - stats : méta-infos (nb samples, coût, etc.)
    """
    video_path = Path(video_path)

    # 1. Télémétrie
    samples = extract_telemetry(video_path)
    telemetry_segs = detect_phases_from_telemetry(samples)

    # 2. Audio
    audio_result = analyze_audio(video_path)
    audio_segs = phases_from_audio(audio_result)

    # 3. Vision (optionnel, coûte quelques requêtes Gemini)
    vision_segs = []
    nb_keyframes = 0
    if use_vision:
        frames = extract_keyframes(video_path, every_n_sec=keyframe_interval)
        nb_keyframes = len(frames)
        gemini_results = classify_keyframes_with_gemini(frames)
        # Durée totale
        duration_s = samples[-1].time_s if samples else (frames[-1][0] if frames else 60)
        vision_segs = phases_from_vision(gemini_results, duration_s)
        # Nettoyage des keyframes temporaires
        for _, fp in frames:
            try: fp.unlink()
            except Exception: pass

    # 4. Fusion
    fused = merge_signals(telemetry_segs, audio_segs, vision_segs)

    return {
        "segments": [asdict(s) for s in fused],
        "stats": {
            "nb_samples_telemetrie": len(samples),
            "nb_segments_telemetrie": len(telemetry_segs),
            "nb_segments_audio": len(audio_segs),
            "nb_segments_vision": len(vision_segs),
            "nb_keyframes_analyses": nb_keyframes,
            "audio_disponible": audio_result.get("disponible", False),
            "vision_activee": use_vision,
        }
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage : python -m core.scene_detector <video.mp4> [--no-vision]")
        sys.exit(1)

    use_vision = "--no-vision" not in sys.argv
    result = detect_scenes(sys.argv[1], use_vision=use_vision)
    print(json.dumps(result, indent=2, ensure_ascii=False))

"""
music_sync.py — Synchronisation des coupes vidéo sur les beats musicaux.

Utilise librosa pour extraire le tempo et les positions des beats d'une piste
audio, puis fournit des helpers pour aligner les durées de chaque scène sur ces
beats. Effet : chaque transition tombe pile sur un beat → sensation cinéma.

Usage minimal :
    from core.music_sync import analyze_beats, quantize_durations
    info = analyze_beats("assets/music/track.mp3")
    snapped = quantize_durations(SCENE_DURATIONS_CIBLE, info["beat_period"])
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger(__name__)


def analyze_beats(music_path: str | Path,
                   sr: Optional[int] = None) -> dict:
    """Analyse une piste audio et retourne tempo + beats.

    Returns:
        dict avec :
          - tempo : float (BPM)
          - beat_period : float (durée d'un beat en secondes)
          - beat_times : list[float] (positions des beats en secondes)
          - duration : float (durée totale du morceau en secondes)
          - n_beats : int

    En cas d'échec (librosa absent, fichier corrompu), retourne un dict avec
    `tempo=None` et un fallback à 120 BPM. Le pipeline reste fonctionnel.
    """
    music_path = Path(music_path)
    fallback = {
        "tempo": None,
        "beat_period": 0.5,  # 120 BPM
        "beat_times": [],
        "duration": 0.0,
        "n_beats": 0,
        "available": False,
    }

    if not music_path.exists():
        log.warning("music_sync: fichier introuvable %s", music_path)
        return fallback

    try:
        import numpy as np
        import librosa
    except ImportError:
        log.warning("music_sync: librosa absent — sync désactivée")
        return fallback

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            y, sr_native = librosa.load(str(music_path), sr=sr, mono=True)
        if y.size == 0:
            log.warning("music_sync: piste audio vide %s", music_path.name)
            return fallback

        tempo_raw, beats = librosa.beat.beat_track(y=y, sr=sr_native)
        # tempo peut être array (librosa >= 0.10) ou scalaire selon version
        tempo = float(np.atleast_1d(tempo_raw)[0]) if tempo_raw is not None else 120.0
        if tempo <= 0:
            tempo = 120.0
        beat_period = 60.0 / tempo
        beat_times = [float(t) for t in librosa.frames_to_time(beats, sr=sr_native)]
        duration = float(len(y) / sr_native)

        log.info("music_sync: %s — %.1f BPM, %d beats, %.1fs",
                  music_path.name, tempo, len(beat_times), duration)
        return {
            "tempo": tempo,
            "beat_period": beat_period,
            "beat_times": beat_times,
            "duration": duration,
            "n_beats": len(beat_times),
            "available": True,
        }
    except Exception as e:
        log.warning("music_sync: échec analyse %s (%s) — fallback 120 BPM",
                     music_path.name, e)
        return fallback


def quantize_duration(duration_s: float, beat_period: float,
                       min_beats: int = 1) -> float:
    """Arrondit une durée au multiple le plus proche d'un beat.

    Garantit au moins `min_beats` beats (sinon le clip serait trop court).
    """
    if beat_period <= 0:
        return duration_s
    n_beats = max(min_beats, round(duration_s / beat_period))
    return round(n_beats * beat_period, 3)


def quantize_durations(durations: dict[str, float],
                        beat_period: float,
                        min_beats_per_scene: Optional[dict[str, int]] = None
                        ) -> dict[str, float]:
    """Snap toutes les durées scène sur des multiples de beat.

    Args:
        durations            : { scene_name: duree_cible_s, ... }
        beat_period          : durée d'un beat en secondes
        min_beats_per_scene  : { scene_name: min_beats } pour forcer des minima

    Returns:
        Un nouveau dict avec les durées snappées au beat.
    """
    min_beats_per_scene = min_beats_per_scene or {}
    out = {}
    for scene, dur in durations.items():
        min_b = min_beats_per_scene.get(scene, 1)
        out[scene] = quantize_duration(dur, beat_period, min_beats=min_b)
    return out


def snap_to_nearest_beat(timestamp_s: float, beat_times: list[float]) -> float:
    """Trouve le beat le plus proche d'un timestamp donné."""
    if not beat_times:
        return timestamp_s
    return min(beat_times, key=lambda t: abs(t - timestamp_s))


# Style des transitions par scène (pour le style C "mix progressif")
# climax → cut sec (frappe le beat)
# calm   → fondu court (smooth narratif)
SCENE_TRANSITION_STYLE = {
    "intro":               "fade",
    "briefing":            "fade",
    "vehicule_embarquement": "fade",
    "montee_avion":        "fade",
    "sortie_avion":        "cut",   # ⚡ climax 1 — cut net sur le beat
    "chute_libre":         "cut",   # ⚡ climax central
    "sous_voile":          "cut",   # ⚡ user feedback : plus de dynamisme
    "atterrissage":        "cut",   # ⚡ climax final
    "reaction_emotion":    "cut",   # ⚡ punch émotionnel
    "interaction_moniteur": "fade",
    "stats":               "fade",
    "outro":               "fade",
}


def transition_style_for(scene: str) -> str:
    """Retourne 'cut' ou 'fade' pour une scène donnée (défaut: fade)."""
    return SCENE_TRANSITION_STYLE.get(scene, "fade")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m core.music_sync <music.mp3>")
        sys.exit(1)
    info = analyze_beats(sys.argv[1])
    print(f"Tempo  : {info['tempo']} BPM")
    print(f"Beats  : {info['n_beats']}")
    print(f"Période: {info['beat_period']:.3f}s")
    print(f"Durée  : {info['duration']:.1f}s")

"""
Tests pour la planification de clips (select_best_clips).

Couvre :
- Vidéo très courte (< 90s) -> mode dégradé
- Vidéo standard avec marqueurs télémétrie
- Vidéo sans Gemini (segments vides)
- Clamping aux frontières [0, video_duration]
- Respect de max_total_duration_s
- Ordre temporel garanti
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.ffmpeg_engine import select_best_clips, SCENE_DURATIONS_CIBLE


def _total_duration(clips):
    return sum(c["end_s"] - c["start_s"] for c in clips)


# ─── Cas 1 : video tres courte (< 90s) ─────────────────────────
def test_video_courte_mode_degrade():
    """Une vidéo de 45s passe en mode dégradé sans crash."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=45.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
    )
    assert len(clips) >= 2, "doit produire au moins quelques clips"
    # Tous les clips dans [0, 45]
    for c in clips:
        assert 0 <= c["start_s"] < c["end_s"] <= 45.0
    # Total ne depasse pas la duree video
    assert _total_duration(clips) <= 45.0


def test_video_zero_duration():
    """Vidéo de 0s -> liste vide, pas de crash."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=0.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
    )
    assert clips == []


# ─── Cas 2 : video standard avec marqueurs telemetrie ──────────
def test_video_standard_telemetrie():
    """Cas TANDEM : 472s, chute=132s. Doit produire ~10 clips ordonnés."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=472.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
        telemetry_chute_start_s=132.0,
    )
    assert len(clips) >= 8, f"trop peu de clips ({len(clips)})"
    # Verifier ordre temporel
    for i in range(len(clips) - 1):
        assert clips[i]["start_s"] <= clips[i + 1]["start_s"], (
            f"Ordre temporel rompu : clip {i} start={clips[i]['start_s']} "
            f"> clip {i+1} start={clips[i+1]['start_s']}"
        )
    # Tous les clips dans [0, 472]
    for c in clips:
        assert 0 <= c["start_s"] < c["end_s"] <= 472.0


def test_scenes_essentielles_presentes():
    """Sur une vidéo TANDEM standard, les 4 scènes essentielles
    (briefing, sortie_avion, chute_libre, atterrissage) DOIVENT etre
    presentes."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=472.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
        telemetry_chute_start_s=132.0,
    )
    scenes_presentes = {c["scene"] for c in clips}
    essentiels = {"briefing", "sortie_avion", "chute_libre", "atterrissage"}
    missing = essentiels - scenes_presentes
    assert not missing, f"Scenes essentielles manquantes : {missing}"


# ─── Cas 3 : Pas de marqueur telemetrie + segments Gemini ──────
def test_fallback_gemini_uniquement():
    """Sans télémétrie, on doit utiliser les segments Gemini."""
    segments = [
        {"start_s": 100, "end_s": 130, "scene": "chute_libre"},
        {"start_s": 200, "end_s": 230, "scene": "atterrissage"},
    ]
    clips = select_best_clips(
        segments=segments,
        video_duration_s=240.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
    )
    assert len(clips) >= 4
    scenes = {c["scene"] for c in clips}
    assert "chute_libre" in scenes
    assert "atterrissage" in scenes


# ─── Cas 4 : Clamping ───────────────────────────────────────────
def test_clamping_aucun_depassement():
    """Aucun clip ne doit avoir start<0 ou end>video_duration."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=200.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
        telemetry_chute_start_s=80.0,
    )
    for c in clips:
        assert c["start_s"] >= 0, f"start<0 sur {c}"
        assert c["end_s"] <= 200.0, f"end>200 sur {c}"
        assert c["end_s"] - c["start_s"] >= 0.5, f"clip trop court {c}"


# ─── Cas 5 : Respect max_total_duration_s (climax preserves) ───
def test_respect_max_total_duration_avec_climax_preserves():
    """Si max=200s, le trim doit reduire mais preserver les climax
    (chute_libre 90s + atterrissage 35s = 125s minimum incompressibles)."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=472.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
        telemetry_chute_start_s=132.0,
        max_total_duration_s=200,
    )
    total = _total_duration(clips)
    # Total <= 220s tolerance (climax incompressibles)
    assert total <= 220, f"Total {total:.1f}s trop loin du budget 200s"
    # Mais chute_libre et atterrissage doivent rester intacts
    chute_dur = sum(c["end_s"] - c["start_s"] for c in clips
                     if c["scene"] == "chute_libre")
    atter_dur = sum(c["end_s"] - c["start_s"] for c in clips
                     if c["scene"] == "atterrissage")
    assert chute_dur >= 80, f"chute_libre tronquee a {chute_dur:.1f}s"
    assert atter_dur >= 30, f"atterrissage tronque a {atter_dur:.1f}s"


# ─── Cas 6 : Edge - video tres longue ──────────────────────────
def test_video_tres_longue():
    """Vidéo de 30 min : pas de crash, total raisonnable."""
    clips = select_best_clips(
        segments=[],
        video_duration_s=1800.0,
        scene_durations=SCENE_DURATIONS_CIBLE,
        telemetry_chute_start_s=900.0,  # chute au milieu
        max_total_duration_s=320,
    )
    assert len(clips) >= 8
    total = _total_duration(clips)
    assert total <= 325


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

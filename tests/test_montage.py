"""Tests du moteur de montage FFmpeg."""
import os
import subprocess

import pytest

from conftest import besoin_ffmpeg
import montage_parachute_ffmpeg as m


def _streams(chemin):
    """Retourne la liste des types de flux (video/audio) d'un fichier."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", chemin],
        capture_output=True, text=True,
    ).stdout.split()
    return out


def _duree(chemin):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", chemin],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


# ── Logique pure (pas de FFmpeg) ─────────────────────────────

def test_filtergraph_un_seul_clip():
    fc, v, a = m.construire_filtergraph_xfade(["x.mp4"], [], 1.0)
    assert fc == ""
    assert v == "[0:v]"
    assert a == "[0:a]"


def test_filtergraph_transition_invalide_retombe_sur_defaut(monkeypatch):
    # Évite l'appel ffprobe réel en simulant des durées fixes.
    monkeypatch.setattr(m, "obtenir_duree", lambda c: 5.0)
    fc, v, a = m.construire_filtergraph_xfade(
        ["a.mp4", "b.mp4"], ["TRANSITION_BIDON"], 1.0
    )
    assert m.CONFIG["transition_defaut"] in fc
    assert "TRANSITION_BIDON" not in fc
    assert v == "[xv0]"


def test_filtergraph_offsets_corrects(monkeypatch):
    monkeypatch.setattr(m, "obtenir_duree", lambda c: 5.0)
    fc, _, _ = m.construire_filtergraph_xfade(
        ["a.mp4", "b.mp4", "c.mp4"], ["fade", "fade"], 1.0
    )
    # offset 1 = 5 - 1 = 4 ; offset 2 = 4 + (5 - 1) = 8
    assert "offset=4" in fc
    assert "offset=8" in fc


# ── Avec FFmpeg ──────────────────────────────────────────────

@besoin_ffmpeg
def test_clip_a_audio(clip_avec_audio, clip_muet):
    assert m.clip_a_audio(clip_avec_audio) is True
    assert m.clip_a_audio(clip_muet) is False


@besoin_ffmpeg
def test_preparer_clip_muet_obtient_audio(clip_muet, tmp_path):
    cfg = {**m.CONFIG, "duree_clip": 2, "resolution": "320x240"}
    sortie = m.preparer_clip(clip_muet, 0, str(tmp_path), cfg)
    assert os.path.isfile(sortie)
    assert "audio" in _streams(sortie), "le clip muet doit recevoir une piste silencieuse"


@besoin_ffmpeg
def test_montage_avec_clip_muet(clip_avec_audio, clip_muet, tmp_path):
    """Régression : un clip muet ne doit plus casser le rendu."""
    sortie = os.path.join(str(tmp_path), "montage.mp4")
    res = m.creer_montage(
        [clip_avec_audio, clip_muet], sortie,
        transitions=["fade"],
        cfg={"duree_clip": 2, "duree_transition": 0.5, "resolution": "320x240",
             "dossier_sortie": str(tmp_path)},
    )
    assert os.path.isfile(res)
    flux = _streams(res)
    assert "video" in flux and "audio" in flux
    # 2 + 2 - 0.5 = 3.5s (tolérance)
    assert 3.0 < _duree(res) < 4.0


@besoin_ffmpeg
def test_montage_clip_unique(clip_avec_audio, tmp_path):
    sortie = os.path.join(str(tmp_path), "solo.mp4")
    res = m.creer_montage(
        [clip_avec_audio], sortie,
        cfg={"duree_clip": 2, "resolution": "320x240", "dossier_sortie": str(tmp_path)},
    )
    assert os.path.isfile(res)
    assert "video" in _streams(res)


def test_creer_montage_liste_vide():
    with pytest.raises(ValueError):
        m.creer_montage([], "x.mp4")

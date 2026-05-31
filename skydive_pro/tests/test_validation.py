"""
Tests de la validation post-montage (validate_montage).

Vérifie qu'un montage cassé (sans audio, durée aberrante, fichier absent)
est bien détecté — pour éviter le "faux succès" du postmortem (bug #6).
Les tests nécessitant FFmpeg sont ignorés s'il est absent.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ffmpeg_engine import validate_montage

FFMPEG = shutil.which("ffmpeg")
besoin_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg non installé")


def _gen(path, duree=5, avec_audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", f"testsrc=duration={duree}:size=320x240:rate=30"]
    if avec_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duree}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
    if avec_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return path


def test_fichier_absent():
    r = validate_montage("/tmp/nexiste_pas_12345.mp4", expected_dur=10)
    assert r["ok"] is False
    assert any("ABSENT" in i for i in r["issues"])


@besoin_ffmpeg
def test_montage_complet_ok(tmp_path):
    v = _gen(tmp_path / "ok.mp4", duree=5, avec_audio=True)
    r = validate_montage(v, expected_dur=5.0)
    assert r["ok"] is True
    assert r["has_video"] and r["has_audio"]
    assert r["video_codec"] == "h264"
    assert r["issues"] == []


@besoin_ffmpeg
def test_montage_sans_audio_detecte(tmp_path):
    v = _gen(tmp_path / "muet.mp4", duree=5, avec_audio=False)
    r = validate_montage(v, expected_dur=5.0)
    assert r["ok"] is False
    assert any("AUDIO" in i for i in r["issues"])


@besoin_ffmpeg
def test_duree_aberrante_detectee(tmp_path):
    v = _gen(tmp_path / "court.mp4", duree=2, avec_audio=True)
    # On attend 30s alors que la vidéo fait 2s -> doit lever un problème
    r = validate_montage(v, expected_dur=30.0)
    assert r["ok"] is False
    assert any("duree" in i for i in r["issues"])


@besoin_ffmpeg
def test_duree_dans_tolerance_ok(tmp_path):
    v = _gen(tmp_path / "tol.mp4", duree=5, avec_audio=True)
    # 5s réel vs 6.5s attendu : delta 1.5s < tolérance 3s -> OK
    r = validate_montage(v, expected_dur=6.5)
    assert r["ok"] is True

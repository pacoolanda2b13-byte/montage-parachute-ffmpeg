"""
Fixtures partagées pour les tests.
Génère de vrais clips vidéo via FFmpeg (avec et sans audio).
Les tests sont automatiquement ignorés si FFmpeg n'est pas installé.
"""
import os
import shutil
import subprocess
import sys

import pytest

# Rendre le package racine importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FFMPEG = shutil.which("ffmpeg")
besoin_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg non installé")


def _gen_clip(chemin, duree=2, avec_audio=True, source="testsrc"):
    """Génère un petit clip de test."""
    cmd = ["ffmpeg", "-y",
           "-f", "lavfi", "-i", f"{source}=duration={duree}:size=320x240:rate=30"]
    if avec_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duree}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
    if avec_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [chemin]
    subprocess.run(cmd, capture_output=True, check=True)
    return chemin


@pytest.fixture
def clip_avec_audio(tmp_path):
    return _gen_clip(str(tmp_path / "avec_audio.mp4"), avec_audio=True)


@pytest.fixture
def clip_muet(tmp_path):
    return _gen_clip(str(tmp_path / "muet.mp4"), avec_audio=False, source="smptebars")


@pytest.fixture
def deux_clips(tmp_path):
    a = _gen_clip(str(tmp_path / "a.mp4"), avec_audio=True, source="testsrc")
    b = _gen_clip(str(tmp_path / "b.mp4"), avec_audio=True, source="testsrc2")
    return [a, b]

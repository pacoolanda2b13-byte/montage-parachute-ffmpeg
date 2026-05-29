"""Tests de l'orchestrateur tout-en-un (monter.py)."""
import os

import pytest

from conftest import besoin_ffmpeg, _gen_clip
import monter


def test_tri_naturel(tmp_path):
    # Crée des fichiers vides ; on ne teste que l'ordre, pas le contenu.
    for nom in ["clip10.mp4", "clip1.mp4", "clip2.mp4", "autre.txt"]:
        (tmp_path / nom).write_text("x")
    videos = monter.trouver_videos(str(tmp_path))
    bases = [os.path.basename(v) for v in videos]
    assert bases == ["clip1.mp4", "clip2.mp4", "clip10.mp4"]  # 10 après 2
    assert "autre.txt" not in bases  # les non-vidéos sont ignorées


def test_dossier_inexistant():
    with pytest.raises(NotADirectoryError):
        monter.trouver_videos("/chemin/qui/nexiste/pas")


def test_transitions_nombre_correct():
    # 4 clips => 3 coupures => 3 transitions
    t = monter.transitions_pour("dynamique", 4)
    assert len(t) == 3
    assert all(x in monter.TRANSITIONS for x in t)


def test_transitions_un_seul_clip():
    assert monter.transitions_pour("dynamique", 1) == []


def test_style_cinematique_que_des_fondus():
    t = monter.transitions_pour("cinematique", 10)
    assert set(t).issubset({"fade", "dissolve", "fadeblack"})


@besoin_ffmpeg
def test_montage_complet_via_orchestrateur(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _gen_clip(str(src / "clip1.mp4"))
    _gen_clip(str(src / "clip2.mp4"), source="testsrc2")
    sortie = str(tmp_path / "resultat.mp4")
    code = monter.main([str(src), "-o", sortie,
                        "--duree-clip", "2", "--duree-transition", "0.5"])
    assert code == 0
    assert os.path.isfile(sortie)

"""Tests de l'API Flask (sécurité des chemins, routes, montage réel)."""
import importlib
import os
import shutil

import pytest

from conftest import besoin_ffmpeg, _gen_clip


@pytest.fixture
def api(tmp_path, monkeypatch):
    """
    Recharge le module serveur_api avec des dossiers temporaires
    et l'authentification désactivée.
    """
    sources = tmp_path / "sources"
    sortie = tmp_path / "output"
    sources.mkdir()
    sortie.mkdir()
    monkeypatch.setenv("DOSSIER_SOURCES", str(sources))
    monkeypatch.setenv("DOSSIER_SORTIE", str(sortie))
    monkeypatch.setenv("API_KEY", "")
    import serveur_api
    importlib.reload(serveur_api)
    serveur_api.app.config.update(TESTING=True)
    client = serveur_api.app.test_client()
    return client, str(sources), str(sortie)


def test_effets(api):
    client, _, _ = api
    r = client.get("/effets")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] > 40
    assert "fade" in data["transitions"]


def test_montage_sans_fichiers(api):
    client, _, _ = api
    r = client.post("/montage", json={})
    assert r.status_code == 400


def test_montage_rejette_chemin_absolu(api):
    client, _, _ = api
    r = client.post("/montage", json={"fichiers": ["/etc/passwd"]})
    assert r.status_code == 400
    assert "autoris" in r.get_json()["erreur"].lower() or \
           "invalide" in r.get_json()["erreur"].lower()


def test_montage_rejette_traversee(api):
    client, _, _ = api
    r = client.post("/montage", json={"fichiers": ["../../etc/passwd"]})
    assert r.status_code == 400


def test_montage_fichier_introuvable(api):
    client, _, _ = api
    r = client.post("/montage", json={"fichiers": ["inexistant.mp4"]})
    assert r.status_code == 404


@besoin_ffmpeg
def test_sante_ok(api):
    client, _, _ = api
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.get_json()["statut"] == "ok"


@besoin_ffmpeg
def test_montage_complet_synchrone(api):
    client, sources, sortie = api
    _gen_clip(os.path.join(sources, "c1.mp4"))
    _gen_clip(os.path.join(sources, "c2.mp4"), source="testsrc2")
    r = client.post("/montage", json={
        "fichiers": ["c1.mp4", "c2.mp4"],
        "nom_sortie": "resultat.mp4",
        "transitions": ["fade"],
        "attendre": True,
        "config": {"duree_clip": 2, "duree_transition": 0.5, "resolution": "320x240"},
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["statut"] == "termine"
    assert os.path.isfile(data["fichier"])


def test_upload_et_nettoyage(api, tmp_path):
    client, sources, _ = api
    # upload
    import io
    r = client.post("/upload", data={
        "fichier": (io.BytesIO(b"contenu factice"), "video.mp4"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert os.path.isfile(os.path.join(sources, "video.mp4"))
    # nettoyage
    r = client.post("/nettoyer")
    assert r.status_code == 200
    assert r.get_json()["supprimes"] >= 1

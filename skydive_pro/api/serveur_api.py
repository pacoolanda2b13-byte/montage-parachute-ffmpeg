"""
serveur_api.py — SkyDive Pro API (v0 démo)

Serveur Flask minimal pour démontrer l'interface et la vision avant
l'implémentation des modules IA.

Routes :
    GET  /                 → Dashboard staff dropzone
    GET  /sante            → Health-check JSON
    GET  /api/config       → Config active (branding, scènes, etc.)
    GET  /api/demo/jobs    → Jobs fictifs pour démo
    POST /api/upload       → (mock) Upload d'une vidéo brute

Lancement :
    cd skydive_pro
    python api/serveur_api.py
"""

import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.logger import get_logger
log = get_logger(__name__)

try:
    from dotenv import load_dotenv
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    log.warning("python-dotenv non installé — .env ignoré")

try:
    import yaml
except ImportError:
    yaml = None
    log.warning("pyyaml non installé — config.yaml ignoré")


app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "ui" / "templates"),
    static_folder=str(BASE_DIR / "ui" / "static"),
)

HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
PORT = int(os.environ.get("FLASK_PORT", 5000))
DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
CONFIG = {}
if yaml:
    cfg_file = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_PATH.parent / "config.yaml.example"
    if cfg_file.exists():
        with open(cfg_file, encoding="utf-8") as f:
            CONFIG = yaml.safe_load(f) or {}


def mock_jobs():
    """Jobs fictifs pour démontrer le dashboard."""
    now = datetime.now()
    return [
        {
            "id": "job-001",
            "passager": "Marie Dubois",
            "date_saut": (now - timedelta(minutes=15)).strftime("%H:%M"),
            "statut": "termine",
            "altitude_max_m": 4050,
            "vitesse_max_kmh": 212,
            "duree_chute_s": 58,
            "email_envoye": True,
        },
        {
            "id": "job-002",
            "passager": "Paul Martin",
            "date_saut": (now - timedelta(minutes=8)).strftime("%H:%M"),
            "statut": "en_cours",
            "etape": "Détection émotions au sol",
            "progression": 72,
        },
        {
            "id": "job-003",
            "passager": "Sarah Leroy",
            "date_saut": (now - timedelta(minutes=3)).strftime("%H:%M"),
            "statut": "en_cours",
            "etape": "Extraction télémétrie GoPro",
            "progression": 15,
        },
        {
            "id": "job-004",
            "passager": "Antoine Garcia",
            "date_saut": (now - timedelta(hours=2)).strftime("%H:%M"),
            "statut": "termine",
            "altitude_max_m": 3980,
            "vitesse_max_kmh": 208,
            "duree_chute_s": 55,
            "email_envoye": True,
        },
        {
            "id": "job-005",
            "passager": "Julie Bernard",
            "date_saut": (now - timedelta(hours=3)).strftime("%H:%M"),
            "statut": "termine",
            "altitude_max_m": 4100,
            "vitesse_max_kmh": 219,
            "duree_chute_s": 61,
            "email_envoye": True,
        },
    ]


@app.route("/")
def index():
    branding = CONFIG.get("branding", {}) or {}
    scenes = [s["nom"] for s in (CONFIG.get("structure", {}) or {}).get("scenes", [])]
    return render_template(
        "dashboard.html",
        branding=branding,
        scenes=scenes,
        jobs=mock_jobs(),
        version="0.1.0-demo",
    )


@app.route("/sante")
def sante():
    import shutil as _sh
    ffmpeg_ok = _sh.which("ffmpeg") is not None
    return jsonify({
        "statut": "ok" if ffmpeg_ok else "degraded",
        "version": "0.1.0-demo",
        "ffmpeg": "disponible" if ffmpeg_ok else "introuvable",
        "config_chargee": bool(CONFIG),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/config")
def api_config():
    return jsonify({
        "branding": CONFIG.get("branding", {}),
        "montage": CONFIG.get("montage", {}),
        "structure_scenes": [s["nom"] for s in (CONFIG.get("structure", {}) or {}).get("scenes", [])],
    })


@app.route("/api/demo/jobs")
def api_demo_jobs():
    return jsonify({"jobs": mock_jobs()})


JOBS_STATE: dict = {}
_JOBS_LOCK = threading.Lock()


def _update_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        state = JOBS_STATE.setdefault(job_id, {})
        state.update(fields)


def _get_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        state = JOBS_STATE.get(job_id)
        return dict(state) if state else None


@app.route("/api/nouveau-saut", methods=["POST"])
def api_nouveau_saut():
    """Enregistre un nouveau saut + lance le pipeline IA en arrière-plan."""
    from werkzeug.utils import secure_filename
    import threading
    import uuid

    prenom = request.form.get("prenom", "").strip()
    nom = request.form.get("nom", "").strip()
    email = request.form.get("email", "").strip()
    date_saut = request.form.get("date_saut", "").strip()
    moniteur = request.form.get("moniteur", "").strip()
    telephone = request.form.get("telephone", "").strip()

    if not (prenom and nom and email and date_saut):
        return jsonify({"erreur": "Champs obligatoires manquants"}), 400

    video = request.files.get("video")
    if not video or not video.filename:
        return jsonify({"erreur": "Vidéo manquante"}), 400

    sources_dir = BASE_DIR / "sources"
    sources_dir.mkdir(exist_ok=True)
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    safe_name = secure_filename(f"{job_id}_{video.filename}")
    dest = sources_dir / safe_name

    try:
        video.save(str(dest))
        taille_mb = dest.stat().st_size / (1024 * 1024)
    except Exception as e:
        return jsonify({"erreur": f"Erreur sauvegarde : {e}"}), 500

    # État initial — thread-safe
    _update_job(job_id,
                 statut="en_cours",
                 etape="Enregistrement terminé, démarrage pipeline...",
                 progression=0,
                 passager=f"{prenom} {nom}",
                 email=email,
                 date_saut=date_saut,
                 moniteur=moniteur,
                 fichier_source=safe_name,
                 taille_mb=round(taille_mb, 1))

    # Lancer le pipeline en arrière-plan (non-bloquant)
    def run_pipeline():
        try:
            from agent.pipeline import process_jump
            import traceback as _tb
            branding = CONFIG.get("branding", {}) or {}
            _update_job(job_id, etape="Extraction télémétrie GoPro",
                         progression=10)

            logo = branding.get("logo")
            logo_path = BASE_DIR / logo if logo else None
            music_cfg = (CONFIG.get("musique", {}) or {}).get("piste_defaut")
            music_path = BASE_DIR / music_cfg if music_cfg else None

            result = process_jump(
                video_path=dest,
                nom_passager=f"{prenom} {nom}",
                email_client=email,
                date_saut=date_saut,
                job_id=job_id,
                moniteur=moniteur,
                dropzone_nom=branding.get("nom", ""),
                dropzone_site=branding.get("site_web", ""),
                logo_path=logo_path if logo_path and logo_path.exists() else None,
                music_path=music_path if music_path and music_path.exists() else None,
                output_dir=BASE_DIR / "output",
            )
            _update_job(job_id,
                         statut=result.statut,
                         etape="Terminé" if result.statut == "succes" else "Erreur",
                         progression=100,
                         resultat=result.to_dict())
        except Exception as e:
            log.exception("[%s] Pipeline exception non gérée", job_id)
            _update_job(job_id,
                         statut="echec",
                         etape=f"Erreur : {e}",
                         progression=0,
                         traceback=_tb.format_exc())

    threading.Thread(target=run_pipeline, daemon=True).start()

    return jsonify({
        "job_id": job_id,
        "statut": "en_cours",
        "message": "Pipeline IA lancé en arrière-plan.",
        "passager": f"{prenom} {nom}",
        "fichier": safe_name,
        "taille_mb": round(taille_mb, 1),
    }), 202


@app.route("/api/job/<job_id>")
def api_job_status(job_id: str):
    """Retourne l'état d'un job en cours (lecture thread-safe)."""
    state = _get_job(job_id)
    if not state:
        return jsonify({"erreur": "Job introuvable"}), 404
    return jsonify({"job_id": job_id, **state})


@app.route("/output/<filename>")
def output_file(filename: str):
    """Sert les montages finaux depuis output/.

    Utilise le converter Flask par défaut (sans path:) pour interdire les
    slashes et une validation supplémentaire contre path traversal.
    """
    from flask import send_from_directory, abort

    # Rejeter toute tentative de path traversal (Windows + Unix)
    if "/" in filename or "\\" in filename or ".." in filename \
            or filename.startswith("."):
        log.warning("Tentative de path traversal bloquée: %r", filename)
        abort(400)

    target = (BASE_DIR / "output" / filename).resolve()
    try:
        target.relative_to((BASE_DIR / "output").resolve())
    except ValueError:
        log.warning("Chemin hors du dossier output bloqué: %r", filename)
        abort(400)

    if not target.is_file():
        abort(404)

    return send_from_directory(BASE_DIR / "output", filename,
                                 as_attachment=False)


if __name__ == "__main__":
    print("=" * 60)
    print(f"[SkyDive Pro] Serveur demo")
    print(f"  Ecoute       : http://{HOST}:{PORT}")
    print(f"  Dashboard    : http://{HOST}:{PORT}/")
    print(f"  Health-check : http://{HOST}:{PORT}/sante")
    print("=" * 60)
    app.run(host=HOST, port=PORT, debug=DEBUG)

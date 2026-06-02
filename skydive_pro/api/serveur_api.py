"""
serveur_api.py — SkyDive Pro API v2

Serveur Flask avec persistance SQLite et pipeline multi-fichiers.

Routes :
    GET  /                        → Dashboard staff dropzone
    GET  /sante                   → Health-check JSON
    GET  /api/config              → Config active
    POST /api/nouveau-saut        → Upload fichier unique + pipeline
    POST /api/nouveau-saut-folder → Import dossier rushs + pipeline multi-fichiers
    POST /api/import-url          → Import depuis URL + pipeline
    GET  /api/job/<job_id>        → Statut d'un job
    GET  /api/jobs                → Liste des jobs récents
    GET  /output/<filename>       → Servir les montages finaux

Lancement :
    cd skydive_pro
    python api/serveur_api.py
"""

import json as _json
import os
import sys
import threading
import traceback as _tb
import uuid
from datetime import datetime
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

from db.models import (
    init_db, get_or_create_client, create_saut, update_saut,
    get_saut, list_sauts, saut_to_dict,
)

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


def _branding_paths():
    branding = CONFIG.get("branding", {}) or {}
    logo = branding.get("logo")
    logo_path = BASE_DIR / logo if logo else None
    music_cfg = (CONFIG.get("musique", {}) or {}).get("piste_defaut")
    music_path = BASE_DIR / music_cfg if music_cfg else None
    return branding, logo_path, music_path


# ══════════════════════════════════════════════════════════════
#  Routes
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    branding = CONFIG.get("branding", {}) or {}
    scenes = [s["nom"] for s in (CONFIG.get("structure", {}) or {}).get("scenes", [])]
    # Vrais jobs depuis la DB
    sauts = list_sauts(limit=20)
    jobs = []
    for s in sauts:
        d = saut_to_dict(s)
        # Adapter pour le template existant
        d["passager"] = f"{s.client.prenom} {s.client.nom}" if s.client else "?"
        d["statut"] = "termine" if s.statut == "succes" else s.statut
        jobs.append(d)
    return render_template(
        "dashboard.html",
        branding=branding,
        scenes=scenes,
        jobs=jobs,
        version="2.0.0",
    )


@app.route("/sante")
def sante():
    import shutil as _sh
    ffmpeg_ok = _sh.which("ffmpeg") is not None
    return jsonify({
        "statut": "ok" if ffmpeg_ok else "degraded",
        "version": "2.0.0",
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


@app.route("/api/jobs")
def api_jobs():
    limit = request.args.get("limit", 50, type=int)
    statut = request.args.get("statut")
    sauts = list_sauts(limit=limit, statut=statut)
    return jsonify({"jobs": [saut_to_dict(s) for s in sauts]})


@app.route("/api/templates")
def api_templates():
    from core.templates import list_templates
    return jsonify({"templates": list_templates()})


# ── Upload fichier unique ────────────────────────────────────

@app.route("/api/nouveau-saut", methods=["POST"])
def api_nouveau_saut():
    from werkzeug.utils import secure_filename

    prenom = request.form.get("prenom", "").strip()
    nom = request.form.get("nom", "").strip()
    email = request.form.get("email", "").strip()
    date_saut = request.form.get("date_saut", "").strip()
    moniteur = request.form.get("moniteur", "").strip()
    telephone = request.form.get("telephone", "").strip()
    lieu = request.form.get("lieu", "").strip()

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
    except Exception as e:
        return jsonify({"erreur": f"Erreur sauvegarde : {e}"}), 500

    # DB
    client = get_or_create_client(prenom, nom, email, telephone)
    create_saut(job_id=job_id, client_id=client.id, date_saut=date_saut,
                lieu=lieu, moniteur=moniteur, statut="en_cours",
                etape="Enregistrement terminé, démarrage pipeline...")

    def run_pipeline():
        try:
            from agent.pipeline import process_jump
            branding, logo_path, music_path = _branding_paths()
            update_saut(job_id, etape="Extraction télémétrie GoPro", progression=10)

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
            update_saut(job_id,
                        statut=result.statut,
                        etape="Terminé" if result.statut == "succes" else "Erreur",
                        progression=100,
                        fichier_montage=result.fichier_montage,
                        taille_montage_mb=result.taille_montage_mb,
                        duree_traitement_s=result.duree_traitement_s,
                        altitude_max_m=result.analyse_telemetrie.get("altitude_max_m"),
                        vitesse_max_kmh=result.analyse_telemetrie.get("vitesse_max_kmh"),
                        duree_chute_s=result.analyse_telemetrie.get("duree_chute_libre_s"),
                        erreurs=_json.dumps(result.erreurs) if result.erreurs else None)
        except Exception as e:
            log.exception("[%s] Pipeline exception", job_id)
            update_saut(job_id, statut="echec", etape=f"Erreur : {e}",
                        progression=0, erreurs=_json.dumps([str(e)]))

    threading.Thread(target=run_pipeline, daemon=True).start()
    return jsonify({"job_id": job_id, "statut": "en_cours",
                    "message": "Pipeline lancé."}), 202


# ── Upload dossier multi-fichiers ────────────────────────────

@app.route("/api/nouveau-saut-folder", methods=["POST"])
def api_nouveau_saut_folder():
    """Reçoit un chemin de dossier local (JSON) et lance le pipeline multi-fichiers."""
    data = request.get_json(silent=True) or {}
    folder = (data.get("folder") or "").strip()
    prenom = (data.get("prenom") or "").strip()
    nom = (data.get("nom") or "").strip()
    email = (data.get("email") or "").strip()
    date_saut = (data.get("date_saut") or "").strip()
    lieu = (data.get("lieu") or "").strip()
    moniteur = (data.get("moniteur") or "").strip()
    telephone = (data.get("telephone") or "").strip()
    template_name = (data.get("template") or "fun_energie").strip()

    if not folder or not Path(folder).is_dir():
        return jsonify({"erreur": "Dossier invalide ou introuvable"}), 400
    if not (prenom and nom and date_saut):
        return jsonify({"erreur": "Champs obligatoires manquants"}), 400

    job_id = f"job-{uuid.uuid4().hex[:8]}"

    client = get_or_create_client(prenom, nom, email, telephone)
    create_saut(job_id=job_id, client_id=client.id, date_saut=date_saut,
                lieu=lieu, moniteur=moniteur, statut="en_cours",
                dossier_source=folder,
                etape="Analyse du dossier de rushs...")

    def run_folder_pipeline():
        try:
            from agent.pipeline import process_folder
            branding, logo_path, music_path = _branding_paths()

            update_saut(job_id, etape="Analyse et ordonnancement des fichiers...",
                        progression=10)

            result = process_folder(
                folder_path=folder,
                nom_passager=f"{prenom} {nom}",
                email_client=email,
                date_saut=date_saut,
                lieu=lieu,
                job_id=job_id,
                moniteur=moniteur,
                dropzone_nom=branding.get("nom", ""),
                dropzone_site=branding.get("site_web", ""),
                logo_path=logo_path if logo_path and logo_path.exists() else None,
                music_path=music_path if music_path and music_path.exists() else None,
                output_dir=BASE_DIR / "output",
                template_name=template_name,
            )
            reels_json = _json.dumps([
                {"type": r.get("type"), "path": str(r.get("path", "")),
                 "duree_s": r.get("duree_s"), "ok": r.get("ok")}
                for r in result.reels
            ]) if result.reels else None

            update_saut(job_id,
                        statut=result.statut,
                        etape="Terminé" if result.statut == "succes" else "Erreur",
                        progression=100,
                        fichier_montage=result.fichier_montage,
                        taille_montage_mb=result.taille_montage_mb,
                        reels=reels_json,
                        duree_traitement_s=result.duree_traitement_s,
                        altitude_max_m=result.analyse_telemetrie.get("altitude_max_m"),
                        vitesse_max_kmh=result.analyse_telemetrie.get("vitesse_max_kmh"),
                        duree_chute_s=result.analyse_telemetrie.get("duree_chute_libre_s"),
                        erreurs=_json.dumps(result.erreurs) if result.erreurs else None)
        except Exception as e:
            log.exception("[%s] Folder pipeline exception", job_id)
            update_saut(job_id, statut="echec", etape=f"Erreur : {e}",
                        progression=0, erreurs=_json.dumps([str(e)]))

    threading.Thread(target=run_folder_pipeline, daemon=True).start()
    return jsonify({"job_id": job_id, "statut": "en_cours",
                    "message": "Pipeline multi-fichiers lancé."}), 202


# ── Import URL ───────────────────────────────────────────────

@app.route("/api/import-url", methods=["POST"])
def api_import_url():
    from werkzeug.utils import secure_filename

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    prenom = (data.get("prenom") or "").strip()
    nom = (data.get("nom") or "").strip()
    email = (data.get("email") or "").strip()
    date_saut = (data.get("date_saut") or "").strip()
    moniteur = (data.get("moniteur") or "").strip()

    if not url:
        return jsonify({"erreur": "URL manquante"}), 400
    if not (prenom and nom and email and date_saut):
        return jsonify({"erreur": "Champs obligatoires manquants"}), 400

    sources_dir = BASE_DIR / "sources"
    sources_dir.mkdir(exist_ok=True)
    job_id = f"job-{uuid.uuid4().hex[:8]}"

    client = get_or_create_client(prenom, nom, email)
    create_saut(job_id=job_id, client_id=client.id, date_saut=date_saut,
                moniteur=moniteur, statut="en_cours",
                etape="Téléchargement de la vidéo...")

    def run_import_and_pipeline():
        try:
            from core.url_importer import import_from_url
            from agent.pipeline import process_jump
            branding, logo_path, music_path = _branding_paths()

            safe_name = secure_filename(f"{job_id}_saut")
            imp = import_from_url(url, sources_dir, nom_fichier=safe_name)
            update_saut(job_id, etape=f"Téléchargé ({imp.taille_mb:.1f} MB)...",
                        progression=15)

            result = process_jump(
                video_path=imp.path,
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
            update_saut(job_id,
                        statut=result.statut,
                        etape="Terminé" if result.statut == "succes" else "Erreur",
                        progression=100,
                        fichier_montage=result.fichier_montage,
                        taille_montage_mb=result.taille_montage_mb,
                        duree_traitement_s=result.duree_traitement_s,
                        erreurs=_json.dumps(result.erreurs) if result.erreurs else None)
        except Exception as e:
            log.exception("[%s] Import+Pipeline exception", job_id)
            update_saut(job_id, statut="echec", etape=f"Erreur : {e}",
                        progression=0, erreurs=_json.dumps([str(e)]))

    threading.Thread(target=run_import_and_pipeline, daemon=True).start()
    return jsonify({"job_id": job_id, "statut": "en_cours",
                    "message": "Téléchargement et pipeline lancés."}), 202


# ── Job status ───────────────────────────────────────────────

@app.route("/api/job/<job_id>")
def api_job_status(job_id: str):
    saut = get_saut(job_id)
    if not saut:
        return jsonify({"erreur": "Job introuvable"}), 404
    return jsonify({"job_id": job_id, **saut_to_dict(saut)})


# ── Servir les fichiers output ───────────────────────────────

@app.route("/output/<filename>")
def output_file(filename: str):
    from flask import send_from_directory, abort

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
    print(f"[SkyDive Pro] Serveur v2.0")
    print(f"  Ecoute       : http://{HOST}:{PORT}")
    print(f"  Dashboard    : http://{HOST}:{PORT}/")
    print(f"  Health-check : http://{HOST}:{PORT}/sante")
    print("=" * 60)
    app.run(host=HOST, port=PORT, debug=DEBUG)

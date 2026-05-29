"""
serveur_api.py
API Flask pour déclencher les montages parachutisme depuis N8N ou tout client HTTP.

Routes :
  GET  /effets              — liste toutes les transitions disponibles
  POST /montage             — crée un montage vidéo
  GET  /sante               — health-check

Dépendances : flask (pip install flask) + FFmpeg installé sur le système.
"""

import os
import uuid
import glob
import hmac
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename

from montage_parachute_ffmpeg import creer_montage, TRANSITIONS, verifier_ffmpeg

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB max upload

# Dossier où les vidéos sources sont attendues
DOSSIER_SOURCES = os.environ.get("DOSSIER_SOURCES", "./sources")
# Dossier de sortie des montages
DOSSIER_SORTIE = os.environ.get("DOSSIER_SORTIE", "./output")
# Clé API simple (optionnelle — laisser vide pour désactiver)
API_KEY = os.environ.get("API_KEY", "")
# Nombre maximum de montages exécutés simultanément (évite la saturation CPU).
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
# Nombre maximum de jobs conservés en mémoire (évite la fuite mémoire).
MAX_JOBS = int(os.environ.get("MAX_JOBS", "200"))

os.makedirs(DOSSIER_SOURCES, exist_ok=True)
os.makedirs(DOSSIER_SORTIE, exist_ok=True)

# Suivi des jobs en cours (en mémoire — suffisant pour usage solo/N8N).
# Protégé par un verrou car manipulé depuis plusieurs threads.
jobs = {}
jobs_lock = threading.Lock()
# Limite le nombre de montages FFmpeg concurrents.
montage_semaphore = threading.Semaphore(MAX_CONCURRENT)


def _purger_jobs():
    """Conserve uniquement les MAX_JOBS jobs les plus récents (anti-fuite mémoire)."""
    if len(jobs) <= MAX_JOBS:
        return
    # Tri par date de création ; on supprime les plus anciens.
    anciens = sorted(jobs.items(), key=lambda kv: kv[1].get("cree_le", ""))
    for job_id, _ in anciens[:len(jobs) - MAX_JOBS]:
        jobs.pop(job_id, None)


def verif_api_key():
    """Vérifie la clé API si elle est configurée (comparaison en temps constant)."""
    if not API_KEY:
        return None
    key = request.headers.get("X-API-Key") or request.args.get("api_key") or ""
    if not hmac.compare_digest(key, API_KEY):
        return jsonify({"erreur": "Clé API invalide"}), 401
    return None


# ─────────────────────────────────────────────
#  GET /sante
# ─────────────────────────────────────────────
@app.route("/sante", methods=["GET"])
def sante():
    """Health-check : vérifie que Flask et FFmpeg sont opérationnels."""
    try:
        verifier_ffmpeg()
        return jsonify({"statut": "ok", "ffmpeg": "disponible"}), 200
    except RuntimeError as e:
        return jsonify({"statut": "erreur", "detail": str(e)}), 500


# ─────────────────────────────────────────────
#  GET /effets
# ─────────────────────────────────────────────
@app.route("/effets", methods=["GET"])
def liste_effets():
    """
    Retourne la liste de toutes les transitions disponibles.
    Pratique depuis N8N pour peupler dynamiquement un menu.
    """
    err = verif_api_key()
    if err:
        return err

    return jsonify({
        "total": len(TRANSITIONS),
        "transitions": TRANSITIONS,
        "categories": {
            "fondu": ["fade", "fadeblack", "fadewhite", "dissolve"],
            "balayage": ["wipeleft", "wiperight", "wipeup", "wipedown"],
            "glissement": ["slideleft", "slideright", "slideup", "slidedown"],
            "cercle": ["circleopen", "circleclose", "circlecrop"],
            "couverture": ["coverleft", "coverright", "coverup", "coverdown"],
            "revelation": ["revealleft", "revealright", "revealup", "revealdown"],
            "diagonal": ["diagtl", "diagtr", "diagbl", "diagbr"],
            "autre": ["radial", "zoomin", "pixelize", "distance",
                      "squeezev", "squeezeh", "rectcrop"],
        }
    })


# ─────────────────────────────────────────────
#  POST /montage
# ─────────────────────────────────────────────
@app.route("/montage", methods=["POST"])
def creer_montage_route():
    """
    Crée un montage vidéo.

    Body JSON attendu :
    {
        "fichiers": ["clip1.mp4", "clip2.mp4", ...],   // noms dans DOSSIER_SOURCES
                                                          // OU chemins absolus
        "nom_sortie": "mon_montage.mp4",               // optionnel
        "transitions": ["fade", "wipeleft"],           // optionnel
        "config": {                                    // optionnel — surcharge CONFIG
            "encodeur": "libx264",
            "crf": 23,
            "resolution": "1920x1080",
            "fps": 30,
            "duree_clip": 5,
            "duree_transition": 1.0,
            "preset": "fast"
        }
    }

    Réponse immédiate (job asynchrone) :
    {
        "job_id": "uuid",
        "statut": "en_cours",
        "message": "Montage démarré"
    }

    Ou réponse synchrone si "attendre": true dans le body.
    """
    err = verif_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    fichiers_raw = data.get("fichiers", [])
    if not fichiers_raw:
        return jsonify({"erreur": "Le champ 'fichiers' est obligatoire (liste non vide)."}), 400

    # Résolution des chemins — strictement confinée à DOSSIER_SOURCES.
    # On rejette les chemins absolus et les traversées (../) pour empêcher
    # la lecture de fichiers arbitraires sur le serveur.
    base_sources = os.path.realpath(DOSSIER_SOURCES)
    fichiers_video = []
    for f in fichiers_raw:
        nom = Path(str(f)).name  # ne garde que le nom de fichier
        if not nom or nom != str(f):
            return jsonify({
                "erreur": f"Nom de fichier invalide : '{f}'. "
                          "Seuls les fichiers du dossier sources sont autorisés."
            }), 400
        chemin = os.path.realpath(os.path.join(base_sources, nom))
        if os.path.commonpath([base_sources, chemin]) != base_sources:
            return jsonify({"erreur": f"Chemin non autorisé : '{f}'"}), 400
        if not os.path.isfile(chemin):
            return jsonify({"erreur": f"Fichier introuvable : {nom}"}), 404
        fichiers_video.append(chemin)

    # Nom de sortie avec date automatique
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    nom_sortie = data.get("nom_sortie") or f"montage_parachute_{date_str}.mp4"
    if not nom_sortie.endswith(".mp4"):
        nom_sortie += ".mp4"
    transitions = data.get("transitions") or None
    cfg = data.get("config") or {}
    cfg["dossier_sortie"] = DOSSIER_SORTIE

    attendre = data.get("attendre", False)

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"statut": "en_cours", "fichier": None, "erreur": None,
                        "cree_le": datetime.now().strftime("%Y%m%d_%H%M%S_%f")}
        _purger_jobs()

    def executer():
        # Le sémaphore borne le nombre de montages FFmpeg simultanés.
        with montage_semaphore:
            try:
                chemin_final = creer_montage(fichiers_video, nom_sortie, transitions, cfg)
                with jobs_lock:
                    jobs[job_id]["statut"] = "termine"
                    jobs[job_id]["fichier"] = chemin_final
            except Exception as e:
                with jobs_lock:
                    jobs[job_id]["statut"] = "erreur"
                    jobs[job_id]["erreur"] = str(e)

    if attendre:
        executer()
        job = jobs[job_id]
        if job["statut"] == "erreur":
            return jsonify({"erreur": job["erreur"]}), 500
        return jsonify({
            "statut": "termine",
            "job_id": job_id,
            "fichier": job["fichier"],
            "nom": nom_sortie,
        }), 200
    else:
        t = threading.Thread(target=executer, daemon=True)
        t.start()
        return jsonify({
            "job_id": job_id,
            "statut": "en_cours",
            "message": f"Montage démarré ({len(fichiers_video)} clips)",
            "verifier_statut": f"/statut/{job_id}",
        }), 202


# ─────────────────────────────────────────────
#  GET /statut/<job_id>
# ─────────────────────────────────────────────
@app.route("/statut/<job_id>", methods=["GET"])
def statut_job(job_id):
    """Retourne le statut d'un job asynchrone."""
    err = verif_api_key()
    if err:
        return err

    job = jobs.get(job_id)
    if not job:
        return jsonify({"erreur": "Job introuvable"}), 404

    return jsonify({"job_id": job_id, **job}), 200


# ─────────────────────────────────────────────
#  GET /telecharger/<nom_fichier>
# ─────────────────────────────────────────────
@app.route("/telecharger/<nom_fichier>", methods=["GET"])
def telecharger(nom_fichier):
    """Télécharge un fichier de sortie depuis le dossier output."""
    err = verif_api_key()
    if err:
        return err

    # Sécurité : interdire les traversées de répertoire
    nom_fichier = Path(nom_fichier).name
    chemin = os.path.join(DOSSIER_SORTIE, nom_fichier)
    if not os.path.exists(chemin):
        return jsonify({"erreur": "Fichier introuvable"}), 404
    return send_file(chemin, as_attachment=True)


# ─────────────────────────────────────────────
#  POST /upload
# ─────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload_fichier():
    """Upload un fichier vidéo dans le dossier sources."""
    err = verif_api_key()
    if err:
        return err

    if "fichier" not in request.files:
        return jsonify({"erreur": "Aucun fichier dans la requête (champ 'fichier')"}), 400

    fichier = request.files["fichier"]
    if fichier.filename == "":
        return jsonify({"erreur": "Nom de fichier vide"}), 400

    nom = secure_filename(fichier.filename)
    chemin = os.path.join(DOSSIER_SOURCES, nom)
    fichier.save(chemin)

    return jsonify({"statut": "ok", "fichier": nom, "chemin": chemin}), 200


# ─────────────────────────────────────────────
#  POST /nettoyer
# ─────────────────────────────────────────────
@app.route("/nettoyer", methods=["POST"])
def nettoyer_sources():
    """Supprime tous les fichiers du dossier sources."""
    err = verif_api_key()
    if err:
        return err

    fichiers = glob.glob(os.path.join(DOSSIER_SOURCES, "*"))
    for f in fichiers:
        os.remove(f)
    return jsonify({"statut": "ok", "supprimes": len(fichiers)}), 200


# ─────────────────────────────────────────────
#  LANCEMENT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"Serveur API Montage Parachute — port {port}")
    print(f"Sources : {os.path.abspath(DOSSIER_SOURCES)}")
    print(f"Sortie  : {os.path.abspath(DOSSIER_SORTIE)}")
    if API_KEY:
        print("Authentification API Key : activée")
    app.run(host="0.0.0.0", port=port, debug=debug)

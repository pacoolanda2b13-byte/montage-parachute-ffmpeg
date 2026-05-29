# Montage Parachute FFmpeg

Pipeline d'automatisation pour assembler des vidéos de parachutisme avec des
transitions FFmpeg (`xfade`), exposé via une API HTTP et orchestrable par N8N.

## Architecture

```
N8N (orchestration)  ──HTTP──▶  API Flask  ──▶  Moteur FFmpeg  ──▶  montage.mp4
   Drive / cron                serveur_api.py   montage_parachute_ffmpeg.py
```

| Composant | Fichier | Rôle |
|---|---|---|
| Moteur | `montage_parachute_ffmpeg.py` | Normalisation des clips, transitions, encodage |
| API | `serveur_api.py` | API HTTP (montage, upload, statut, téléchargement) |
| Orchestration | `n8n_workflow_parachute_ffmpeg.json` | Workflow N8N (Drive → API → Drive → email) |

## Prérequis

- **FFmpeg** installé et accessible (`ffmpeg`, `ffprobe` dans le PATH).
  - Linux : `sudo apt install ffmpeg`
  - macOS : `brew install ffmpeg`
  - Windows : `winget install Gyan.FFmpeg` (la détection gère WinGet automatiquement)
- **Python 3.10+**

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env   # puis ajuster les valeurs
```

## Utilisation

### En ligne de commande

```bash
# Montage simple
python montage_parachute_ffmpeg.py clip1.mp4 clip2.mp4 clip3.mp4 -o sortie.mp4

# Avec transitions choisies
python montage_parachute_ffmpeg.py a.mp4 b.mp4 -t fade circleopen --duree-clip 5

# Lister les transitions disponibles
python montage_parachute_ffmpeg.py --list-transitions
```

> Les clips **muets** (GoPro/drone) sont gérés automatiquement : une piste audio
> silencieuse est injectée pour homogénéiser le montage.

### Via l'API

```bash
python serveur_api.py          # démarre sur le port 5000
```

| Méthode | Route | Description |
|---|---|---|
| GET  | `/sante` | Health-check (Flask + FFmpeg) |
| GET  | `/effets` | Liste des transitions (par catégories) |
| POST | `/upload` | Upload d'une vidéo dans le dossier sources |
| POST | `/montage` | Crée un montage (asynchrone, ou synchrone avec `"attendre": true`) |
| GET  | `/statut/<job_id>` | Statut d'un job asynchrone |
| GET  | `/telecharger/<nom>` | Télécharge un montage produit |
| POST | `/nettoyer` | Vide le dossier sources |

Exemple :

```bash
curl -X POST http://localhost:5000/montage \
  -H "Content-Type: application/json" \
  -d '{
    "fichiers": ["saut1.mp4", "saut2.mp4"],
    "transitions": ["fade", "circleopen"],
    "attendre": true,
    "config": {"resolution": "1920x1080", "fps": 30, "duree_clip": 6}
  }'
```

> **Sécurité** : le champ `fichiers` n'accepte **que** des noms de fichiers
> présents dans `DOSSIER_SOURCES`. Les chemins absolus et les traversées
> (`../`) sont rejetés.

### Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `5000` | Port d'écoute |
| `DEBUG` | `false` | Mode debug Flask |
| `API_KEY` | *(vide)* | Clé API (header `X-API-Key`). Vide = auth désactivée |
| `DOSSIER_SOURCES` | `./sources` | Dossier des vidéos sources |
| `DOSSIER_SORTIE` | `./output` | Dossier des montages produits |
| `MAX_CONCURRENT` | `1` | Montages FFmpeg simultanés (anti-saturation CPU) |
| `MAX_JOBS` | `200` | Jobs conservés en mémoire (anti-fuite) |

## Docker

```bash
docker build -t montage-parachute .
docker run -p 5000:5000 -v $(pwd)/sources:/app/sources -v $(pwd)/output:/app/output montage-parachute
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

Les tests nécessitant FFmpeg sont automatiquement ignorés s'il est absent.

## Orchestration N8N — note de déploiement

Le workflow fourni suppose que **N8N et l'API partagent le même système de
fichiers** (mêmes dossiers `sources`/`output`, p. ex. via un volume Docker
commun) : N8N dépose les vidéos puis appelle `/montage` avec leurs noms.

Si N8N et l'API sont sur des machines **séparées**, il faut, avant l'appel à
`/montage`, envoyer chaque vidéo via la route `/upload` (multipart). Cette
adaptation du workflow est suivie dans [`ROADMAP.md`](./ROADMAP.md) (Phase 1).

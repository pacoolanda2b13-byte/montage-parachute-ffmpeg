# Plan d'action — Consolidation de l'architecture SkyDive Pro

> **Issu de l'ADR-001** (revue complète du package `skydive_pro/`).
> **Horizon :** 3 phases, ~3-4 semaines de travail réel post-démo client.
> **Règle d'or :** on **ne démarre rien** avant la démo client de ce soir. La preuve commerciale d'abord.

---

## Légende

| Priorité | Définition |
|---|---|
| 🔴 **P0** | Bloquant avant 2ᵉ déploiement client |
| 🟠 **P1** | À faire dans le mois suivant le 1er client signé |
| 🟡 **P2** | Qualité / dette — à faire avant 3ᵉ dropzone |

**Estimation effort** : XS (< 30 min) · S (1-3 h) · M (1/2 journée) · L (1 journée) · XL (2+ jours)

---

## Phase 1 — Socle production (semaine +1)

Objectif : rendre le code **installable, testable, redémarrable sans perte**.

### 🔴 T-01 — Transformer en vrai package Python installable — `S`

**Fichiers** : nouveau `pyproject.toml`, supprimer `sys.path.insert` dans `api/serveur_api.py:29`.

**Acceptance**
- [ ] `pip install -e .` fonctionne depuis la racine
- [ ] `from skydive_pro.core.logger import get_logger` fonctionne sans hack
- [ ] `python -m skydive_pro.api.serveur_api` démarre le serveur
- [ ] Les tests (une fois créés) tournent via `pytest` sans config PYTHONPATH

**Détail technique**
```toml
# pyproject.toml
[project]
name = "skydive-pro"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "flask>=3.0", "python-dotenv>=1", "pyyaml>=6", "pydantic>=2.6",
    "moviepy==1.0.3", "ffmpeg-python>=0.2",
    "librosa>=0.10", "soundfile>=0.12", "numpy>=1.26", "scipy>=1.12",
    "opencv-python>=4.9", "Pillow>=10.2",
    "google-generativeai>=0.4",
    "google-api-python-client>=2.120", "google-auth-httplib2>=0.2", "google-auth-oauthlib>=1.2",
    "qrcode[pil]>=7.4",
    "sqlalchemy>=2.0",
    "yt-dlp>=2024.1", "gdown>=5", "requests>=2.31",
    "waitress>=3",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=4", "ruff>=0.3"]

[tool.setuptools.packages.find]
include = ["skydive_pro*"]
```

---

### 🔴 T-02 — Persister les jobs en SQLite — `M`

**Pourquoi** : aujourd'hui `JOBS_STATE` est un dict en RAM → perte totale au redémarrage. Bloquant pour démo multi-jours.

**Fichiers** :
- nouveau `skydive_pro/infra/db.py` (SQLAlchemy engine)
- nouveau `skydive_pro/infra/jobs_repo.py` (CRUD sur table `jobs`)
- modifier `skydive_pro/api/serveur_api.py` → remplacer `_update_job/_get_job` par le repo

**Schema**
```python
class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(16), primary_key=True)      # job-xxxx
    statut = Column(String(16))                     # en_cours | succes | echec | partiel
    etape = Column(String(200))
    progression = Column(Integer, default=0)
    passager = Column(String(200))
    email = Column(String(200))
    date_saut = Column(String(10))
    moniteur = Column(String(100))
    fichier_source = Column(String(300))
    taille_mb = Column(Float)
    resultat_json = Column(Text)                    # PipelineResult.to_dict() sérialisé
    traceback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Acceptance**
- [ ] Table créée au premier démarrage (pas d'Alembic pour l'instant)
- [ ] `_update_job(job_id, **fields)` écrit en DB avec lock SQLite
- [ ] Dashboard affiche les jobs des 7 derniers jours (pas juste ceux en mémoire)
- [ ] Redémarrage serveur → jobs terminés toujours visibles, jobs "en cours" passent à "echec" (reprise non supportée en v1)

---

### 🔴 T-03 — Tests parseur GPMF (critique) — `M`

**Pourquoi** : le parseur binaire KLV est le cœur de la promesse "altitude/vitesse réelles". Une régression silencieuse = client qui voit `4050 m` devenir `0 m`.

**Fichier** : nouveau `skydive_pro/tests/test_telemetry_gopro.py`.

**Fixtures déjà en place** : `tests/fixtures/hero5.mp4`, `hero6.mp4`, `karma.mp4`.

**Tests à écrire**
```python
def test_has_gpmf_stream_hero5():
    assert has_gpmf_stream("tests/fixtures/hero5.mp4") is not None

def test_extract_returns_samples_hero5():
    samples = extract_telemetry("tests/fixtures/hero5.mp4")
    assert len(samples) > 100
    # hero5 filmé à Carlsbad CA : lat ~33.12
    lats = [s.lat for s in samples if s.lat is not None]
    assert 33.0 < sum(lats)/len(lats) < 33.3

def test_no_gpmf_on_regular_mp4(tmp_path):
    # ffmpeg -f lavfi -i color=c=black:s=64x64:d=1 fake.mp4
    fake = tmp_path / "fake.mp4"
    subprocess.run([...], check=True)
    assert has_gpmf_stream(fake) is None

def test_zerodivision_guard_on_uninitialized_scale():
    # SCAL=0 ne doit pas crasher
    ...

def test_analyze_skydive_returns_reasonable_altitude():
    samples = extract_telemetry("tests/fixtures/karma.mp4")
    analysis = analyze_skydive(samples)
    assert 0 <= (analysis.altitude_max_m or 0) <= 10000
```

**Acceptance**
- [ ] `pytest skydive_pro/tests/` vert en local
- [ ] Coverage ≥ 60% sur `telemetry_gopro.py`

---

### 🔴 T-04 — Waitress au lieu du serveur dev Flask — `XS`

**Fichiers** : `setup.ps1`, `setup.sh`, README.

**Commande cible**
```powershell
.\.venv\Scripts\waitress-serve --host=0.0.0.0 --port=5000 --threads=4 skydive_pro.api.serveur_api:app
```

**Acceptance**
- [ ] Ajouter `waitress>=3` dans `pyproject.toml` (fait en T-01)
- [ ] Script de lancement `scripts/serve.ps1` crée
- [ ] README mis à jour : "ne jamais utiliser `python serveur_api.py` en prod"

---

### 🟠 T-05 — Purger les dépendances orphelines — `S`

**Fichiers** : `skydive_pro/requirements.txt` (ou `pyproject.toml` après T-01).

**À retirer** (toutes **inutilisées** dans le code actuel) :
- `gopro-overlay` (remplacée par parseur custom)
- `scenedetect[opencv]` (détection est hybride custom)
- `deepface` (pas utilisée, Python 3.14 incompat)
- `tf-keras` (dépendance de deepface)
- `mediapipe` (pas utilisée, J2c non commencé)
- `anthropic` (fallback non codé)
- `alembic` (pas de migrations pour l'instant)
- `loguru` (on utilise `logging` stdlib via `core/logger.py`)
- `twilio` (SMS pas codé)
- `black` (remplacé par ruff-format)

**Acceptance**
- [ ] `pip install -e .` depuis un venv neuf prend < 90 s (vs 4+ min actuellement)
- [ ] Taille `.venv` < 1 GB (vs ~2.5 GB actuellement)
- [ ] À réintégrer au moment où la fonctionnalité démarre, pas avant

---

## Phase 2 — Scalabilité raisonnable (semaines +2/+3)

Objectif : absorber 10-30 sauts/jour **sans saturer le PC dropzone**.

### 🔴 T-06 — Thread pool borné pour le pipeline — `M`

**Problème actuel**
```python
threading.Thread(target=run_pipeline, daemon=True).start()
```
Si 10 vidéos arrivent en 2 min, 10 ffmpeg concurrents saturent GPU/disque.

**Fix** : `concurrent.futures.ThreadPoolExecutor` global, `max_workers=2` (1 encodeur AMF = 1 GPU).

**Fichier** : nouveau `skydive_pro/infra/queue.py` + refactor des 2 routes dans `serveur_api.py`.

```python
# infra/queue.py
from concurrent.futures import ThreadPoolExecutor
_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("PIPELINE_WORKERS", "2")))
def submit(fn, *args, **kw): return _POOL.submit(fn, *args, **kw)
def shutdown(): _POOL.shutdown(wait=True)
```

**Acceptance**
- [ ] Paramétrable via `.env` : `PIPELINE_WORKERS=2`
- [ ] Job status `"en_attente"` apparaît quand pool saturé
- [ ] Arrêt propre (CTRL+C) termine les jobs en cours

---

### 🟠 T-07 — Auth par API-Key header — `S`

**Pourquoi** : aujourd'hui n'importe qui sur le LAN peut uploader / voir les vidéos.

**Fichier** : nouveau `skydive_pro/api/auth.py` + décorateur `@require_api_key`.

```python
@app.before_request
def check_key():
    if request.path in ("/sante",) or request.method == "GET" and request.path == "/":
        return  # public
    token = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(token, os.getenv("API_KEY", "")):
        abort(401)
```

**Acceptance**
- [ ] `API_KEY` lu depuis `.env`, généré à l'installation
- [ ] Dashboard envoie le header via `fetch` (clé stockée en localStorage au 1er login)
- [ ] Tests manuels : requête sans clé → 401

---

### 🟠 T-08 — Fusion des 2 extractions télémétrie — `XS`

**Fichier** : `agent/pipeline.py` (passer `samples` à `detect_scenes`).

**Diff**
```python
samples = extract_telemetry(video_path)
scenes_result = detect_scenes(video_path, use_vision=use_vision,
                               keyframe_interval=keyframe_interval,
                               samples=samples)  # ← nouveau
```
+ modifier `detect_scenes()` pour accepter `samples: list[TelemetrySample] | None`.

**Gain** : 5-15 s économisées par job selon taille vidéo.

---

### 🟡 T-09 — Rétention automatique des montages — `S`

**Problème** : `output/` grossit indéfiniment → disque plein en 2-3 mois.

**Fichier** : nouveau `scripts/purge_output.py` + tâche Windows planifiée.

```python
# Supprime les .mp4 de output/ > 30 jours
for f in Path("output").glob("*.mp4"):
    if time.time() - f.stat().st_mtime > 30*86400:
        f.unlink()
```

**Acceptance**
- [ ] Script testable à la main
- [ ] Tâche planifiée Windows (setup.ps1 ajoute `schtasks /create /sc daily`)
- [ ] Rétention configurable via `.env` : `OUTPUT_RETENTION_DAYS=30`

---

### 🟡 T-10 — Imports inline hissés en haut de fichier — `XS`

**Fichier** : `api/serveur_api.py` (lignes 180, 226, 279, 310).

**Pourquoi** : lisibilité + éviter les surprises d'import à la première requête.

---

### 🟡 T-11 — CI GitHub Actions — `S`

**Fichier** : nouveau `.github/workflows/ci.yml`.

```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -e ".[dev]"
      - run: ruff check skydive_pro/
      - run: pytest skydive_pro/tests/ -v
```

**Acceptance**
- [ ] Badge CI dans le README
- [ ] PR bloquée si tests rouges

---

## Phase 3 — Refactor structurel (quand 3+ dropzones)

Objectif : préparer l'architecture pour multi-tenant et équipe à 2+ devs.

### 🟡 T-12 — Restructuration domain/adapters/services/infra — `XL`

**Cible** (voir ADR-001 §9) :
```
skydive_pro/
├── domain/    (models, constantes, zéro I/O)
├── adapters/  (gopro_gpmf, ffmpeg, gemini, url_importer, overlays)
├── services/  (scene_service, pipeline_service)
├── infra/     (db, jobs_repo, queue, config)
└── api/
```

**Acceptance**
- [ ] Tests du domaine runnables sans aucun I/O (pas de vidéo sur disque)
- [ ] Les adapters exposent des interfaces (protocols) → testable par mock

**Estimation** : 2 jours de refacto mécanique. À ne lancer **qu'après** T-01 à T-11 validés.

---

### 🟡 T-13 — Dockerfile + compose pour déploiement — `M`

Utile le jour où une dropzone veut héberger en ligne (pas de PC local).

**Cible** : image basée sur `python:3.11-slim-bookworm` + ffmpeg système, pas d'AMF (CPU x264 seul sur serveur cloud).

---

### 🟡 T-14 — Logs structurés JSON + Sentry — `S`

**Fichier** : modifier `core/logger.py`.

Formatter JSON + handler Sentry optionnel (clé dans `.env`). Utile dès 2ᵉ dropzone pour centraliser les erreurs.

---

## Tableau récapitulatif

| # | Titre | Priorité | Effort | Dépend de | Phase |
|---|---|---|---|---|---|
| T-01 | pyproject.toml + package install | 🔴 P0 | S | — | 1 |
| T-02 | SQLite jobs persistence | 🔴 P0 | M | T-01 | 1 |
| T-03 | Tests parseur GPMF | 🔴 P0 | M | T-01 | 1 |
| T-04 | Waitress en prod | 🔴 P0 | XS | T-01 | 1 |
| T-05 | Purge dépendances orphelines | 🟠 P1 | S | T-01 | 1 |
| T-06 | Thread pool borné | 🔴 P0 | M | T-02 | 2 |
| T-07 | Auth API-Key | 🟠 P1 | S | — | 2 |
| T-08 | Fusion extractions télémétrie | 🟠 P1 | XS | — | 2 |
| T-09 | Rétention output auto | 🟡 P2 | S | — | 2 |
| T-10 | Imports hissés | 🟡 P2 | XS | — | 2 |
| T-11 | CI GitHub Actions | 🟡 P2 | S | T-03 | 2 |
| T-12 | Refactor domain/adapters/... | 🟡 P2 | XL | T-01..T-11 | 3 |
| T-13 | Dockerfile | 🟡 P2 | M | T-01 | 3 |
| T-14 | Logs JSON + Sentry | 🟡 P2 | S | — | 3 |

**Total P0 seul : ~2 jours de dev** (T-01 + T-02 + T-03 + T-04 + T-06).
**Phase 1 complète : ~1 semaine** calendrier.

---

## Séquence recommandée (ordre d'exécution)

```
Jour 1 matin   : T-01 (pyproject)         ← débloque tout
Jour 1 après   : T-05 (purge deps)        ← venv propre
Jour 2         : T-02 (SQLite jobs)       ← plus de perte de données
Jour 3         : T-03 (tests GPMF)        ← filet de sécurité
Jour 4 matin   : T-04 (Waitress)          ← prod-ready
Jour 4 après   : T-08 + T-10              ← quick wins
Jour 5         : T-06 (thread pool)       ← scale 10+ sauts/jour

→ À ce stade, le système est OK pour 1 dropzone à 30 sauts/jour.

Semaine +2 : T-07, T-09, T-11
Semaine +3+ : T-12, T-13, T-14 quand besoin réel.
```

---

## Ce qu'on **ne fait pas** (et pourquoi)

| Tentation | Pourquoi on reporte |
|---|---|
| Passer à FastAPI | Coût migration > bénéfice tant qu'on a < 100 req/s |
| Celery + Redis | Ajoute une dépendance système (Redis). ThreadPool suffit jusqu'à 3+ dropzones |
| Postgres | SQLite gère 1000 écritures/s. Suffisant pour 30 sauts/jour pendant des années |
| Front React séparé | Le dashboard = 1 page vue par 1 user. HTMX suffit si besoin |
| OAuth / multi-user | Staff dropzone unique. API-Key simple suffit |
| Kubernetes | 😅 |

---

## Checklist de validation globale

Quand tout la Phase 1 est faite, on doit pouvoir :

- [ ] Cloner le repo sur une machine neuve et `pip install -e ".[dev]"` en < 2 min
- [ ] Lancer `pytest` et voir ≥ 5 tests verts
- [ ] Démarrer le serveur Waitress, uploader une vidéo, redémarrer le serveur, **voir le job dans le dashboard**
- [ ] Saturer avec 5 uploads simultanés, vérifier que le pool ne fait tourner que 2 ffmpeg
- [ ] Voir le log `skydive_pro.*` dans `logs/skydive_pro.log` (1 ligne par étape)

---

**Dernière mise à jour** : 2026-04-17 — post-ADR-001.

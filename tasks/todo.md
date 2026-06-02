# SkyDive Pro v2 — Plan d'exécution

## Phase 0 — Corrections critiques ✅
- [x] P0.1 Fix GEMINI_MODEL default → `gemini-2.5-flash`
- [x] P0.2 Fix `_cut_clip` encoder hardcodé → paramétré
- [x] P0.3 Unifier requirements.txt + fix `google-genai`
- [x] P0.4 Supprimer fichiers racine obsolètes
- [x] P0.5 pytest passent

## Phase 1 — Multi-fichiers + Ordonnancement ✅
- [x] P1.1 `core/file_sorter.py` : ordonnancement multi-signaux
- [x] P1.2 `core/folder_analyzer.py` : analyse dossier → metadata.json
- [x] P1.3 `pipeline.py` : `process_folder()` orchestrateur N fichiers
- [x] P1.4 `build_montage` adapté multi-source
- [x] P1.5 Tests file_sorter (22 tests)

## Phase 2 — Reels Instagram ✅
- [x] P2.1 `core/reels_generator.py` : 3 templates verticaux
- [x] P2.2 Intégré dans process_folder

## Phase 3 — SQLite + Dashboard réel ✅
- [x] P3.1 `db/models.py` SQLAlchemy + SQLite
- [x] P3.2 `serveur_api.py` refactoré avec DB
- [x] P3.3 Routes folder pipeline + templates API

## Phase 4 — Livraison ✅
- [x] P4.1 `core/delivery.py` : email + QR + page HTML
- [x] P4.2 Intégré dans process_folder

## Phase 5 — Polish ✅
- [x] P5.1 `core/templates.py` : 3 templates (fun_energie, cinema_epique, doux_souvenir)
- [x] P5.2 LUT placeholders (ffmpeg color filters)
- [x] P5.3 Template intégré dans pipeline + API (`template_name` param)
- [x] P5.4 `setup.ps1` + `setup.sh` : installation one-click
- [x] P5.5 Route `/api/templates` pour le frontend

---
## Review finale

### Bilan quantitatif
- **8 nouveaux modules Python** créés
- **~8 500 lignes Python** au total (25 fichiers)
- **43 tests passent** (0 régression)
- **2 scripts d'installation** (Windows + Mac/Linux)
- **3 fichiers LUT** (color grading par template)

### Modules livrés
| Module | Lignes | Rôle |
|---|---|---|
| `core/file_sorter.py` | 700 | Ordonnancement multi-signaux GoPro |
| `core/folder_analyzer.py` | 540 | Analyse dossier → timeline unifiée |
| `core/reels_generator.py` | ~300 | 3 Reels Instagram verticaux |
| `core/delivery.py` | ~250 | Email + QR code + page HTML |
| `core/templates.py` | ~200 | 3 templates de montage |
| `db/models.py` | ~400 | SQLite persistant |
| `api/serveur_api.py` | ~310 | API Flask v2 avec DB |
| `tests/test_file_sorter.py` | ~110 | 22 tests ordonnancement |

### Vérifié
- Tous imports cross-modules OK
- 43/43 pytest passent
- DB se crée automatiquement
- Templates chargent et s'appliquent
- API Flask démarre sans erreur

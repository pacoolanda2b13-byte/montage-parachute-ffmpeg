# CLAUDE.md — Règles du projet SkyDive Pro

> Lisez ce fichier en début de chaque session avant de toucher au code.
> Il consolide les leçons des erreurs passées et fixe les invariants.

---

## 🎯 Mission du projet

SaaS de **montage vidéo automatique** pour dropzones tandem.
**Input** : vidéo GoPro brute (5–15 min, MP4/H.264)
**Output** : montage cinéma 3–5 min, branding intégré, prêt à livrer au passager.
**Coût IA cible** : 0–5 €/mois.

---

## 🚨 Règles d'or apprises douloureusement

### 1. **Ne JAMAIS mélanger 2 sources de positionnement**
**Le bug le plus coûteux de la session 2026-04-28** : on combinait fallback positionnel (zone 0-132s) avec segments Gemini (zone 144-456s) → contenu vidéo qui jumpait dans tous les sens.
**Règle** : une seule stratégie active à la fois. Aujourd'hui = **stratégie POSITIONNELLE pure** (Gemini → marqueurs uniquement, découpe séquentielle dans l'ordre temporel).

### 2. **Hiérarchie des signaux de fiabilité**
1. **Télémétrie GoPro** (altitude max, accel) — précision ±0.1s, source de vérité
2. **Vision Gemini** (classification frames) — précision ±15s, peut se tromper massivement
3. **Heuristiques positionnelles** — fallback uniquement si les 2 ci-dessus indisponibles

Toujours préférer télémétrie quand disponible. Ne JAMAIS faire confiance aveugle à Gemini.

### 3. **`gemini-flash-lite` est moins précis que `flash`**
Quand Gemini-flash est en surcharge 503, le retry tombe sur flash-lite qui classifie souvent 70-80% des frames dans une seule scène (`montee_avion` ou `sous_voile`). Code prévu pour ça : fallback positionnel + log warning si distribution biaisée (`Gemini Q-WARNING`).

### 4. **Toujours valider POST-montage avec ffprobe**
La fonction `build_montage` log maintenant : durée réelle vs attendue, présence audio, codec vidéo. Si écart > 3s ou audio manquant → `WARNING` dans les logs. Ne jamais retourner "succès" silencieux.

### 5. **Tests d'abord, refacto ensuite**
On a perdu ~2h sur des bugs en cascade. Avant tout refacto majeur de `select_best_clips`, lancer `pytest tests/` doit passer.

### 6. **Encodeur AMD AMF + faststart auto obligatoire**
AMF n'écrit pas correctement le moov atom au début. Le pipeline fait toujours un re-mux final `ffmpeg -c copy -movflags +faststart`. Ne pas supprimer.

### 7. **Filtrage altitudes aberrantes**
`extract_telemetry` peut retourner alt = -767m ou 15000m (drift GPS / bug calibration). Toujours filtrer `-100 < alt < 12000` avant d'utiliser pour calculs.

---

## 📐 Architecture actuelle (post-cleanup 2026-04-28)

```
skydive_pro/
├── agent/
│   └── pipeline.py          # Orchestrateur (process_jump)
├── core/
│   ├── telemetry_gopro.py   # Parser GPMF + analyse skydive
│   ├── scene_detector.py    # Gemini + retry/fallback + audio + fusion
│   ├── ffmpeg_engine.py     # Cut/concat/mix + select_best_clips
│   ├── overlay_generator.py # Intro/outro/stats PNG
│   ├── music_sync.py        # Beat detection librosa + transition style
│   ├── url_importer.py      # Import YouTube/WT/Drive/Dropbox
│   └── logger.py
├── api/
│   └── serveur_api.py       # Flask
├── ui/
│   └── templates/dashboard.html
├── tests/
│   ├── test_clip_planning.py    # 8 tests
│   └── test_telemetry.py        # 8 tests
└── assets/
    └── music/ref_audio.m4a   # 125 BPM, 7m27
```

---

## 🔧 Commandes courantes

### Tests
```bash
cd skydive_pro
.venv/Scripts/python.exe -m pytest tests/ -v
```

### Run pipeline en CLI
```bash
.venv/Scripts/python.exe -m agent.pipeline <video.mp4> "Nom Passager"
```

### Smoke test rapide (≈15s)
```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from agent.pipeline import process_jump
r = process_jump('tests/fixtures/karma.mp4', 'Test', use_vision=False,
                  music_path=Path('assets/music/ref_audio.m4a'))
print(r.statut, r.taille_montage_mb, 'MB')
"
```

### Démo client (1 commande)
```powershell
.\demo.ps1 -Long -Passager "Sophie" -Dropzone "Skydive Lyon"
```

---

## 🪂 Seuils télémétrie skydiving (validés)

| Phase | Signal | Seuil |
|---|---|---|
| Chute libre détection | accel_g < 0.5G pendant ≥ 5s | déjà codé |
| Chute_start télémétrie | altitude ≥ 95% alt_max | implémenté |
| Atterrissage | altitude ≤ alt_5e_percentile + 30m | implémenté |
| Vitesse terminale tandem | 50-65 m/s (180-235 km/h) | référence |
| Ouverture parachute | décélération 2-4G sur 1-3s | non utilisé encore |
| Sous voile | descente 4-8 m/s stable | non utilisé encore |

---

## 📊 Modèles Gemini utilisés (Tier 1 payant)

- **Principal** : `gemini-2.5-flash`
- **Fallback 503** : `gemini-2.5-flash-lite` (moins précis, à éviter si possible)
- **À éviter** : `gemini-2.0-flash` (404 sur nouveaux comptes), `gemini-flash-latest` (résout vers preview)

Clé API stockée dans `.env` (gitignored) : `GEMINI_API_KEY=AIzaSy...`
Projet GCP : `SkyDive Pro` (lié à billing My Billing Account, organisation santolanlabs.fr).

---

## 🎬 Durées scènes par défaut (configurables)

| Scène | Durée | Style transition |
|---|---|---|
| Briefing | 10s | fade |
| Embarquement véhicule | 5s | fade |
| Dans l'avion | 10s | fade |
| **Paysage avion (mer/montagne)** | **30s** | fade |
| Montée avion | 5s | fade |
| Sortie d'avion | 30s | **cut sec** ⚡ |
| Chute libre | 90s | **cut sec** ⚡ |
| Sous voile (3 cuts) | 30s | **cut sec** ⚡ |
| Atterrissage | 35s | **cut sec** ⚡ |
| Réaction émotion | 30s | **cut sec** ⚡ |
| Interaction moniteur | 15s | fade |

**Total cible** : ~290s = 4 min 50

---

## 🛡️ Garde-fous de robustesse

1. **Vidéo < 90s** → mode dégradé simple (briefing + chute + atterrissage proportionnels)
2. **Vidéo > 20 min** → adaptive keyframe interval (max 40 frames Gemini = ~10c€ max)
3. **Pas de GPMF** → fallback uniquement Gemini + heuristiques position
4. **Pas d'audio source** → musique seule (pas de mix), log explicite
5. **Pas de musique** → cut secs partout, pas de fade
6. **Faststart auto** → re-mux à la fin, garantit lecture universelle
7. **Validation post-ffprobe** → check durée, audio, codec → log WARNING si KO

---

## 📦 Dépendances clés

```
flask>=3.1
python-dotenv>=1.0
google-genai          # Tier 1 propre (PAS google-generativeai)
librosa>=0.11         # beat detection
opencv-python>=4.9
Pillow>=10.2          # overlays
numpy, scipy
ffmpeg (system)       # 7.x + h264_amf actif sur AMD
ffprobe (system)
pytest                # tests dev
```

---

## 🚫 Anti-patterns interdits

1. **Ne PAS** mélanger fallback positionnel + segments Gemini sans hiérarchie
2. **Ne PAS** ignorer les exceptions FFmpeg silencieusement (toujours log stderr)
3. **Ne PAS** retourner "succès" si validation post échoue
4. **Ne PAS** hardcoder des durées dans les fonctions (utiliser SCENE_DURATIONS_CIBLE)
5. **Ne PAS** faire confiance à `gemini-flash-latest` (preview, quotas séparés)
6. **Ne PAS** supposer que la vidéo a de la télémétrie GPMF
7. **Ne PAS** committer `.env` (clés API)
8. **Ne PAS** patcher sans comprendre la cause profonde (cf. session 2026-04-28)

---

## 📚 Documentation produite

- `README.md` — pitch produit
- `PLAN_EXECUTION.md` — roadmap 7 jalons
- `DEMO_CLIENT.md` — guide démo client
- `docs/POSTMORTEM_2026-04-28.md` — leçons session bugs
- `docs/ADR-002_Vision_Backend.md` — décision Gemini cloud vs local
- `docs/PLAN_ACTION_ARCHI.md` — phase 1 consolidation post-démo
- Vault Obsidian : `Documents/Obsidian Vault/Projets/SkyDive Pro/` (10 notes)

---

## 🆘 Si quelque chose casse

1. Lance `pytest tests/` pour vérifier les invariants
2. Check `git log --oneline -20` pour voir les derniers changements
3. Tag de retour stable : `git checkout demo-safe-2026-04-27`
4. Branche en cours : `chore/demo-prep`

---

**Dernière mise à jour** : 2026-04-28 (refacto post-postmortem)

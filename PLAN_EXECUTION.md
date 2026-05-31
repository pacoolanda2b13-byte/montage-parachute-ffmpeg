# 📋 Plan d'Exécution — SkyDive Pro

**Projet** : Montage vidéo automatique IA pour dropzones tandem
**Repo source** : `pacoolanda2b13-byte/montage-parachute-ffmpeg`
**Machine cible** : Ryzen 7 6800H / 32 GB / iGPU AMD Radeon 680M / Windows 11 Pro
**Stratégie IA** : **Hybride gratuit** → télémétrie + audio + Gemini Free + DeepFace local (fallback Claude optionnel sur scènes ambiguës)
**Coût IA cible** : 0 à 5 €/mois en pleine saison

---

## 🗺️ Vue d'ensemble — 7 jalons

```
┌──────────────────────────────────────────────────────────────────┐
│  J0   : Setup & validation environnement                         │
│  J1   : Extraction télémétrie GoPro (GPMF)                       │
│  J2   : Détection scènes (télémétrie + audio + Gemini Free)      │
│  J2b  : Détection émotions réaction au sol (DeepFace local)      │
│  J2c  : Détection interaction moniteur↔passager (MediaPipe)      │
│  J3   : Overlays brandés (logo, nom, altitude, vitesse)          │
│  J4   : Montage cinéma (musique + sync + LUT + transitions)      │
│  J5   : Dashboard web + base clients                             │
│  J6   : Livraison auto (Gmail + Drive + SMS optionnel)           │
│  J7   : Déploiement client + formation + monitoring              │
└──────────────────────────────────────────────────────────────────┘
```

Chaque jalon est **livrable seul** et **testé** avant de passer au suivant.

---

## ✅ Jalon 0 — Setup & validation environnement

**Objectif** : S'assurer que toute la stack est installée et fonctionne avant d'écrire du code métier.

### Tâches

| # | Tâche | Validation |
|---|---|---|
| 0.1 | Cloner le repo actuel en local sur le PC | `git clone` OK |
| 0.2 | Créer une nouvelle branche `feat/skydive-pro-v2` | `git branch` OK |
| 0.3 | Installer Python 3.11+ (vérifier `python --version`) | Version ≥ 3.11 |
| 0.4 | Installer FFmpeg via winget, vérifier AMF | `ffmpeg -hide_banner -encoders \| grep amf` → liste h264_amf |
| 0.5 | Créer venv Python dédié | `python -m venv .venv` |
| 0.6 | Installer les dépendances actuelles | `pip install -r requirements.txt` |
| 0.7 | Obtenir une clé API Claude (Anthropic) | Clé en main |
| 0.8 | Tester le script actuel avec 2 vidéos | Montage test généré |
| 0.9 | Préparer **1 vidéo tandem test** (15 min, GoPro) | Fichier .mp4 prêt |
| 0.10 | Noter le modèle exact de GoPro | Ex: "Hero 11 Black" |

**Livrable** : environnement fonctionnel + vidéo test + clé API.
**Durée estimée** : 1-2 heures.

---

## 🛰️ Jalon 1 — Extraction télémétrie GoPro

**Objectif** : Lire les données GPMF embarquées dans la vidéo (altitude, vitesse, accéléromètre, GPS).

### Pourquoi c'est la 1ère vraie étape

La télémétrie est un **signal gratuit** qui répond à 50% des besoins de détection de scène **sans aucune IA**. On valide ce pilier avant tout.

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 1.1 | Installer `gopro-overlay` et `gpmf-parser` | `pip install gopro-overlay` |
| 1.2 | Créer `core/telemetry_gopro.py` | Nouveau module |
| 1.3 | Fonction `extract_gpmf(video_path)` | Retourne dict : `{time, altitude, speed, accel, gps}` |
| 1.4 | Fonction `detect_freefall(telemetry)` | Détecte l'intervalle où `accel_vertical ≈ 0` |
| 1.5 | Fonction `detect_canopy(telemetry)` | Détecte l'intervalle sous voile (altitude descend lentement) |
| 1.6 | Fonction `get_stats(telemetry)` | Retourne `{altitude_max, vitesse_max_kmh, duree_chute_s}` |
| 1.7 | Tests unitaires sur la vidéo de test | Pytest → résultats cohérents |
| 1.8 | Commit : `feat(telemetry): GPMF extraction + detection chute libre/voile` | Push |

**Livrable** : fichier JSON pour chaque vidéo avec `{altitude_max: 4100, vitesse_max: 215, duree_chute: 58, timestamps_chute: [60, 118], timestamps_voile: [118, 420]}`.

**Durée estimée** : 4-6 heures.

**Risques** :
- GPMF absent si la GoPro n'a pas activé la télémétrie → fallback : saisie manuelle dans le dashboard.
- Certains modèles GoPro (anciens) ont une précision GPS limitée → gérer avec un filtre de lissage.

---

## 🎬 Jalon 2 — Détection de scènes hybride

**Objectif** : Identifier les 7 scènes clés (briefing, véhicule, avion, sortie, chute, voile, atterrissage).

### Approche en 3 couches

1. **Couche télémétrie** (gratuite, rapide) — gère chute libre + sous voile + atterrissage
2. **Couche audio** (gratuite, rapide) — distingue moteur avion / vent / silence via spectrogramme
3. **Couche Claude Vision** (cloud, 0,01 € par image) — classifie les scènes restantes (briefing, véhicule) sur quelques keyframes

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 2.1 | Installer `scenedetect`, `librosa`, `anthropic` | `pip install ...` |
| 2.2 | Créer `core/scene_detector.py` | Nouveau module |
| 2.3 | Fonction `detect_cuts(video)` via PySceneDetect | Liste des coupes ContentDetector |
| 2.4 | Fonction `analyze_audio(video)` | Retourne labels `[engine, wind, silence, speech]` par seconde |
| 2.5 | Fonction `extract_keyframes(video, every_n_sec=30)` | Liste d'images JPEG compressées |
| 2.6 | Fonction `classify_with_claude(keyframes)` | Appel API Claude Vision → labels par keyframe |
| 2.7 | Prompt système pour Claude dans `agent/prompts/scene_classification.md` | Prompt calibré pour skydive |
| 2.8 | Fonction `merge_signals(telemetry, audio, vision)` | Fusion des 3 couches → timeline finale |
| 2.9 | Tests sur la vidéo réelle | Vérifier visuellement que les scènes sont bien découpées |
| 2.10 | Commit : `feat(scenes): hybrid scene detection (telemetry + audio + Claude Vision)` | Push |

**Livrable** : pour chaque vidéo brute, un fichier `timeline.json` :
```json
[
  {"scene": "briefing", "start": 0, "end": 120},
  {"scene": "vehicule_embarquement", "start": 120, "end": 180},
  {"scene": "montee_avion", "start": 180, "end": 900},
  {"scene": "sortie_avion", "start": 900, "end": 905},
  {"scene": "chute_libre", "start": 905, "end": 963},
  {"scene": "sous_voile", "start": 963, "end": 1265},
  {"scene": "atterrissage", "start": 1265, "end": 1320}
]
```

**Durée estimée** : 1-2 jours.
**Coût API estimé pour les tests** : ~2-5 €.

---

## 😃 Jalon 2b — Détection d'émotions post-atterrissage

**Objectif** : Identifier les 3-5 secondes les plus émotionnelles après l'atterrissage (euphorie, larmes, rire, fierté) pour les mettre en climax de l'outro.

### Pourquoi c'est un jalon à part

C'est le **moment viral** du montage. On veut une pipeline dédiée, **100% locale et gratuite** (pas d'API).

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 2b.1 | Installer `deepface` et `retinaface` | `pip install deepface` (CPU-compatible) |
| 2b.2 | Créer `core/emotion_detector.py` | Nouveau module |
| 2b.3 | Fonction `extract_frames_after_landing(video, timeline)` | Extrait 1 frame/sec entre `atterrissage.end` et `video.end` |
| 2b.4 | Fonction `detect_faces(frame)` | Retourne boxes + landmarks des visages |
| 2b.5 | Fonction `classify_emotions(face_crop)` | `{happy: 0.8, surprised: 0.15, ...}` |
| 2b.6 | Fonction `score_emotional_moments(frames)` | Score composite : joie + surprise × intensité |
| 2b.7 | Fonction `select_best_emotional_clips(scores, n=3, duration=2s)` | Top 3 segments |
| 2b.8 | Test sur vidéos réelles + review humaine | Les moments sélectionnés sont-ils les bons ? |
| 2b.9 | Si qualité insuffisante → fallback Claude Vision | Seulement si nécessaire |
| 2b.10 | Commit : `feat(emotion): local face emotion detection for outro climax` | Push |

**Livrable** : pour chaque vidéo, un fichier `emotional_moments.json` :
```json
[
  {"start": 1320, "end": 1322, "dominant": "happy", "intensity": 0.92, "reason": "euphoric smile + arms up"},
  {"start": 1335, "end": 1337, "dominant": "surprised", "intensity": 0.88, "reason": "shocked expression + laughter"},
  {"start": 1345, "end": 1347, "dominant": "happy", "intensity": 0.85, "reason": "hug with instructor"}
]
```

**Durée estimée** : 1 jour.
**Coût API** : **0 €** (tout en local via DeepFace).

**Risques** :
- DeepFace peut être lent sur CPU (~2-3s par frame). Mitigation : n'analyser qu'1 frame/seconde.
- Si le visage du passager est caché par le casque → fallback sur le visage du moniteur ou analyse audio (rires).

---

## 🤝 Jalon 2c — Détection d'interaction moniteur ↔ passager

**Objectif** : Identifier les moments de complicité entre le moniteur et le passager après atterrissage (high-five, check, accolade, bras levés, rires partagés).

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 2c.1 | Installer `mediapipe` | `pip install mediapipe` (CPU-compatible, open source Google) |
| 2c.2 | Créer `core/interaction_detector.py` | Nouveau module |
| 2c.3 | Fonction `detect_poses(frame)` | Retourne 33 landmarks par personne (max 2 personnes) |
| 2c.4 | Fonction `detect_hands(frame)` | Retourne position des mains de chaque personne |
| 2c.5 | Fonction `classify_gesture(pose_a, pose_b)` | Détecte : high-five / check / accolade / bras levés |
| 2c.6 | Fonction `detect_laughter_audio(segment)` | Via Librosa + modèle audio léger |
| 2c.7 | Fonction `score_interaction(gesture, emotions, audio)` | Score composite de « moment fort » |
| 2c.8 | Intégration avec `emotion_detector` (J2b) | Fusion des signaux émotions + pose |
| 2c.9 | Tests sur vidéos réelles | Review manuelle |
| 2c.10 | Commit : `feat(interaction): detect instructor-passenger bonding moments via MediaPipe` | Push |

**Livrable** : fichier `interaction_moments.json` qui enrichit `emotional_moments.json` avec des gestes et interactions.

```json
[
  {"start": 1340, "end": 1342, "gesture": "high_five", "confidence": 0.91, "actors": ["passenger", "instructor"]},
  {"start": 1355, "end": 1358, "gesture": "hug", "confidence": 0.87},
  {"start": 1375, "end": 1377, "gesture": "arms_raised_triumph", "confidence": 0.94, "actor": "passenger"}
]
```

**Durée estimée** : 1 jour.
**Coût API** : **0 €** (MediaPipe 100% local).

**Note technique** : MediaPipe Pose tourne en temps réel sur CPU (même sans GPU), environ 20-30 FPS. Sur 60 secondes de vidéo post-atterrissage, analyse en ~10 secondes.

---

## 🎨 Jalon 3 — Overlays brandés

**Objectif** : Générer les éléments visuels qui s'incrustent sur la vidéo finale (logo, nom client, HUD altitude/vitesse animé).

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 3.1 | Créer `core/overlay_generator.py` | Nouveau module, basé sur Pillow |
| 3.2 | Fonction `generate_intro(nom_client, date, logo)` | Image PNG transparente pour l'intro |
| 3.3 | Fonction `generate_outro(dropzone_name, cta)` | Image PNG transparente pour l'outro |
| 3.4 | Fonction `generate_hud_frames(telemetry, fps)` | Série de PNG animés (altitude + vitesse qui évoluent) |
| 3.5 | Récupérer logo dropzone + créer template graphique | PSD ou Figma → PNG |
| 3.6 | Intégration avec FFmpeg `overlay` filter | Exemple de commande qui superpose HUD sur la chute libre |
| 3.7 | Test visuel complet | Vidéo de 10s avec HUD live |
| 3.8 | Commit : `feat(overlay): branded intro + outro + animated HUD` | Push |

**Livrable** : démo 10 secondes de chute libre avec altitude/vitesse qui s'animent en coin haut-gauche, logo dropzone en coin haut-droit.

**Durée estimée** : 1 jour.

---

## 🎞️ Jalon 4 — Montage cinéma final

**Objectif** : Assembler tout ça en un montage 3-4 min avec musique sync et transitions pro.

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 4.1 | Créer `core/music_sync.py` | Beat detection via `librosa` → timestamps |
| 4.2 | Créer `core/template_engine.py` | Orchestre l'ordre des scènes + durées cibles |
| 4.3 | Refactor `core/ffmpeg_engine.py` depuis `montage_parachute_ffmpeg.py` | Extraire le moteur dans `core/` |
| 4.4 | Ajouter support **musique externe** (-i music.mp3, ducking audio) | FFmpeg sidechaincompress |
| 4.5 | Ajouter support **LUT color grading** | FFmpeg `lut3d` filter |
| 4.6 | Fonction `build_montage(timeline, overlays, music, config)` | Orchestre tout |
| 4.7 | Acheter / récupérer **1 piste musicale libre de droits** | Epidemic Sound ou Artlist |
| 4.8 | Télécharger / créer **1 LUT cinéma** | `.cube` file |
| 4.9 | Génération d'un montage complet sur la vidéo test | Review humaine — note /10 |
| 4.10 | Itérer durée/rythme jusqu'à satisfaisant | 2-3 passes de calibration |
| 4.11 | Commit : `feat(montage): full cinema pipeline with music sync + LUT` | Push |

**Livrable** : **1ère vidéo 3-4 min** professionnelle, prête à être montrée à un passager fictif.

**Durée estimée** : 2-3 jours.

**Point critique** : c'est ici qu'on **juge le rendu final**. Si insatisfaisant, on itère avant de continuer.

---

## 🖥️ Jalon 5 — Dashboard web + base clients

**Objectif** : Interface simple pour le staff dropzone (upload + suivi + config).

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 5.1 | Créer `db/schema.sql` | Tables `clients`, `jumps`, `montages`, `jobs` |
| 5.2 | Créer `db/migrations/001_init.sql` | Migration initiale SQLite |
| 5.3 | Étendre `api/serveur_api.py` : routes `/clients`, `/jumps`, `/upload` | CRUD de base |
| 5.4 | Créer `ui/dashboard.html` | Page unique : upload + tableau jobs + statut live |
| 5.5 | Formulaire : nom passager / email / date saut / upload vidéo | HTML simple + JS vanilla |
| 5.6 | Websocket ou polling pour statut live des jobs | Polling /statut toutes 3s |
| 5.7 | Historique des montages par client (searchable) | Vue /clients/{id} |
| 5.8 | Preview vidéo dans le dashboard avant livraison | Lecteur HTML5 |
| 5.9 | Test UX avec le client dropzone | Feedback |
| 5.10 | Commit : `feat(ui): dropzone staff dashboard with job tracking` | Push |

**Livrable** : dashboard web accessible sur `http://localhost:5000/dashboard`, utilisable par un non-tech.

**Durée estimée** : 2 jours.

---

## 📬 Jalon 6 — Livraison automatique

**Objectif** : Envoyer le montage au passager sans intervention manuelle.

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 6.1 | Configurer **Gmail MCP** (déjà dispo dans ton environnement Claude) | OAuth Google |
| 6.2 | Configurer **Google Drive API** | OAuth + dossier racine |
| 6.3 | Créer `api/delivery.py` | Module unifié |
| 6.4 | Fonction `upload_to_drive(file, folder_id, client_name)` | Upload + récup lien public |
| 6.5 | Fonction `send_email(client_email, link, montage_info)` | Template HTML stylé |
| 6.6 | Créer `templates/email_livraison.html` | Template joli (branding dropzone) |
| 6.7 | *(Optionnel)* Intégrer Twilio SMS + QR code | `pip install twilio qrcode` |
| 6.8 | Orchestration : après montage → livraison auto | Hook dans le pipeline |
| 6.9 | Test end-to-end avec une vraie adresse email | Reçoit bien l'email |
| 6.10 | Commit : `feat(delivery): Gmail + Drive + optional SMS delivery` | Push |

**Livrable** : dès qu'un montage est généré, le passager reçoit un email avec un lien Drive.

**Durée estimée** : 1 jour.

---

## 🚀 Jalon 7 — Déploiement client + monitoring

**Objectif** : Livrer le système en prod chez la dropzone.

### Tâches

| # | Tâche | Détail |
|---|---|---|
| 7.1 | Créer script `setup.sh` (Windows + Mac) | Installation one-shot |
| 7.2 | Doc utilisateur non-tech | `GUIDE_UTILISATEUR.md` avec captures d'écran |
| 7.3 | Installer sur le PC du client dropzone | Déploiement physique |
| 7.4 | Créer service Windows (démarrage auto du serveur Flask) | `nssm` ou Task Scheduler |
| 7.5 | Configurer sauvegarde auto base clients | Export SQLite quotidien sur Drive |
| 7.6 | Formation staff dropzone (1-2 h) | Session en présentiel ou visio |
| 7.7 | Setup monitoring (logs + alertes email si crash) | `loguru` + email erreur |
| 7.8 | Préparer **pack premium** : export version 30s Instagram Reels | Bonus revenue |
| 7.9 | Documentation maintenance | Runbook |
| 7.10 | Commit final + tag v1.0 | Release |

**Livrable** : système opérationnel 24/7 chez le client, staff formé.

**Durée estimée** : 1 jour setup + 1 jour formation.

---

## 📊 Récap budget & durées

| Jalon | Durée | Coût API (tests) |
|---|---|---|
| J0 Setup | 1-2 h | 0 € |
| J1 Télémétrie | 4-6 h | 0 € |
| J2 Détection scènes | 1-2 j | 0 € (Gemini Free) |
| J2b Émotions | 1 j | 0 € (DeepFace local) |
| J2c Interactions | 1 j | 0 € (MediaPipe local) |
| J3 Overlays | 1 j | 0 € |
| J4 Montage cinéma | 2-3 j | 0-2 € |
| J5 Dashboard | 2 j | 0 € |
| J6 Livraison | 1 j | 0 € |
| J7 Déploiement | 1-2 j | 0 € |
| **TOTAL** | **~12-16 jours** | **0-2 €** |

### Coûts récurrents en production (client dropzone, stratégie hybride gratuite)
- **API Gemini** (quota gratuit 1500 req/jour) : **0 €** tant qu'on reste dedans
- **API Claude** *(fallback scènes ambiguës uniquement)* : **~5-15 €/mois** en pleine saison
- **Google Workspace** (Drive + Gmail) : 15 €/mois
- **Musique libre de droits** : 15-30 €/mois (Epidemic Sound pro)
- **Twilio SMS** *(optionnel)* : ~0,05 € par SMS → négligeable
- **Total prod** : ~130-195 €/mois été, 15-45 €/mois hiver

### Modèle de facturation au client suggéré
- **Setup initial** : forfait fixe (définir)
- **Abonnement mensuel** : couvre API + support + maintenance
- **Marge** : appliquer coefficient × 2 à 3 sur les coûts récurrents

---

## 🔌 MCPs et outils utilisés durant le développement

| Outil | Étape | Usage |
|---|---|---|
| **Context7 MCP** | Tous jalons | Docs à jour MoviePy, FFmpeg, PySceneDetect, Anthropic SDK |
| **Skill `claude-api`** | J2 + J4 | Intégration Claude Vision + orchestration |
| **Gmail MCP** | J6 | Envoi emails de livraison |
| **Playwright MCP** | J5 | Tests automatisés du dashboard |
| **Claude Preview MCP** | J5 | Dev live du dashboard web |
| **Scheduled-tasks MCP** | J7 | Polling auto / sauvegardes / rapports |
| **Skill `superpowers:writing-plans`** | Ce document | Rédaction du plan |
| **Notion MCP** | J7 | Documentation client + suivi bugs |

---

## ⚠️ Points de vigilance

1. **Droits musicaux** : ne pas utiliser de musique commerciale sans licence (risque juridique majeur). Prévoir abonnement Epidemic Sound ou équivalent.
2. **RGPD** : les vidéos contiennent des visages identifiables. Prévoir consentement écrit du passager (formulaire signature numérique ?).
3. **Panne API Claude** : prévoir un **fallback mode manuel** dans le dashboard (timeline éditable à la main).
4. **Volume de stockage** : 30 vidéos brutes/jour × 3 Go = 90 Go/jour. Prévoir rotation automatique (suppression brutes après 7 jours).
5. **Qualité GoPro variable** : stabilisation activée ? Résolution ? → définir des **presets GoPro recommandés** pour le staff dropzone.
6. **Latence de livraison** : le passager s'attend à recevoir la vidéo dans l'heure. Prévoir dimensionnement (parallélisation) pour absorber les pics été.

---

## 🎬 Prochaine étape concrète

Une fois ce plan validé par toi :

1. Je crée les **premiers fichiers de structure** (arborescence + squelette des modules).
2. J'attaque **J0 + J1** (télémétrie) en premier — c'est le plus risqué techniquement (si les GoPro ne sortent pas de GPMF exploitable, il faut replanifier).
3. Tu me fournis **1 vidéo tandem test GoPro** (15 min) et je valide le pipeline télémétrie dessus avant d'aller plus loin.

---

**Document vivant** — à mettre à jour après chaque jalon.

# 🪂 SkyDive Pro — Montage Auto IA pour Tandems

**Plateforme de montage vidéo automatique** destinée aux **dropzones de saut en parachute tandem**. Transforme chaque vidéo brute GoPro (~15 min) en un **condensé professionnel de 3-4 min**, prêt à livrer au passager — intro brandée, overlays stylisés, musique synchronisée, transitions cinéma.

> *« Le passager saute. Le montage est dans sa boîte mail avant qu'il rentre chez lui. »*

---

## 🎯 Pour qui ?

**Dropzones tandem** qui veulent :
- **Industrialiser** la post-production (10 à 30 sauts/jour en été)
- **Livrer vite** au passager (email / SMS / QR code avec lien Drive)
- **Professionnaliser** le rendu (branding cohérent, look cinéma)
- **Zéro intervention manuelle** : l'IA s'occupe de tout

---

## ⚡ Ce que fait le système

### 1️⃣ Analyse intelligente de la vidéo brute
À partir d'une vidéo GoPro de 15 min, l'IA détecte automatiquement les **moments clés** du saut :

| Scène | Détection |
|---|---|
| 🗣️ **Briefing au sol** | Vision IA (personnes debout, scène statique) |
| 🚐 **Entrée / sortie du véhicule** | Vision IA + audio |
| ✈️ **Montée en avion** | Audio (moteur) + télémétrie (altitude croissante) |
| 🎢 **Sortie de l'avion** | Télémétrie (accélération verticale brutale) |
| 🌬️ **Chute libre** | Télémétrie (accéléromètre ≈ 0G) + audio (vent fort) |
| 🪂 **Sous voile** | Télémétrie (altitude qui descend lentement) |
| 🌍 **Atterrissage** | Télémétrie (vitesse → 0) + vision IA |
| 😃 **Réaction au sol (émotions)** | Détection de visages + classification émotions (joie, surprise, euphorie, fierté, larmes) → **sélection automatique des meilleures réactions** pour l'outro |
| 🤝 **Interaction moniteur ↔ passager** | Détection de pose + proximité (MediaPipe) : high-five, check, poignée de main, accolade, bras levés en triomphe + audio (rires, "bravo", félicitations) → **moment social fort** mis en valeur |

### 🎁 Bonus : analyse émotionnelle post-atterrissage

À la fin du saut, l'IA détecte les **visages du passager et du moniteur** et classifie les **émotions** en temps réel :
- 😄 Joie / euphorie
- 😲 Surprise
- 🥹 Émotion forte (larmes de joie)
- 🤝 Échanges (félicitations moniteur ↔ passager)
- 🏆 Fierté

→ Les **3-5 secondes les plus émotionnelles** sont automatiquement sélectionnées et placées en **climax de l'outro**. C'est le moment le plus viral à partager sur les réseaux.

**Tech utilisée** : DeepFace ou `fer` (open source, **100% gratuit**, tourne en local sur CPU — pas besoin d'API payante pour cette étape).

### 🤝 Détection d'interaction moniteur ↔ passager

Un deuxième module identifie les **moments de complicité** entre le moniteur et le passager après le saut :

- 🖐️ **High-five** (détection du geste main levée entre 2 personnes)
- ✊ **Check / poignée de main** (mains en contact au centre)
- 🤗 **Accolade / hug** (corps rapprochés, bras enveloppants)
- 🙌 **Bras levés en triomphe** (pose victorieuse)
- 😂 **Rires partagés** (analyse audio + synchronisation des sourires)

Le système classe ces interactions par **score d'intensité émotionnelle** et les insère dans la partie outro du montage. L'instant où le moniteur félicite le passager est **systématiquement détecté et priorisé**.

**Tech utilisée** : **MediaPipe Pose + Hands** (Google, open source, gratuit, CPU) pour le tracking multi-personnes, **Librosa** pour les rires audio. **0 € d'API**.

### 2️⃣ Extraction automatique des données télémétrie GoPro
Grâce au format **GPMF** embarqué dans les vidéos GoPro (Hero 5+) :
- **Altitude max** (ex: 4 000 m)
- **Vitesse max en chute libre** (ex: 210 km/h)
- **Durée de chute libre** (ex: 58 s)
- **Trajectoire GPS**

→ Ces données sont **affichées en overlay** sur la vidéo finale.

### 3️⃣ Montage automatisé style cinéma
- ✂️ Sélection des **meilleurs clips** de chaque scène
- 🎬 **Intro brandée** avec logo dropzone + nom du passager + date du saut
- 📊 **Overlays dynamiques** (altitude, vitesse en temps réel pendant la chute libre)
- 🎵 **Musique fixe** synchronisée sur les coupes (beat detection)
- 🌈 **Color grading** pro (LUTs cinéma)
- 🎞️ **Transitions** FFmpeg cinéma (50+ effets au choix)
- 🏁 **Outro** avec logo + coordonnées dropzone + CTA (réseaux sociaux)

### 4️⃣ Livraison automatique au passager
- 📧 Email avec lien Drive et preview
- 📱 SMS (optionnel, via Twilio) avec QR code vers la vidéo
- ☁️ Upload Drive dans un dossier dédié par passager
- 🎁 Option : pack premium (version courte 30s pour Instagram Reels + version longue 3-4 min)

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  STAFF DROPZONE                                              │
│  📤 Upload vidéo brute GoPro via dashboard web               │
│  ✍️ Renseigne : nom passager + email + date saut            │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  PIPELINE AUTOMATIQUE (Python + IA)                          │
│                                                              │
│  [1] Extraction télémétrie GoPro (GPMF)                     │
│      → altitude, vitesse, accéléromètre, GPS                │
│                                                              │
│  [2] Détection scènes (hybride)                             │
│      • Signaux télémétrie (chute libre, sous voile, sol)   │
│      • Audio (moteur avion / vent / silence)                │
│      • Claude Vision API (briefing, véhicule, atterrissage) │
│                                                              │
│  [3] Sélection clips (agent Claude)                         │
│      → garde les 3-5 meilleures secondes par scène          │
│                                                              │
│  [4] Génération overlays (Pillow + FFmpeg drawtext)         │
│      → logo, nom, date, altitude animée, vitesse animée    │
│                                                              │
│  [5] Montage FFmpeg                                         │
│      → xfade transitions + musique sync + color LUT         │
│      → encodage h264_amf (hardware AMD)                     │
│                                                              │
│  [6] Livraison multi-canal                                  │
│      → Drive + Gmail + SMS (optionnel)                      │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  PASSAGER                                                    │
│  📬 Reçoit un email avec son montage 3-4 min                │
│  📱 Clic → visionne sur mobile                              │
│  🎉 Partage sur ses réseaux                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 Structure du projet

```
skydive_pro/
├── core/
│   ├── ffmpeg_engine.py        # Moteur FFmpeg (transitions, encodage, concat)
│   ├── telemetry_gopro.py      # Extraction GPMF (altitude, vitesse, G-force)
│   ├── scene_detector.py       # PySceneDetect + Claude Vision → classif scènes
│   ├── overlay_generator.py    # Génération logo + texte + HUD animés
│   ├── music_sync.py           # Beat detection + sync coupes sur la musique
│   └── template_engine.py      # Templates intro/outro + LUT color grading
│
├── agent/
│   ├── claude_agent.py         # Agent Claude : orchestre le pipeline
│   └── prompts/                # Prompts système par étape
│       ├── scene_classification.md
│       ├── clip_selection.md
│       └── quality_review.md
│
├── api/
│   ├── serveur_api.py          # API Flask (routes /montage, /client, /statut)
│   └── delivery.py             # Gmail + Drive + Twilio
│
├── db/
│   ├── clients.sqlite          # Passagers ↔ sauts ↔ montages
│   └── migrations/
│
├── ui/
│   ├── dashboard.html          # Dashboard staff (upload + statut jobs)
│   ├── static/
│   └── templates/
│
├── assets/
│   ├── branding/
│   │   ├── logo_dropzone.png
│   │   └── outro_template.mp4
│   ├── music/
│   │   └── default_track.mp3
│   └── luts/
│       └── cinematic.cube
│
├── n8n_workflow_v2.json        # Workflow N8N (option, si Drive externe)
│
├── tests/
│   ├── test_telemetry.py
│   ├── test_scene_detector.py
│   └── fixtures/
│       └── sample_gopro.mp4
│
├── .env.example                # Clés API Claude, Gmail, Twilio, Drive
├── requirements.txt            # moviepy, scenedetect, gopro-overlay, anthropic, ...
├── setup.sh                    # Installation one-shot (Windows + Mac + Linux)
└── README.md
```

---

## 💸 Stratégies IA — payant vs gratuit

Le projet utilise l'IA **principalement pour 2 tâches** :
1. **Classification de scènes visuelles** (briefing, véhicule, atterrissage) — quelques keyframes à analyser
2. **Analyse d'émotions sur visages** — détection joie/surprise pendant la réaction au sol

Plusieurs stratégies sont possibles selon ton budget :

### 🎯 Option 1 : Claude API (payant, qualité max)
- **Qualité** : ⭐⭐⭐⭐⭐ (meilleure compréhension contextuelle)
- **Coût** : ~0,15 €/montage → ~135 €/mois en pleine saison
- **Latence** : rapide (2-5s par classification)
- **Pour qui** : quand la qualité du montage est critique (clientèle premium)

### 🆓 Option 2 : Google Gemini API (gratuit sous conditions)
- **Quota gratuit** : 15 requêtes/min, **1 500 requêtes/jour** sur Gemini 1.5 Flash
- **Suffisant pour** : ~30 montages/jour (≈10 req/montage)
- **Qualité** : ⭐⭐⭐⭐ (très bonne pour vision)
- **Coût** : **0 €** tant qu'on reste dans le quota
- **Limite** : si la dropzone dépasse 30 sauts/jour, on passe sur payant (~0,01 €/req, dérisoire)
- **Pour qui** : **recommandé pour démarrer sans frais**

### 🆓 Option 3 : Groq (gratuit, ultra-rapide)
- **Quota gratuit** : 30 requêtes/min (variable selon modèles)
- **Modèles dispos** : **Llama 3.2 Vision 90B**, Llama 3.3 70B
- **Latence** : la plus rapide du marché (~0,5s par classification)
- **Coût** : **0 €** sur free tier
- **Limite** : file d'attente possible aux heures de pointe
- **Pour qui** : idéal pour analyser des volumes importants rapidement

### 🆓 Option 4 : Ollama local (100% gratuit, offline)
- **Modèles dispos** : Llama 3.2 Vision, LLaVA, Qwen2-VL 7B
- **Coût** : **0 €** (ni API ni internet requis)
- **Vitesse sur ton PC (Ryzen 7 6800H sans GPU dédié)** : ⚠️ **lent** (~30-60s par image) — tolérable si batch nocturne
- **Vitesse avec RTX 4060+** : rapide (~2s)
- **Pour qui** : déploiement 100% offline chez clients sensibles à la vie privée

### 🆓 Option 5 : Hybride intelligent (recommandé pour ton cas)
**Stratégie qui combine le meilleur de tout, gratuite à 95%** :

| Tâche | Technologie | Coût |
|---|---|---|
| Détection scènes chute libre/voile/atterrissage | **Télémétrie GoPro** | 0 € |
| Détection audio (moteur/vent/silence) | **Librosa** (Python) | 0 € |
| Détection coupes vidéo | **PySceneDetect** | 0 € |
| Classification briefing/véhicule (~5 keyframes/vidéo) | **Gemini Flash gratuit** | 0 € |
| Détection visages + émotions réaction au sol | **DeepFace** (local, CPU) | 0 € |
| *(Fallback)* scènes ambiguës / qualité premium | **Claude API** | ~0,02 €/vidéo |

**Total coût IA** : **0 à 5 €/mois** en pleine saison → **économies de ~130 €/mois** vs full Claude.

> ✅ **Recommandation** : démarrer en **Option 5 (hybride Gemini + DeepFace local)**. Si le client veut booster la qualité plus tard, on bascule les tâches critiques sur Claude.

### 🔍 Hybride vs Full Claude — comparaison honnête

| Critère | Full Claude API | Hybride (Gemini + DeepFace + MediaPipe) | Verdict |
|---|---|---|---|
| **Classification de scènes** (briefing, véhicule, avion) | ⭐⭐⭐⭐⭐ Excellente | ⭐⭐⭐⭐ Très bonne (Gemini Flash proche de Claude 3.5) | **Quasi-égalité** |
| **Détection de visages** | ⭐⭐⭐ OK mais généraliste | ⭐⭐⭐⭐⭐ DeepFace = **modèle spécialisé** plus précis | **Hybride GAGNE** |
| **Classification émotions** | ⭐⭐⭐ Description textuelle | ⭐⭐⭐⭐⭐ DeepFace retourne des scores numériques par émotion (`happy: 0.8, surprised: 0.15...`) | **Hybride GAGNE** |
| **Détection de pose / gestes** (high-five, check) | ⭐⭐ Limité (texte seulement) | ⭐⭐⭐⭐⭐ MediaPipe donne les coordonnées exactes des 33 points du corps | **Hybride GAGNE** |
| **Détection audio** (moteur, rires, vent) | ❌ Pas de support natif | ⭐⭐⭐⭐⭐ Librosa = outil métier | **Hybride GAGNE** |
| **Raisonnement contextuel complexe** (ex: "est-ce un moment émouvant parce que le passager évoque un proche décédé ?") | ⭐⭐⭐⭐⭐ Unique | ❌ Impossible | **Claude GAGNE** |
| **Latence moyenne par vidéo** | 2-5 min | 3-8 min (plus d'étapes mais CPU direct) | **Full Claude légèrement + rapide** |
| **Fiabilité offline** | ❌ Dépend de l'API | ✅ DeepFace + MediaPipe offline, Gemini en ligne | **Hybride GAGNE** |
| **Coût annuel** (estim. 5000 montages/an) | ~750 € | 0-30 € | **Hybride : -96%** |
| **Scalabilité** | Paiement à l'usage, illimité | Quota gratuit 1500 req/jour, payant au-delà | Match nul |

**Conclusion honnête** :

🎯 Pour **ton cas d'usage précis** (montage parachutisme tandem), l'**hybride est AU MOINS aussi bon que Claude seul**, voire **meilleur** sur plusieurs tâches clés (émotions, pose, audio). Pourquoi ? Parce qu'on utilise le **bon outil pour le bon problème** :
- Les **modèles spécialisés** (DeepFace, MediaPipe) battent les LLM généralistes sur leur domaine
- Gemini Flash atteint 95% de la qualité de Claude sur les classifications simples
- La télémétrie GoPro est **objectivement plus fiable** qu'une IA pour détecter l'altitude ou la chute libre

👎 **Seul cas où Claude seul serait supérieur** : si tu voulais que l'IA rédige des **descriptions cinématographiques élaborées** de chaque scène, ou **dialogue avec le passager** avant le saut. Ce qui n'est pas ton besoin.

💡 **Astuce** : on peut quand même garder **Claude en "contrôleur qualité"** — il regarde le montage final généré et suggère des ajustements. Usage marginal (~0,05 €/montage), qui apporte les 5% de finition haut de gamme.

---

## 💻 Compatibilité matérielle

### Scénario A : IA dans le cloud (recommandé)
**L'IA d'analyse (Claude Vision) tourne sur les serveurs Anthropic. Ton PC ne fait que l'encodage vidéo.**

| Composant | Minimum | Recommandé |
|---|---|---|
| CPU | Ryzen 5 / i5 10e gen | Ryzen 7 / i7 11e+ |
| GPU | iGPU récente (AMD Radeon 680M, Intel Xe, Apple M1+) | GPU dédié ou Apple Silicon |
| RAM | 16 Go | 32 Go |
| SSD | 256 Go libres | 1 To NVMe |
| Bande passante | 50 Mbps upload | Fibre 200+ Mbps |

**Coût API Claude estimé** : ~0,15 €/montage → **~135 €/mois** en pleine saison (30 montages/jour × 30j).

### Scénario B : Tout en local (100% offline)
**Nécessite un GPU NVIDIA costaud ou un Mac Apple Silicon.**

| Composant | Minimum | Recommandé |
|---|---|---|
| GPU | RTX 4060 16GB | RTX 4070 Super / RTX 4080 |
| OU Mac | M2 Pro 32GB | M3 Max / M4 Pro 36GB+ |
| RAM | 32 Go | 64 Go |

**Coût API** : 0 €. **Vitesse** : 2-3× plus lent que le scénario A.

---

## 🚀 Installation

### Prérequis
1. **Python 3.11+** — https://www.python.org/downloads/
2. **FFmpeg** (doit être dans le PATH)
   - Windows : `winget install ffmpeg`
   - Mac : `brew install ffmpeg`
   - Linux : `sudo apt install ffmpeg`
3. **Compte Anthropic** (clé API Claude) — https://console.anthropic.com
4. **Compte Google Cloud** (Drive + Gmail API)
5. *(Optionnel)* **Compte Twilio** pour SMS

### Installation du projet
```bash
git clone https://github.com/pacoolanda2b13-byte/montage-parachute-ffmpeg.git
cd montage-parachute-ffmpeg
pip install -r requirements.txt
cp .env.example .env
# → renseigne tes clés API dans .env
```

### Lancement du serveur
```bash
python api/serveur_api.py
# → ouvre http://localhost:5000 dans ton navigateur
```

---

## 🎨 Personnalisation

Tout est centralisé dans `config/config.yaml` :

```yaml
branding:
  logo: "assets/branding/logo_dropzone.png"
  nom_dropzone: "Skydive Adventure"
  couleur_primaire: "#FF6B00"
  site_web: "skydive-adventure.fr"

montage:
  duree_cible: 210          # 3min30 en secondes
  format: "16:9"            # ou "9:16" pour vertical
  resolution: "1920x1080"   # ou "1080x1920"
  fps: 30
  encodeur: "h264_amf"      # libx264 | h264_nvenc | h264_amf | h264_videotoolbox

overlays:
  afficher_nom_passager: true
  afficher_date_saut: true
  afficher_altitude_max: true
  afficher_vitesse_max: true
  afficher_duree_chute: true

musique:
  piste: "assets/music/default_track.mp3"
  volume: 0.35
  sync_sur_beat: true

livraison:
  canaux: ["email", "drive"]   # + "sms" si Twilio configuré
  template_email: "templates/email_livraison.html"
```

---

## ❓ FAQ

**Q : Combien de temps pour un montage ?**
R : 5 à 10 minutes en Scénario A, sur ton Ryzen 7 6800H. Tu peux paralléliser 2-3 jobs.

**Q : Ça marche avec d'autres caméras que la GoPro ?**
R : Oui, mais la télémétrie auto (altitude/vitesse) ne marche qu'avec GoPro Hero 5+. Sans GoPro, il faudra saisir ces infos manuellement ou les ignorer.

**Q : Combien ça me coûte par mois ?**
R : Avec le Scénario A cloud : **~100-150 € d'API Claude** en pleine saison, + **hébergement Drive** (15 €/mois Google Workspace). Zéro coût l'hiver si aucun saut.

**Q : Et si je passe sur Mac ?**
R : Un MacBook Pro M3 Pro 32GB permet de faire tourner l'IA en local → **0 € d'API**, mais coût machine ~2500 €. Rentable si volume > 2000 montages/an.

**Q : La musique, droits SACEM ?**
R : ⚠️ Point important. Utilise soit une **licence SACEM pro**, soit des **pistes libres** (Epidemic Sound, Artlist, YouTube Audio Library).

---

## 📜 Licence

Projet privé — Tous droits réservés. Usage réservé aux dropzones licenciées.

---

## 🛠️ Stack technique

- **Python 3.11+**
- **FFmpeg** (moteur d'encodage)
- **MoviePy** (compositing Python)
- **PySceneDetect** (détection de coupes)
- **gopro-overlay** / **GPMF-parser** (télémétrie)
- **Anthropic SDK** (Claude pour analyse IA)
- **Flask** (API + dashboard)
- **SQLite** (base clients)
- **N8N** (orchestration optionnelle)
- **Google Drive API** + **Gmail API** (livraison)
- *(Optionnel)* **Twilio** (SMS)

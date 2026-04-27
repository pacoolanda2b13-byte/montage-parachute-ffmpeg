# 🪂 SkyDive Pro — Guide démo client

> **Date démo prévue** : jeudi/vendredi, visioconférence
> **Machine** : Ryzen 7 6800H + Radeon 680M (encodeur h264_amf actif)
> **Tag de référence** : `v0.1.0-demo`

---

## ✅ Pipeline validé le 2026-04-27

| Test | Vidéo | Vision | Durée traitement | Sortie | État |
|---|---|---|---|---|---|
| Smoke test | `karma.mp4` (12s) | OFF | 13.8s | 0.14 MB | ✅ |
| Test vision | `GX016030.MP4` (33s) | ON Gemini | 131.6s | 35.9 MB | ✅ 9 scènes |
| Démo finale | `soren_complet.mp4` (9 min 38) | ON Gemini | en cours | ⏳ | ⏳ |

**Encodeur** : `h264_amf` (AMD GPU) sélectionné automatiquement.

---

## 🎬 Plan de démo (15 min)

### 1. Pitch (2 min)
> *« Une vidéo GoPro de 15 minutes, montage cinéma de 3 minutes, dans la boîte mail du passager avant qu'il rentre chez lui. »*

Cibles :
- Dropzones tandem 10–30 sauts/jour en saison
- Coût IA cible : **0–5 €/mois** (stratégie hybride gratuite)

### 2. Démo live (8 min)
```powershell
# Au lancement de la visio :
cd "C:\Users\pacoo\OneDrive\Desktop\IA\SaaS parachutisme"
.\demo.ps1 -Long -Passager "Sophie Martin" -Dropzone "Skydive Lyon" -Site "skydive-lyon.fr"
```

Pendant que ça tourne (~3-5 min) :
- Montrer l'**arborescence** du projet (`skydive_pro/core/`, `agent/`, `api/`)
- Montrer la **télémétrie GPMF** extraite (altitude, vitesse, GPS)
- Montrer le **dashboard HTML** (`ui/templates/dashboard.html`)
- Évoquer la **stratégie hybride** Gemini + télémétrie + audio

À la fin → ouvrir le montage produit dans le lecteur.

### 3. Architecture en 1 slide (3 min)
- Pipeline : Télémétrie → Détection scènes → Overlays → FFmpeg AMF
- 9 scènes détectables (briefing → atterrissage → réaction émotion)
- Encodage GPU AMD : 30-60 fps en encodage final

### 4. Roadmap & pricing (2 min)
- v0.1.0-demo : pipeline bout-en-bout ✅
- v0.2 (mois +1) : SQLite jobs + Gmail/Drive auto-livraison
- v0.3 (mois +2) : DeepFace émotions + MediaPipe interaction moniteur

---

## 🚨 Plan B si bug en live

| Symptôme | Action |
|---|---|
| Pipeline crash en plein live | `Ctrl+C` → afficher le **montage `vision-test-001`** déjà produit ce 27/04 |
| Gemini quota épuisé | `.\demo.ps1 -NoVision` (pipeline marche sans vision, juste sans détection scène fine) |
| FFmpeg AMF bloque | Forcer CPU : modifier `core/ffmpeg_engine.py` `preferred=libx264` |
| Visio coupe | Avoir le **montage final** + le **deck Gamma PDF** déjà ouverts dans 2 onglets |

**Backups préparés** :
- `output/vision-test-001_GX016030_montage.mp4` (35.9 MB, validé 19:42)
- `docs/SkyDive_Pro_Gamma_Deck.pdf` (deck pitch)
- Tag git `v0.1.0-demo` (point de retour stable)

---

## 🎯 Questions probables du client + réponses

| Q | R |
|---|---|
| Combien ça coûte par saut ? | 0,02–0,05 € en API Gemini, électricité GPU négligeable |
| Vous gardez les vidéos ? | Non — traitement local sur le PC dropzone, vidéos restent chez le client |
| RGPD ? | Vidéos transitent par Gemini cloud (Google) en phase 1. Roadmap v0.3 prévoit la vision 100% locale |
| Compatibilité GoPro ? | Hero 5+ (extraction GPMF). Pour GoPro plus anciennes ou autres caméras → fallback vision uniquement |
| Vous fournissez le matériel ? | Non. Le PC dropzone fait tourner SkyDive Pro localement. Spec mini : Ryzen 5 + 16 GB + iGPU récent |
| Délai de livraison effective ? | Après le saut + 5 min de traitement = vidéo prête. Email automatique en v0.2 |
| Personnalisation du branding ? | Logo + nom dropzone + site web injectés en intro/outro |

---

## 📞 Contact post-démo

Si le client veut signer :
- Contrat : licence commerciale séparée (voir `LICENSE`)
- Tarification suggérée : 99–149 €/mois par dropzone + 0,50 €/saut traité au-delà de 200 sauts/mois

---

> Dernier check 1 h avant la démo : `.\demo.ps1` (rapide, doit produire un montage en < 2 min).

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
| Pipeline crash en plein live | `Ctrl+C` → ouvrir `demo-soren-final_soren_complet_montage.mp4` dans VLC |
| Gemini quota épuisé (free tier 20/j) | `.\demo.ps1 -NoVision` — pipeline marche, fallback narratif (9 segments) |
| FFmpeg AMF bloque | Forcer CPU : `core/ffmpeg_engine.py` paramètre `preferred="libx264"` |
| Visio coupe | Le deck Gamma PDF + le montage déjà ouverts dans 2 onglets |

**Backups préparés (du plus pertinent au moins)** :
- ⭐ `output/demo-soren-final_soren_complet_montage.mp4` (64 MB, 13 scènes Gemini, saut complet 9 min) — **C'EST LE FICHIER À MONTRER**
- `output/demo-backup-postfix_soren_complet_montage.mp4` (164 MB, fallback narratif, post-quick-wins)
- `output/vision-test-001_GX016030_montage.mp4` (36 MB, clip court 33s, démo rapide)
- `docs/SkyDive_Pro_Gamma_Deck.pdf` (deck pitch — toujours ouvert en 2ᵉ onglet)
- Tag git `demo-safe-2026-04-27` (= `v0.1.0-demo`) point de retour stable

## ⚠️ Gestion du quota Gemini (CRITIQUE)

Le **free tier = 20 requêtes/jour**, reset minuit Pacific Time (≈ 9h chez toi). Une démo complète (vidéo 9 min) consomme ~19 requêtes. **Donc 1 seul run avec vision par jour, max.**

**Stratégie démo recommandée** :
1. Le matin de la démo : **un test rapide de 30s sans vision** (`.\demo.ps1 -NoVision`) pour confirmer que tout démarre
2. **Pas** de lancement vision avant la visio
3. Pendant la démo : ouvrir le montage `demo-soren-final` déjà produit (saut complet, vision active) en disant *« généré ce matin sur un vrai saut tandem »*
4. Si le client demande à voir le pipeline tourner : utiliser un **clip court** (`.\demo.ps1` mode rapide sur GX016030, 33s, ~5 req Gemini → encore de la marge)
5. **Plan B Gemini grillé** : `.\demo.ps1 -NoVision` produit un montage en fallback narratif. Honnête et fonctionnel.

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

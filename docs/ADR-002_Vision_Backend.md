# ADR-002 — Choix du backend vision pour la classification de scènes

**Statut :** Accepté
**Date :** 2026-04-17
**Décideurs :** Paco (owner)
**Supersede :** aucun (premier ADR sur ce sujet)
**Lié à :** ADR-001 (revue architecture), `docs/BENCHMARK_VISION.md`

---

## 1. Contexte

`skydive_pro/core/scene_detector.py` utilise **Google Gemini Flash** via l'API
cloud pour classifier des keyframes en 9 scènes de saut tandem
(briefing, chute libre, atterrissage, etc.). Trois forces poussent à
réévaluer ce choix :

1. **Contrainte de quota** — free tier = 20 req/jour. Un saut consomme 10-20
   keyframes → **1-2 sauts/jour gratuits max** avant épuisement.
2. **Contrainte RGPD / confidentialité** — les vidéos de passagers transitent
   par les serveurs Google. Argument commercial fort si on peut les garder
   locales.
3. **Émergence de modèles vision open-source compétitifs** — Moondream2,
   Qwen2.5-VL, Qwen3-VL, LLaVA, MiniCPM-V. Licence Apache 2.0, usage
   commercial autorisé.

**Hardware cible** : PC dropzone Windows avec GPU **AMD** (encodeur AMF
visible dans FFmpeg), **8-16 GB VRAM** probables.

**Contrainte temporelle** : démo client **ce soir** — toute décision doit
être compatible avec une mise en production immédiate.

---

## 2. Données du benchmark (2026-04-17)

Bench exécuté via `scripts/bench_vision_models.py` sur 6 keyframes de
`tests/fixtures/karma.mp4`, Ollama 0.x Windows, AMD GPU, Python 3.14.

| Modèle | Backend | Warmup | Latence moy./frame | Verdict |
|---|---|---|---|---|
| **Gemini Flash** | Cloud | — | 1-3 s | Référence |
| **Moondream 1.8B** | Ollama Windows (**CPU**) | 21 s | **17 s** | ❌ 10× trop lent |

**Finding clé** : Ollama sous Windows **n'exploite pas le GPU AMD nativement**
(ROCm absent). L'inférence tombe sur CPU → latence multipliée par 10.

---

## 3. Décision

> **Conserver Gemini Flash cloud pour la phase 1 (démos + 3 premiers clients),
> garder le code structuré pour permettre un swap vers un backend local dès
> que (a) le volume le justifie ou (b) ROCm Windows mûrit.**

Concrètement :
- Ne **pas** coder tout de suite l'adapter Ollama
- **Mais** extraire l'appel Gemini derrière une **interface
  `VisionBackend`** (protocol Python) pour préparer le swap futur
- Ajouter un paramètre `.env` `VISION_BACKEND=gemini` (valeur unique pour
  l'instant, mais l'abstraction est prête)

---

## 4. Options considérées

### Option A — **Gemini Flash cloud** ✅ retenue

| Dimension | Assessment |
|---|---|
| Complexité | Low — déjà en place |
| Coût | 0 € gratis (20/j) → ~1-3 €/mois si Pro pour 30 sauts/j |
| Latence | 1-3 s/frame (bon) |
| Scalabilité | Excellente (API Google) |
| Familiarité équipe | Déjà codée et testée |
| RGPD | ⚠️ Vidéos transitent par Google US |
| Dépendance réseau | Oui — internet requis |

**Pros**
- Zéro effort, déjà fonctionnel
- Latence acceptable
- Qualité référence (SOTA)

**Cons**
- Vendor lock-in Google
- RGPD limite l'argument "données restent chez vous"
- Quota free aléatoire

---

### Option B — **Ollama local (CPU Windows)** ❌ rejetée

| Dimension | Assessment |
|---|---|
| Complexité | Low (install Ollama) |
| Coût | 0 € |
| Latence | **17-20 s/frame** (**inacceptable**) |
| Scalabilité | Limitée par CPU |
| Familiarité équipe | Stack nouvelle |
| RGPD | ✅ Parfait (100 % local) |
| Dépendance réseau | Non |

**Pros** : confidentialité totale, coût nul.
**Cons** : **latence × 10 vs Gemini**, rend le pipeline de 10 min → 20 min.
**Verdict bench** : 17 s/frame mesuré le 2026-04-17. Déal-breaker pour la cible UX "livraison < 10 min".

---

### Option C — **llama.cpp Vulkan AMD Windows** ⏸️ différée

| Dimension | Assessment |
|---|---|
| Complexité | **High** — compilation custom, tuning |
| Coût | 0 € |
| Latence | ~2-3 s/frame estimée (non mesurée) |
| Scalabilité | Bonne si GPU dispo |
| Familiarité équipe | Nouveau stack |
| RGPD | ✅ Parfait |
| Dépendance réseau | Non |

**Pros** : seule voie locale viable sur Windows AMD aujourd'hui, RGPD OK.
**Cons** : 2-4 h de setup par machine dropzone, binaire custom à maintenir, risque de régression à chaque update driver AMD.
**Verdict** : techniquement faisable mais **coût d'intégration disproportionné** pour phase 1. Reconsidérer quand 5+ dropzones déployées.

---

### Option D — **Serveur GPU cloud mutualisé** ⏸️ différée (phase 3)

Un seul serveur **RunPod** / **Vast.ai** avec Qwen2.5-VL-7B, accédé en HTTP
par toutes les dropzones clientes.

| Dimension | Assessment |
|---|---|
| Complexité | Med — Docker + auth API-Key |
| Coût | ~20 €/mois serveur GPU 4090 spot |
| Latence | 1-2 s/frame (GPU NVIDIA) |
| Scalabilité | Bonne (1 serveur sert N dropzones) |
| Familiarité équipe | Stack à maîtriser |
| RGPD | ⚠️ Selon hébergeur (EU = OK) |
| Dépendance réseau | Oui |

**Pros** : meilleur ratio coût/perf si 5+ clients, contrôle total, pas de Google.
**Cons** : coût fixe même à 0 usage, ops supplémentaires, internet obligatoire.
**Verdict** : **pertinent à partir de 3-5 dropzones actives**. Pas avant.

---

### Option E — **Hybride Gemini + fallback cloud GPU** ⏸️ différée

Gemini par défaut, bascule sur serveur GPU custom si quota épuisé ou si
client a opté pour plan "premium confidentiel".

**Verdict** : complexité non justifiée avant stade payant multi-tier.

---

## 5. Analyse trade-off

| Critère | A (Gemini) | B (Ollama CPU) | C (llama.cpp) | D (serveur GPU) |
|---|---|---|---|---|
| **Dispo démo ce soir** | ✅ | ❌ (latence) | ❌ (non codé) | ❌ (non déployé) |
| **Coût mensuel 30 sauts/j** | 1-3 € | 0 € | 0 € | 20 € |
| **Argument RGPD** | ⚠️ | ✅ | ✅ | ~ |
| **Effort de mise en œuvre** | 0 h | ~2 h (validé KO) | ~4 h/machine | ~8 h setup + ops |
| **Risque technique** | Faible | Faible | **Haut** | Moyen |

**Conclusion** : Gemini reste le choix rationnel **maintenant**. La vraie
question n'est pas *"open source ou pas ?"* mais *"à quel seuil bascule-t-on ?"*.

**Seuils de ré-évaluation définis** :

| Signal | Action |
|---|---|
| Dépassement régulier des 1 500 req/j Gemini Pro payant | Passer option D |
| Prospect qui exige contractuellement "données 100 % locales" | Passer option C pour ce client |
| ROCm officiel pour Windows sorti | Passer option C |
| Budget vision > 50 €/mois | Passer option D |

---

## 6. Conséquences

### Devient plus facile
- Démo ce soir : aucun changement, ça tourne
- Onboarding 1er client : stack simple, setup 15 min
- Ajout d'un 2ᵉ/3ᵉ client : même clé API ou clé dédiée par dropzone

### Devient plus dur
- Argument commercial "vos vidéos ne sortent jamais" → temporairement indisponible
- Dépendance Google → à documenter dans le contrat client

### À revisiter
- Relancer le bench **quand Ollama publie le support GPU AMD Windows officiel** (watch le [changelog Ollama](https://github.com/ollama/ollama/releases))
- Quand la facture Gemini dépasse 20 €/mois → lancer option D
- Quand un prospect refuse explicitement Gemini → exception contractuelle option C

---

## 7. Action Items

### Phase 1 (cette semaine, après démo)
- [ ] **A1** Créer `skydive_pro/adapters/vision_backend.py` — Protocol `VisionBackend.classify(image_bytes) -> str`
- [ ] **A2** Refactorer `core/scene_detector.py` → utilise `VisionBackend` via DI
- [ ] **A3** Implémenter `GeminiVisionBackend` (l'existant, juste déplacé)
- [ ] **A4** Ajouter `VISION_BACKEND=gemini` dans `.env.example` (valeur unique pour l'instant)
- [ ] **A5** Documenter dans README la procédure pour ajouter un backend custom

### Phase 2 (dans 1-2 mois, selon signaux)
- [ ] **A6** Stub `OllamaVisionBackend` prêt-à-cliper — activable via `.env`
- [ ] **A7** Script de health-check qui alerte quand la latence Gemini > 5 s ou quota < 10 %

### Veille (continue)
- [ ] **A8** Setup watch GitHub sur `ollama/ollama` pour "AMD Windows support"
- [ ] **A9** Re-benchmarker tous les 3 mois les modèles open-source dispo

---

## 8. Notes annexes

- **Bench Moondream n'a pas classifié les scènes** : 6/6 "autre" sur karma.mp4. Ce **n'est pas un échec du modèle** — karma.mp4 est du footage drone, aucune scène tandem n'était présente. La qualité réelle de Moondream **reste non testée** ; à re-mesurer sur une vraie vidéo tandem.
- **Coût réel Gemini Pro** : tarif 2026-04-17 = `0.075 $/M tokens input`. Une keyframe ≈ 250 tokens, 30 sauts/jour × 15 frames = 450 frames/jour = 112 500 tokens/jour = 3.4 M tokens/mois ≈ **0.25 $/mois**. À peine visible sur la facture.
- Ce verdict repose sur un **unique bench Ollama CPU**. Un test en condition GPU (via llama.cpp Vulkan ou sur machine NVIDIA) donnerait des chiffres différents — l'ADR devra être revu si ce bench est refait.

---

## 9. Décision finale

✅ **Accepté.** On garde Gemini, on structure le code pour permettre le swap,
on réévalue quand un des 4 signaux du §5 apparaît.

**Suite immédiate** : aucun blocage. La démo de ce soir se fait avec Gemini.
Les action items A1-A5 peuvent démarrer en phase 1 du plan d'action
(voir `PLAN_ACTION_ARCHI.md`).

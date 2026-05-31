# Post-mortem — Session du 2026-04-28 (matin)

**Durée session** : ~5h (8h00 → 13h00)
**Versions produites** : v3 → v9 (7 itérations sur le même montage)
**Bugs identifiés** : 12 bugs successifs, certains liés à des fixes précédents
**État final** : Pipeline qui produit un montage 4 min 14, structure narrative correcte mais pas validé visuellement par l'utilisateur

---

## Vue d'ensemble — le pattern

> *« Chaque fix introduisait un nouveau bug parce qu'on patchait sans vue d'ensemble. »*

On a empilé **5 stratégies différentes de sélection des clips** dans une même fonction (`select_best_clips`) :
1. Multi-segment basé Gemini
2. Fallback positionnel briefing/embarquement
3. Extension contextuelle (étendre les scènes courtes)
4. Subdivision multi-segment (sous_voile en 3 cuts)
5. Stratégie positionnelle pure (réécriture finale)

Chaque stratégie résolvait un cas mais cassait un autre. Le code legacy n'a jamais été supprimé, créant des interactions imprévisibles.

---

## Liste des bugs rencontrés (chronologique)

### 1. Quota Gemini free tier épuisé (8h00)
**Symptôme** : `429 RESOURCE_EXHAUSTED` après 4 runs.
**Cause** : free tier 20 req/jour, multi-runs de test cumulés.
**Fix** : Activation Tier 1 + nouvelle clé API dans projet santolanlabs lié au billing.
**Leçon** : ⚠️ Toujours utiliser un projet GCP avec billing actif, même en dev.

### 2. SDK Gemini déprécié (`google.generativeai`)
**Symptôme** : Quota 0 sur les nouveaux modèles malgré Tier 1.
**Cause** : Ancien SDK ne propage pas correctement le tier.
**Fix** : Migration vers `google-genai`.
**Leçon** : ⚠️ Surveiller les warnings de dépréciation des SDK.

### 3. Modèle `gemini-flash-latest` (= gemini-3-flash) en preview
**Symptôme** : `limit: 0` même sur Tier 1.
**Cause** : Modèles preview ont des quotas séparés.
**Fix** : Bascule sur `gemini-2.5-flash` stable + fallback `flash-lite`.
**Leçon** : ⚠️ Pin un modèle stable, pas `*-latest`.

### 4. Modèle `gemini-2.0-flash` 404 pour nouveaux comptes
**Symptôme** : `This model is no longer available to new users`.
**Cause** : Modèle déprécié pour les nouveaux comptes Tier 1 créés après une certaine date.
**Fix** : `gemini-2.5-flash` (current).
**Leçon** : ⚠️ Tester avec un appel simple AVANT de lancer le pipeline complet.

### 5. Gemini 503 UNAVAILABLE (surcharge serveur matinale)
**Symptôme** : 100% des frames retournent 503.
**Cause** : Pic de charge mondial sur 2.5-flash.
**Fix** : Retry exponentiel + fallback automatique vers `flash-lite`.
**Leçon** : ✅ Toujours coder retry + fallback pour les API cloud.

### 6. Pipeline retourne "succès" en fallback narratif silencieux
**Symptôme** : Statut succes mais aucune classification réelle.
**Cause** : Les frames Gemini en erreur étaient ignorées au lieu de marquer le run comme dégradé.
**Fix** : Log explicite `Fallback narratif active`.
**Leçon** : ❌ "Soft fail" trompeur. Le statut devrait être `partiel` ou un sous-niveau explicite.

### 7. Faststart MP4 non appliqué par AMD AMF
**Symptôme** : Vidéo refuse de jouer dans Movies & TV Windows.
**Cause** : Encodeur GPU AMD AMF n'écrit pas toujours moov atom au début.
**Fix** : Re-mux explicite `ffmpeg -c copy -movflags +faststart` en fin de pipeline.
**Leçon** : ⚠️ Toujours faire un re-mux final pour garantir la compatibilité lecteurs.

### 8. Doublons visuels — extension contextuelle qui chevauche
**Symptôme** : "2 fois la sortie d'avion".
**Cause** : `select_best_clips` étendait `sortie_avion` backward de 15s, qui chevauchait `chute_libre` étendue symétriquement.
**Fix** : `_resolve_overlaps` — mais introduit un nouveau bug (cf #9).
**Leçon** : ❌ Les "fixes" qui ne traitent pas la cause profonde créent des bugs en cascade.

### 9. `_resolve_overlaps` trop agressif
**Symptôme** : Chute libre de 90s tronquée à 4s.
**Cause** : Seuil de chevauchement trop bas (5s) — coupait des scènes entières.
**Fix** : Seuil relaxé à 15s, puis stratégie positionnelle qui supprime le besoin de _resolve_overlaps.
**Leçon** : ❌ Les fix défensifs (anti-overlap) traitent les symptômes, pas la cause.

### 10. Mélange de 2 sources de positionnement (BUG ROOT CAUSE)
**Symptôme** : Le contenu vidéo "sautait" — briefing source 0-10s, dans_avion source 157s, paysage source 25s, retour source 127s.
**Cause profonde** : `select_best_clips` mélangeait :
- Segments **fallback positionnel** (basés sur position 0-132s)
- Segments **Gemini réels** (à 144-456s)
L'ordre narratif des SCÈNES était respecté mais le contenu VIDÉO sautait dans tous les sens.
**Fix** : Réécriture complète en stratégie positionnelle pure (Gemini → marqueurs uniquement).
**Leçon** : 🎯 **C'était le bug le plus important de la session**. Le diagnostic a pris 4h car on patchait des symptômes au lieu de chercher le mismatch entre les sources de données.

### 11. Gemini classifie 132s du début en "montee_avion"
**Symptôme** : Briefing/embarquement/dans_avion absents même sur fallback positionnel.
**Cause** : `gemini-flash-lite` (utilisé par fallback 503) est moins précis que `flash`.
**Fix** : Fallback positionnel étendu pour découper le gros segment "montee_avion" en briefing + embarquement + dans_avion + paysage_avion + montée.
**Leçon** : ⚠️ La qualité de Gemini n'est pas constante. Toujours prévoir un fallback par signal alternatif (télémétrie, position).

### 12. Atterrissage tronqué à 12s (au lieu de 35s)
**Symptôme** : "Je n'ai pas l'atterrissage complet".
**Cause** : Vidéo finit à 472s, atter_start (Gemini) = 460s → 12s seulement.
**Fix** : Étendre atter_start en arrière si `atter_end - atter_start < target`.
**Leçon** : ✅ Quand une fenêtre est trop courte, l'étendre dans la direction où on a de la matière.

---

## Causes profondes (analyse 5 Why)

### Pourquoi tant de bugs ?

1. **Pas de tests automatisés** — chaque modif crée une régression silencieuse, on découvre les bugs en visionnant le résultat 5-10 min plus tard
2. **Logique de sélection trop complexe** — `select_best_clips` fait 6 jobs en même temps (multi-segment, fallback, extension, subdivision, anti-overlap, ordre narratif). Trop de couplage.
3. **Pas de validation post-montage** — on retourne "succès" même quand le montage est cassé. Le pipeline ne vérifie pas la durée finale, l'ordre des scènes, etc.
4. **Logging insuffisant** — beaucoup de bugs se sont révélés visuellement, pas dans les logs. Manque de métriques (durée par scène, % couverture des scènes attendues, etc.).
5. **Hardcoding** — durées scènes en dur dans le code. Pas adaptable selon longueur vidéo source.
6. **Mélange de signaux** — Gemini + fallback positionnel + télémétrie utilisés simultanément sans hiérarchie claire de fiabilité.
7. **Pas de POSTMORTEM en temps réel** — on a découvert tard que certains "patches" interagissaient mal. Une analyse à mi-session aurait économisé 2h.

---

## Patterns observés (anti-patterns à éviter)

### 🚫 Patch-driven development sous pression
On a fait 7 versions, chacune fixant 1-2 bugs et en introduisant 0-1. Net positif faible.
**Mieux** : prendre 30 min pour comprendre la cause profonde **avant** de coder.

### 🚫 Fonctions qui font trop de choses
`select_best_clips` faisait : sélection + fallback + extension + subdivision + anti-overlap + ordering = 6 responsabilités. Impossible à raisonner.
**Mieux** : Single Responsibility Principle. Une fonction par job.

### 🚫 Code legacy non supprimé
Après refacto, garde `_resolve_overlaps` "au cas où". Mais il introduit toujours du risque.
**Mieux** : `git revert` ou suppression franche, pas de code mort qui peut être réutilisé par accident.

### 🚫 Pipeline "boîte noire"
Le user voit le résultat final, on devine ce qui s'est passé.
**Mieux** : exposer les segments sélectionnés, durées par scène, marqueurs détectés, % de fiabilité Gemini.

### 🚫 Faire confiance à Gemini sans validation croisée
Gemini a placé `chute_libre` à 180s alors que la télémétrie disait 132s. On a perdu 4h là-dessus.
**Mieux** : Hiérarchie de signaux : télémétrie (±0.1s) > vision (±15s) > heuristique (±X%).

---

## Décisions clés prises (et leur justification)

| Décision | Pourquoi | Coût |
|---|---|---|
| Migration `google.generativeai` → `google-genai` | Tier 1 propre | 30 min |
| Tier 1 payant Gemini | Plus de limite quota dev | 0 € (10 € prépayé encore) |
| Stratégie positionnelle pure | Garantit ordre temporel | 1h refacto |
| Télémétrie comme source vérité | Précision ±0.1s vs Gemini ±15s | Déjà codé |
| Faststart auto en fin de pipeline | Lecture universelle | 10 min |
| `_resolve_overlaps` désactivé | Plus utile en stratégie positionnelle | Suppression |

---

## Ce qu'il faut maintenant pour ne pas reproduire ça

### Court terme (cette session)
1. **Tests pytest** sur les fonctions critiques (`select_best_clips`, `analyze_skydive`, `_cut_clip`)
2. **Validation post-montage** : check durée finale, intégrité fichier, scènes présentes
3. **Adaptive durations** : la durée des scènes scale avec la longueur de la vidéo source
4. **Filtrage altitudes aberrantes** : `alt_min = -767m` non sensé, à filtrer
5. **Logging structuré** : un dict `metrics` qui contient tout ce qui s'est passé (durée par scène, modèle Gemini utilisé, fallbacks déclenchés, etc.)
6. **Configuration externalisée** : `config/montage_profile.yaml` avec les durées
7. **Documentation** : un guide "Comment marche le pipeline" en 1 page

### Moyen terme (semaine prochaine)
- Refacto `select_best_clips` en plusieurs fonctions atomiques testables
- Suppression du code legacy
- CI GitHub Actions qui run pytest sur PR
- Profil "saut court" / "saut long" / "saut sans réaction post"

### Long terme
- Détection scène 100% local (PySceneDetect + télémétrie) → réduire dépendance Gemini
- Tests d'intégration sur 5+ vidéos types

---

## Métriques de la session

| Métrique | Valeur |
|---|---|
| Lignes de code modifiées | ~600 |
| Commits | 8 |
| Versions de montage testées | 7 (v3-v9) |
| Bugs identifiés et fixés | 12 |
| Bugs introduits par les fixes | ~4 |
| Temps perdu sur le bug "mélange de sources" | ~2h |
| Coût API Gemini (Tier 1) | < 1 € (très loin du plafond 20€/mois) |

---

## Citation à retenir

> *« Cherche le problème en profondeur, putain »* — l'utilisateur, à la 5ème itération, exaspéré

C'est ce qui a finalement débloqué la session. À retenir : **prendre 30 min pour comprendre VRAIMENT la cause avant de coder un nouveau fix**.

---

**Auteur** : analyse Claude Sonnet 4.7 — session du 2026-04-28
**Branche concernée** : `chore/demo-prep`
**Commits référencés** : `c91c687` → `68bdaf4`

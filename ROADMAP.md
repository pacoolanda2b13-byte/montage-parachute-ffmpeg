# Roadmap — Montage Parachute FFmpeg

Feuille de route du projet, par phases. Chaque phase est livrable indépendamment.
Objectif prioritaire défini avec l'utilisateur : **fiabiliser l'orchestration**.

---

## Contexte technique

Le projet a **3 couches** :

| Couche | Fichier | Rôle |
|---|---|---|
| Moteur | `montage_parachute_ffmpeg.py` | Normalisation des clips + transitions xfade + encodage |
| API | `serveur_api.py` | API Flask (montage, upload, statut, téléchargement) |
| Orchestration | `n8n_workflow_parachute_ffmpeg.json` | Drive → API → Drive → email |

### Windows / Linux / Hermes — à retenir
- L'environnement de dev cloud tourne sous **Linux** (jetable, ce n'est pas le PC de l'utilisateur).
- Le serveur de prod cible : **Linux** recommandé.
- **Hermes (LLM Nous Research) n'exige PAS Linux** : il tourne sous Windows via Ollama / LM Studio (`ollama run hermes3`).
- Pour l'objectif « fiabiliser l'orchestration », Hermes (LLM) n'est **pas** le bon outil → il intervient en dernier (Phase 4). La fiabilité passe par une vraie file de jobs + corrections de bugs.

---

> **Vidéos sources** : 6 clips réels (`clip1.mp4` … `clip6.mp4`) sont sur le
> Google Drive de l'utilisateur, dossier **"Parachute Sources"**. Le connecteur
> Drive ne permet pas de les rapatrier ici (téléchargement base64 trop volumineux
> pour le contexte). Test grandeur nature à faire sur la machine de l'utilisateur
> (`python monter.py sources/`) ou via N8N branché sur Drive.

## Phase 0 — Fondations & validation
- [x] Rendre le moteur **Linux-compatible** (détection FFmpeg multi-OS).
- [x] Valider le montage de bout en bout (clips de test, FFmpeg réel).
- [ ] Décider l'OS cible du serveur (Linux recommandé).

## Phase 0.5 — Simplification (tout-en-un Python)
- [x] `monter.py` : un dossier en entrée → un montage en sortie, transitions auto.
- [x] Tri naturel des fichiers (clip2 avant clip10).
- [x] Styles prédéfinis (`dynamique`, `cinematique`).

## Phase 1 — Bugs bloquants
- [ ] **Intégration N8N ↔ API** : N8N télécharge les vidéos mais ne les transmet jamais à l'API
      (elle n'attend que des noms de fichiers). À corriger via upload réel (`/upload`) ou volume partagé.
      *Sans ça, le workflow ne tourne pas de bout en bout.*
- [ ] **Clips sans audio** : gérer les vidéos GoPro muettes (sinon le mapping `[i:a]` plante le rendu).
- [ ] **Sécurité** : restreindre les chemins de `fichiers` à `DOSSIER_SOURCES` (lecture de fichiers arbitraires aujourd'hui).
- [ ] **Sync A/V** : vérifier l'alignement audio (`acrossfade` sans offset) vs vidéo (`xfade` avec offset) sur 4-5 clips.

## Phase 2 — Fiabiliser l'orchestration (objectif principal)
- [ ] Remplacer `jobs = {}` + threading par une **file Redis + RQ** : persistance, retries, **1 FFmpeg à la fois**.
- [ ] Logs structurés + endpoint `/sante` enrichi.
- [ ] **Dockerfile + docker-compose** (API + Redis + FFmpeg) → déploiement reproductible, fin du casse-tête Windows/Linux.

## Phase 3 — Qualité & confiance
- [ ] Tests automatisés (moteur + routes API).
- [ ] **README** complet (install, usage, déploiement).
- [ ] CI GitHub Actions (lint + tests à chaque push).

## Phase 4 — Couche IA (Hermes)
- [ ] Génération auto titre / description YouTube / hashtags via Hermes.
- [ ] Choix des transitions selon une consigne en langage naturel.
- [ ] (Optionnel) Détection des meilleurs moments du saut.

---

## Pistes d'intégration (alternatives à N8N)
Connecteurs disponibles pouvant remplacer ou compléter N8N :
- **Google Drive** : lister / télécharger / uploader les vidéos.
- **Gmail** : notifications succès / erreur.
- **Vercel** : déploiement de l'API.
- **GitHub** : PRs, CI, issues.

Deux stratégies :
- **Garder N8N** comme orchestrateur visuel, fiabiliser l'API derrière.
- **Remplacer N8N** par un orchestrateur Python utilisant ces APIs directement (plus robuste, moins visuel).

---

## Ordre conseillé
**Commencer par la Phase 1 (bug N8N ↔ API)** : sans elle, rien ne tourne en conditions réelles.

# Vision SaaS — Montage parachutisme automatisé

> Document de cap. Décrit **où on va** et **dans quel ordre**, pour ne pas se
> disperser. Aucune ligne de code n'est imposée ici : c'est la carte, pas le moteur.

---

## 1. Le projet en une phrase

**Permettre à une école de parachutisme de livrer automatiquement, à chaque
élève, une vidéo montée de son saut — sans monteur vidéo.**

- **Cible** : écoles / centres de parachutisme (pas les particuliers au départ).
- **Pourquoi les écoles** : une école fait des dizaines de sauts/jour, chaque
  élève veut SA vidéo. Volume récurrent = vrai besoin, vrai marché.
- **Statut actuel** : **prototype perso** (faire marcher pour soi avant de vendre).

---

## 2. Ce qui existe déjà (acquis)

| Brique | État | Fichier |
|---|---|---|
| Moteur de montage (transitions, normalisation, encodage) | ✅ fait, testé | `montage_parachute_ffmpeg.py` |
| Gestion clips muets (GoPro) | ✅ fait | idem |
| Orchestrateur tout-en-un (1 dossier → 1 montage) | ✅ fait, testé | `monter.py` |
| API HTTP (upload, montage, statut, download) | ✅ fait, durcie | `serveur_api.py` |
| Tests automatisés | ✅ 22 tests verts | `tests/` |
| Workflow N8N (Drive → API → Drive → email) | ⚠️ existe, chaînon Drive à finir | `n8n_workflow_parachute_ffmpeg.json` |

**Le cœur technique le plus difficile (le montage) est déjà résolu.**

---

## 3. La brique manquante n°1 : le regroupement par élève

C'est LE point spécifique au métier « école ». Un saut filmé = plusieurs sources
(caméra main du moniteur, caméra casque, drone/sol). Il faut regrouper les bons
clips pour le bon élève.

Convention proposée pour le prototype : **un sous-dossier = un élève/saut.**

```
sources/
├── 2026-05-29_dupont/
│   ├── clip1.mp4   (sortie avion)
│   ├── clip2.mp4   (chute libre)
│   └── clip3.mp4   (sous voile)
└── 2026-05-29_martin/
    ├── clip1.mp4
    └── clip2.mp4
```

→ `monter.py` en **mode lot** produit `output/2026-05-29_dupont.mp4`,
`output/2026-05-29_martin.mp4`, etc., en une commande.

---

## 4. Feuille de route SaaS (du prototype au produit)

### Étape A — Prototype perso (maintenant)
But : **ça marche pour moi, sur ma machine, avec mes vraies vidéos.**
- [ ] Tester `monter.py` sur les 6 vraies vidéos (sur la machine de l'utilisateur).
- [ ] **Mode lot par élève** (un sous-dossier → un montage).
- [ ] **Branding école** : intro/logo + nom de l'élève en surimpression.
- [ ] Choisir 2-3 styles de montage validés visuellement.

### Étape B — Pilote avec UNE école (validation marché)
But : **une vraie école teste, on apprend.**
- [ ] Process simple de réception des vidéos (dossier partagé Drive/Dropbox).
- [ ] Livraison du montage (lien de téléchargement par élève).
- [ ] Mesurer : temps gagné, qualité perçue, prix acceptable.
- [ ] (Option) File de jobs si le volume le justifie (Redis/RQ).

### Étape C — Produit payant (si le pilote convainc)
But : **plusieurs écoles, en autonomie, paiement.**
- [ ] Page web : l'école dépose ses vidéos, suit l'avancement.
- [ ] Comptes / espaces isolés par école.
- [ ] Paiement / abonnement (Stripe).
- [ ] Stockage cloud par client (S3 ou Drive).
- [ ] Orchestration interne robuste (file de jobs + retries + notifications).
  - C'est ici que **n8n + n8n-mcp** ou un orchestrateur Python prennent leur sens.

---

## 5. Outils notés pour plus tard (PAS maintenant)

- **n8n + [n8n-mcp](https://github.com/czlonkowski/n8n-mcp)** (MCP, 21k★, MIT) :
  permet à Claude de construire/piloter des workflows n8n sur une instance
  auto-hébergée (`N8N_API_URL` + `N8N_API_KEY`). Pertinent à l'**Étape C** pour
  l'orchestration et les notifications. Surdimensionné en phase prototype.
- **Hermes (LLM)** : génération auto de titres/descriptions, choix de style en
  langage naturel. Pertinent une fois le pipeline solide. Tourne sous Windows
  via Ollama (`ollama run hermes3`) — Linux non requis.

---

## 6. Principe directeur

> **Une seule pièce mobile à la fois.** Tant qu'on est en prototype, on reste
> sur le tout-en-un Python (simple à déboguer). On n'ajoute n8n, le web ou le
> paiement que lorsqu'une vraie école valide le besoin. Pas avant.

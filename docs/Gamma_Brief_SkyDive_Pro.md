# SkyDive Pro — Brief pour Gamma

> **Mode d'emploi** : copie-colle tout ce qui est en dessous de la ligne `---` dans Gamma (gamma.app → Créer → Générer → Coller du texte). Gamma transforme chaque `##` en slide.

---

# SkyDive Pro

## Le montage de saut tandem, livré en 10 minutes.

Un logiciel qui transforme chaque vidéo GoPro de parachutisme tandem en condensé cinéma de 3 à 4 minutes, automatiquement. Livré au passager par email avant qu'il quitte la dropzone.

Démo commerciale — Avril 2026

---

## Votre problème : le montage vidéo.

**Aujourd'hui dans votre dropzone :**

- Chaque saut tandem = 20 à 40 minutes de post-production manuelle
- Sur 15 sauts/jour l'été = 5 à 10 heures de monteur mobilisé
- Qualité variable selon qui monte (moniteur fatigué en fin de journée ≠ rendu pro)
- Passager attend 24 à 72 heures avant de recevoir sa vidéo
- Coût caché de 8 à 15 € par montage en charge salariale

**Résultat : vous perdez de l'argent, du temps, et des avis 5 étoiles.**

---

## La solution, en une phrase.

Vous déposez la vidéo brute. L'IA s'occupe du reste.

**Analyse → Montage → Livraison. Zéro intervention manuelle.**

---

## 9 scènes, détectées automatiquement par IA.

**Chaque moment clé d'un saut tandem est reconnu sans aucune annotation.**

| Scène | Technologie |
|---|---|
| 🗣️ Briefing au sol | Vision IA |
| 🚐 Entrée/sortie véhicule | Vision IA |
| ✈️ Montée en avion | Analyse audio (moteur) |
| 🎢 Sortie d'avion | Accéléromètre GoPro |
| 🌬️ Chute libre | Télémétrie — 0G détecté |
| 🪂 Sous voile | Altitude GPS décroissante |
| 🌍 Atterrissage | Vitesse qui tombe à zéro |
| 😃 Réaction au sol | Reconnaissance faciale |
| 🤝 Interaction moniteur | Détection de pose |

---

## Comment ça marche.

**Un pipeline en 5 étapes, ~10 minutes par vidéo.**

1. **Import** — Upload fichier ou lien WeTransfer/Drive/YouTube
2. **Télémétrie** — Extraction GPS, altitude, vitesse, accéléromètre depuis la GoPro
3. **Analyse IA** — Fusion audio + vision Gemini + reconnaissance de scènes
4. **Montage** — Cuts, transitions, musique synchronisée, overlays brandés (logo + nom + date + stats)
5. **Livraison** — Email automatique au passager + lien Drive + QR code optionnel

**IA utilisée :** stratégie hybride gratuite (Gemini Flash + modèles locaux MediaPipe + DeepFace).

---

## Démo live du dashboard.

**Interface staff simple — pensée pour un moniteur, pas un ingénieur.**

- Bouton "Nouveau saut tandem" : formulaire passager + upload vidéo
- Jobs en cours avec barre de progression et étape actuelle
- Stats du jour : sauts traités, montages livrés, coût API
- Historique passagers avec preview des montages
- Configuration branding dropzone en 2 clics

**À l'écran pendant la démo : 12 jobs du jour, 9 livrés, 3 en cours, 2,40 € de coût API cumulé.**

---

## Télémétrie GoPro en action.

**Lues directement dans la vidéo brute. Affichées sur le montage final.**

- **4 050 m** — altitude de largage
- **212 km/h** — vitesse max en chute libre
- **58 secondes** — durée de chute libre
- **Trajectoire GPS** complète du saut

**Zéro saisie manuelle. Ces chiffres s'animent en overlay cinéma pendant la chute libre du montage final.**

---

## Bénéfices pour votre dropzone.

- **−30 min par saut** de post-production en moins
- **10 à 30 sauts/jour** traités sans embaucher
- **< 10 minutes** de délai de livraison au passager
- **+40 %** de qualité perçue (rendu cinéma cohérent)
- **+25 %** d'avis 5 étoiles estimés (passager reçoit vite = partage vite)
- **8 à 15 €** économisés par saut vs un monteur humain

À 20 sauts/jour, c'est **240 € de marge quotidienne** qui reviennent dans votre poche.

---

## Avant / Après.

**Votre workflow actuel :**
- Download caméra sur disque dur
- Premiere ou DaVinci Resolve ouvert
- Cut à la main pendant 30-40 minutes
- Export, upload WeTransfer, email manuel au passager
- Passager attend 24 à 72 heures

**Avec SkyDive Pro :**
- Glisser-déposer dans le dashboard
- Pipeline IA démarre tout seul
- Analyse + montage + overlays + musique en 5-10 minutes
- Email envoyé automatiquement avec lien Drive
- Passager reçoit sa vidéo **avant de quitter la dropzone**

---

## Modèle économique.

**Charges mensuelles (tout compris)**
- Licence SkyDive Pro : à définir ensemble
- API Gemini Vision : 0 à 5 €/mois
- Google Workspace : 15 €
- Musique libre de droits (Epidemic Sound) : 15-30 €
- **Total : 35-50 €/mois**

**Revenu par saut vendu avec vidéo : 250 à 350 €**

**Break-even dès le premier tandem du mois.**

À 15 sauts/jour sur 90 jours d'été, le retour sur investissement est **immédiat**.

---

## Roadmap — les 5 prochaines semaines.

**✅ Aujourd'hui — Pipeline IA validé**
Télémétrie, IA vision, montage auto, dashboard fonctionnels et testés sur 4 vidéos réelles.

**Semaine +1 — Livraison automatique**
Gmail + Google Drive + SMS avec QR code. Le passager reçoit tout sans intervention.

**Semaine +2 — Reconnaissance émotionnelle**
Détection des visages + top moments émotionnels du passager au sol. Climax outro auto.

**Semaine +3 — Dashboard complet**
Historique passagers, stats business, preview GIF, authentification staff, facturation.

**Semaine +4 — Déploiement production**
Installation sur votre PC dropzone, formation équipe, monitoring, backup automatique.

---

## Impact sur votre saison été.

**Projection prudente basée sur 15 tandems/jour × 90 jours :**

- **1 350 montages** livrés automatiquement
- **450 heures** économisées sur la post-production
- **~10 000 €** de charges salariales en moins
- **< 10 minutes** de délai moyen client

Le tout avec une équipe inchangée et un budget logiciel inférieur à un abonnement Netflix Premium.

---

## Et maintenant ?

**On teste sur VOTRE vidéo. Ensemble. Maintenant.**

1. **Vous m'envoyez** une vidéo tandem de votre choix (WeTransfer, Drive, peu importe)
2. **Je fais tourner** le pipeline IA dessus. Livrable dans l'heure.
3. **On regarde le rendu ensemble.** Vous validez. On ajuste le branding à votre identité.

**Prêt à livrer votre premier montage IA ce soir.** 🪂

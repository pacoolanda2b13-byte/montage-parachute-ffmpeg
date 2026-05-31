# Benchmark Vision Locale — Moondream vs Qwen2.5-VL vs Qwen3-VL

> **But** : mesurer sur ton PC (AMD GPU) si on peut remplacer Gemini Flash par
> un modèle vision local **gratuit** dans `scene_detector.py`.

## Setup — 15 min chrono

### 1. Installer Ollama (Windows, 1 clic)

Télécharge l'installeur : **https://ollama.com/download/windows**

Une fois installé, Ollama tourne en service en arrière-plan. Vérifie :

```powershell
ollama --version
# puis :
curl http://localhost:11434/api/tags
```

Si `curl` répond avec du JSON → Ollama est prêt.

### 2. Pull des 3 modèles

```powershell
ollama pull moondream          # ~1.7 GB
ollama pull qwen2.5vl:3b       # ~3.3 GB
ollama pull qwen3-vl:4b        # ~4.5 GB (si disponible)
```

**Total : ~10 GB de download.** À faire une seule fois.

> Si `qwen3-vl:4b` n'existe pas encore sur Ollama, remplace par la variante
> disponible (`ollama search qwen`). Le script s'adapte automatiquement aux
> modèles présents.

### 3. Installer `requests` côté Python

```powershell
cd "C:\Users\pacoo\OneDrive\Desktop\IA\SaaS parachutisme\skydive_pro"
.\.venv\Scripts\pip install requests pillow
```

---

## Lancer le benchmark

```powershell
cd "C:\Users\pacoo\OneDrive\Desktop\IA\SaaS parachutisme\skydive_pro"
.\.venv\Scripts\python scripts\bench_vision_models.py tests\fixtures\karma.mp4
```

**Ce que ça fait** :
1. Extrait 6 keyframes de `karma.mp4` (12 s vidéo → 1 frame toutes les 2 s)
2. Envoie chaque frame aux 3 modèles via l'API locale Ollama
3. Chronomètre chaque appel
4. Demande aux modèles de classer dans une des 9 scènes du saut
5. Imprime un tableau récap + dump JSON pour analyse

---

## Sortie attendue (exemple)

```
─── moondream ─────────────────────────────────────
  warmup... 3.8s
  ✓ [ 1/6] kf_001.jpg → autre                     0.82s
  ✓ [ 2/6] kf_002.jpg → chute_libre               0.79s
  ...

─── qwen2.5vl:3b ──────────────────────────────────
  warmup... 6.2s
  ✓ [ 1/6] kf_001.jpg → autre                     1.43s
  ...

══════════════════════════════════════════════════════════════════════
RÉSUMÉ — 6 keyframes de karma.mp4
══════════════════════════════════════════════════════════════════════
Modèle                   Warmup     Moy     Min     Max    OK
----------------------------------------------------------------------
moondream                  3.8s   0.85s   0.78s   1.12s   6/6
qwen2.5vl:3b               6.2s   1.52s   1.41s   1.88s   6/6
qwen3-vl:4b                7.1s   1.95s   1.80s   2.21s   6/6
```

---

## Comment interpréter les résultats

### 🟢 Scénario "vas-y, swap Gemini"
- ≥ 80 % des labels entre modèles sont identiques
- Latence moyenne < 2 s sur le plus lent
- Aucune erreur / timeout

→ Ticket **T-15** : remplacer l'adapter Gemini par Ollama dans `scene_detector.py`

### 🟡 Scénario "garde Gemini en fallback"
- Moondream rapide mais classif incohérente sur certaines scènes
- Qwen2.5 bon mais latence ≥ 3 s
- Diverge de la vérité terrain (tu dois valider à l'œil)

→ Stratégie hybride : **Moondream d'abord, Gemini si confiance faible**

### 🔴 Scénario "reste sur Gemini"
- Erreurs fréquentes / timeouts
- VRAM insuffisante (ton GPU swappe avec la RAM)
- Labels non-sensés (ex: `atterrissage` pour une scène de briefing)

→ Reporter le switch, rester sur Gemini + upgrader plus tard

---

## Limites du bench

- **karma.mp4 = 12 s de drone, pas de saut tandem**. Les labels "vraie vie"
  seront plus fiables sur une vraie vidéo tandem (WeTransfer ce soir).
- Pas de mesure de **précision absolue** : on compare juste la **cohérence**
  entre modèles. Pour un vrai score, il faudrait labelliser manuellement
  20-50 keyframes comme ground truth.
- Latence mesurée côté Python — inclut le round-trip HTTP local (~5 ms
  négligeables).

---

## Next step après le bench

Si Moondream gagne → créer `skydive_pro/adapters/ollama_vision.py`
avec la même interface que l'appel Gemini actuel, et ajouter un paramètre
`VISION_BACKEND=ollama|gemini` dans `.env`.

Je peux coder ça en ~30 min une fois qu'on a les chiffres.

"""
bench_vision_models.py — Benchmark vision locaux vs Gemini pour SkyDive Pro.

Objectif : mesurer **latence + qualité** de 3 modèles vision sur des keyframes
extraites d'une vidéo skydive, afin de choisir le modèle qui remplacera Gemini
dans `core/scene_detector.py`.

Modèles testés (par défaut) :
    - moondream          (1.8B — petit, rapide)
    - qwen2.5vl:3b       (3B — sweet spot)
    - qwen3-vl:4b        (4B — dernière génération)

Pré-requis :
    1. Ollama installé et démarré (https://ollama.com/download/windows)
    2. Modèles pullés :
           ollama pull moondream
           ollama pull qwen2.5vl:3b
           ollama pull qwen3-vl:4b   # ou remplace par celui dispo
    3. ffmpeg dans le PATH
    4. pip install requests pillow

Usage :
    cd skydive_pro
    python scripts/bench_vision_models.py tests/fixtures/karma.mp4

Sortie :
    - Console : tableau latence + classification par modèle
    - JSON    : bench_results_<timestamp>.json pour comparaison ultérieure
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("[ERREUR] pip install requests", file=sys.stderr)
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════
OLLAMA_URL = "http://localhost:11434/api/generate"
MODELS = ["moondream", "qwen2.5vl:3b", "qwen3-vl:4b"]

SCENE_LABELS = [
    "briefing", "vehicule_embarquement", "montee_avion",
    "sortie_avion", "chute_libre", "sous_voile",
    "atterrissage", "reaction_emotion", "interaction_moniteur",
    "autre",
]

PROMPT = f"""Tu es un classifieur de scènes de saut tandem en parachutisme.
Classe cette image dans EXACTEMENT UNE des catégories suivantes :
{", ".join(SCENE_LABELS)}.

Réponds UNIQUEMENT avec le nom de la catégorie, en minuscules, sans phrase,
sans explication. Exemple de bonne réponse : chute_libre"""


# ══════════════════════════════════════════════════════════════
#  Extraction keyframes
# ══════════════════════════════════════════════════════════════
def extract_keyframes(video: Path, out_dir: Path, interval_s: int = 2,
                       max_frames: int = 12) -> list[Path]:
    """Extrait des keyframes toutes les `interval_s` secondes (max N)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "kf_%03d.jpg"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video),
        "-vf", f"fps=1/{interval_s},scale=640:-1",
        "-frames:v", str(max_frames),
        "-q:v", "3",
        str(pattern),
    ]
    subprocess.run(cmd, check=True)
    frames = sorted(out_dir.glob("kf_*.jpg"))
    print(f"[OK] {len(frames)} keyframes extraites dans {out_dir}")
    return frames


# ══════════════════════════════════════════════════════════════
#  Appel Ollama
# ══════════════════════════════════════════════════════════════
def ollama_classify(model: str, image_path: Path,
                     timeout_s: int = 90) -> tuple[str, float, Optional[str]]:
    """Retourne (label_normalise, latence_s, erreur_ou_None)."""
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 20},
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout_s)
        latency = time.perf_counter() - t0
        if r.status_code != 200:
            return ("ERREUR", latency, f"HTTP {r.status_code}: {r.text[:200]}")
        raw = (r.json().get("response") or "").strip().lower()
        # Normalisation : on garde le 1er label valide trouvé dans la réponse
        label = "autre"
        for l in SCENE_LABELS:
            if l in raw:
                label = l
                break
        return (label, latency, None)
    except requests.exceptions.Timeout:
        return ("TIMEOUT", timeout_s, "timeout")
    except Exception as e:
        return ("ERREUR", time.perf_counter() - t0, str(e))


def check_ollama() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_installed_models() -> set[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return set()


# ══════════════════════════════════════════════════════════════
#  Bench principal
# ══════════════════════════════════════════════════════════════
def run_bench(video: Path, models: list[str],
               interval_s: int, max_frames: int) -> dict:
    if not check_ollama():
        print("[ERREUR] Ollama n'est pas accessible sur http://localhost:11434")
        print("         Télécharge-le sur https://ollama.com/download/windows")
        print("         Puis lance : ollama serve")
        sys.exit(2)

    installed = list_installed_models()
    missing = [m for m in models if not any(m in i for i in installed)]
    if missing:
        print(f"[AVERTISSEMENT] Modèles non installés : {missing}")
        print("  Pull : " + " ; ".join(f"ollama pull {m}" for m in missing))
        # on continue avec ceux qui sont dispo
        models = [m for m in models if any(m in i for i in installed)]
        if not models:
            sys.exit(3)

    tmp = Path(tempfile.mkdtemp(prefix="bench_kf_"))
    try:
        frames = extract_keyframes(video, tmp, interval_s, max_frames)
        if not frames:
            print("[ERREUR] Aucune keyframe extraite")
            sys.exit(4)

        results = {
            "video": str(video),
            "nb_frames": len(frames),
            "par_modele": {},
        }

        for model in models:
            print(f"\n--- {model} " + "-" * (50 - len(model)))
            # warmup (1er call charge le modèle en VRAM)
            print("  warmup...", end=" ", flush=True)
            _, warm, _ = ollama_classify(model, frames[0], timeout_s=180)
            print(f"{warm:.1f}s")

            per_frame = []
            labels_count: dict[str, int] = {}
            for i, f in enumerate(frames):
                label, lat, err = ollama_classify(model, f)
                per_frame.append({"frame": f.name, "label": label,
                                   "latency_s": round(lat, 2), "erreur": err})
                labels_count[label] = labels_count.get(label, 0) + 1
                status = "OK" if err is None else "KO"
                print(f"  {status} [{i+1:2d}/{len(frames)}] {f.name} → {label:26s} {lat:5.2f}s")

            latencies = [p["latency_s"] for p in per_frame if p["erreur"] is None]
            results["par_modele"][model] = {
                "warmup_s": round(warm, 2),
                "nb_ok": len(latencies),
                "latence_moyenne_s": round(sum(latencies)/len(latencies), 2) if latencies else None,
                "latence_min_s": round(min(latencies), 2) if latencies else None,
                "latence_max_s": round(max(latencies), 2) if latencies else None,
                "distribution_labels": labels_count,
                "par_frame": per_frame,
            }

        return results

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def print_summary(results: dict) -> None:
    print("\n" + "=" * 70)
    print(f"RESUME -- {results['nb_frames']} keyframes de {Path(results['video']).name}")
    print("=" * 70)
    print(f"{'Modèle':<22} {'Warmup':>8} {'Moy':>7} {'Min':>7} {'Max':>7} {'OK':>5}")
    print("-" * 70)
    for model, r in results["par_modele"].items():
        moy = f"{r['latence_moyenne_s']:.2f}s" if r["latence_moyenne_s"] else "—"
        mn = f"{r['latence_min_s']:.2f}s" if r["latence_min_s"] else "—"
        mx = f"{r['latence_max_s']:.2f}s" if r["latence_max_s"] else "—"
        print(f"{model:<22} {r['warmup_s']:>6.1f}s {moy:>7} {mn:>7} {mx:>7} "
              f"{r['nb_ok']:>3}/{results['nb_frames']}")

    print("\nDistribution des labels (par modèle) :")
    for model, r in results["par_modele"].items():
        dist = ", ".join(f"{k}={v}" for k, v in
                          sorted(r["distribution_labels"].items(), key=lambda x: -x[1]))
        print(f"  {model}: {dist}")


# ══════════════════════════════════════════════════════════════
#  Entrée
# ══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("video", type=Path, help="Vidéo à analyser")
    parser.add_argument("--models", nargs="+", default=MODELS,
                         help="Liste des modèles Ollama à tester")
    parser.add_argument("--interval", type=int, default=2,
                         help="Intervalle (s) entre keyframes (def: 2)")
    parser.add_argument("--max-frames", type=int, default=12,
                         help="Nb max de keyframes (def: 12)")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"[ERREUR] Vidéo introuvable : {args.video}")
        sys.exit(1)

    results = run_bench(args.video, args.models, args.interval, args.max_frames)
    print_summary(results)

    out_json = Path(f"bench_results_{int(time.time())}.json")
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    print(f"\n[OK] Résultats détaillés : {out_json}")


if __name__ == "__main__":
    main()

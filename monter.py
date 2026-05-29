"""
monter.py — Montage parachutisme tout-en-un.

Usage le plus simple (prend toutes les vidéos du dossier ./sources) :

    python monter.py

Ou en précisant un dossier et un style :

    python monter.py mes_videos/ --style dynamique
    python monter.py mes_videos/ --style cinematique -o saut_du_jour.mp4

Le script :
  1. récupère et trie naturellement les vidéos du dossier (clip1, clip2, ... clip10) ;
  2. choisit automatiquement les transitions selon le style choisi ;
  3. produit le montage dans ./output.

Aucune liste de transitions à taper à la main : tout est automatique.
"""

import argparse
import os
import re
import sys
from datetime import datetime

from montage_parachute_ffmpeg import creer_montage, verifier_ffmpeg, TRANSITIONS

EXTENSIONS_VIDEO = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm")

# Jeux de transitions par style. On pioche dedans en boucle pour varier.
STYLES = {
    # Rythmé : transitions visibles et variées.
    "dynamique": ["fade", "circleopen", "wipeleft", "radial", "slideup",
                  "diagtl", "zoomin", "dissolve", "wiperight", "circleclose"],
    # Posé : uniquement des fondus doux.
    "cinematique": ["fade", "dissolve", "fadeblack"],
}


def _cle_naturelle(nom: str):
    """Tri naturel : clip2 avant clip10 (et non l'inverse comme en tri ASCII)."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", nom)]


def trouver_videos(dossier: str) -> list:
    """Retourne les chemins des vidéos du dossier, triées naturellement."""
    if not os.path.isdir(dossier):
        raise NotADirectoryError(f"Dossier introuvable : {dossier}")
    noms = [n for n in os.listdir(dossier)
            if n.lower().endswith(EXTENSIONS_VIDEO)]
    noms.sort(key=_cle_naturelle)
    return [os.path.join(dossier, n) for n in noms]


def transitions_pour(style: str, n_clips: int) -> list:
    """Construit la liste des transitions (une par coupure) pour le style donné."""
    palette = STYLES.get(style, STYLES["dynamique"])
    nb_coupures = max(0, n_clips - 1)
    return [palette[i % len(palette)] for i in range(nb_coupures)]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Montage parachutisme tout-en-un (un dossier -> un montage).")
    parser.add_argument("dossier", nargs="?", default="./sources",
                        help="Dossier contenant les vidéos (défaut : ./sources)")
    parser.add_argument("-o", "--output", default=None,
                        help="Nom du fichier de sortie (défaut : montage daté)")
    parser.add_argument("--style", choices=list(STYLES.keys()), default="dynamique",
                        help="Style de transitions (défaut : dynamique)")
    parser.add_argument("--duree-clip", type=float, default=6.0,
                        help="Durée max par clip en secondes (défaut : 6)")
    parser.add_argument("--duree-transition", type=float, default=1.0,
                        help="Durée des transitions en secondes (défaut : 1.0)")
    parser.add_argument("--encodeur", default="libx264",
                        help="libx264 (CPU) | h264_nvenc (NVIDIA) | h264_amf (AMD)")
    args = parser.parse_args(argv)

    try:
        verifier_ffmpeg()
    except RuntimeError as e:
        print(f"[ERREUR] {e}", file=sys.stderr)
        return 1

    try:
        videos = trouver_videos(args.dossier)
    except NotADirectoryError as e:
        print(f"[ERREUR] {e}", file=sys.stderr)
        return 1

    if not videos:
        print(f"[ERREUR] Aucune vidéo trouvée dans '{args.dossier}'.\n"
              f"         Formats acceptés : {', '.join(EXTENSIONS_VIDEO)}",
              file=sys.stderr)
        return 1

    print(f"{len(videos)} vidéo(s) trouvée(s) dans '{args.dossier}' :")
    for v in videos:
        print(f"  - {os.path.basename(v)}")

    transitions = transitions_pour(args.style, len(videos))
    print(f"\nStyle : {args.style}  |  transitions : {transitions or '(aucune)'}")

    nom_sortie = args.output or f"montage_parachute_{datetime.now():%Y%m%d_%H%M%S}.mp4"

    cfg = {
        "duree_clip": args.duree_clip,
        "duree_transition": args.duree_transition,
        "encodeur": args.encodeur,
    }

    chemin = creer_montage(videos, nom_sortie, transitions, cfg)
    print(f"\n✅ Montage prêt : {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
montage_parachute_ffmpeg.py
Crée un montage vidéo parachutisme avec transitions FFmpeg xfade.
Dépendances : FFmpeg installé sur le système. Aucun pip requis.
"""

import subprocess
import os
import json
import tempfile
import shutil
from pathlib import Path


# ─────────────────────────────────────────────
#  DETECTION AUTOMATIQUE DE FFMPEG
# ─────────────────────────────────────────────
def _trouver_ffmpeg():
    """Cherche ffmpeg dans PATH puis dans les emplacements WinGet/courants."""
    import shutil as _shutil
    if _shutil.which("ffmpeg"):
        return "ffmpeg", "ffprobe"
    # Emplacements typiques Windows
    chemins = [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
    ]
    # WinGet
    winget_base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget_base):
        for d in os.listdir(winget_base):
            if "FFmpeg" in d or "ffmpeg" in d:
                candidate = os.path.join(winget_base, d)
                for root, dirs, files in os.walk(candidate):
                    if "ffmpeg.exe" in files:
                        chemins.insert(0, root)
                        break
    for rep in chemins:
        ff = os.path.join(rep, "ffmpeg.exe")
        fp = os.path.join(rep, "ffprobe.exe")
        if os.path.isfile(ff):
            return ff, fp
    return "ffmpeg", "ffprobe"


FFMPEG_BIN, FFPROBE_BIN = _trouver_ffmpeg()


# ─────────────────────────────────────────────
#  CONFIG — modifier ici selon votre machine
# ─────────────────────────────────────────────
CONFIG = {
    # Encodeur vidéo : "libx264" (CPU) | "h264_nvenc" (NVIDIA) | "h264_amf" (AMD) | "h264_videotoolbox" (Mac)
    "encodeur": "libx264",
    # Qualité CRF (0=lossless, 23=défaut, 28=léger) — ignoré avec GPU
    "crf": 23,
    # Bitrate GPU (ex: "8M") — utilisé uniquement avec encodeur GPU
    "bitrate_gpu": "8M",
    # Résolution de sortie (None = conserver l'originale)
    "resolution": "1920x1080",
    # FPS de sortie
    "fps": 30,
    # Durée de chaque clip (secondes, None = durée originale)
    "duree_clip": 5,
    # Durée des transitions (secondes)
    "duree_transition": 1.0,
    # Transition par défaut
    "transition_defaut": "fade",
    # Codec audio
    "codec_audio": "aac",
    # Bitrate audio
    "bitrate_audio": "192k",
    # Dossier de sortie
    "dossier_sortie": "./output",
    # Préset d'encodage CPU (ultrafast/superfast/veryfast/faster/fast/medium/slow/veryslow)
    "preset": "fast",
}

# ─────────────────────────────────────────────
#  TRANSITIONS DISPONIBLES (50+)
# ─────────────────────────────────────────────
TRANSITIONS = [
    "fade", "fadeblack", "fadewhite",
    "distance", "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circlecrop", "rectcrop",
    "circleopen", "circleclose",
    "vertopen", "vertclose", "horzopen", "horzclose",
    "dissolve", "pixelize",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "radial", "zoomin",
    "squeezev", "squeezeh",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
]


def verifier_ffmpeg():
    """Vérifie que FFmpeg est installé."""
    result = subprocess.run(
        [FFMPEG_BIN, "-version"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError("FFmpeg n'est pas installé ou introuvable dans le PATH.")
    version_line = result.stdout.split("\n")[0]
    print(f"[OK] {version_line}")


def preparer_clip(entree: str, index: int, dossier_tmp: str, cfg: dict) -> str:
    """
    Normalise un clip : résolution, FPS, durée.
    Retourne le chemin du clip normalisé.
    """
    sortie = os.path.join(dossier_tmp, f"clip_{index:03d}.mp4")
    resolution = cfg.get("resolution") or CONFIG["resolution"]
    fps = cfg.get("fps", CONFIG["fps"])
    duree = cfg.get("duree_clip", CONFIG["duree_clip"])

    vf_filters = [f"scale={resolution}:force_original_aspect_ratio=decrease",
                  f"pad={resolution}:(ow-iw)/2:(oh-ih)/2",
                  f"fps={fps}"]
    vf = ",".join(vf_filters)

    cmd = [FFMPEG_BIN, "-y", "-i", entree]
    if duree:
        cmd += ["-t", str(duree)]
    cmd += [
        "-vf", vf,
        "-c:v", "libx264",       # toujours CPU pour la préparation (rapide)
        "-preset", "ultrafast",
        "-crf", "18",
        "-c:a", cfg.get("codec_audio", CONFIG["codec_audio"]),
        "-b:a", cfg.get("bitrate_audio", CONFIG["bitrate_audio"]),
        "-ar", "44100",
        sortie
    ]
    print(f"  Préparation clip {index+1} : {os.path.basename(entree)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Erreur préparation clip {entree}:\n{result.stderr}")
    return sortie


def obtenir_duree(chemin: str) -> float:
    """Retourne la durée d'un fichier vidéo via ffprobe."""
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", chemin
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe impossible sur {chemin}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def construire_filtergraph_xfade(clips: list, transitions: list, duree_transition: float) -> tuple:
    """
    Construit le filtergraph FFmpeg pour enchaîner N clips avec xfade.
    Retourne (filter_complex, label_sortie_video, label_sortie_audio).
    """
    n = len(clips)
    if n == 1:
        return "", "[0:v]", "[0:a]"

    durees = [obtenir_duree(c) for c in clips]
    dt = duree_transition

    filter_lines = []
    offsets = []
    offset = 0.0
    for i in range(n - 1):
        offset += durees[i] - dt
        offsets.append(round(offset, 4))

    # Labels vidéo
    v_labels = [f"[{i}:v]" for i in range(n)]
    a_labels = [f"[{i}:a]" for i in range(n)]

    current_v = v_labels[0]
    current_a = a_labels[0]

    for i in range(n - 1):
        trans = transitions[i] if i < len(transitions) else CONFIG["transition_defaut"]
        if trans not in TRANSITIONS:
            trans = CONFIG["transition_defaut"]

        out_v = f"[xv{i}]"
        out_a = f"[xa{i}]"

        filter_lines.append(
            f"{current_v}{v_labels[i+1]}xfade=transition={trans}"
            f":duration={dt}:offset={offsets[i]}{out_v}"
        )
        filter_lines.append(
            f"{current_a}{a_labels[i+1]}acrossfade=d={dt}{out_a}"
        )
        current_v = out_v
        current_a = out_a

    filter_complex = "; ".join(filter_lines)
    return filter_complex, current_v, current_a


def creer_montage(
    fichiers_video: list,
    fichier_sortie: str,
    transitions: list = None,
    cfg: dict = None
) -> str:
    """
    Point d'entrée principal.

    Args:
        fichiers_video : liste de chemins vers les vidéos sources
        fichier_sortie : chemin du fichier de sortie (.mp4)
        transitions    : liste de noms de transitions (une par coupure)
                         ex: ["fade", "wipeleft", "circleopen"]
        cfg            : dict de config optionnel (surcharge CONFIG)

    Returns:
        Chemin absolu du fichier de sortie
    """
    if cfg is None:
        cfg = {}
    merged_cfg = {**CONFIG, **cfg}

    verifier_ffmpeg()

    if not fichiers_video:
        raise ValueError("Aucun fichier vidéo fourni.")

    if transitions is None:
        transitions = [merged_cfg["transition_defaut"]] * (len(fichiers_video) - 1)

    # Dossier de sortie
    os.makedirs(merged_cfg["dossier_sortie"], exist_ok=True)
    if not os.path.isabs(fichier_sortie):
        fichier_sortie = os.path.join(merged_cfg["dossier_sortie"], fichier_sortie)

    dossier_tmp = tempfile.mkdtemp(prefix="montage_parachute_")
    try:
        print(f"\n[1/3] Préparation des {len(fichiers_video)} clips...")
        clips_normalises = []
        for i, f in enumerate(fichiers_video):
            clip = preparer_clip(f, i, dossier_tmp, merged_cfg)
            clips_normalises.append(clip)

        print("\n[2/3] Construction du filtergraph FFmpeg...")
        filter_complex, label_v, label_a = construire_filtergraph_xfade(
            clips_normalises, transitions, merged_cfg["duree_transition"]
        )

        print("\n[3/3] Encodage final...")
        cmd = [FFMPEG_BIN, "-y"]
        for clip in clips_normalises:
            cmd += ["-i", clip]

        encodeur = merged_cfg["encodeur"]
        est_gpu = encodeur != "libx264"

        if filter_complex:
            cmd += ["-filter_complex", filter_complex,
                    "-map", label_v, "-map", label_a]
        else:
            cmd += ["-map", "0:v", "-map", "0:a"]

        cmd += ["-c:v", encodeur]

        if est_gpu:
            cmd += ["-b:v", merged_cfg["bitrate_gpu"]]
        else:
            cmd += ["-preset", merged_cfg["preset"], "-crf", str(merged_cfg["crf"])]

        cmd += [
            "-c:a", merged_cfg["codec_audio"],
            "-b:a", merged_cfg["bitrate_audio"],
            "-movflags", "+faststart",
            fichier_sortie
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Erreur FFmpeg encodage final:\n{result.stderr}")

        taille = os.path.getsize(fichier_sortie) / (1024 * 1024)
        print(f"\n[OK] Montage terminé : {fichier_sortie} ({taille:.1f} MB)")
        return os.path.abspath(fichier_sortie)

    finally:
        shutil.rmtree(dossier_tmp, ignore_errors=True)


# ─────────────────────────────────────────────
#  UTILISATION EN LIGNE DE COMMANDE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Montage vidéo parachutisme via FFmpeg")
    parser.add_argument("videos", nargs="+", help="Fichiers vidéo sources")
    parser.add_argument("-o", "--output", default="montage_final.mp4", help="Fichier de sortie")
    parser.add_argument("-t", "--transitions", nargs="*",
                        help=f"Transitions ({', '.join(TRANSITIONS[:8])}...)")
    parser.add_argument("--list-transitions", action="store_true",
                        help="Lister toutes les transitions disponibles")
    parser.add_argument("--encodeur", default=None,
                        help="Encodeur : libx264 | h264_nvenc | h264_amf")
    parser.add_argument("--duree-clip", type=float, default=None,
                        help="Durée max par clip (secondes)")
    parser.add_argument("--duree-transition", type=float, default=None,
                        help="Durée de chaque transition (secondes)")
    args = parser.parse_args()

    if args.list_transitions:
        print("Transitions disponibles :")
        for i, t in enumerate(TRANSITIONS, 1):
            print(f"  {i:2d}. {t}")
        exit(0)

    cfg_override = {}
    if args.encodeur:
        cfg_override["encodeur"] = args.encodeur
    if args.duree_clip is not None:
        cfg_override["duree_clip"] = args.duree_clip
    if args.duree_transition is not None:
        cfg_override["duree_transition"] = args.duree_transition

    creer_montage(args.videos, args.output, args.transitions, cfg_override)

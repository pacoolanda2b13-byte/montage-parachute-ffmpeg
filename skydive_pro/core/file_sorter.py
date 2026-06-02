"""
file_sorter.py — Classement des fichiers GoPro dans l'ordre narratif d'un saut tandem.

Stratégie :
    Pour chaque fichier vidéo (5-9 fichiers GoPro typiques), on extrait 3 signaux
    d'ordre independants, puis on vote pour determiner la sequence finale :

    1. Numero GoPro dans le nom de fichier (GX010045 -> 45, GOPR0123 -> 123)
    2. creation_time dans les metadonnees MP4 via ffprobe
    3. Profil d'altitude GPMF (montee = debut, chute rapide = milieu, sol = fin)

    Si >= 2 signaux sur 3 s'accordent -> confiance elevee.
    Fallback : tri par numero de fichier uniquement (presque toujours correct).

Usage :
    from core.file_sorter import sort_files
    result = sort_files(Path("sources/saut_2026_05_22/"))
    for f in result.fichiers:
        print(f.index, f.path.name, f.confiance_ordre)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.logger import get_logger
from core.telemetry_gopro import analyze_skydive, extract_telemetry

log = get_logger(__name__)

# Extensions video acceptees
_VIDEO_EXTENSIONS = {".mp4", ".MP4", ".mov", ".MOV", ".m4v", ".M4V"}

# Pattern GoPro : GX010045, GOPR0123, GH010067, GX020045 ...
# On extrait le numero de clip final (4 chiffres finaux = sequence)
_GOPRO_RE = re.compile(
    r"""
    (?:
        GX\d{2}(\d{4})   # Hero 9+ : GX010045 -> groupe 1 = 0045
      | GH\d{2}(\d{4})   # Hero 8   : GH010067 -> groupe 2 = 0067
      | GOPR(\d{4})       # Hero <=7  : GOPR0123 -> groupe 3 = 0123
      | GP\d{2}(\d{4})    # Hero 7   : GP010045 -> groupe 4 = 0045
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


# =================================================================
#  Modeles de donnees
# =================================================================

@dataclass
class FileInfo:
    path: Path
    index: int                        # Position dans la sequence finale (0-based)
    duree_s: float
    resolution: str                   # "1920x1080"
    fps: float
    has_audio: bool
    has_gpmf: bool
    altitude_moyenne: Optional[float]
    scenes_detectees: list[str]
    confiance_ordre: float            # 0.0-1.0
    source_ordre: str                 # "telemetrie" | "filename" | "creation_time" | "vote"


@dataclass
class SortResult:
    fichiers: list[FileInfo]          # Liste ordonnee
    confiance_globale: float
    avertissements: list[str]


# =================================================================
#  Helpers ffprobe
# =================================================================

def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _run_ffprobe(args: list[str]) -> Optional[dict]:
    """Lance ffprobe -print_format json et retourne le dict parse, ou None si erreur."""
    cmd = [_ffprobe(), "-v", "error", "-print_format", "json"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.debug("ffprobe non-zero(%d): %s", result.returncode,
                      result.stderr[:200])
            return None
        return json.loads(result.stdout)
    except FileNotFoundError:
        log.error("ffprobe introuvable dans PATH")
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffprobe timeout sur commande %s", args[-1] if args else "")
        return None
    except json.JSONDecodeError as e:
        log.warning("ffprobe JSON invalide: %s", e)
        return None


def _probe_file(path: Path) -> Optional[dict]:
    """Retourne les metadonnees completes (streams + format) d'un fichier."""
    return _run_ffprobe(["-show_streams", "-show_format", str(path)])


# =================================================================
#  Signal 1 : numero GoPro dans le nom de fichier
# =================================================================

def extract_gopro_number(path: str | Path) -> Optional[int]:
    """
    Extrait le numero de sequence GoPro du nom de fichier.

    Exemples :
        GX010045.MP4 -> 45
        GOPR0123.MP4 -> 123
        GH010067.MP4 -> 67
        GP010045.MP4 -> 45

    Retourne None si le nom ne correspond pas au pattern GoPro.
    """
    m = _GOPRO_RE.search(Path(path).stem)
    if not m:
        return None
    for grp in m.groups():
        if grp is not None:
            return int(grp)
    return None


# =================================================================
#  Signal 2 : creation_time dans les metadonnees MP4
# =================================================================

def _extract_creation_time(probe_data: dict) -> Optional[datetime]:
    """
    Extrait creation_time depuis format_tags ou stream_tags.

    GoPro Hero 5+ ecrit : 2026-05-22T14:32:11.000000Z
    Certains re-mux perdent ce tag -> retourne None.
    """
    fmt_tags = probe_data.get("format", {}).get("tags", {})
    raw = fmt_tags.get("creation_time")

    if not raw:
        for stream in probe_data.get("streams", []):
            raw = stream.get("tags", {}).get("creation_time")
            if raw:
                break

    if not raw:
        return None

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.debug("creation_time non parseable: %r", raw)
    return None


# =================================================================
#  Signal 3 : profil d'altitude GPMF
# =================================================================

def _classify_altitude_profile(altitude_moyenne: Optional[float],
                                alt_max: Optional[float],
                                alt_min: Optional[float],
                                duree_s: float) -> Optional[str]:
    """
    Classifie le profil d'altitude d'un fichier pour determiner sa phase.

    Retourne :
        "avion"  - altitude elevee, montee ou stable en altitude
        "chute"  - chute rapide d'altitude (chute libre)
        "sol"    - altitude basse et stable
        None     - donnees insuffisantes
    """
    if altitude_moyenne is None or alt_max is None or alt_min is None:
        return None

    amplitude = alt_max - alt_min

    # Altitude > 1000m = probablement dans l'avion ou en sortie
    if altitude_moyenne > 1000:
        return "avion"

    # Grande amplitude (> 500m) ET altitude moyenne moderee = chute libre
    if amplitude > 500 and altitude_moyenne > 200:
        return "chute"

    # Altitude basse et stable = au sol avant ou apres
    if altitude_moyenne < 300 and amplitude < 200:
        return "sol"

    # Amplitude importante mais altitude moyenne basse = fin de chute / atterrissage
    if amplitude > 300 and altitude_moyenne < 500:
        return "chute"

    return None


# =================================================================
#  Extraction des metadonnees d'un fichier
# =================================================================

@dataclass
class _RawFileData:
    """Donnees brutes avant tri."""
    path: Path
    gopro_number: Optional[int]
    creation_time: Optional[datetime]
    altitude_moyenne: Optional[float]
    altitude_max: Optional[float]
    altitude_min: Optional[float]
    altitude_profile: Optional[str]   # "avion" | "chute" | "sol" | None
    duree_s: float
    resolution: str
    fps: float
    has_audio: bool
    has_gpmf: bool


def _extract_file_data(path: Path) -> Optional[_RawFileData]:
    """
    Extrait toutes les metadonnees utiles d'un fichier video.
    Retourne None si le fichier n'est pas lisible par ffprobe.
    """
    log.info("Analyse de %s ...", path.name)

    probe = _probe_file(path)
    if probe is None:
        log.warning("ffprobe a echoue sur %s - fichier ignore", path.name)
        return None

    # --- Duree ---
    duree_s = 0.0
    try:
        duree_s = float(probe.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        pass

    # --- Resolution et FPS depuis le flux video principal ---
    resolution = "0x0"
    fps = 0.0
    has_audio = False
    for stream in probe.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video" and resolution == "0x0":
            w = stream.get("width", 0)
            h = stream.get("height", 0)
            resolution = f"{w}x{h}"
            rfr = stream.get("r_frame_rate", "0/1")
            try:
                num, den = rfr.split("/")
                fps = round(int(num) / int(den), 3) if int(den) else 0.0
            except (ValueError, ZeroDivisionError):
                fps = 0.0
        elif codec_type == "audio":
            has_audio = True

    # --- Numero GoPro ---
    gopro_number = extract_gopro_number(path)
    if gopro_number is None:
        log.debug("%s : pas de pattern GoPro dans le nom", path.name)

    # --- creation_time ---
    creation_time = _extract_creation_time(probe)
    if creation_time is None:
        log.debug("%s : creation_time absent ou non parseable", path.name)

    # --- Telemetrie GPMF ---
    altitude_moyenne: Optional[float] = None
    altitude_max: Optional[float] = None
    altitude_min: Optional[float] = None
    altitude_profile: Optional[str] = None
    has_gpmf = False

    try:
        samples = extract_telemetry(path)
        if samples:
            has_gpmf = True
            analysis = analyze_skydive(samples)
            if analysis.altitude_max_m is not None and analysis.altitude_min_m is not None:
                altitude_max = analysis.altitude_max_m
                altitude_min = analysis.altitude_min_m
                altitude_moyenne = round(
                    (altitude_max + altitude_min) / 2, 1
                )
                altitude_profile = _classify_altitude_profile(
                    altitude_moyenne, altitude_max, altitude_min, duree_s
                )
                log.debug(
                    "%s : alt moy=%.0fm max=%.0fm min=%.0fm profil=%s",
                    path.name, altitude_moyenne, altitude_max,
                    altitude_min, altitude_profile,
                )
    except RuntimeError as e:
        log.warning("Impossible d'extraire GPMF pour %s: %s", path.name, e)
    except Exception as e:  # noqa: BLE001
        log.warning("Erreur inattendue GPMF pour %s: %s", path.name, e)

    return _RawFileData(
        path=path,
        gopro_number=gopro_number,
        creation_time=creation_time,
        altitude_moyenne=altitude_moyenne,
        altitude_max=altitude_max,
        altitude_min=altitude_min,
        altitude_profile=altitude_profile,
        duree_s=duree_s,
        resolution=resolution,
        fps=fps,
        has_audio=has_audio,
        has_gpmf=has_gpmf,
    )


# =================================================================
#  Tri par vote
# =================================================================

def _rank_by_filename(files: list[_RawFileData]) -> Optional[list[int]]:
    """
    Retourne l'ordre par numero GoPro ou None si tous les numeros sont None.
    L'ordre est une liste d'indices dans `files` (tri croissant par numero).
    Les fichiers sans numero sont places a la fin tries par nom.
    """
    with_num = [(i, f) for i, f in enumerate(files) if f.gopro_number is not None]
    without_num = [(i, f) for i, f in enumerate(files) if f.gopro_number is None]

    if not with_num:
        return [i for i, _ in sorted(enumerate(files), key=lambda x: x[1].path.name)]

    with_num.sort(key=lambda x: x[1].gopro_number)  # type: ignore[arg-type]
    without_num.sort(key=lambda x: x[1].path.name)
    return [i for i, _ in with_num] + [i for i, _ in without_num]


def _rank_by_creation_time(files: list[_RawFileData]) -> Optional[list[int]]:
    """
    Retourne l'ordre par creation_time croissante, ou None si aucun fichier
    n'a de creation_time valide.
    """
    with_ts = [(i, f) for i, f in enumerate(files) if f.creation_time is not None]
    if not with_ts:
        return None
    if len(with_ts) < len(files):
        log.debug("_rank_by_creation_time: %d/%d fichiers ont un timestamp",
                  len(with_ts), len(files))

    with_ts.sort(key=lambda x: x[1].creation_time)  # type: ignore[arg-type]
    ordered_indices = [i for i, _ in with_ts]
    without_ts = sorted(
        [i for i, f in enumerate(files) if f.creation_time is None],
        key=lambda i: files[i].path.name,
    )
    return ordered_indices + without_ts


# Ordre narratif attendu des phases dans un saut tandem
_PHASE_ORDER = {"avion": 0, "chute": 1, "sol": 2}


def _rank_by_telemetry(files: list[_RawFileData]) -> Optional[list[int]]:
    """
    Classe les fichiers selon le profil d'altitude :
        avion (0) -> chute (1) -> sol (2)

    A l'interieur d'une meme phase, on trie par altitude_moyenne decroissante
    pour avion (le plus haut = le plus recent avant saut), et altitude decroissante
    pour chute (la chute commence haut).

    Retourne None si aucun fichier n'a de profil d'altitude.
    """
    with_profile = [(i, f) for i, f in enumerate(files)
                    if f.altitude_profile is not None]
    if not with_profile:
        return None

    def _sort_key(item: tuple[int, _RawFileData]) -> tuple[int, float]:
        _, f = item
        phase_rank = _PHASE_ORDER.get(f.altitude_profile or "", 1)
        # Secondaire : altitude decroissante (haut en premier dans la meme phase)
        alt = -(f.altitude_moyenne or 0.0)
        return (phase_rank, alt)

    with_profile.sort(key=_sort_key)
    ordered_indices = [i for i, _ in with_profile]

    # Fichiers sans profil -> tries par nom de fichier, inseres a la fin
    without_profile = sorted(
        [i for i, f in enumerate(files) if f.altitude_profile is None],
        key=lambda i: files[i].path.name,
    )
    return ordered_indices + without_profile


def _compute_kendall_distance(order_a: list[int], order_b: list[int]) -> int:
    """
    Nombre de paires (i, j) en desaccord entre deux ordres (distance de Kendall).
    Permet de mesurer l'accord entre signaux independamment de leur valeur absolue.
    """
    n = min(len(order_a), len(order_b))
    rank_b = {v: k for k, v in enumerate(order_b[:n])}
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            ea, eb = order_a[i], order_a[j]
            if ea not in rank_b or eb not in rank_b:
                continue
            if rank_b[ea] > rank_b[eb]:
                count += 1
    return count


def _orders_agree(order_a: list[int], order_b: list[int],
                  threshold: float = 0.25) -> bool:
    """
    Deux ordres s'accordent si leur distance de Kendall normalisee est <= threshold.
    threshold=0.25 -> accord si <= 25% des paires sont inversees.
    """
    n = min(len(order_a), len(order_b))
    if n < 2:
        return True
    max_pairs = n * (n - 1) / 2
    dist = _compute_kendall_distance(order_a, order_b)
    return (dist / max_pairs) <= threshold


def _vote_for_order(
    order_filename: Optional[list[int]],
    order_creation: Optional[list[int]],
    order_telemetry: Optional[list[int]],
    n: int,
) -> tuple[list[int], float, str]:
    """
    Vote entre les 3 signaux disponibles.

    Retourne (ordre_final, confiance_globale, source_str).
    source_str = "telemetrie" | "filename" | "creation_time" | "vote"

    Hierarchie :
        1. Si telemetrie disponible et accordee avec >=1 autre -> telemetrie gagne
        2. Si filename et creation concordent -> filename (plus stable)
        3. Sinon : ordre de priorite : telemetrie > filename > creation
    """
    available = {
        "telemetrie": order_telemetry,
        "filename": order_filename,
        "creation_time": order_creation,
    }
    present = {k: v for k, v in available.items() if v is not None}

    if not present:
        return list(range(n)), 0.0, "filename"

    if len(present) == 1:
        key, order = next(iter(present.items()))
        return order, 0.4, key

    # --- Calcul des accords par paire ---
    keys = list(present.keys())
    orders = list(present.values())
    agreements: dict[str, int] = {k: 0 for k in keys}

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if _orders_agree(orders[i], orders[j]):  # type: ignore[arg-type]
                agreements[keys[i]] += 1
                agreements[keys[j]] += 1

    # --- Choisir le signal dominant ---
    # Score = nb_accords x priorite (telemetrie compte triple)
    priority_weight = {"telemetrie": 3, "filename": 2, "creation_time": 1}
    weighted_scores = {
        k: agreements[k] * priority_weight.get(k, 1)
        for k in present
    }

    best_key = max(weighted_scores, key=weighted_scores.get)  # type: ignore[arg-type]
    best_order = present[best_key]

    # --- Confiance ---
    raw_agreements = agreements[best_key]

    if len(present) >= 3 and raw_agreements >= 2:
        confiance = 0.95
    elif len(present) >= 2 and raw_agreements >= 1:
        confiance = 0.75
    elif best_key == "telemetrie":
        confiance = 0.65
    elif best_key == "filename":
        confiance = 0.55
    else:
        confiance = 0.40

    source = "vote" if raw_agreements > 0 and len(present) > 1 else best_key
    return best_order, confiance, source


# =================================================================
#  Fonction principale
# =================================================================

def sort_files(folder_path: Path) -> SortResult:
    """
    Trie les fichiers video GoPro d'un dossier dans l'ordre narratif du saut.

    Args:
        folder_path: Dossier contenant les fichiers video (5-9 fichiers typiques).

    Returns:
        SortResult avec la liste ordonnee de FileInfo, la confiance globale
        et les avertissements eventuels.
    """
    folder_path = Path(folder_path)
    avertissements: list[str] = []

    if not folder_path.exists():
        raise FileNotFoundError(f"Dossier introuvable : {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(f"N'est pas un dossier : {folder_path}")

    # --- Collecte des fichiers video ---
    video_files = sorted(
        [p for p in folder_path.iterdir()
         if p.is_file() and p.suffix in _VIDEO_EXTENSIONS],
        key=lambda p: p.name,
    )

    if not video_files:
        log.warning("Aucun fichier video trouve dans %s", folder_path)
        return SortResult(fichiers=[], confiance_globale=0.0,
                          avertissements=["Aucun fichier video trouve"])

    n = len(video_files)
    if n < 2:
        log.warning("Un seul fichier trouve - tri trivial")
        avertissements.append("Un seul fichier video : tri trivial")
    elif n > 9:
        avertissements.append(
            f"{n} fichiers trouves - le module est optimise pour 5-9 fichiers"
        )

    log.info("sort_files : %d fichiers dans %s", n, folder_path)

    # --- Extraction des metadonnees ---
    raw_data: list[_RawFileData] = []
    for path in video_files:
        data = _extract_file_data(path)
        if data is not None:
            raw_data.append(data)
        else:
            avertissements.append(
                f"Impossible de lire les metadonnees de {path.name} - fichier ignore"
            )

    if not raw_data:
        avertissements.append("Aucun fichier lisible - resultat vide")
        return SortResult(fichiers=[], confiance_globale=0.0,
                          avertissements=avertissements)

    # --- Verification GPMF ---
    nb_gpmf = sum(1 for f in raw_data if f.has_gpmf)
    if nb_gpmf == 0:
        avertissements.append(
            "Aucun fichier n'a de flux GPMF - tri base sur filename/creation_time uniquement"
        )
    elif nb_gpmf < len(raw_data):
        avertissements.append(
            f"Seulement {nb_gpmf}/{len(raw_data)} fichiers ont un flux GPMF"
        )

    # --- Verification creation_time ---
    nb_creation = sum(1 for f in raw_data if f.creation_time is not None)
    if nb_creation == 0:
        avertissements.append(
            "Aucun fichier n'a de creation_time - signal ignore"
        )
    elif nb_creation < len(raw_data):
        avertissements.append(
            f"Seulement {nb_creation}/{len(raw_data)} fichiers ont un creation_time"
        )

    # --- Verification numeros GoPro ---
    nb_gopro = sum(1 for f in raw_data if f.gopro_number is not None)
    if nb_gopro == 0:
        avertissements.append(
            "Aucun fichier ne correspond au pattern GoPro (GX/GH/GOPR/GP) - tri alphabetique"
        )

    # --- Calcul des 3 ordres ---
    order_filename = _rank_by_filename(raw_data)
    order_creation = _rank_by_creation_time(raw_data)
    order_telemetry = _rank_by_telemetry(raw_data)

    log.debug("Ordre filename   : %s", order_filename)
    log.debug("Ordre creation   : %s", order_creation)
    log.debug("Ordre telemetrie : %s", order_telemetry)

    # --- Vote ---
    final_order, confiance_globale, source_ordre = _vote_for_order(
        order_filename, order_creation, order_telemetry, len(raw_data)
    )

    log.info("Ordre final (source=%s, confiance=%.2f) : %s",
             source_ordre, confiance_globale, final_order)

    # --- Detection incoherences eventuelles ---
    if order_filename and order_creation:
        if not _orders_agree(order_filename, order_creation, threshold=0.35):
            avertissements.append(
                "Incoherence entre numeros GoPro et creation_time - "
                "les fichiers ont peut-etre ete copies/renommes"
            )

    if order_filename and order_telemetry:
        if not _orders_agree(order_filename, order_telemetry, threshold=0.35):
            avertissements.append(
                "Incoherence entre numeros GoPro et profil d'altitude - "
                "verifier que les fichiers proviennent du meme saut"
            )

    # --- Construction de la liste FileInfo ordonnee ---
    fichiers: list[FileInfo] = []
    for rank, raw_idx in enumerate(final_order):
        f = raw_data[raw_idx]

        # Confiance individuelle : legerement plus elevee si le signal dominant
        # est la telemetrie et que ce fichier a du GPMF
        confiance_individuelle = confiance_globale
        if source_ordre in ("telemetrie", "vote") and f.has_gpmf:
            confiance_individuelle = min(1.0, confiance_globale + 0.05)
        elif source_ordre == "filename" and f.gopro_number is not None:
            confiance_individuelle = min(1.0, confiance_globale + 0.03)

        fichiers.append(FileInfo(
            path=f.path,
            index=rank,
            duree_s=round(f.duree_s, 2),
            resolution=f.resolution,
            fps=f.fps,
            has_audio=f.has_audio,
            has_gpmf=f.has_gpmf,
            altitude_moyenne=f.altitude_moyenne,
            scenes_detectees=[f.altitude_profile] if f.altitude_profile else [],
            confiance_ordre=round(confiance_individuelle, 3),
            source_ordre=source_ordre,
        ))

    return SortResult(
        fichiers=fichiers,
        confiance_globale=round(confiance_globale, 3),
        avertissements=avertissements,
    )


# =================================================================
#  CLI
# =================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage : python -m core.file_sorter <dossier_gopro/>")
        sys.exit(1)

    folder = Path(sys.argv[1])
    result = sort_files(folder)

    print(f"\nConfiance globale : {result.confiance_globale:.0%}")
    if result.avertissements:
        print("\nAvertissements :")
        for w in result.avertissements:
            print(f"  [!] {w}")

    print(f"\nSequence ({len(result.fichiers)} fichiers) :")
    for fi in result.fichiers:
        gpmf_flag = "[GPMF]" if fi.has_gpmf else "      "
        alt = f"alt={fi.altitude_moyenne:.0f}m" if fi.altitude_moyenne else "alt=N/A"
        print(
            f"  [{fi.index}] {fi.path.name:40s}  {fi.duree_s:6.1f}s  "
            f"{fi.resolution:10s}  {fi.fps:.1f}fps  {gpmf_flag}  {alt}"
            f"  conf={fi.confiance_ordre:.0%}  ({fi.source_ordre})"
        )

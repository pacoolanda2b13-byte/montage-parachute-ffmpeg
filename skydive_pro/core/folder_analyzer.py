"""
folder_analyzer.py — Analyse complète d'un dossier de rush GoPro pour un saut tandem.

Ce module orchestre le pipeline d'analyse multi-fichiers :
    1. Scan du dossier pour les fichiers vidéo (.mp4, .MP4, .mov, .MOV)
    2. Tri chronologique via core.file_sorter.sort_files()
    3. Détection de scènes sur chaque fichier via core.scene_detector.detect_scenes()
    4. Fusion des segments en timeline globale avec timestamps absolus
    5. Fusion de la télémétrie de tous les fichiers (altitude_max, vitesse_max, …)
    6. Écriture d'un metadata.json dans le dossier

Usage :
    from pathlib import Path
    from core.folder_analyzer import analyze_folder

    result = analyze_folder(
        Path("rush/saut_001"),
        client_nom="Sophie Durand",
        date_saut="2026-06-01",
        lieu="Skydive Lyon",
    )
    print(result.timeline_unifiee)
    result.save_metadata()
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from core.logger import get_logger
from core.file_sorter import sort_files, FileInfo, SortResult
from core.scene_detector import detect_scenes

log = get_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".MP4", ".mov", ".MOV"}


# ═══════════════════════════════════════════════════════════════
#  Helpers bas-niveau
# ═══════════════════════════════════════════════════════════════

def _find_ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _get_duration_s(path: Path) -> Optional[float]:
    """Retourne la durée en secondes d'un fichier vidéo via ffprobe."""
    ffprobe = _find_ffprobe()
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             check=True, timeout=20)
        data = json.loads(res.stdout)
        return float(data["format"]["duration"])
    except FileNotFoundError:
        log.error("ffprobe introuvable — durée impossible à lire")
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("ffprobe durée échouée sur %s : %s", path.name, e)
        return None


# ═══════════════════════════════════════════════════════════════
#  Fusion de la timeline multi-fichiers
# ═══════════════════════════════════════════════════════════════

def _to_global_segments(segments: list[dict],
                        offset_s: float,
                        source_file: Path) -> list[dict]:
    """Convertit des segments locaux (relatifs au fichier) en timestamps globaux.

    Chaque segment reçoit :
        - source_file  : chemin absolu du fichier vidéo source
        - start_s      : timestamp global (offset + start local)
        - end_s        : timestamp global (offset + end local)
        - scene        : nom de scène
        - confiance    : score de confiance [0.0, 1.0]
    """
    global_segs = []
    for seg in segments:
        global_segs.append({
            "source_file": str(source_file),
            "local_start_s": round(seg["start_s"], 3),
            "local_end_s": round(seg["end_s"], 3),
            "start_s": round(offset_s + seg["start_s"], 3),
            "end_s": round(offset_s + seg["end_s"], 3),
            "scene": seg["scene"],
            "confiance": seg.get("confiance", 0.5),
        })
    return global_segs


def _merge_consecutive_same_scene(segments: list[dict],
                                   gap_tolerance_s: float = 1.0) -> list[dict]:
    """Fusionne les segments consécutifs de même type de scène.

    Deux segments sont fusionnés si :
        - même scène
        - gap entre eux ≤ gap_tolerance_s

    La confiance du segment fusionné est la moyenne pondérée par la durée.
    Le source_file conservé est celui du premier segment de la séquence.
    """
    if not segments:
        return []

    merged = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        gap = seg["start_s"] - prev["end_s"]
        if seg["scene"] == prev["scene"] and gap <= gap_tolerance_s:
            # Pondération durée pour la confiance
            dur_prev = prev["end_s"] - prev["start_s"]
            dur_cur = seg["end_s"] - seg["start_s"]
            total = dur_prev + dur_cur
            new_conf = (
                (prev["confiance"] * dur_prev + seg["confiance"] * dur_cur) / total
                if total > 0 else prev["confiance"]
            )
            prev["end_s"] = seg["end_s"]
            prev["confiance"] = round(new_conf, 4)
        else:
            merged.append(dict(seg))
    return merged


# ═══════════════════════════════════════════════════════════════
#  Fusion de la télémétrie multi-fichiers
# ═══════════════════════════════════════════════════════════════

def _merge_telemetry(per_file_stats: list[dict],
                     file_offsets_s: list[float]) -> Optional[dict]:
    """Fusionne les statistiques de télémétrie de tous les fichiers.

    Règles :
        - altitude_max   = max global
        - vitesse_max    = max global
        - chute_start_s  = timestamp global du premier segment chute_libre
        - atterrissage_start_s = timestamp global du premier segment atterrissage

    Retourne None si aucune donnée disponible.
    """
    altitude_max: Optional[float] = None
    vitesse_max: Optional[float] = None
    chute_start_s: Optional[float] = None
    atterrissage_start_s: Optional[float] = None
    has_data = False

    for stats, offset in zip(per_file_stats, file_offsets_s):
        if stats is None:
            continue
        has_data = True

        # altitude_max
        alt = stats.get("altitude_max")
        if alt is not None:
            if altitude_max is None or alt > altitude_max:
                altitude_max = alt

        # vitesse_max (peut s'appeler speed_max ou vitesse_max selon le source)
        vit = stats.get("vitesse_max") or stats.get("speed_max")
        if vit is not None:
            if vitesse_max is None or vit > vitesse_max:
                vitesse_max = vit

        # chute_libre → timestamp global
        chute_local = stats.get("chute_start_s")
        if chute_local is not None and chute_start_s is None:
            chute_start_s = round(offset + chute_local, 3)

        # atterrissage → timestamp global
        atter_local = stats.get("atterrissage_start_s")
        if atter_local is not None and atterrissage_start_s is None:
            atterrissage_start_s = round(offset + atter_local, 3)

    if not has_data:
        return None

    result: dict = {}
    if altitude_max is not None:
        result["altitude_max"] = altitude_max
    if vitesse_max is not None:
        result["vitesse_max"] = vitesse_max
    if chute_start_s is not None:
        result["chute_start_s"] = chute_start_s
    if atterrissage_start_s is not None:
        result["atterrissage_start_s"] = atterrissage_start_s
    return result if result else None


def _extract_telemetry_stats_from_segments(segments: list[dict],
                                            file_path: Path) -> dict:
    """Extrait les informations de télémétrie utiles depuis les segments détectés.

    Cherche dans les segments les timestamps des phases clés.
    Tente aussi d'extraire altitude_max et vitesse_max via la télémétrie brute.
    """
    stats: dict = {}

    # Timestamps des phases clés depuis les segments
    for seg in segments:
        scene = seg.get("scene", "")
        if scene == "chute_libre" and "chute_start_s" not in stats:
            stats["chute_start_s"] = seg["start_s"]
        elif scene == "atterrissage" and "atterrissage_start_s" not in stats:
            stats["atterrissage_start_s"] = seg["start_s"]

    # Télémétrie brute pour altitude_max et vitesse_max
    try:
        from core.telemetry_gopro import extract_telemetry, analyze_skydive
        samples = extract_telemetry(file_path)
        if samples:
            skydive = analyze_skydive(samples)
            if skydive is not None:
                info = skydive.to_dict() if hasattr(skydive, "to_dict") else asdict(skydive)
                # Les clés peuvent varier ; on cherche les plus communes
                for key_src, key_dst in [
                    ("altitude_max_m", "altitude_max"),
                    ("altitude_max", "altitude_max"),
                    ("vitesse_max_kmh", "vitesse_max"),
                    ("vitesse_max", "vitesse_max"),
                    ("speed_max_kmh", "vitesse_max"),
                    ("speed_max_mps", "vitesse_max"),
                ]:
                    val = info.get(key_src)
                    if val is not None and key_dst not in stats:
                        stats[key_dst] = val
    except Exception as e:
        log.debug("Télémétrie brute non disponible sur %s : %s", file_path.name, e)

    return stats


# ═══════════════════════════════════════════════════════════════
#  Dataclass principale
# ═══════════════════════════════════════════════════════════════

@dataclass
class FolderAnalysis:
    """Résultat complet de l'analyse d'un dossier de rush tandem."""
    folder_path: Path
    client_nom: str
    date_saut: str
    lieu: str

    # Liste des FileInfo (de file_sorter)
    fichiers: list  # List[FileInfo]

    # Timeline globale : [{source_file, start_s, end_s, scene, confiance}]
    timeline_unifiee: list[dict]

    # Durée totale (somme des durées de tous les fichiers)
    duree_totale_s: float

    # Télémétrie fusionnée (altitude_max, vitesse_max, chute_start_s, atterrissage_start_s)
    telemetrie_globale: Optional[dict]

    # Confiance sur l'ordre des fichiers (issue de file_sorter)
    confiance_ordre: float

    # Avertissements collectés tout au long du pipeline
    avertissements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Sérialise l'analyse en dict JSON-compatible."""
        # Sérialise les FileInfo — ils peuvent venir de file_sorter avec attribut .path (Path)
        fichiers_serial = []
        for fi in self.fichiers:
            if hasattr(fi, "__dict__"):
                d = {k: (str(v) if isinstance(v, Path) else v)
                     for k, v in fi.__dict__.items()}
            else:
                d = str(fi)
            fichiers_serial.append(d)

        return {
            "folder_path": str(self.folder_path),
            "client_nom": self.client_nom,
            "date_saut": self.date_saut,
            "lieu": self.lieu,
            "fichiers": fichiers_serial,
            "nb_fichiers": len(self.fichiers),
            "timeline_unifiee": self.timeline_unifiee,
            "nb_segments": len(self.timeline_unifiee),
            "duree_totale_s": round(self.duree_totale_s, 3),
            "telemetrie_globale": self.telemetrie_globale,
            "confiance_ordre": round(self.confiance_ordre, 4),
            "avertissements": self.avertissements,
        }

    def save_metadata(self) -> Path:
        """Écrit metadata.json dans le dossier analysé.

        Retourne le chemin du fichier créé.
        """
        out_path = self.folder_path / "metadata.json"
        data = self.to_dict()
        try:
            out_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("metadata.json écrit : %s", out_path)
        except OSError as e:
            log.error("Impossible d'écrire metadata.json dans %s : %s",
                      self.folder_path, e)
            raise
        return out_path


# ═══════════════════════════════════════════════════════════════
#  Fonction principale
# ═══════════════════════════════════════════════════════════════

def analyze_folder(
    folder_path: Path,
    client_nom: str = "",
    date_saut: str = "",
    lieu: str = "",
    use_vision: bool = True,
    keyframe_interval: int = 30,
) -> FolderAnalysis:
    """Analyse complète d'un dossier de rush GoPro pour un saut tandem.

    Étapes :
        1. Tri des fichiers via file_sorter.sort_files()
        2. Pour chaque fichier : détection de scènes via scene_detector.detect_scenes()
        3. Conversion des timestamps locaux en timestamps globaux
        4. Fusion des segments consécutifs de même scène
        5. Fusion de la télémétrie multi-fichiers
        6. Construction du FolderAnalysis

    Args:
        folder_path       : Chemin vers le dossier de rush (doit exister)
        client_nom        : Nom du passager (métadonnée pure)
        date_saut         : Date du saut ISO-8601 (métadonnée pure)
        lieu              : Nom de la dropzone (métadonnée pure)
        use_vision        : Activer la classification Gemini (keyframes)
        keyframe_interval : Intervalle entre keyframes analysées (secondes)

    Returns:
        FolderAnalysis avec la timeline globale, la télémétrie fusionnée,
        et les avertissements collectés.
    """
    folder_path = Path(folder_path).resolve()
    avertissements: list[str] = []

    log.info("analyze_folder démarré : %s (client=%s, vision=%s)",
             folder_path, client_nom or "—", use_vision)

    # ── 1. Tri des fichiers ────────────────────────────────────────────
    sort_result: SortResult = sort_files(folder_path)
    sorted_paths: list[Path] = sort_result.files
    confiance_ordre: float = sort_result.confidence

    if sort_result.method in ("empty", "unknown") or not sorted_paths:
        log.warning("Aucun fichier vidéo dans %s", folder_path)
        avertissements.append(f"Aucun fichier vidéo trouvé dans {folder_path}")
        return FolderAnalysis(
            folder_path=folder_path,
            client_nom=client_nom,
            date_saut=date_saut,
            lieu=lieu,
            fichiers=[],
            timeline_unifiee=[],
            duree_totale_s=0.0,
            telemetrie_globale=None,
            confiance_ordre=0.0,
            avertissements=avertissements,
        )

    log.info("sort_files : %d fichier(s), méthode=%s, confiance=%.0f%%",
             len(sorted_paths), sort_result.method, confiance_ordre * 100)

    # Les FileInfo de sort_files sont des Path — on crée des FileInfo enrichis
    # si disponible, sinon on conserve les chemins bruts.
    fichiers_result: list = []
    # sort_result.files est une List[Path]; on n'a pas de FileInfo enrichi
    # directement mais on peut les reconstruire.
    # Pour respecter l'interface, on stocke les chemins (les FileInfo de
    # file_sorter ne sont pas exposés depuis sort_files tel qu'il est).
    for p in sorted_paths:
        fichiers_result.append(FileInfo(path=p, gopro_number=None,
                                         creation_time=None))

    # ── 2. Détection de scènes + durées par fichier ───────────────────
    # On calcule les offsets globaux au fur et à mesure.
    timeline_global: list[dict] = []
    per_file_telemetry: list[dict] = []
    file_offsets: list[float] = []
    duree_totale = 0.0

    for i, video_path in enumerate(sorted_paths):
        log.info("[%d/%d] Analyse de %s …", i + 1, len(sorted_paths),
                 video_path.name)

        # Offset global de ce fichier = somme des durées précédentes
        offset = duree_totale
        file_offsets.append(offset)

        # Durée via ffprobe (nécessaire pour calculer l'offset du suivant)
        duree_fichier = _get_duration_s(video_path)
        if duree_fichier is None:
            avertissements.append(
                f"{video_path.name} : durée non lisible via ffprobe "
                "— offset des fichiers suivants peut être inexact"
            )
            duree_fichier = 0.0

        # Détection de scènes sur ce fichier
        try:
            scene_result = detect_scenes(
                video_path,
                use_vision=use_vision,
                keyframe_interval=keyframe_interval,
            )
        except Exception as e:
            log.error("detect_scenes a échoué sur %s : %s", video_path.name, e)
            avertissements.append(
                f"{video_path.name} : détection de scènes échouée ({e})"
            )
            duree_totale += duree_fichier
            per_file_telemetry.append({})
            continue

        segments_locaux: list[dict] = scene_result.get("segments", [])
        stats = scene_result.get("stats", {})

        # Log stats de détection pour ce fichier
        log.info(
            "  → %d segments, tele=%d, audio=%s, vision=%s, fallback=%s",
            len(segments_locaux),
            stats.get("nb_segments_telemetrie", 0),
            "oui" if stats.get("audio_disponible") else "non",
            "oui" if stats.get("vision_activee") else "non",
            "oui" if stats.get("fallback_narratif_active") else "non",
        )
        if stats.get("fallback_narratif_active"):
            avertissements.append(
                f"{video_path.name} : fallback narratif activé "
                "(télémétrie + vision insuffisants)"
            )

        # Conversion en timestamps globaux
        segs_global = _to_global_segments(segments_locaux, offset, video_path)
        timeline_global.extend(segs_global)

        # Collecte de la télémétrie de ce fichier pour fusion ultérieure
        tele_stats = _extract_telemetry_stats_from_segments(segments_locaux,
                                                             video_path)
        per_file_telemetry.append(tele_stats)

        duree_totale += duree_fichier

    # ── 3. Fusion des segments consécutifs de même scène ─────────────
    # Les segments sont déjà triés par start_s car on les a ajoutés dans
    # l'ordre des fichiers. On fusionne seulement si même source_file pour
    # des raisons de préservation des coupures de fichier, sauf si les
    # segments sont vraiment contigus (gap ≤ 1s).
    timeline_global.sort(key=lambda s: s["start_s"])
    timeline_unifiee = _merge_consecutive_same_scene(timeline_global)

    log.info(
        "Timeline unifiée : %d segments (avant fusion : %d), durée totale : %.1fs",
        len(timeline_unifiee), len(timeline_global), duree_totale,
    )

    # ── 4. Fusion de la télémétrie ────────────────────────────────────
    telemetrie_globale = _merge_telemetry(per_file_telemetry, file_offsets)

    if telemetrie_globale:
        log.info(
            "Télémétrie globale : alt_max=%.0f m, vit_max=%.1f, "
            "chute_start=%.1fs, atterro_start=%.1fs",
            telemetrie_globale.get("altitude_max") or 0,
            telemetrie_globale.get("vitesse_max") or 0,
            telemetrie_globale.get("chute_start_s") or 0,
            telemetrie_globale.get("atterrissage_start_s") or 0,
        )
    else:
        log.info("Pas de télémétrie disponible sur les fichiers du dossier")

    # ── 5. Avertissements complémentaires ─────────────────────────────
    if confiance_ordre < 0.6:
        avertissements.append(
            f"Confiance d'ordre faible ({confiance_ordre:.0%}) — "
            f"méthode : {sort_result.method}. Vérifier l'ordre manuellement."
        )

    if not timeline_unifiee:
        avertissements.append(
            "Timeline vide — aucun segment de scène détecté. "
            "Vérifier les fichiers vidéo."
        )

    return FolderAnalysis(
        folder_path=folder_path,
        client_nom=client_nom,
        date_saut=date_saut,
        lieu=lieu,
        fichiers=fichiers_result,
        timeline_unifiee=timeline_unifiee,
        duree_totale_s=round(duree_totale, 3),
        telemetrie_globale=telemetrie_globale,
        confiance_ordre=confiance_ordre,
        avertissements=avertissements,
    )


# ═══════════════════════════════════════════════════════════════
#  CLI minimal pour tests rapides
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage : python -m core.folder_analyzer <dossier> "
              "[client_nom] [date_saut] [lieu] [--no-vision]")
        sys.exit(1)

    folder = Path(sys.argv[1])
    nom = sys.argv[2] if len(sys.argv) > 2 else ""
    date = sys.argv[3] if len(sys.argv) > 3 else ""
    lieu_arg = sys.argv[4] if len(sys.argv) > 4 else ""
    vision = "--no-vision" not in sys.argv

    analysis = analyze_folder(folder, nom, date, lieu_arg, use_vision=vision)
    analysis.save_metadata()
    print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))

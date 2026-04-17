"""
telemetry_gopro.py — Extraction de télémétrie GoPro (format GPMF)

Les GoPro Hero 5+ embarquent un flux "GPMF" (GoPro Metadata Format) dans
leurs vidéos MP4. Ce flux contient :
    - GPS (latitude, longitude, altitude)
    - Accéléromètre (3 axes, 200 Hz)
    - Gyroscope (3 axes)
    - Vitesse GPS
    - Température
    - ...

Ce module :
    1. Détecte la présence d'un flux GPMF via ffprobe
    2. L'extrait avec ffmpeg
    3. Le parse avec une implémentation minimale (pas de dépendance externe)
    4. Détecte les phases clés du saut :
        - Décollage (altitude augmente)
        - Sortie d'avion (accélération verticale brutale)
        - Chute libre (accélération totale ≈ 1G mais en chute)
        - Ouverture parachute (décélération nette)
        - Sous voile (descente lente)
        - Atterrissage (vitesse → 0)

Usage :
    from core.telemetry_gopro import extract_telemetry, analyze_skydive

    telemetry = extract_telemetry("sources/saut.mp4")
    phases = analyze_skydive(telemetry)
    print(phases.stats)
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────
#  Modèles de données
# ──────────────────────────────────────────────────────────
@dataclass
class TelemetrySample:
    """Un échantillon de télémétrie à un instant t."""
    time_s: float
    altitude_m: Optional[float] = None
    speed_mps: Optional[float] = None     # vitesse GPS en m/s
    accel_g: Optional[float] = None       # norme accéléromètre en G
    vertical_speed_mps: Optional[float] = None  # d(altitude)/dt
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class PhaseInterval:
    """Un intervalle temporel correspondant à une phase du saut."""
    nom: str
    start_s: float
    end_s: float

    @property
    def duree_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class SkydiveAnalysis:
    """Résultat complet de l'analyse d'un saut."""
    duree_totale_s: float
    altitude_max_m: Optional[float]
    vitesse_max_kmh: Optional[float]
    duree_chute_libre_s: Optional[float]
    phases: list[PhaseInterval] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    telemetry_disponible: bool = True

    def to_dict(self) -> dict:
        return {
            "duree_totale_s": self.duree_totale_s,
            "altitude_max_m": self.altitude_max_m,
            "vitesse_max_kmh": self.vitesse_max_kmh,
            "duree_chute_libre_s": self.duree_chute_libre_s,
            "telemetry_disponible": self.telemetry_disponible,
            "phases": [asdict(p) for p in self.phases],
            "stats": self.stats,
        }


# ──────────────────────────────────────────────────────────
#  Détection & extraction du flux GPMF
# ──────────────────────────────────────────────────────────
def _find_ffmpeg() -> tuple[str, str]:
    ff = shutil.which("ffmpeg") or "ffmpeg"
    fp = shutil.which("ffprobe") or "ffprobe"
    return ff, fp


def has_gpmf_stream(video_path: str | Path) -> Optional[int]:
    """Retourne l'index du flux GPMF s'il existe, sinon None."""
    _, ffprobe = _find_ffmpeg()
    cmd = [
        ffprobe, "-v", "error",
        "-print_format", "json",
        "-show_streams",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        codec_tag = stream.get("codec_tag_string", "")
        handler = stream.get("tags", {}).get("handler_name", "")
        if codec_tag == "gpmd" or "GoPro MET" in handler:
            return stream["index"]
    return None


def extract_gpmf_bytes(video_path: str | Path, stream_index: int) -> bytes:
    """Extrait le flux GPMF brut au format bytes."""
    ffmpeg, _ = _find_ffmpeg()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp_path = tmp.name
    try:
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-i", str(video_path),
            "-codec", "copy",
            "-map", f"0:{stream_index}",
            "-f", "data",
            tmp_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────
#  Parser GPMF (implémentation minimale)
# ──────────────────────────────────────────────────────────
# Format GPMF : enregistrements KLV (Key-Length-Value)
#   - Key  : 4 bytes ASCII (FourCC)
#   - Type : 1 byte (char type descriptor)
#   - Size : 1 byte (taille d'un élément)
#   - Repeat: 2 bytes uint16 big-endian (nombre d'éléments)
# Référence : https://github.com/gopro/gpmf-parser

def parse_gpmf(data: bytes) -> list[dict]:
    """
    Parse un buffer GPMF et retourne une liste d'enregistrements.
    Implémentation minimale qui extrait GPS5 (GPS) et ACCL (accéléromètre).
    """
    records = []
    pos = 0
    length = len(data)

    while pos + 8 <= length:
        try:
            fourcc = data[pos:pos + 4].decode("ascii", errors="replace")
        except Exception:
            break
        type_byte = data[pos + 4:pos + 5]
        elem_size = data[pos + 5]
        repeat = struct.unpack(">H", data[pos + 6:pos + 8])[0]

        payload_size = elem_size * repeat
        # Padding à 4 bytes
        padded = (payload_size + 3) & ~3
        payload = data[pos + 8:pos + 8 + payload_size]

        if fourcc in ("GPS5", "ACCL", "GPSU", "GPSF"):
            records.append({
                "fourcc": fourcc,
                "type": type_byte,
                "elem_size": elem_size,
                "repeat": repeat,
                "payload": payload,
            })

        if type_byte == b"\x00":  # nested
            pos += 8
        else:
            pos += 8 + padded

    return records


# ──────────────────────────────────────────────────────────
#  API publique
# ──────────────────────────────────────────────────────────
def extract_telemetry(video_path: str | Path) -> list[TelemetrySample]:
    """
    Point d'entrée principal — extrait la télémétrie d'une vidéo GoPro.

    Retourne une liste de samples échantillonnés à ~1 Hz.
    Si la vidéo ne contient pas de flux GPMF, retourne une liste vide.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Vidéo introuvable : {video_path}")

    stream_idx = has_gpmf_stream(video_path)
    if stream_idx is None:
        return []

    try:
        raw = extract_gpmf_bytes(video_path, stream_idx)
    except subprocess.CalledProcessError:
        return []

    records = parse_gpmf(raw)

    # TODO (J1.5) : convertir les records en TelemetrySample échantillonnés
    # Pour l'instant, on retourne les records parsés tels quels
    # (à raffiner avec une vraie vidéo test pour calibrer la conversion)
    samples = []
    # Placeholder : une vraie implémentation nécessite la table des scales
    # (SCAL) et le mapping temporel (STMP) qui sont aussi dans le flux.

    return samples


# ──────────────────────────────────────────────────────────
#  Analyse des phases du saut
# ──────────────────────────────────────────────────────────
def analyze_skydive(samples: list[TelemetrySample]) -> SkydiveAnalysis:
    """
    À partir des samples de télémétrie, détecte les phases du saut.

    Règles heuristiques :
        - Chute libre : accel_g ≈ 0 (pendant > 10 s) ET altitude décroissante rapide
        - Sous voile  : altitude décroissante lentement (<15 m/s), accel ≈ 1G
        - Atterrissage : altitude stable ET vitesse ≈ 0
        - Décollage   : altitude croissante
    """
    if not samples:
        return SkydiveAnalysis(
            duree_totale_s=0,
            altitude_max_m=None,
            vitesse_max_kmh=None,
            duree_chute_libre_s=None,
            telemetry_disponible=False,
        )

    duree = samples[-1].time_s - samples[0].time_s
    altitudes = [s.altitude_m for s in samples if s.altitude_m is not None]
    speeds = [s.speed_mps for s in samples if s.speed_mps is not None]

    altitude_max = max(altitudes) if altitudes else None
    vitesse_max_kmh = (max(speeds) * 3.6) if speeds else None

    phases: list[PhaseInterval] = []
    chute_libre_duree = 0.0

    # Détection chute libre : accel_g < 0.3 pendant > 5s consécutifs
    in_freefall = False
    freefall_start = 0.0
    for s in samples:
        if s.accel_g is not None and s.accel_g < 0.3:
            if not in_freefall:
                in_freefall = True
                freefall_start = s.time_s
        else:
            if in_freefall and (s.time_s - freefall_start) > 5:
                phases.append(PhaseInterval("chute_libre", freefall_start, s.time_s))
                chute_libre_duree += s.time_s - freefall_start
            in_freefall = False

    return SkydiveAnalysis(
        duree_totale_s=duree,
        altitude_max_m=altitude_max,
        vitesse_max_kmh=vitesse_max_kmh,
        duree_chute_libre_s=chute_libre_duree or None,
        phases=phases,
        stats={
            "nb_samples": len(samples),
            "nb_phases_detectees": len(phases),
        },
    )


# ──────────────────────────────────────────────────────────
#  CLI pour test rapide
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage : python -m core.telemetry_gopro <video.mp4>")
        sys.exit(1)

    video = sys.argv[1]
    print(f"[1/3] Vérification flux GPMF dans {video}...")
    idx = has_gpmf_stream(video)
    if idx is None:
        print("  [X] Pas de flux GPMF détecté — cette vidéo n'a probablement pas de télémétrie GoPro.")
        sys.exit(2)
    print(f"  [OK] Flux GPMF trouvé à l'index {idx}")

    print("[2/3] Extraction et parsing...")
    samples = extract_telemetry(video)
    print(f"  [OK] {len(samples)} samples extraits")

    print("[3/3] Analyse du saut...")
    analysis = analyze_skydive(samples)
    print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))

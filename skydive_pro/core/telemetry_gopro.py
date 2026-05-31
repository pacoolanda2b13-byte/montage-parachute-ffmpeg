"""
telemetry_gopro.py — Extraction de télémétrie GoPro (format GPMF)

Les GoPro Hero 5+ embarquent un flux "GPMF" (GoPro Metadata Format) dans
leurs vidéos MP4. Ce module :

    1. Détecte la présence d'un flux GPMF via ffprobe
    2. L'extrait avec ffmpeg (-codec copy -f data)
    3. Le parse récursivement (KLV avec conteneurs imbriqués)
    4. Décode GPS5 (lat/lon/altitude/vitesse) et ACCL (3 axes)
    5. Détecte les phases d'un saut parachute

Références :
    https://github.com/gopro/gpmf-parser
    https://gopro.github.io/gpmf-parser/

Usage :
    from core.telemetry_gopro import extract_telemetry, analyze_skydive
    samples = extract_telemetry("sources/saut.mp4")
    print(analyze_skydive(samples).to_dict())
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════
#  Modèles de données
# ═════════════════════════════════════════════════════════════════
@dataclass
class TelemetrySample:
    time_s: float
    altitude_m: Optional[float] = None
    speed_mps: Optional[float] = None
    speed_3d_mps: Optional[float] = None
    accel_g: Optional[float] = None
    vertical_speed_mps: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class PhaseInterval:
    nom: str
    start_s: float
    end_s: float

    @property
    def duree_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class SkydiveAnalysis:
    duree_totale_s: float
    altitude_max_m: Optional[float]
    altitude_min_m: Optional[float]
    vitesse_max_kmh: Optional[float]
    duree_chute_libre_s: Optional[float]
    chute_start_s: Optional[float] = None  # NEW : t. exact debut chute libre
    chute_end_s: Optional[float] = None    # NEW : t. exact ouverture parachute
    atterrissage_start_s: Optional[float] = None  # NEW : t. exact atterrissage
    phases: list[PhaseInterval] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    telemetry_disponible: bool = True

    def to_dict(self) -> dict:
        return {
            "duree_totale_s": round(self.duree_totale_s, 2),
            "altitude_max_m": self.altitude_max_m,
            "altitude_min_m": self.altitude_min_m,
            "vitesse_max_kmh": self.vitesse_max_kmh,
            "duree_chute_libre_s": self.duree_chute_libre_s,
            "chute_start_s": self.chute_start_s,
            "chute_end_s": self.chute_end_s,
            "atterrissage_start_s": self.atterrissage_start_s,
            "telemetry_disponible": self.telemetry_disponible,
            "phases": [asdict(p) for p in self.phases],
            "stats": self.stats,
        }


# ═════════════════════════════════════════════════════════════════
#  Détection & extraction du flux GPMF
# ═════════════════════════════════════════════════════════════════
def _find_ffmpeg() -> tuple[str, str]:
    return (shutil.which("ffmpeg") or "ffmpeg",
            shutil.which("ffprobe") or "ffprobe")


def has_gpmf_stream(video_path: str | Path) -> Optional[int]:
    """Retourne l'index du flux GPMF ou None s'il n'existe pas.

    Lève RuntimeError si ffprobe est introuvable (distinction claire avec
    'pas de flux GPMF').
    """
    _, ffprobe = _find_ffmpeg()
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_streams", str(video_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        log.error("ffprobe introuvable dans PATH")
        raise RuntimeError("ffprobe introuvable — installe FFmpeg") from e
    except subprocess.CalledProcessError as e:
        log.warning("ffprobe a échoué sur %s: %s", video_path,
                    (e.stderr or b"").decode("utf-8", errors="replace")[:200])
        return None
    except json.JSONDecodeError as e:
        log.warning("ffprobe stdout invalide: %s", e)
        return None

    try:
        streams = json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return None
    for stream in streams:
        codec_tag = stream.get("codec_tag_string", "")
        handler = stream.get("tags", {}).get("handler_name", "")
        if codec_tag == "gpmd" or "GoPro MET" in handler:
            return stream.get("index")
    return None


def extract_gpmf_bytes(video_path: str | Path, stream_index: int) -> bytes:
    """Extrait le flux GPMF brut."""
    ffmpeg, _ = _find_ffmpeg()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp_path = tmp.name
    try:
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(video_path),
               "-codec", "copy", "-map", f"0:{stream_index}",
               "-f", "data", tmp_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════
#  Parser GPMF — KLV avec conteneurs imbriqués
# ═════════════════════════════════════════════════════════════════
# Format : 4-byte FourCC + 1-byte Type + 1-byte Size + 2-byte Repeat + Payload
# Type '\0' = nested container (payload = more KLV data)
# Types courants : 'l' int32, 'L' uint32, 's' int16, 'S' uint16, 'f' float32,
#                  'd' double, 'c' char, 'b' int8, 'B' uint8
# Le payload est aligné sur 4 octets.

_STRUCT_FMT = {
    b"l": ("i", 4),
    b"L": ("I", 4),
    b"s": ("h", 2),
    b"S": ("H", 2),
    b"f": ("f", 4),
    b"d": ("d", 8),
    b"b": ("b", 1),
    b"B": ("B", 1),
    b"j": ("q", 8),
    b"J": ("Q", 8),
}


def _decode_values(payload: bytes, type_byte: bytes,
                   elem_size: int, repeat: int) -> list:
    """Décode un payload selon le type GPMF. Retourne une liste de tuples si
    elem_size > taille_unité (struct composite), sinon une liste plate.

    Retourne une liste vide en cas de données corrompues (silencieux mais loggé
    en debug car ça peut arriver sur bordures de blocs)."""
    fmt = _STRUCT_FMT.get(type_byte)
    if fmt is None:
        return []

    struct_char, base_size = fmt
    if elem_size == 0 or elem_size % base_size != 0:
        return []

    values_per_elem = elem_size // base_size
    fmt_string = ">" + struct_char * values_per_elem

    # Plafonner repeat selon la taille reelle du payload : protection
    # contre les GPMF corrompus qui annoncent un repeat enorme (ex:
    # 65535) sur un payload tronque -> evite des dizaines de milliers
    # d'iterations vides.
    max_repeat = len(payload) // elem_size
    safe_repeat = min(repeat, max_repeat)
    if safe_repeat < repeat:
        log.debug("_decode_values: repeat=%d plafonne a %d (payload trop court)",
                   repeat, safe_repeat)

    out = []
    for i in range(safe_repeat):
        chunk = payload[i * elem_size:(i + 1) * elem_size]
        if len(chunk) < elem_size:
            break
        try:
            decoded = struct.unpack(fmt_string, chunk)
        except struct.error as e:
            log.debug("struct.unpack failed (type=%r size=%d): %s",
                      type_byte, elem_size, e)
            break
        out.append(decoded if values_per_elem > 1 else decoded[0])
    return out


def _iter_klv(data: bytes, offset: int = 0, end: Optional[int] = None):
    """Itère sur les enregistrements KLV à un niveau donné.

    Clamp strictement toutes les bornes sur [offset, end] pour éviter les
    lectures hors-bornes sur vidéos tronquées ou GPMF corrompu.
    """
    if end is None:
        end = len(data)
    end = min(end, len(data))
    pos = offset
    while pos + 8 <= end:
        fourcc = data[pos:pos + 4]
        type_byte = data[pos + 4:pos + 5]
        elem_size = data[pos + 5]
        repeat = struct.unpack(">H", data[pos + 6:pos + 8])[0]
        payload_size = elem_size * repeat
        padded = (payload_size + 3) & ~3

        payload_start = pos + 8
        # Clamp strict : jamais au-delà de end
        payload_end = min(payload_start + payload_size, end)
        next_pos = min(payload_start + padded, end)
        if next_pos <= pos:
            # Progression impossible (elem_size=0 avec repeat=0 par ex) → stop
            break

        yield {
            "fourcc": fourcc.decode("ascii", errors="replace"),
            "type": type_byte,
            "elem_size": elem_size,
            "repeat": repeat,
            "payload_start": payload_start,
            "payload_end": payload_end,
        }

        pos = next_pos


# ═════════════════════════════════════════════════════════════════
#  Extraction des samples télémétrie
# ═════════════════════════════════════════════════════════════════
def extract_telemetry(video_path: str | Path) -> list[TelemetrySample]:
    """
    Extrait les samples de télémétrie d'une vidéo GoPro.

    Stratégie :
        - Chaque bloc DEVC (Device) représente ~1 seconde de données
        - Chaque STRM (Stream) dans DEVC = un capteur (GPS5, ACCL, ...)
        - SCAL dans un STRM = facteurs d'échelle à appliquer aux data
        - On distribue les samples uniformément sur la seconde du DEVC
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    stream_idx = has_gpmf_stream(video_path)
    if stream_idx is None:
        return []

    try:
        data = extract_gpmf_bytes(video_path, stream_idx)
    except subprocess.CalledProcessError as e:
        log.error("Extraction GPMF a échoué pour %s: %s", video_path,
                  (e.stderr or b"").decode("utf-8", errors="replace")[:500])
        return []
    except FileNotFoundError:
        log.error("ffmpeg introuvable — impossible d'extraire GPMF")
        raise RuntimeError("ffmpeg introuvable") from None

    samples: list[TelemetrySample] = []
    devc_index = 0  # chaque DEVC ≈ 1 seconde de timeline vidéo

    for devc in _iter_klv(data):
        if devc["fourcc"] != "DEVC":
            continue
        devc_time_start = float(devc_index)
        devc_index += 1

        # Niveau DEVC → contient STRM et des métadonnées
        for inner in _iter_klv(data, devc["payload_start"], devc["payload_end"]):
            if inner["fourcc"] != "STRM":
                continue

            # Niveau STRM → contient SCAL + les données (GPS5, ACCL, ...)
            scale = None
            for item in _iter_klv(data, inner["payload_start"], inner["payload_end"]):
                fourcc = item["fourcc"]
                payload = data[item["payload_start"]:item["payload_end"]]

                if fourcc == "SCAL":
                    values = _decode_values(payload, item["type"],
                                            item["elem_size"], item["repeat"])
                    scale = values if values else None

                elif fourcc == "GPS5":
                    pts = _decode_values(payload, item["type"],
                                         item["elem_size"], item["repeat"])
                    if not pts or not isinstance(pts[0], tuple):
                        continue
                    n = len(pts)
                    for i, pt in enumerate(pts):
                        lat, lon, alt, spd2d, spd3d = (pt + (0, 0, 0, 0, 0))[:5]
                        # Garde par champ : on tolère qu'un scale=0 invalide
                        # uniquement le champ correspondant (ex: GPS partiel)
                        if scale and len(scale) >= 5:
                            s_lat, s_lon, s_alt, s_spd2d, s_spd3d = scale[:5]
                            lat = (lat / s_lat) if s_lat else None
                            lon = (lon / s_lon) if s_lon else None
                            alt = (alt / s_alt) if s_alt else None
                            spd2d = (spd2d / s_spd2d) if s_spd2d else None
                            spd3d = (spd3d / s_spd3d) if s_spd3d else None
                        t = devc_time_start + (i / n)
                        samples.append(TelemetrySample(
                            time_s=t, lat=lat, lon=lon,
                            altitude_m=alt,
                            speed_mps=spd2d, speed_3d_mps=spd3d,
                        ))

                elif fourcc == "ACCL":
                    pts = _decode_values(payload, item["type"],
                                         item["elem_size"], item["repeat"])
                    if not pts:
                        continue
                    n = len(pts)
                    accl_scale = scale[0] if scale else 1.0
                    for i, pt in enumerate(pts):
                        if isinstance(pt, tuple) and len(pt) >= 3:
                            x, y, z = pt[:3]
                            if accl_scale:
                                x, y, z = x / accl_scale, y / accl_scale, z / accl_scale
                            # norme en m/s², convertir en G (1G = 9.81)
                            norm_mps2 = (x * x + y * y + z * z) ** 0.5
                            accel_g = norm_mps2 / 9.81
                            t = devc_time_start + (i / n)
                            samples.append(TelemetrySample(
                                time_s=t, accel_g=accel_g,
                            ))

    samples.sort(key=lambda s: s.time_s)
    return samples


# ═════════════════════════════════════════════════════════════════
#  Analyse du saut parachute
# ═════════════════════════════════════════════════════════════════
def analyze_skydive(samples: list[TelemetrySample]) -> SkydiveAnalysis:
    """
    Détecte les phases d'un saut à partir des samples télémétrie.

    Heuristiques :
        - Chute libre : accel_g < 0.5 pendant ≥ 5s consécutifs
        - Ces valeurs sont calibrées pour parachutisme (à ajuster sur vraies
          données tandem)
    """
    if not samples:
        return SkydiveAnalysis(
            duree_totale_s=0, altitude_max_m=None, altitude_min_m=None,
            vitesse_max_kmh=None, duree_chute_libre_s=None,
            telemetry_disponible=False,
        )

    # Filtrage des valeurs aberrantes :
    # - altitudes : ignorer < -100m (bug GPS ou drift) et > 12000m (avion ligne)
    # - vitesses : ignorer > 400 km/h = 111 m/s (au-dela du raisonnable tandem)
    altitudes_raw = [s.altitude_m for s in samples
                      if s.altitude_m is not None]
    altitudes = [a for a in altitudes_raw if -100 < a < 12000]
    if len(altitudes_raw) > len(altitudes):
        log.info("Filtrage altitudes : %d valeurs aberrantes ecartees "
                  "(sur %d)",
                  len(altitudes_raw) - len(altitudes), len(altitudes_raw))

    speeds_raw = [s.speed_3d_mps for s in samples
                   if s.speed_3d_mps is not None]
    speeds = [v for v in speeds_raw if 0 <= v < 111]  # 400 km/h max
    accels = [(s.time_s, s.accel_g) for s in samples
              if s.accel_g is not None and 0 <= s.accel_g < 10]

    altitude_max = round(max(altitudes), 1) if altitudes else None
    altitude_min = round(min(altitudes), 1) if altitudes else None
    vitesse_max_kmh = round(max(speeds) * 3.6, 1) if speeds else None
    duree = samples[-1].time_s - samples[0].time_s

    # ─── Detection PRECISE du chute_start via altitude max ───
    # En tandem, on monte en avion jusqu'au palier (~4000m), puis on
    # saute. Le timestamp où l'altitude max est atteinte = chute_start.
    chute_start_s = None
    chute_end_s = None
    atter_start_s = None
    if altitudes and altitude_max:
        # Trouver le 1er sample qui atteint au moins 95% de l'altitude max
        threshold_high = altitude_max * 0.95
        for s in samples:
            if s.altitude_m is not None and s.altitude_m >= threshold_high:
                chute_start_s = s.time_s
                break

        # Detecter l'ouverture parachute = transition entre chute libre
        # (descente rapide ~50m/s) et sous voile (descente lente ~5m/s).
        # Approche : chercher le moment ou la pente d'altitude diminue
        # significativement (de -50m/s a -5m/s).
        if chute_start_s is not None:
            samples_after_chute = [
                s for s in samples
                if s.time_s > chute_start_s and s.altitude_m is not None
            ]
            # Calcul vitesse verticale par segments de 1s
            if len(samples_after_chute) >= 10:
                window_s = 2.0
                for i in range(len(samples_after_chute) - 1):
                    s_now = samples_after_chute[i]
                    s_after = next((s for s in samples_after_chute[i+1:]
                                     if s.time_s - s_now.time_s >= window_s),
                                    None)
                    if not s_after:
                        break
                    dh = s_now.altitude_m - s_after.altitude_m
                    dt = s_after.time_s - s_now.time_s
                    vz = dh / dt if dt > 0 else 0  # m/s positif = descend
                    # Si vitesse de descente < 15 m/s -> sous voile
                    if vz < 15 and s_now.time_s > chute_start_s + 10:
                        chute_end_s = s_now.time_s
                        break

        # Detecter atterrissage : on cherche le moment ou l'altitude
        # commence a stagner pres du sol. On prend la mediane des
        # altitudes filtrees pour estimer le sol (plus robuste que min).
        if altitudes:
            # Sol estime = mediane des 10% derniers samples
            sorted_alts = sorted(altitudes)
            sol_estime = sorted_alts[int(len(sorted_alts) * 0.05)]  # 5e percentile
            threshold_low = sol_estime + 30  # 30m au-dessus du sol
            # Trouver le 1er sample qui descend sous threshold APRES la chute
            if chute_start_s is not None:
                for s in samples:
                    if (s.altitude_m is not None and
                            -100 < s.altitude_m < 12000 and  # filtre aberrant
                            s.altitude_m <= threshold_low and
                            s.time_s > chute_start_s + 30):
                        atter_start_s = s.time_s
                        break

    # Detection chute libre via accelerometre (legacy, pour duree_s)
    phases = []
    chute_libre_duree = 0.0
    in_ff = False
    ff_start = 0.0
    last_t = 0.0
    for t, g in accels:
        if g < 0.5:
            if not in_ff:
                in_ff = True
                ff_start = t
        else:
            if in_ff and (t - ff_start) >= 5:
                phases.append(PhaseInterval("chute_libre",
                                            round(ff_start, 2),
                                            round(t, 2)))
                chute_libre_duree += t - ff_start
            in_ff = False
        last_t = t
    if in_ff and (last_t - ff_start) >= 5:
        phases.append(PhaseInterval("chute_libre",
                                    round(ff_start, 2),
                                    round(last_t, 2)))
        chute_libre_duree += last_t - ff_start

    # Si la detection accel n'a rien donne mais qu'on a chute_start/end
    # via altitude, on l'ajoute aux phases
    if not phases and chute_start_s is not None and chute_end_s is not None:
        phases.append(PhaseInterval("chute_libre",
                                     round(chute_start_s, 2),
                                     round(chute_end_s, 2)))
        chute_libre_duree = chute_end_s - chute_start_s

    return SkydiveAnalysis(
        duree_totale_s=duree,
        altitude_max_m=altitude_max,
        altitude_min_m=altitude_min,
        vitesse_max_kmh=vitesse_max_kmh,
        duree_chute_libre_s=round(chute_libre_duree, 2) or None,
        chute_start_s=round(chute_start_s, 2) if chute_start_s else None,
        chute_end_s=round(chute_end_s, 2) if chute_end_s else None,
        atterrissage_start_s=(round(atter_start_s, 2)
                                if atter_start_s else None),
        phases=phases,
        stats={
            "nb_samples": len(samples),
            "nb_samples_gps": len(altitudes),
            "nb_samples_accl": len(accels),
        },
    )


# ═════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage : python -m core.telemetry_gopro <video.mp4>")
        sys.exit(1)

    video = sys.argv[1]
    print(f"[1/3] Verification flux GPMF dans {video}...")
    idx = has_gpmf_stream(video)
    if idx is None:
        print("  [X] Pas de flux GPMF detecte.")
        sys.exit(2)
    print(f"  [OK] Flux GPMF a l'index {idx}")

    print("[2/3] Extraction et parsing...")
    samples = extract_telemetry(video)
    print(f"  [OK] {len(samples)} samples extraits")

    print("[3/3] Analyse du saut...")
    analysis = analyze_skydive(samples)
    print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))

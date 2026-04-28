"""
pipeline.py — Orchestrateur du pipeline complet SkyDive Pro.

Enchaîne :
    1. Extraction télémétrie GoPro
    2. Détection de scènes (télémétrie + audio + Gemini)
    3. Génération des overlays brandés
    4. Montage final via FFmpeg
    5. (à terme) Livraison par email/Drive

Usage :
    from agent.pipeline import process_jump
    result = process_jump(
        video_path="sources/saut.mp4",
        nom_passager="Marie Dubois",
        email_client="marie@example.fr",
        date_saut="2026-04-17",
        job_id="job-abc123",
    )
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.telemetry_gopro import extract_telemetry, analyze_skydive
from core.scene_detector import detect_scenes
from core.overlay_generator import build_intro, build_outro, build_stats_panel
from core.ffmpeg_engine import build_montage
from core.logger import get_logger

log = get_logger(__name__)


BASE_DIR = Path(__file__).resolve().parent.parent

# Charger .env en mode CLI (le serveur Flask le fait deja de son cote).
# Sans ca, GEMINI_API_KEY n'est pas lue et la vision est desactivee.
try:
    from dotenv import load_dotenv
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass


@dataclass
class PipelineResult:
    job_id: str
    statut: str  # "succes" | "echec" | "partiel"
    duree_traitement_s: float = 0.0
    fichier_montage: Optional[str] = None
    taille_montage_mb: Optional[float] = None
    analyse_telemetrie: dict = field(default_factory=dict)
    scenes_detectees: int = 0
    etapes: list[dict] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)

    def ajouter_etape(self, nom: str, duree_s: float, ok: bool, detail: str = ""):
        self.etapes.append({
            "nom": nom, "duree_s": round(duree_s, 2),
            "ok": ok, "detail": detail,
        })

    def to_dict(self) -> dict:
        return asdict(self)


def _timer():
    return time.perf_counter()


def process_jump(video_path: str | Path,
                  nom_passager: str,
                  email_client: str = "",
                  date_saut: str = "",
                  job_id: str = "job-xxx",
                  moniteur: str = "",
                  use_vision: bool = True,
                  keyframe_interval: int = 30,
                  max_duration_s: int = 210,
                  music_path: Optional[Path] = None,
                  dropzone_nom: str = "",
                  dropzone_site: str = "",
                  logo_path: Optional[Path] = None,
                  output_dir: Optional[Path] = None,
                  ) -> PipelineResult:
    """Pipeline complet. Retourne un PipelineResult.

    Ne lève pas d'exception : les erreurs sont capturées dans .erreurs.
    """
    t_global = _timer()
    video_path = Path(video_path)
    output_dir = Path(output_dir) if output_dir else (BASE_DIR / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    result = PipelineResult(job_id=job_id, statut="echec")

    if not video_path.exists():
        result.erreurs.append(f"Vidéo introuvable : {video_path}")
        return result

    # Tmpdir unique pour tous les overlays d'un job → cleanup facile
    overlays_dir = Path(tempfile.mkdtemp(prefix=f"skydive_overlays_{job_id}_"))
    log.info("[%s] Pipeline démarré — video=%s", job_id, video_path.name)

    try:
        # ── 1. Télémétrie ────────────────────────────────────────
        t = _timer()
        analysis = None
        try:
            samples = extract_telemetry(video_path)
            analysis = analyze_skydive(samples)
            result.analyse_telemetrie = analysis.to_dict()
            stats = analysis.to_dict().get("stats", {}) or {}
            n_gps = stats.get("nb_samples_gps", 0)
            n_accl = stats.get("nb_samples_accl", 0)
            result.ajouter_etape(
                "telemetrie", _timer() - t, True,
                f"{len(samples)} samples (GPS={n_gps}, ACCL={n_accl}), "
                f"alt_max={analysis.altitude_max_m}, "
                f"v_max={analysis.vitesse_max_kmh}",
            )
        except RuntimeError as e:
            # ffprobe/ffmpeg absent : erreur bloquante
            log.error("[%s] Télémétrie bloquante: %s", job_id, e)
            result.ajouter_etape("telemetrie", _timer() - t, False, str(e))
            result.erreurs.append(f"Télémétrie : {e}")
        except Exception as e:
            log.error("[%s] Télémétrie: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("telemetrie", _timer() - t, False, str(e))
            result.erreurs.append(f"Télémétrie : {e}")

        # ── 2. Détection de scènes ───────────────────────────────
        t = _timer()
        segments = []
        try:
            scenes_result = detect_scenes(video_path,
                                           use_vision=use_vision,
                                           keyframe_interval=keyframe_interval)
            segments = scenes_result["segments"]
            result.scenes_detectees = len(segments)
            result.ajouter_etape("detection_scenes", _timer() - t, True,
                                  f"{len(segments)} segments, "
                                  f"vision_activee={scenes_result['stats'].get('vision_activee')}")
        except Exception as e:
            log.error("[%s] Détection scènes: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("detection_scenes", _timer() - t, False, str(e))
            result.erreurs.append(f"Détection scènes : {e}")

        # ── 3. Overlays ──────────────────────────────────────────
        t = _timer()
        intro = outro = stats = None
        try:
            date_fmt = date_saut
            if date_saut:
                try:
                    date_fmt = datetime.strptime(date_saut, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError as ve:
                    log.warning("[%s] Date invalide '%s' (%s) — utilisée brute",
                                 job_id, date_saut, ve)

            intro = build_intro(nom_passager=nom_passager,
                                 date_saut=date_fmt or "",
                                 logo_path=logo_path,
                                 dropzone_nom=dropzone_nom,
                                 output_dir=overlays_dir)
            outro = build_outro(dropzone_nom=dropzone_nom,
                                 site_web=dropzone_site,
                                 logo_path=logo_path,
                                 output_dir=overlays_dir)
            if analysis:
                stats = build_stats_panel(
                    altitude_max_m=analysis.altitude_max_m,
                    vitesse_max_kmh=analysis.vitesse_max_kmh,
                    duree_chute_s=analysis.duree_chute_libre_s,
                    output_dir=overlays_dir,
                )
            result.ajouter_etape("overlays", _timer() - t, True,
                                  f"intro={intro.name if intro else '-'}")
        except Exception as e:
            log.error("[%s] Overlays: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("overlays", _timer() - t, False, str(e))
            result.erreurs.append(f"Overlays : {e}")

        # ── 4. Montage final ─────────────────────────────────────
        t = _timer()
        try:
            output_file = output_dir / f"{job_id}_{Path(video_path).stem}_montage.mp4"
            # Marqueurs telemetrie pour la strategie positionnelle :
            # priorite haute car bcp plus fiable que Gemini
            telemetry_chute_start = (analysis.chute_start_s
                                       if analysis else None)
            telemetry_atter_start = (analysis.atterrissage_start_s
                                       if analysis else None)
            build_montage(
                video_source=video_path,
                segments=segments,
                output_path=output_file,
                intro_overlay=intro,
                outro_overlay=outro,
                stats_overlay=stats,
                music_path=music_path,
                max_duration_s=max_duration_s,
                telemetry_chute_start_s=telemetry_chute_start,
                telemetry_atter_start_s=telemetry_atter_start,
            )
            if output_file.exists():
                result.fichier_montage = str(output_file)
                result.taille_montage_mb = round(
                    output_file.stat().st_size / (1024 * 1024), 2)
                result.statut = "succes"
            result.ajouter_etape("montage", _timer() - t, True,
                                  f"fichier={output_file.name}")
        except Exception as e:
            log.error("[%s] Montage: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("montage", _timer() - t, False, str(e))
            result.erreurs.append(f"Montage : {e}")

    finally:
        # Cleanup overlays tmpdir — toujours, même en cas d'exception
        shutil.rmtree(overlays_dir, ignore_errors=True)

    result.duree_traitement_s = round(_timer() - t_global, 2)
    if result.statut != "succes" and not result.erreurs:
        result.statut = "partiel"

    log.info("[%s] Pipeline terminé (%s) en %.1fs — %d erreurs",
             job_id, result.statut, result.duree_traitement_s, len(result.erreurs))
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage : python -m agent.pipeline <video.mp4> <nom_passager>")
        sys.exit(1)

    res = process_jump(
        video_path=sys.argv[1],
        nom_passager=sys.argv[2],
        date_saut=datetime.now().strftime("%Y-%m-%d"),
        job_id=f"cli-{int(time.time())}",
        dropzone_nom=os.environ.get("DROPZONE_NOM", "Skydive Adventure"),
        dropzone_site=os.environ.get("DROPZONE_SITE", ""),
    )
    print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))

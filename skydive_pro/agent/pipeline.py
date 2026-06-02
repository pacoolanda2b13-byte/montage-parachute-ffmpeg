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
    reels: list[dict] = field(default_factory=list)  # [{type, path, duree_s, ok}]
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

    # PROFILE DE LA VIDEO SOURCE (signal cle pour diag posteriori)
    try:
        import subprocess as _sp
        r = _sp.run(
            ["ffprobe", "-v", "error",
             "-show_entries",
             "format=duration,bit_rate,size:stream=codec_name,codec_type,"
             "width,height,r_frame_rate",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            import json as _json
            meta = _json.loads(r.stdout)
            fmt = meta.get("format", {})
            streams = meta.get("streams", [])
            v_stream = next((s for s in streams
                              if s.get("codec_type") == "video"), {})
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            size_mb = float(fmt.get("size", 0)) / (1024 * 1024)
            log.info("[%s] Source : %s | %.1fs | %s %dx%d %s | "
                      "audio=%s | %.1f MB",
                      job_id, video_path.name,
                      float(fmt.get("duration", 0)),
                      v_stream.get("codec_name", "?"),
                      v_stream.get("width", 0), v_stream.get("height", 0),
                      v_stream.get("r_frame_rate", "?"),
                      "OUI" if has_audio else "NON",
                      size_mb)
    except Exception as e:
        log.warning("[%s] ffprobe source meta echoue : %s", job_id, e)
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
                # Lire le rapport de validation post-montage : un montage
                # produit mais cassé (pas d'audio, durée aberrante) doit
                # être marqué "partiel", pas "succes" (cf postmortem #6).
                rapport_path = output_file.with_suffix(
                    output_file.suffix + ".validation.json")
                validation_ok = True
                detail_validation = ""
                if rapport_path.exists():
                    try:
                        import json as _json
                        rapport = _json.loads(rapport_path.read_text("utf-8"))
                        validation_ok = rapport.get("ok", True)
                        if not validation_ok:
                            detail_validation = (
                                " | validation: "
                                + "; ".join(rapport.get("issues", [])))
                            result.erreurs.append(
                                "Montage dégradé : "
                                + "; ".join(rapport.get("issues", [])))
                    except (ValueError, OSError) as e:
                        log.warning("[%s] Lecture rapport validation: %s",
                                     job_id, e)
                result.statut = "succes" if validation_ok else "partiel"
                result.ajouter_etape(
                    "montage", _timer() - t, validation_ok,
                    f"fichier={output_file.name}{detail_validation}")
            else:
                result.ajouter_etape("montage", _timer() - t, False,
                                      "fichier de sortie absent")
                result.erreurs.append("Montage : fichier de sortie absent")
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


def process_folder(folder_path: str | Path,
                    nom_passager: str,
                    email_client: str = "",
                    date_saut: str = "",
                    lieu: str = "",
                    job_id: str = "job-xxx",
                    moniteur: str = "",
                    use_vision: bool = True,
                    keyframe_interval: int = 30,
                    max_duration_s: int = 420,
                    music_path: Optional[Path] = None,
                    dropzone_nom: str = "",
                    dropzone_site: str = "",
                    logo_path: Optional[Path] = None,
                    output_dir: Optional[Path] = None,
                    template_name: str = "fun_energie",
                    ) -> PipelineResult:
    """Pipeline multi-fichiers : analyse un dossier de rushs GoPro.

    Étapes :
        1. Analyser le dossier (ordonner les fichiers, détecter les scènes)
        2. Construire une timeline unifiée cross-fichiers
        3. Sélectionner les meilleurs clips dans chaque fichier source
        4. Générer overlays (intro, outro, stats)
        5. Monter la vidéo longue (6-7 min)

    Ne lève pas d'exception : les erreurs sont capturées dans .erreurs.
    """
    t_global = _timer()
    folder_path = Path(folder_path)
    output_dir = Path(output_dir) if output_dir else (BASE_DIR / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    result = PipelineResult(job_id=job_id, statut="echec")

    if not folder_path.exists() or not folder_path.is_dir():
        result.erreurs.append(f"Dossier introuvable : {folder_path}")
        return result

    # Charger le template de montage
    try:
        from core.templates import get_template, apply_template
        tmpl = get_template(template_name)
        tmpl_config = apply_template(tmpl)
        max_duration_s = tmpl_config.get("max_duration_s", max_duration_s)
        log.info("[%s] Template: %s (%s)", job_id, tmpl.name, tmpl.label)
    except Exception as e:
        log.warning("[%s] Template '%s' non trouvé: %s — défaut", job_id, template_name, e)
        tmpl = None
        tmpl_config = {}

    overlays_dir = Path(tempfile.mkdtemp(prefix=f"skydive_overlays_{job_id}_"))

    try:
        # ── 1. Analyse du dossier (ordonnancement + scènes) ──────
        t = _timer()
        try:
            from core.folder_analyzer import analyze_folder
            analysis = analyze_folder(
                folder_path,
                client_nom=nom_passager,
                date_saut=date_saut,
                lieu=lieu,
                use_vision=use_vision,
                keyframe_interval=keyframe_interval,
            )
            n_files = len(analysis.fichiers)
            n_segments = len(analysis.timeline_unifiee)
            result.scenes_detectees = n_segments
            result.ajouter_etape(
                "analyse_dossier", _timer() - t, True,
                f"{n_files} fichiers, {n_segments} segments, "
                f"confiance={analysis.confiance_ordre:.0%}",
            )

            # Avertissements de l'analyse
            for warn in analysis.avertissements:
                result.erreurs.append(f"Avertissement : {warn}")

            # Télémétrie globale
            if analysis.telemetrie_globale:
                result.analyse_telemetrie = analysis.telemetrie_globale

        except Exception as e:
            log.error("[%s] Analyse dossier: %s\n%s", job_id, e,
                      traceback.format_exc())
            result.ajouter_etape("analyse_dossier", _timer() - t, False, str(e))
            result.erreurs.append(f"Analyse dossier : {e}")
            result.duree_traitement_s = round(_timer() - t_global, 2)
            return result

        if n_files == 0:
            result.erreurs.append("Aucun fichier vidéo trouvé dans le dossier")
            result.duree_traitement_s = round(_timer() - t_global, 2)
            return result

        # ── 2. Overlays ──────────────────────────────────────────
        t = _timer()
        intro = outro = stats = None
        try:
            date_fmt = date_saut
            if date_saut:
                try:
                    date_fmt = datetime.strptime(date_saut, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    pass

            intro = build_intro(nom_passager=nom_passager,
                                date_saut=date_fmt or "",
                                logo_path=logo_path,
                                dropzone_nom=dropzone_nom,
                                output_dir=overlays_dir)
            outro = build_outro(dropzone_nom=dropzone_nom,
                                site_web=dropzone_site,
                                logo_path=logo_path,
                                output_dir=overlays_dir)

            telem = analysis.telemetrie_globale or {}
            if any(telem.get(k) for k in ("altitude_max_m", "vitesse_max_kmh")):
                stats = build_stats_panel(
                    altitude_max_m=telem.get("altitude_max_m"),
                    vitesse_max_kmh=telem.get("vitesse_max_kmh"),
                    duree_chute_s=telem.get("duree_chute_libre_s"),
                    output_dir=overlays_dir,
                )
            result.ajouter_etape("overlays", _timer() - t, True, "")
        except Exception as e:
            log.error("[%s] Overlays: %s", job_id, e)
            result.ajouter_etape("overlays", _timer() - t, False, str(e))

        # ── 3. Montage multi-sources ─────────────────────────────
        t = _timer()
        try:
            output_file = output_dir / f"{job_id}_montage.mp4"

            telem = analysis.telemetrie_globale or {}
            build_montage(
                video_source=analysis.fichiers[0].path,  # fallback source
                segments=analysis.timeline_unifiee,
                output_path=output_file,
                intro_overlay=intro,
                outro_overlay=outro,
                stats_overlay=stats,
                music_path=music_path,
                music_volume=tmpl_config.get("music_volume", 0.35),
                max_duration_s=max_duration_s,
                fade_duration_s=tmpl_config.get("fade_duration_s", 0.4),
                telemetry_chute_start_s=telem.get("chute_start_s"),
                telemetry_atter_start_s=telem.get("atterrissage_start_s"),
                pre_selected=True,  # segments déjà sélectionnés par folder_analyzer
            )

            if output_file.exists():
                result.fichier_montage = str(output_file)
                result.taille_montage_mb = round(
                    output_file.stat().st_size / (1024 * 1024), 2)

                rapport_path = output_file.with_suffix(
                    output_file.suffix + ".validation.json")
                validation_ok = True
                if rapport_path.exists():
                    try:
                        rapport = json.loads(rapport_path.read_text("utf-8"))
                        validation_ok = rapport.get("ok", True)
                        if not validation_ok:
                            result.erreurs.append(
                                "Montage dégradé : "
                                + "; ".join(rapport.get("issues", [])))
                    except (ValueError, OSError):
                        pass

                result.statut = "succes" if validation_ok else "partiel"
                result.ajouter_etape("montage", _timer() - t, validation_ok,
                                     f"fichier={output_file.name}")
            else:
                result.ajouter_etape("montage", _timer() - t, False,
                                     "fichier de sortie absent")
                result.erreurs.append("Montage : fichier de sortie absent")
        except Exception as e:
            log.error("[%s] Montage: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("montage", _timer() - t, False, str(e))
            result.erreurs.append(f"Montage : {e}")

        # ── 4. Reels Instagram ────────────────────────────────────
        t = _timer()
        try:
            from core.reels_generator import generate_reels
            telem = analysis.telemetrie_globale or {}
            reels_result = generate_reels(
                segments=analysis.timeline_unifiee,
                output_dir=output_dir,
                nom_passager=nom_passager,
                date_saut=date_saut,
                lieu=lieu,
                vitesse_max_kmh=telem.get("vitesse_max_kmh"),
                music_path=music_path,
                job_id=job_id,
            )
            result.reels = reels_result
            n_ok = sum(1 for r in reels_result if r.get("ok"))
            result.ajouter_etape("reels", _timer() - t, n_ok > 0,
                                 f"{n_ok}/{len(reels_result)} reels générés")
        except Exception as e:
            log.error("[%s] Reels: %s\n%s", job_id, e, traceback.format_exc())
            result.ajouter_etape("reels", _timer() - t, False, str(e))

        # ── 5. Livraison (QR + page + email) ─────────────────────
        if email_client and result.fichier_montage:
            t = _timer()
            try:
                from core.delivery import deliver
                delivery_result = deliver(
                    job_id=job_id,
                    nom_passager=nom_passager,
                    email_client=email_client,
                    date_saut=date_saut,
                    lieu=lieu,
                    montage_path=Path(result.fichier_montage),
                    reels=result.reels,
                    output_dir=output_dir,
                )
                result.ajouter_etape(
                    "livraison", _timer() - t, True,
                    f"email={'OK' if delivery_result.get('email_sent') else 'NON'}, "
                    f"qr={'OK' if delivery_result.get('qr_code') else 'NON'}",
                )
            except Exception as e:
                log.error("[%s] Livraison: %s", job_id, e)
                result.ajouter_etape("livraison", _timer() - t, False, str(e))

        # Sauvegarder metadata.json dans le dossier source
        try:
            analysis.save_metadata()
        except Exception as e:
            log.warning("[%s] Sauvegarde metadata.json: %s", job_id, e)

    finally:
        shutil.rmtree(overlays_dir, ignore_errors=True)

    result.duree_traitement_s = round(_timer() - t_global, 2)
    if result.statut != "succes" and not result.erreurs:
        result.statut = "partiel"

    log.info("[%s] Pipeline folder terminé (%s) en %.1fs — %d erreurs",
             job_id, result.statut, result.duree_traitement_s, len(result.erreurs))
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage :")
        print("  python -m agent.pipeline <video.mp4> <nom_passager>")
        print("  python -m agent.pipeline --folder <dossier_rushs> <nom_passager>")
        sys.exit(1)

    if sys.argv[1] == "--folder":
        if len(sys.argv) < 4:
            print("Usage : python -m agent.pipeline --folder <dossier> <nom>")
            sys.exit(1)
        res = process_folder(
            folder_path=sys.argv[2],
            nom_passager=sys.argv[3],
            date_saut=datetime.now().strftime("%Y-%m-%d"),
            job_id=f"cli-{int(time.time())}",
            dropzone_nom=os.environ.get("DROPZONE_NOM", "Skydive Adventure"),
        )
    else:
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

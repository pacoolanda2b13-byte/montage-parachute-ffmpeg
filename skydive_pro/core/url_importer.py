"""
url_importer.py — Téléchargement universel de vidéos à partir d'un lien.

Supporte :
    - URL directe (https://.../video.mp4) → requests
    - WeTransfer (wetransfer.com/downloads/...) → transferwee (fallback: requests)
    - Google Drive (drive.google.com/...) → gdown
    - Dropbox (dropbox.com/...) → force ?dl=1 + requests
    - YouTube / Vimeo / etc. → yt-dlp (550+ sites supportés)

⚠️ Les vidéos YouTube/Vimeo sont re-encodées et ne contiennent PAS de
télémétrie GPMF. Le pipeline fonctionnera mais sans altitude/vitesse.

Usage :
    from core.url_importer import import_from_url
    result = import_from_url("https://we.tl/t-xxx", dest_dir="sources")
    # result = {"path": Path, "source": "wetransfer", "taille_mb": 123.4}
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from core.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  Modèles
# ══════════════════════════════════════════════════════════════
@dataclass
class ImportResult:
    path: Path
    source: str                     # "youtube" | "wetransfer" | "drive" | "dropbox" | "direct"
    titre: Optional[str] = None
    taille_mb: float = 0.0
    duree_s: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "source": self.source,
            "titre": self.titre,
            "taille_mb": round(self.taille_mb, 2),
            "duree_s": self.duree_s,
        }


# ══════════════════════════════════════════════════════════════
#  Détection du type d'URL
# ══════════════════════════════════════════════════════════════
def detect_source(url: str) -> str:
    """Identifie la plateforme à partir de l'URL."""
    host = (urlparse(url).netloc or "").lower()

    if any(h in host for h in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return "youtube"
    if any(h in host for h in ("vimeo.com", "player.vimeo.com")):
        return "vimeo"
    if any(h in host for h in ("wetransfer.com", "we.tl")):
        return "wetransfer"
    if any(h in host for h in ("drive.google.com", "docs.google.com")):
        return "drive"
    if any(h in host for h in ("dropbox.com", "dl.dropboxusercontent.com")):
        return "dropbox"

    # URL directe si termine par extension vidéo
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".webm", ".avi")):
        return "direct"

    # Par défaut, on tente yt-dlp (supporte 1000+ sites)
    return "other"


# ══════════════════════════════════════════════════════════════
#  Backends de téléchargement
# ══════════════════════════════════════════════════════════════
def _download_direct(url: str, dest: Path, taille_max_mb: int = 5120) -> Path:
    """Téléchargement HTTP direct avec streaming + limite de taille."""
    import requests
    log.info("Téléchargement direct : %s", url)
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        total = 0
        max_bytes = taille_max_mb * 1024 * 1024
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(
                        f"Fichier > {taille_max_mb} MB, download annulé")
                f.write(chunk)
    return dest


def _download_dropbox(url: str, dest: Path) -> Path:
    """Force ?dl=1 pour obtenir le contenu binaire."""
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    q["dl"] = ["1"]
    new_url = urlunparse(parsed._replace(query=urlencode(q, doseq=True)))
    return _download_direct(new_url, dest)


def _download_drive(url: str, dest: Path) -> Path:
    """Utilise gdown pour les fichiers Google Drive."""
    try:
        import gdown
    except ImportError as e:
        raise RuntimeError(
            "gdown non installé — pip install gdown") from e

    # Extraire l'ID du fichier
    file_id = None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        file_id = m.group(1)
    else:
        m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
        if m:
            file_id = m.group(1)

    if not file_id:
        raise RuntimeError(f"Impossible d'extraire l'ID Drive de : {url}")

    log.info("Téléchargement Drive id=%s", file_id)
    gdown.download(id=file_id, output=str(dest), quiet=False, fuzzy=True)
    if not dest.exists():
        raise RuntimeError("gdown a échoué — fichier absent après download")
    return dest


def _download_wetransfer(url: str, dest: Path) -> Path:
    """WeTransfer : essaie transferwee, puis fallback yt-dlp.

    WeTransfer ne publie pas d'API officielle ; transferwee fait du scraping.
    Le format des liens a changé plusieurs fois, donc on prévoit un fallback.
    """
    try:
        from transferwee import download as wt_download
        log.info("Téléchargement WeTransfer via transferwee")
        wt_download(url, dest.parent)
        # transferwee sauve avec le nom d'origine ; on cherche le plus récent
        candidates = sorted(dest.parent.glob("*"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
        candidates = [c for c in candidates if c.is_file() and c.stat().st_size > 1024]
        if candidates:
            # Renomme vers dest si pas déjà là
            if candidates[0] != dest:
                shutil.move(str(candidates[0]), str(dest))
            return dest
    except ImportError:
        log.warning("transferwee non installé, essai via yt-dlp")
    except Exception as e:
        log.warning("transferwee a échoué (%s), essai via yt-dlp", e)

    # Fallback yt-dlp (supporte certains liens wetransfer)
    return _download_ytdlp(url, dest)


def _download_ytdlp(url: str, dest: Path,
                     format_str: str = "bestvideo[height<=1080]+bestaudio/best") -> Path:
    """Téléchargement via yt-dlp (YouTube, Vimeo, et 1000+ sites)."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp non installé") from e

    log.info("Téléchargement yt-dlp : %s", url)
    # yt-dlp ajoute souvent .mp4/.webm ; on laisse faire puis on renomme
    tmpl = str(dest.parent / (dest.stem + ".%(ext)s"))
    opts = {
        "outtmpl": tmpl,
        "format": format_str,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        # Limite au cas où
        "max_filesize": 5 * 1024 * 1024 * 1024,  # 5 GB
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Chercher le fichier final
            produced = Path(ydl.prepare_filename(info))
            if not produced.exists():
                # yt-dlp change parfois l'extension après merge
                for candidate in dest.parent.glob(dest.stem + ".*"):
                    if candidate.suffix in (".mp4", ".mkv", ".webm"):
                        produced = candidate
                        break
            if produced != dest and produced.exists():
                produced.rename(dest)
            return dest
    except Exception as e:
        raise RuntimeError(f"yt-dlp a échoué : {e}") from e


# ══════════════════════════════════════════════════════════════
#  API publique
# ══════════════════════════════════════════════════════════════
def import_from_url(url: str,
                     dest_dir: str | Path,
                     nom_fichier: Optional[str] = None,
                     taille_max_mb: int = 5120) -> ImportResult:
    """Télécharge une vidéo depuis n'importe quel lien supporté.

    Args:
        url           : URL complète
        dest_dir      : dossier de destination (sera créé si absent)
        nom_fichier   : nom du fichier final (sans extension, auto si None)
        taille_max_mb : garde-fou anti-abus

    Returns:
        ImportResult avec path, source, taille et titre si disponible.
    """
    if not url or not url.strip():
        raise ValueError("URL vide")
    url = url.strip()

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    source = detect_source(url)
    log.info("Import depuis %s → source=%s", url[:80], source)

    # Nom par défaut basé sur un hash court + timestamp
    import time, hashlib
    if not nom_fichier:
        h = hashlib.sha1(url.encode()).hexdigest()[:8]
        nom_fichier = f"{source}_{int(time.time())}_{h}"
    # Dest par défaut .mp4 ; sera renommée après DL si autre format
    dest = dest_dir / f"{nom_fichier}.mp4"

    if source == "youtube" or source == "vimeo" or source == "other":
        _download_ytdlp(url, dest)
    elif source == "wetransfer":
        _download_wetransfer(url, dest)
    elif source == "drive":
        _download_drive(url, dest)
    elif source == "dropbox":
        _download_dropbox(url, dest)
    elif source == "direct":
        _download_direct(url, dest, taille_max_mb=taille_max_mb)
    else:
        raise RuntimeError(f"Source inconnue : {source}")

    if not dest.exists():
        raise RuntimeError(f"Téléchargement terminé mais fichier introuvable : {dest}")
    taille_mb = dest.stat().st_size / (1024 * 1024)
    log.info("Import OK : %s (%.1f MB)", dest, taille_mb)

    return ImportResult(path=dest, source=source, taille_mb=taille_mb,
                        titre=nom_fichier)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage : python -m core.url_importer <url> [dest_dir]")
        sys.exit(1)
    dest = sys.argv[2] if len(sys.argv) > 2 else "sources"
    res = import_from_url(sys.argv[1], dest)
    import json
    print(json.dumps(res.to_dict(), indent=2))

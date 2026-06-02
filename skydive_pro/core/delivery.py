"""
delivery.py — Livraison des montages SkyDive Pro aux clients.

Fonctionnalités :
- Génération de QR code pointant vers la page de téléchargement
- Génération d'une page HTML standalone (dark theme, branding SkyDive Pro)
- Envoi d'email SMTP avec lien de téléchargement
- Orchestrateur `deliver()` qui coordonne le tout

Usage :
    from core.delivery import deliver
    result = deliver(
        job_id="abc123",
        nom_passager="Sophie",
        email_client="sophie@example.com",
        date_saut="2026-06-02",
        lieu="Skydive Lyon",
        montage_path=Path("output/montage.mp4"),
        reels=[{"type": "instagram", "path": "output/reel_ig.mp4", "duree_s": 30}],
        output_dir=Path("output"),
        base_url="https://skydivepro.fr",
    )
    # result = {"qr_code": Path, "download_page": Path, "email_sent": bool}
"""

from __future__ import annotations

import os
import smtplib
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Couleurs de la marque SkyDive Pro
# ---------------------------------------------------------------------------
BRAND_ORANGE = "#FF6B00"
BRAND_BG = "#0B0B13"
BRAND_CARD = "#13131F"
BRAND_TEXT = "#E8E8EE"
BRAND_MUTED = "#888899"


# ---------------------------------------------------------------------------
# 1. QR Code
# ---------------------------------------------------------------------------

def generate_qr_code(url: str, output_path: Path, size: int = 300) -> Path:
    """Génère un QR code PNG pointant vers `url`.

    Si la librairie `qrcode` n'est pas installée, crée un fichier texte
    .qr.txt avec l'URL en fallback — ne plante jamais.

    Args:
        url: L'URL vers laquelle le QR code pointe.
        output_path: Chemin du fichier PNG à créer.
        size: Taille approximative en pixels (utilisé pour box_size).

    Returns:
        Le chemin du fichier créé (PNG ou TXT en fallback).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import qrcode  # type: ignore

        box_size = max(1, size // 33)  # 33 modules × box_size ≈ size px
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=box_size,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="white", back_color=BRAND_BG)
        img.save(str(output_path))
        log.info("QR code généré : %s → %s", url, output_path)
        return output_path

    except ImportError:
        log.warning(
            "Librairie 'qrcode' absente — QR code non généré. "
            "Fallback fichier texte créé."
        )
        fallback = output_path.with_suffix(".qr.txt")
        fallback.write_text(url, encoding="utf-8")
        return fallback

    except Exception as exc:  # noqa: BLE001
        log.error("Erreur génération QR code : %s", exc, exc_info=True)
        fallback = output_path.with_suffix(".qr.txt")
        try:
            fallback.write_text(url, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return fallback


# ---------------------------------------------------------------------------
# 2. Page de téléchargement HTML
# ---------------------------------------------------------------------------

def _reel_label(reel_type: str) -> str:
    """Retourne un label lisible pour le type de reel."""
    labels = {
        "instagram": "Reel Instagram (9:16)",
        "tiktok": "TikTok (9:16)",
        "youtube": "YouTube Shorts",
        "square": "Format Carré (1:1)",
        "landscape": "Format Paysage (16:9)",
    }
    return labels.get(reel_type.lower(), reel_type.capitalize())


def generate_download_page(
    nom_passager: str,
    date_saut: str,
    lieu: str,
    montage_filename: str,
    reels: list[dict],
    output_dir: Path,
    base_url: str = "http://localhost:5000",
) -> Path:
    """Génère une page HTML standalone de téléchargement pour le client.

    La page est auto-contenue (CSS inline, aucune dépendance externe).
    Elle affiche le nom du passager, la date, le lieu, un bouton de
    téléchargement pour le montage long et un bouton par Reel.

    Args:
        nom_passager: Prénom/nom du passager tandem.
        date_saut: Date du saut (ex: "2026-06-02").
        lieu: Lieu du saut (ex: "Skydive Lyon").
        montage_filename: Nom du fichier montage (ex: "montage_sophie.mp4").
        reels: Liste de dicts [{type, path, duree_s}].
        output_dir: Dossier où écrire le fichier HTML.
        base_url: URL de base du serveur de téléchargement.

    Returns:
        Chemin absolu du fichier HTML généré.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    montage_url = f"{base_url.rstrip('/')}/download/{montage_filename}"

    # Construction des boutons reels
    reel_buttons_html = ""
    for reel in reels:
        reel_path = reel.get("path", "")
        reel_filename = Path(reel_path).name if reel_path else "reel.mp4"
        reel_type = reel.get("type", "reel")
        duree = reel.get("duree_s", 0)
        label = _reel_label(reel_type)
        reel_url = f"{base_url.rstrip('/')}/download/{reel_filename}"
        duree_str = f" ({int(duree)}s)" if duree else ""

        reel_buttons_html += f"""
        <a href="{reel_url}" download="{reel_filename}" class="btn btn-secondary">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18"
                 viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            {label}{duree_str}
        </a>"""

    html = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="robots" content="noindex, nofollow">
            <title>Ton saut — SkyDive Pro</title>
            <style>
                *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

                body {{
                    background: {BRAND_BG};
                    color: {BRAND_TEXT};
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                                 Roboto, "Helvetica Neue", Arial, sans-serif;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 24px 16px;
                }}

                .card {{
                    background: {BRAND_CARD};
                    border: 1px solid rgba(255,107,0,0.15);
                    border-radius: 16px;
                    padding: 40px 32px;
                    max-width: 520px;
                    width: 100%;
                    box-shadow: 0 8px 40px rgba(0,0,0,0.6);
                    text-align: center;
                }}

                .logo {{
                    font-size: 13px;
                    font-weight: 700;
                    letter-spacing: 0.2em;
                    text-transform: uppercase;
                    color: {BRAND_ORANGE};
                    margin-bottom: 32px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }}

                .logo-icon {{
                    font-size: 20px;
                }}

                .hero-title {{
                    font-size: clamp(22px, 5vw, 30px);
                    font-weight: 800;
                    line-height: 1.2;
                    margin-bottom: 8px;
                    color: {BRAND_TEXT};
                }}

                .hero-title span {{
                    color: {BRAND_ORANGE};
                }}

                .meta {{
                    font-size: 14px;
                    color: {BRAND_MUTED};
                    margin-bottom: 32px;
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                }}

                .divider {{
                    border: none;
                    border-top: 1px solid rgba(255,255,255,0.06);
                    margin: 24px 0;
                }}

                .section-label {{
                    font-size: 11px;
                    font-weight: 700;
                    letter-spacing: 0.15em;
                    text-transform: uppercase;
                    color: {BRAND_MUTED};
                    margin-bottom: 14px;
                }}

                .buttons {{
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }}

                .btn {{
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 10px;
                    padding: 14px 24px;
                    border-radius: 10px;
                    font-size: 15px;
                    font-weight: 600;
                    text-decoration: none;
                    transition: opacity 0.15s, transform 0.1s;
                    cursor: pointer;
                    border: none;
                }}

                .btn:hover {{
                    opacity: 0.88;
                    transform: translateY(-1px);
                }}

                .btn:active {{
                    transform: translateY(0);
                }}

                .btn-primary {{
                    background: {BRAND_ORANGE};
                    color: #fff;
                    font-size: 16px;
                    padding: 16px 28px;
                    box-shadow: 0 4px 20px rgba(255,107,0,0.35);
                }}

                .btn-secondary {{
                    background: rgba(255,255,255,0.07);
                    color: {BRAND_TEXT};
                    border: 1px solid rgba(255,255,255,0.1);
                }}

                .thank-you {{
                    margin-top: 36px;
                    padding-top: 24px;
                    border-top: 1px solid rgba(255,255,255,0.06);
                    font-size: 17px;
                    color: {BRAND_TEXT};
                    font-weight: 500;
                }}

                .thank-you .emoji {{
                    display: block;
                    font-size: 32px;
                    margin-bottom: 10px;
                }}

                .footer {{
                    margin-top: 28px;
                    font-size: 12px;
                    color: {BRAND_MUTED};
                }}

                @media (max-width: 480px) {{
                    .card {{ padding: 28px 20px; }}
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="logo">
                    <span class="logo-icon">🪂</span>
                    SkyDive Pro
                </div>

                <h1 class="hero-title">
                    Le saut de<br><span>{nom_passager}</span>
                </h1>

                <div class="meta">
                    <span>📅 {date_saut}</span>
                    <span>📍 {lieu}</span>
                </div>

                <div class="section-label">Montage complet</div>
                <div class="buttons">
                    <a href="{montage_url}" download="{montage_filename}" class="btn btn-primary">
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"
                             viewBox="0 0 24 24" fill="none" stroke="currentColor"
                             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="7 10 12 15 17 10"/>
                            <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                        Télécharger le film (HD)
                    </a>
                </div>

                {f'<hr class="divider"><div class="section-label">Reels à partager</div><div class="buttons">{reel_buttons_html}</div>' if reels else ""}

                <div class="thank-you">
                    <span class="emoji">🙏</span>
                    Merci d'avoir sauté avec nous !
                </div>

                <p class="footer">Ce lien est personnel — ne le partagez pas publiquement.</p>
            </div>
        </body>
        </html>
    """)

    output_file = output_dir / "download.html"
    output_file.write_text(html, encoding="utf-8")
    log.info("Page de téléchargement générée : %s", output_file)
    return output_file


# ---------------------------------------------------------------------------
# 3. Envoi email SMTP
# ---------------------------------------------------------------------------

def send_delivery_email(
    to_email: str,
    nom_passager: str,
    date_saut: str,
    lieu: str,
    download_url: str,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
    from_email: str = "",
) -> bool:
    """Envoie un email HTML branded avec le lien de téléchargement.

    Les paramètres SMTP peuvent être passés directement ou lus depuis les
    variables d'environnement : SMTP_HOST, SMTP_PORT, SMTP_USER,
    SMTP_PASSWORD, FROM_EMAIL.

    Ne plante jamais — retourne False si l'envoi échoue.

    Args:
        to_email: Adresse email du destinataire.
        nom_passager: Prénom/nom du passager.
        date_saut: Date du saut.
        lieu: Lieu du saut.
        download_url: URL de la page de téléchargement.
        smtp_host: Serveur SMTP (ex: "smtp.gmail.com").
        smtp_port: Port SMTP (587 TLS par défaut).
        smtp_user: Utilisateur SMTP.
        smtp_password: Mot de passe SMTP.
        from_email: Adresse expéditeur.

    Returns:
        True si l'email a été envoyé avec succès, False sinon.
    """
    # Résolution des paramètres depuis les env vars si non fournis
    resolved_host = smtp_host or os.environ.get("SMTP_HOST", "")
    resolved_port_str = os.environ.get("SMTP_PORT", str(smtp_port))
    resolved_port = int(resolved_port_str) if resolved_port_str.isdigit() else smtp_port
    resolved_user = smtp_user or os.environ.get("SMTP_USER", "")
    resolved_password = smtp_password or os.environ.get("SMTP_PASSWORD", "")
    resolved_from = from_email or os.environ.get("FROM_EMAIL", resolved_user)

    if not resolved_host:
        log.warning(
            "SMTP non configuré (SMTP_HOST manquant) — email non envoyé à %s.",
            to_email,
        )
        return False

    if not to_email or "@" not in to_email:
        log.warning("Adresse email invalide : %r — email non envoyé.", to_email)
        return False

    subject = f"🪂 Ton saut à {lieu} — {nom_passager}, ton film est prêt !"

    html_body = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ margin: 0; padding: 0; background: #f4f4f8;
                        font-family: -apple-system, BlinkMacSystemFont,
                        "Segoe UI", Roboto, Arial, sans-serif; }}
                .wrapper {{ max-width: 560px; margin: 32px auto; background: {BRAND_BG};
                            border-radius: 12px; overflow: hidden; }}
                .header {{ background: {BRAND_ORANGE}; padding: 28px 32px; text-align: center; }}
                .header h1 {{ margin: 0; color: #fff; font-size: 22px; font-weight: 800; }}
                .header p {{ margin: 4px 0 0; color: rgba(255,255,255,0.85);
                             font-size: 13px; letter-spacing: 0.15em;
                             text-transform: uppercase; }}
                .body {{ padding: 32px; color: {BRAND_TEXT}; }}
                .greeting {{ font-size: 20px; font-weight: 700; margin-bottom: 12px; }}
                .meta {{ background: {BRAND_CARD}; border-radius: 8px;
                         padding: 16px 20px; margin: 20px 0; font-size: 14px;
                         color: #aaa; line-height: 1.8; }}
                .meta strong {{ color: {BRAND_TEXT}; }}
                .cta {{ display: block; background: {BRAND_ORANGE}; color: #fff;
                        text-decoration: none; text-align: center; padding: 16px 24px;
                        border-radius: 10px; font-size: 16px; font-weight: 700;
                        margin: 28px 0; }}
                .note {{ font-size: 13px; color: #666; margin-top: 8px; }}
                .footer {{ padding: 20px 32px; border-top: 1px solid rgba(255,255,255,0.06);
                           font-size: 12px; color: #555; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="wrapper">
                <div class="header">
                    <h1>🪂 SkyDive Pro</h1>
                    <p>Ton film de saut est prêt</p>
                </div>
                <div class="body">
                    <p class="greeting">Salut {nom_passager} !</p>
                    <p>Ton montage vidéo est prêt à télécharger. Revivez
                       chaque seconde de ce saut incroyable !</p>
                    <div class="meta">
                        <strong>📅 Date :</strong> {date_saut}<br>
                        <strong>📍 Lieu :</strong> {lieu}
                    </div>
                    <a href="{download_url}" class="cta">
                        ⬇️ Télécharger mon film
                    </a>
                    <p class="note">
                        Ce lien est personnel. Si tu as des problèmes,
                        réponds directement à cet email.
                    </p>
                </div>
                <div class="footer">
                    SkyDive Pro — Montage vidéo automatique pour parachutistes.<br>
                    Ce message t'a été envoyé suite à ton saut tandem.
                </div>
            </div>
        </body>
        </html>
    """)

    # Version texte brut en fallback
    text_body = (
        f"Salut {nom_passager} !\n\n"
        f"Ton film de saut est prêt.\n"
        f"Date : {date_saut}\n"
        f"Lieu : {lieu}\n\n"
        f"Télécharge ton montage ici :\n{download_url}\n\n"
        f"Merci d'avoir sauté avec nous !\n"
        f"— SkyDive Pro"
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = resolved_from or "noreply@skydivepro.fr"
        msg["To"] = to_email

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(resolved_host, resolved_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if resolved_user and resolved_password:
                server.login(resolved_user, resolved_password)
            server.sendmail(
                msg["From"],
                [to_email],
                msg.as_string(),
            )

        log.info("Email envoyé à %s (saut : %s / %s)", to_email, date_saut, lieu)
        return True

    except smtplib.SMTPAuthenticationError as exc:
        log.error("Échec authentification SMTP : %s", exc)
        return False
    except smtplib.SMTPException as exc:
        log.error("Erreur SMTP lors de l'envoi à %s : %s", to_email, exc)
        return False
    except OSError as exc:
        log.error(
            "Impossible de joindre le serveur SMTP %s:%s — %s",
            resolved_host,
            resolved_port,
            exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Erreur inattendue lors de l'envoi email : %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 4. Orchestrateur
# ---------------------------------------------------------------------------

def deliver(
    job_id: str,
    nom_passager: str,
    email_client: str,
    date_saut: str,
    lieu: str,
    montage_path: Path,
    reels: list[dict],
    output_dir: Path,
    base_url: str = "http://localhost:5000",
) -> dict:
    """Orchestre la livraison complète d'un montage SkyDive Pro.

    Enchaîne :
    1. Génération de la page HTML de téléchargement
    2. Génération du QR code pointant vers la page
    3. Envoi de l'email au client

    Ne plante jamais — les erreurs sont loguées et reflétées dans le
    dict retourné.

    Args:
        job_id: Identifiant unique du job (utilisé pour nommer les fichiers).
        nom_passager: Prénom/nom du passager tandem.
        email_client: Adresse email du passager.
        date_saut: Date du saut (ex: "2026-06-02").
        lieu: Lieu du saut (ex: "Skydive Lyon").
        montage_path: Chemin absolu du fichier montage principal.
        reels: Liste de dicts [{type, path, duree_s}].
        output_dir: Dossier de sortie pour les fichiers générés.
        base_url: URL de base du serveur de téléchargement.

    Returns:
        Dict avec les clés :
        - "qr_code" (Path) : chemin du QR code (PNG ou TXT fallback)
        - "download_page" (Path) : chemin de la page HTML
        - "email_sent" (bool) : True si l'email a été envoyé
    """
    log.info(
        "Démarrage livraison job=%s passager=%s email=%s",
        job_id,
        nom_passager,
        email_client,
    )

    output_dir = Path(output_dir)
    montage_path = Path(montage_path)

    # URLs
    download_page_url = f"{base_url.rstrip('/')}/jobs/{job_id}/download.html"
    montage_filename = montage_path.name

    # ------------------------------------------------------------------
    # Étape 1 — Page HTML de téléchargement
    # ------------------------------------------------------------------
    download_page: Path
    try:
        download_page = generate_download_page(
            nom_passager=nom_passager,
            date_saut=date_saut,
            lieu=lieu,
            montage_filename=montage_filename,
            reels=reels,
            output_dir=output_dir,
            base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Impossible de générer la page de téléchargement : %s", exc, exc_info=True)
        # Fichier de secours minimaliste
        download_page = output_dir / "download.html"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            download_page.write_text(
                f"<html><body><a href='{base_url}/download/{montage_filename}'>"
                f"Télécharger</a></body></html>",
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Étape 2 — QR code
    # ------------------------------------------------------------------
    qr_code: Path
    try:
        qr_code = generate_qr_code(
            url=download_page_url,
            output_path=output_dir / f"qr_{job_id}.png",
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Impossible de générer le QR code : %s", exc, exc_info=True)
        qr_code = output_dir / f"qr_{job_id}.png"  # chemin attendu, peut ne pas exister

    # ------------------------------------------------------------------
    # Étape 3 — Email
    # ------------------------------------------------------------------
    email_sent = False
    try:
        email_sent = send_delivery_email(
            to_email=email_client,
            nom_passager=nom_passager,
            date_saut=date_saut,
            lieu=lieu,
            download_url=download_page_url,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Erreur inattendue lors de l'envoi email : %s", exc, exc_info=True)

    result = {
        "qr_code": qr_code,
        "download_page": download_page,
        "email_sent": email_sent,
    }
    log.info(
        "Livraison terminée job=%s | page=%s | qr=%s | email_sent=%s",
        job_id,
        download_page,
        qr_code,
        email_sent,
    )
    return result

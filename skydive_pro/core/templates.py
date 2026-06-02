"""
templates.py — Système de templates de montage pour SkyDive Pro.

Définit 3 styles visuels prédéfinis qui contrôlent :
  - les durées des scènes
  - les styles de transitions (cut / fade) et leur durée
  - l'étalonnage colorimétrique (filtre ffmpeg ou fichier LUT)
  - le style des overlays (couleurs)
  - la musique (tempo cible, volume)
  - les types de Reels activés

Usage :
    from core.templates import get_template, apply_template, DEFAULT_TEMPLATE

    tmpl = get_template("cinema_epique")
    overrides = apply_template(tmpl)
    # overrides["scene_durations"], overrides["fade_duration_s"], ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════
#  Répertoire des LUT (relatif au dossier assets/)
# ══════════════════════════════════════════════════════════════
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_LUTS_DIR = _ASSETS_DIR / "luts"


# ══════════════════════════════════════════════════════════════
#  Dataclass principale
# ══════════════════════════════════════════════════════════════
@dataclass
class MontageTemplate:
    """Définition complète d'un template de montage.

    Tous les champs sont des valeurs prêtes à l'emploi : le pipeline
    n'a pas à deviner quoi que ce soit — il lit le template et applique.

    Attributs
    ---------
    name : str
        Identifiant machine (clé dans TEMPLATES).
    label : str
        Nom affiché dans l'UI (français).
    description : str
        Description courte pour l'UI (1-2 phrases).
    scene_durations : dict[str, float]
        Durée cible par scène en secondes.
        Doit couvrir toutes les scènes définies dans SCENE_DURATIONS_CIBLE
        (ffmpeg_engine.py). Les scènes absentes utilisent les valeurs par
        défaut de ffmpeg_engine.
    transition_styles : dict[str, str]
        Style de transition après chaque scène : "cut" | "fade".
        Prioritaire sur SCENE_TRANSITION_STYLE (music_sync.py).
    fade_duration_s : float
        Durée du fondu (en secondes) pour les transitions "fade".
    lut_file : Optional[str]
        Nom du fichier LUT dans assets/luts/ (ex: "fun_energie.cube").
        None si pas de LUT réelle → ffmpeg_color_filter utilisé en fallback.
    ffmpeg_color_filter : str
        Chaîne de filtres ffmpeg (-vf) pour l'étalonnage colorimétrique.
        Toujours fourni : utilisé si lut_file est None ou si le fichier est
        introuvable. Exemple : "eq=saturation=1.3:contrast=1.1"
    overlay_style : dict
        Couleurs pour l'overlay (OverlayStyle dans overlay_generator.py).
        Clés : "color_primary", "color_secondary", "color_text" — tuples RGBA.
    music_tempo_range : tuple[int, int]
        Plage BPM cible (min, max) pour la sélection automatique de musique.
    music_volume : float
        Volume de la musique relative (0.0–1.0). Passé à _mix_music().
    enabled_reels : list[str]
        Sous-formats Reel activés pour ce template.
        Valeurs possibles : "adrenaline", "emotion", "paysage".
    max_duration_s : int
        Durée maximale du montage en secondes. Passé à select_best_clips().
    """

    name: str
    label: str
    description: str

    # Durées scènes (override complet de SCENE_DURATIONS_CIBLE)
    scene_durations: dict[str, float]

    # Transitions
    transition_styles: dict[str, str]   # scene -> "cut" | "fade"
    fade_duration_s: float

    # Étalonnage colorimétrique
    lut_file: Optional[str]             # fichier dans assets/luts/
    ffmpeg_color_filter: str            # filtre ffmpeg fallback (toujours fourni)

    # Overlays
    overlay_style: dict                 # color_primary, color_secondary, color_text

    # Musique
    music_tempo_range: tuple[int, int]  # (bpm_min, bpm_max)
    music_volume: float                 # 0.0-1.0

    # Reels
    enabled_reels: list[str]           # ["adrenaline", "emotion", "paysage"]

    # Budget durée
    max_duration_s: int

    # ── helpers ───────────────────────────────────────────────
    def lut_path(self) -> Optional[Path]:
        """Retourne le chemin absolu du fichier LUT, ou None si absent/indisponible."""
        if not self.lut_file:
            return None
        p = _LUTS_DIR / self.lut_file
        return p if p.exists() else None

    def effective_color_filter(self) -> str:
        """Retourne le filtre ffmpeg à utiliser (LUT ou fallback eq=...).

        Si un fichier LUT .cube est présent, construit la chaîne
        ``lut3d=<path>`` appropriée. Sinon retourne ffmpeg_color_filter.
        """
        lut = self.lut_path()
        if lut and lut.suffix.lower() == ".cube":
            # Échapper les backslashes Windows pour le graphe de filtres ffmpeg
            lut_posix = lut.as_posix().replace("\\", "/")
            return f"lut3d='{lut_posix}'"
        return self.ffmpeg_color_filter


# ══════════════════════════════════════════════════════════════
#  Catalogue des 3 templates
# ══════════════════════════════════════════════════════════════

# ── Constantes partagées ──────────────────────────────────────
# Scènes considérées comme "climax" dans tous les templates (never faded
# dans fun_energie, override possible dans les autres).
_ALL_SCENES = [
    "intro",
    "briefing",
    "vehicule_embarquement",
    "dans_avion",
    "paysage_avion",
    "montee_avion",
    "sortie_avion",
    "chute_libre",
    "sous_voile",
    "atterrissage",
    "reaction_emotion",
    "interaction_moniteur",
    "stats",
    "outro",
]

TEMPLATES: dict[str, MontageTemplate] = {

    # ──────────────────────────────────────────────────────────
    # 1. FUN & ÉNERGIE (default)
    # Public : jeunes clients, réseaux sociaux
    # ──────────────────────────────────────────────────────────
    "fun_energie": MontageTemplate(
        name="fun_energie",
        label="Fun & Énergie",
        description=(
            "Montage nerveux et dynamique pour les réseaux sociaux. "
            "Cuts secs, couleurs saturées, énergie maximale."
        ),

        scene_durations={
            "briefing":                  8.0,   # court — on veut aller vite
            "vehicule_embarquement":     4.0,
            "dans_avion":                8.0,
            "paysage_avion":            20.0,   # réduit vs défaut
            "montee_avion":              4.0,
            "sortie_avion":             28.0,
            "chute_libre":             100.0,   # allongé — climax principal
            "sous_voile":               25.0,
            "atterrissage":             30.0,
            "reaction_emotion":         25.0,
            "interaction_moniteur":     10.0,
        },

        transition_styles={
            "intro":                    "fade",  # ouverture douce
            "briefing":                 "cut",   # direct
            "vehicule_embarquement":    "cut",
            "dans_avion":               "cut",
            "paysage_avion":            "cut",
            "montee_avion":             "cut",
            "sortie_avion":             "cut",   # ⚡ climax
            "chute_libre":              "cut",   # ⚡ climax
            "sous_voile":               "cut",   # ⚡ climax
            "atterrissage":             "cut",   # ⚡ climax
            "reaction_emotion":         "cut",   # ⚡ punch
            "interaction_moniteur":     "fade",
            "stats":                    "fade",
            "outro":                    "fade",
        },
        fade_duration_s=0.25,  # fondu très court pour les rares fades

        lut_file=None,         # pas de .cube réel → filtre eq
        ffmpeg_color_filter="eq=saturation=1.3:contrast=1.1:brightness=0.02",

        overlay_style={
            "color_primary":   (255, 107,   0, 255),   # orange vif #FF6B00
            "color_secondary": ( 26,  26,  46, 255),   # bleu nuit
            "color_text":      (255, 255, 255, 255),   # blanc pur — bold
        },

        music_tempo_range=(120, 140),  # EDM / électro upbeat
        music_volume=0.40,

        enabled_reels=["adrenaline", "emotion", "paysage"],

        max_duration_s=280,
    ),

    # ──────────────────────────────────────────────────────────
    # 2. CINÉMA ÉPIQUE
    # Public : clients premium, souvenir cinématographique
    # ──────────────────────────────────────────────────────────
    "cinema_epique": MontageTemplate(
        name="cinema_epique",
        label="Cinéma Épique",
        description=(
            "Style cinéma grand angle. Transitions fondues, étalonnage teal/orange, "
            "rythme généreux qui met en valeur chaque plan."
        ),

        scene_durations={
            "briefing":                 12.0,
            "vehicule_embarquement":     6.0,
            "dans_avion":               12.0,
            "paysage_avion":            40.0,   # allongé — le panorama mérite d'être vu
            "montee_avion":              6.0,
            "sortie_avion":             32.0,
            "chute_libre":              90.0,
            "sous_voile":               35.0,   # allongé — flying contemplation
            "atterrissage":             38.0,
            "reaction_emotion":         28.0,
            "interaction_moniteur":     18.0,
        },

        transition_styles={
            "intro":                    "fade",
            "briefing":                 "fade",
            "vehicule_embarquement":    "fade",
            "dans_avion":               "fade",
            "paysage_avion":            "fade",
            "montee_avion":             "fade",
            "sortie_avion":             "fade",  # cinématique : pas de cut brutal
            "chute_libre":              "cut",   # seul cut net du film — impact max
            "sous_voile":               "fade",
            "atterrissage":             "fade",
            "reaction_emotion":         "fade",
            "interaction_moniteur":     "fade",
            "stats":                    "fade",
            "outro":                    "fade",
        },
        fade_duration_s=0.60,  # fondus longs = style cinéma

        lut_file=None,
        # Teal-orange cinema look : légère désaturation + contenu chaud + décalage
        # colorimétrique (rouges renforcés, bleus légèrement poussés = teal shadows)
        ffmpeg_color_filter=(
            "eq=saturation=0.85:contrast=1.15,"
            "colorbalance=rs=0.05:gs=-0.03:bs=0.08"
        ),

        overlay_style={
            "color_primary":   (212, 175,  55, 255),   # gold #D4AF37
            "color_secondary": ( 15,  15,  25, 255),   # noir cinéma
            "color_text":      (240, 235, 220, 255),   # blanc crème — élégant
        },

        music_tempo_range=(80, 100),   # orchestral / épique
        music_volume=0.35,

        # Pas de reel "adrenaline" — trop brut pour ce style
        enabled_reels=["paysage", "emotion"],

        max_duration_s=330,  # plus long — format premium
    ),

    # ──────────────────────────────────────────────────────────
    # 3. DOUX SOUVENIR
    # Public : familles, souvenir émotionnel
    # ──────────────────────────────────────────────────────────
    "doux_souvenir": MontageTemplate(
        name="doux_souvenir",
        label="Doux Souvenir",
        description=(
            "Montage doux et chaleureux centré sur les émotions familiales. "
            "Tout en fondus, tons pastels, musique acoustique."
        ),

        scene_durations={
            "briefing":                 12.0,
            "vehicule_embarquement":     6.0,
            "dans_avion":               12.0,
            "paysage_avion":            25.0,
            "montee_avion":              5.0,
            "sortie_avion":             28.0,
            "chute_libre":              80.0,   # moins long — pas l'objet
            "sous_voile":               30.0,
            "atterrissage":             35.0,
            "reaction_emotion":         40.0,   # allongé — cœur du film
            "interaction_moniteur":     20.0,   # allongé — le débriefing humain
        },

        transition_styles={
            "intro":                    "fade",
            "briefing":                 "fade",
            "vehicule_embarquement":    "fade",
            "dans_avion":               "fade",
            "paysage_avion":            "fade",
            "montee_avion":             "fade",
            "sortie_avion":             "fade",
            "chute_libre":              "fade",
            "sous_voile":               "fade",
            "atterrissage":             "fade",
            "reaction_emotion":         "fade",  # moment clé — fondu doux
            "interaction_moniteur":     "fade",
            "stats":                    "fade",
            "outro":                    "fade",
        },
        fade_duration_s=0.80,  # fondus longs et doux

        lut_file=None,
        # Tons chauds doux + léger vignettage (fenêtre de vieux souvenir)
        ffmpeg_color_filter=(
            "eq=saturation=0.9:contrast=0.95:brightness=0.03,"
            "vignette=PI/4"
        ),

        overlay_style={
            "color_primary":   (232, 168, 124, 255),   # pastel pêche #E8A87C
            "color_secondary": ( 50,  40,  35, 255),   # brun doux
            "color_text":      (255, 252, 245, 255),   # blanc chaud
        },

        music_tempo_range=(70, 90),   # acoustique / piano
        music_volume=0.30,

        # Uniquement "emotion" — c'est le moment famille
        enabled_reels=["emotion"],

        max_duration_s=300,
    ),
}

# Template utilisé par défaut si aucun n'est spécifié
DEFAULT_TEMPLATE = "fun_energie"


# ══════════════════════════════════════════════════════════════
#  API publique
# ══════════════════════════════════════════════════════════════

def get_template(name: str) -> MontageTemplate:
    """Retourne le template demandé.

    Args:
        name : identifiant du template ("fun_energie", "cinema_epique",
               "doux_souvenir") ou None/chaîne vide → DEFAULT_TEMPLATE.

    Raises:
        KeyError : si le nom n'existe pas dans TEMPLATES.
    """
    if not name:
        name = DEFAULT_TEMPLATE
    if name not in TEMPLATES:
        raise KeyError(
            f"Template inconnu : '{name}'. "
            f"Disponibles : {list(TEMPLATES.keys())}"
        )
    return TEMPLATES[name]


def list_templates() -> list[dict]:
    """Retourne la liste des templates sous forme de dicts pour l'UI.

    Returns:
        Liste de dicts avec les clés : name, label, description,
        enabled_reels, music_tempo_range, max_duration_s.
    """
    return [
        {
            "name":              t.name,
            "label":             t.label,
            "description":       t.description,
            "enabled_reels":     t.enabled_reels,
            "music_tempo_range": t.music_tempo_range,
            "max_duration_s":    t.max_duration_s,
        }
        for t in TEMPLATES.values()
    ]


def apply_template(template: MontageTemplate) -> dict:
    """Traduit un MontageTemplate en un dict plat d'overrides pour le pipeline.

    Le pipeline (agent/pipeline.py et core/ffmpeg_engine.py) consomme
    directement ce dict : les clés correspondent aux paramètres de
    ``build_montage`` et aux constantes de ``ffmpeg_engine``.

    Returns:
        dict avec les clés :
          - scene_durations       : dict[str, float]
          - transition_styles     : dict[str, str]
          - fade_duration_s       : float
          - color_filter          : str  — chaîne ffmpeg -vf (LUT ou eq=...)
          - lut_path              : Optional[Path]  — None si pas de .cube
          - overlay_style         : dict (color_primary, color_secondary, color_text)
          - music_tempo_range     : tuple[int, int]
          - music_volume          : float
          - enabled_reels         : list[str]
          - max_duration_s        : int
          - template_name         : str  — pour logging / traçabilité
    """
    return {
        "scene_durations":    template.scene_durations,
        "transition_styles":  template.transition_styles,
        "fade_duration_s":    template.fade_duration_s,
        "color_filter":       template.effective_color_filter(),
        "lut_path":           template.lut_path(),
        "overlay_style":      template.overlay_style,
        "music_tempo_range":  template.music_tempo_range,
        "music_volume":       template.music_volume,
        "enabled_reels":      template.enabled_reels,
        "max_duration_s":     template.max_duration_s,
        "template_name":      template.name,
    }


# ══════════════════════════════════════════════════════════════
#  Smoke test CLI
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=== Templates disponibles ===\n")
    for info in list_templates():
        print(f"[{info['name']}]  {info['label']}")
        print(f"  {info['description']}")
        print(f"  Reels    : {', '.join(info['enabled_reels'])}")
        print(f"  BPM cible: {info['music_tempo_range'][0]}–{info['music_tempo_range'][1]}")
        print(f"  Durée max: {info['max_duration_s']}s")
        print()

    print("=== apply_template(cinema_epique) ===\n")
    t = get_template("cinema_epique")
    overrides = apply_template(t)
    for k, v in overrides.items():
        print(f"  {k:<22} = {v}")

#!/usr/bin/env bash
# ====================================================================
#  SkyDive Pro — Script d'installation Mac / Linux
#  Usage : bash setup.sh   (depuis le dossier skydive_pro/)
# ====================================================================

# Couleurs ANSI
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
RESET='\033[0m'

STEPS=9

step()  { echo "" ; echo -e "${YELLOW}[$1/$STEPS] $2${RESET}"; }
ok()    { echo -e "${GREEN}  OK $1${RESET}"; }
warn()  { echo -e "${YELLOW}  ATTENTION $1${RESET}"; }
err()   { echo -e "${RED}  ERREUR $1${RESET}"; }
note()  { echo -e "${GRAY}  $1${RESET}"; }

echo ""
echo -e "${CYAN}  SkyDive Pro - Installation Mac/Linux${RESET}"
echo -e "${CYAN}  ======================================${RESET}"
echo ""

# ─── Se placer dans le repertoire du script ─────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"


# ─── [1/9] Verifier Python 3.11+ ─────────────────────────────────────────────
step "1" "Verification de Python 3.11+..."

PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version_str=$("$cmd" --version 2>&1)
        if [[ "$version_str" =~ Python[[:space:]]([0-9]+)\.([0-9]+) ]]; then
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python 3.11+ non detecte."
    echo -e "${RED}    Mac   : brew install python@3.11${RESET}"
    echo -e "${RED}    Linux : sudo apt install python3.11 python3.11-venv${RESET}"
    echo ""
    exit 1
fi

PY_VER=$("$PYTHON_CMD" --version 2>&1)
ok "$PY_VER detecte ($PYTHON_CMD)"


# ─── [2/9] Verifier FFmpeg ────────────────────────────────────────────────────
step "2" "Verification de FFmpeg..."

FFMPEG_OK=false
if command -v ffmpeg &>/dev/null; then
    FF_VER=$(ffmpeg -version 2>&1 | head -n 1)
    ok "$FF_VER"
    FFMPEG_OK=true

    # Hardware encoder check
    ENCODERS=$(ffmpeg -hide_banner -encoders 2>&1)
    if echo "$ENCODERS" | grep -q "h264_videotoolbox"; then
        ok "Encodeur Apple VideoToolbox disponible (acceleration hardware)"
    elif echo "$ENCODERS" | grep -q "h264_nvenc"; then
        ok "Encodeur NVIDIA NVENC disponible (acceleration hardware)"
    elif echo "$ENCODERS" | grep -q "h264_amf"; then
        ok "Encodeur AMD AMF disponible (acceleration hardware)"
    else
        warn "Aucun encodeur hardware detecte — encodage CPU uniquement"
    fi
else
    warn "FFmpeg non detecte. Tentative d'installation automatique..."

    OS_TYPE="$(uname -s)"
    INSTALLED=false

    if [ "$OS_TYPE" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            echo -e "${GRAY}  -> brew install ffmpeg (peut prendre quelques minutes)...${RESET}"
            if brew install ffmpeg; then
                ok "FFmpeg installe via Homebrew"
                FFMPEG_OK=true
                INSTALLED=true
            fi
        else
            warn "Homebrew non trouve."
            echo -e "${YELLOW}    Installe Homebrew : https://brew.sh${RESET}"
            echo -e "${YELLOW}    Puis : brew install ffmpeg${RESET}"
        fi
    elif [ "$OS_TYPE" = "Linux" ]; then
        if command -v apt-get &>/dev/null; then
            echo -e "${GRAY}  -> sudo apt-get install -y ffmpeg...${RESET}"
            if sudo apt-get install -y ffmpeg; then
                ok "FFmpeg installe via apt"
                FFMPEG_OK=true
                INSTALLED=true
            fi
        elif command -v dnf &>/dev/null; then
            echo -e "${GRAY}  -> sudo dnf install -y ffmpeg...${RESET}"
            if sudo dnf install -y ffmpeg; then
                ok "FFmpeg installe via dnf"
                FFMPEG_OK=true
                INSTALLED=true
            fi
        else
            warn "Gestionnaire de paquets non reconnu."
        fi
    fi

    if [ "$INSTALLED" = false ]; then
        warn "FFmpeg n'a pas pu etre installe automatiquement."
        echo -e "${YELLOW}    Mac   : brew install ffmpeg${RESET}"
        echo -e "${YELLOW}    Linux : sudo apt install ffmpeg${RESET}"
        echo -e "${YELLOW}    Le script continue, mais le pipeline ne fonctionnera pas sans FFmpeg.${RESET}"
    fi
fi


# ─── [3/9] Creer le venv ─────────────────────────────────────────────────────
step "3" "Creation de l'environnement virtuel Python (.venv)..."

if [ ! -d ".venv" ]; then
    if ! "$PYTHON_CMD" -m venv .venv; then
        err "Echec de la creation du venv."
        echo -e "${RED}    Mac   : brew install python@3.11${RESET}"
        echo -e "${RED}    Linux : sudo apt install python3.11-venv${RESET}"
        exit 1
    fi
    ok ".venv cree"
else
    ok ".venv deja existant"
fi


# ─── [4/9] Activer le venv et installer les dependances ──────────────────────
step "4" "Installation des dependances Python..."
note "(peut prendre 5-10 minutes la 1ere fois — TensorFlow / DeepFace sont volumineux)"

# shellcheck disable=SC1091
source .venv/bin/activate

PYTHON_VENV=".venv/bin/python"
PIP_VENV=".venv/bin/pip"

if ! "$PYTHON_VENV" -m pip install --upgrade pip --quiet; then
    err "Echec de la mise a jour de pip."
    exit 1
fi

if ! "$PIP_VENV" install -r requirements.txt; then
    err "Echec de l'installation des dependances (pip install -r requirements.txt)."
    echo -e "${RED}    Verifie ta connexion internet et les erreurs ci-dessus.${RESET}"
    exit 1
fi
ok "Dependances installees"


# ─── [5/9] Creer .env depuis .env.example ────────────────────────────────────
step "5" "Initialisation de la configuration (.env)..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp ".env.example" ".env"
        warn ".env cree depuis .env.example — remplis-le avec tes cles API !"
    else
        warn ".env.example introuvable — cree .env manuellement."
    fi
else
    ok ".env existe deja"
fi


# ─── [6/9] Creer les repertoires necessaires ─────────────────────────────────
step "6" "Creation des repertoires necessaires..."

for d in sources output assets/music assets/luts assets/branding; do
    if [ ! -d "$d" ]; then
        mkdir -p "$d"
        ok "Cree : $d"
    else
        ok "Existe : $d"
    fi
done


# ─── [7/9] Initialiser la base de donnees SQLite ─────────────────────────────
step "7" "Initialisation de la base de donnees SQLite..."

if "$PYTHON_VENV" -c "from db.models import init_db; init_db()" 2>&1; then
    ok "Base de donnees initialisee"
else
    warn "Echec de l'initialisation de la BDD."
    echo -e "${YELLOW}    Tu pourras relancer : .venv/bin/python -c \"from db.models import init_db; init_db()\"${RESET}"
fi


# ─── [8/9] Lancer les tests ───────────────────────────────────────────────────
step "8" "Lancement des tests (pytest tests/ -v)..."

PYTEST_VENV=".venv/bin/pytest"
if [ -f "$PYTEST_VENV" ]; then
    if "$PYTEST_VENV" tests/ -v; then
        ok "Tous les tests passent"
    else
        warn "Certains tests ont echoue (voir ci-dessus). Le pipeline peut quand meme fonctionner."
    fi
else
    warn "pytest introuvable dans le venv — tests non lances."
fi


# ─── [9/9] Resume et prochaines etapes ───────────────────────────────────────
step "9" "Installation terminee !"
echo ""
echo -e "${CYAN}  Prochaines etapes :${RESET}"
echo ""
echo -e "  1. Edite .env et renseigne au moins GEMINI_API_KEY"
echo -e "     ${GRAY}Obtenir une cle gratuite : https://aistudio.google.com/app/apikey${RESET}"
echo ""
echo -e "  2. Place une video GoPro test dans sources/"
echo ""
echo -e "  3. Place ton logo dans assets/branding/logo_dropzone.png"
echo ""
echo -e "  4. Active le venv avant chaque session de dev :"
echo -e "     ${GRAY}source .venv/bin/activate${RESET}"
echo ""
echo -e "  5. Lance le pipeline :"
echo -e "     ${GRAY}.venv/bin/python -m agent.pipeline sources/ta_video.mp4 'Prenom Passager'${RESET}"
echo ""

if [ "$FFMPEG_OK" = false ]; then
    echo -e "${YELLOW}  ATTENTION : FFmpeg n'est pas installe — installe-le avant d'utiliser le pipeline.${RESET}"
    echo -e "${YELLOW}              Mac : brew install ffmpeg | Linux : sudo apt install ffmpeg${RESET}"
    echo ""
fi

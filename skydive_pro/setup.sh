#!/usr/bin/env bash
# ====================================================================
#  SkyDive Pro — Script d'installation Mac / Linux
#  Usage : bash setup.sh
# ====================================================================

set -e

echo ""
echo "🪂  SkyDive Pro - Installation Mac/Linux"
echo "========================================"
echo ""

# ─── 1. Vérifier Python ─────────────────────────────────
echo "[1/6] Vérification de Python..."
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 non détecté."
    echo "    Mac   : brew install python@3.11"
    echo "    Linux : sudo apt install python3.11 python3.11-venv"
    exit 1
fi
PY_VERSION=$(python3 --version)
echo "  ✓ $PY_VERSION"

# ─── 2. Vérifier FFmpeg ─────────────────────────────────
echo ""
echo "[2/6] Vérification de FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "  ✗ FFmpeg non détecté."
    echo "    Mac   : brew install ffmpeg"
    echo "    Linux : sudo apt install ffmpeg"
    exit 1
fi
FF_VERSION=$(ffmpeg -version 2>&1 | head -n 1)
echo "  ✓ $FF_VERSION"

# Encodeur hardware disponible ?
if ffmpeg -hide_banner -encoders 2>&1 | grep -q "h264_videotoolbox"; then
    echo "  ✓ Encodeur Apple VideoToolbox disponible"
elif ffmpeg -hide_banner -encoders 2>&1 | grep -q "h264_nvenc"; then
    echo "  ✓ Encodeur NVIDIA NVENC disponible"
elif ffmpeg -hide_banner -encoders 2>&1 | grep -q "h264_amf"; then
    echo "  ✓ Encodeur AMD AMF disponible"
else
    echo "  ⚠ Encodeur hardware non détecté — encodage CPU only"
fi

# ─── 3. Créer le venv ───────────────────────────────────
echo ""
echo "[3/6] Création de l'environnement virtuel Python..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  ✓ .venv créé"
else
    echo "  ✓ .venv déjà existant"
fi

# ─── 4. Installer les dépendances ───────────────────────
echo ""
echo "[4/6] Installation des dépendances Python..."
echo "  (ça peut prendre 5-10 minutes la 1ère fois)"
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
echo "  ✓ Dépendances installées"

# ─── 5. Copier les fichiers de config ───────────────────
echo ""
echo "[5/6] Initialisation de la configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ .env créé — ⚠️  remplis-le avec tes clés API !"
else
    echo "  ✓ .env existe déjà"
fi

if [ ! -f "config/config.yaml" ]; then
    cp config/config.yaml.example config/config.yaml
    echo "  ✓ config.yaml créé"
else
    echo "  ✓ config.yaml existe déjà"
fi

# ─── 6. Récap ────────────────────────────────────────────
echo ""
echo "[6/6] Installation terminée ! 🎉"
echo ""
echo "Prochaines étapes :"
echo "  1. Édite le fichier .env et renseigne au moins GEMINI_API_KEY"
echo "     → Obtenir une clé gratuite : https://aistudio.google.com/app/apikey"
echo ""
echo "  2. Édite config/config.yaml pour ton branding dropzone"
echo ""
echo "  3. Place ton logo dans assets/branding/logo_dropzone.png"
echo ""
echo "  4. Place une vidéo GoPro test dans sources/"
echo ""
echo "  5. Active le venv avant chaque session :"
echo "     source .venv/bin/activate"
echo ""

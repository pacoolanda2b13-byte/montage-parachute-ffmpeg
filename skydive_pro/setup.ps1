# ====================================================================
#  SkyDive Pro — Script d'installation Windows
#  Usage : Ouvrir PowerShell dans le dossier skydive_pro puis :
#          .\setup.ps1
# ====================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "🪂  SkyDive Pro - Installation Windows" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# ─── 1. Vérifier Python ──────────────────────────────────
Write-Host "[1/6] Vérification de Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python non détecté." -ForegroundColor Red
    Write-Host "    Installe Python 3.11+ depuis https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "    (⚠️  coche bien 'Add Python to PATH' pendant l'installation)" -ForegroundColor Red
    exit 1
}

# ─── 2. Vérifier FFmpeg ──────────────────────────────────
Write-Host ""
Write-Host "[2/6] Vérification de FFmpeg..." -ForegroundColor Yellow
try {
    $ffmpegVersion = ffmpeg -version 2>&1 | Select-Object -First 1
    Write-Host "  ✓ $ffmpegVersion" -ForegroundColor Green

    # Check AMF encoder (AMD)
    $hasAmf = (ffmpeg -hide_banner -encoders 2>&1 | Select-String "h264_amf") -ne $null
    if ($hasAmf) {
        Write-Host "  ✓ Encodeur AMD AMF disponible (accélération hardware)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ Encodeur AMD AMF non détecté — encodage CPU only" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ✗ FFmpeg non détecté." -ForegroundColor Red
    Write-Host "    Installation : winget install ffmpeg" -ForegroundColor Red
    Write-Host "    Puis redémarre PowerShell." -ForegroundColor Red
    exit 1
}

# ─── 3. Créer le venv ───────────────────────────────────
Write-Host ""
Write-Host "[3/6] Création de l'environnement virtuel Python..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  ✓ .venv créé" -ForegroundColor Green
} else {
    Write-Host "  ✓ .venv déjà existant" -ForegroundColor Green
}

# ─── 4. Activer le venv et installer les deps ──────────
Write-Host ""
Write-Host "[4/6] Installation des dépendances Python..." -ForegroundColor Yellow
Write-Host "  (ça peut prendre 5-10 minutes la 1ère fois — TensorFlow/DeepFace sont volumineux)" -ForegroundColor DarkGray
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
Write-Host "  ✓ Dépendances installées" -ForegroundColor Green

# ─── 5. Copier les fichiers de config ───────────────────
Write-Host ""
Write-Host "[5/6] Initialisation de la configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "  ✓ .env créé — ⚠️  remplis-le avec tes clés API !" -ForegroundColor Yellow
} else {
    Write-Host "  ✓ .env existe déjà" -ForegroundColor Green
}

if (-not (Test-Path "config\config.yaml")) {
    Copy-Item config\config.yaml.example config\config.yaml
    Write-Host "  ✓ config.yaml créé" -ForegroundColor Green
} else {
    Write-Host "  ✓ config.yaml existe déjà" -ForegroundColor Green
}

# ─── 6. Récap ────────────────────────────────────────────
Write-Host ""
Write-Host "[6/6] Installation terminée ! 🎉" -ForegroundColor Green
Write-Host ""
Write-Host "Prochaines étapes :" -ForegroundColor Cyan
Write-Host "  1. Édite le fichier .env et renseigne au moins GEMINI_API_KEY" -ForegroundColor White
Write-Host "     → Obtenir une clé gratuite : https://aistudio.google.com/app/apikey" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  2. Édite config\config.yaml pour ton branding dropzone" -ForegroundColor White
Write-Host ""
Write-Host "  3. Place ton logo dans assets\branding\logo_dropzone.png" -ForegroundColor White
Write-Host ""
Write-Host "  4. Place une vidéo GoPro test dans sources\" -ForegroundColor White
Write-Host ""
Write-Host "  5. Active le venv avant chaque session de dev :" -ForegroundColor White
Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor DarkGray
Write-Host ""

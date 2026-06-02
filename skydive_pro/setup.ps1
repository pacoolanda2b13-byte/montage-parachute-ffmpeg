# ====================================================================
#  SkyDive Pro — Script d'installation Windows
#  Usage : Ouvrir PowerShell dans le dossier skydive_pro puis :
#          .\setup.ps1
# ====================================================================

$ErrorActionPreference = "Stop"
$STEPS = 9

function Write-Step { param($n, $msg) Write-Host "" ; Write-Host "[$n/$STEPS] $msg" -ForegroundColor Yellow }
function Write-OK   { param($msg) Write-Host "  OK $msg" -ForegroundColor Green }
function Write-WARN { param($msg) Write-Host "  ATTENTION $msg" -ForegroundColor Yellow }
function Write-ERR  { param($msg) Write-Host "  ERREUR $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  SkyDive Pro - Installation Windows" -ForegroundColor Cyan
Write-Host "  =====================================" -ForegroundColor Cyan
Write-Host ""

# ─── Determine script location ──────────────────────────────────────────────
# Support both: running from inside skydive_pro/ or from project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir


# ─── [1/9] Verifier Python 3.11+ ─────────────────────────────────────────────
Write-Step "1" "Verification de Python 3.11+..."

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                $pythonCmd = $cmd
                break
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-ERR "Python 3.11+ non detecte."
    Write-Host "    Installe Python 3.11 ou superieur depuis https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "    (Coche bien 'Add Python to PATH' pendant l'installation)" -ForegroundColor Red
    Write-Host ""
    exit 1
}

$pyVer = & $pythonCmd --version 2>&1
Write-OK "$pyVer detecte ($pythonCmd)"


# ─── [2/9] Verifier FFmpeg ────────────────────────────────────────────────────
Write-Step "2" "Verification de FFmpeg..."

$ffmpegOk = $false
try {
    $ffVer = ffmpeg -version 2>&1 | Select-Object -First 1
    $ffmpegOk = $true
    Write-OK $ffVer

    # Hardware encoder check
    $encoders = ffmpeg -hide_banner -encoders 2>&1
    if ($encoders | Select-String "h264_amf") {
        Write-OK "Encodeur AMD AMF disponible (acceleration hardware)"
    } elseif ($encoders | Select-String "h264_nvenc") {
        Write-OK "Encodeur NVIDIA NVENC disponible (acceleration hardware)"
    } else {
        Write-WARN "Aucun encodeur hardware detecte — encodage CPU uniquement"
    }
} catch {
    Write-WARN "FFmpeg non detecte. Tentative d'installation via winget..."
    try {
        winget install --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
        Write-OK "FFmpeg installe via winget. Redemarrage de PowerShell recommande apres ce script."
        $ffmpegOk = $true
    } catch {
        Write-WARN "Installation automatique echouee."
        Write-Host "    Installe manuellement : winget install ffmpeg" -ForegroundColor Yellow
        Write-Host "    Puis redемarre PowerShell et relance ce script." -ForegroundColor Yellow
        Write-Host "    (le script continue, mais le pipeline ne fonctionnera pas sans FFmpeg)" -ForegroundColor Yellow
    }
}


# ─── [3/9] Creer le venv ─────────────────────────────────────────────────────
Write-Step "3" "Creation de l'environnement virtuel Python (.venv)..."

if (-not (Test-Path ".venv")) {
    & $pythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-ERR "Echec de la creation du venv. Assure-toi que python3-venv est installe."
        exit 1
    }
    Write-OK ".venv cree"
} else {
    Write-OK ".venv deja existant"
}


# ─── [4/9] Activer le venv et installer les dependances ──────────────────────
Write-Step "4" "Installation des dependances Python..."
Write-Host "  (peut prendre 5-10 minutes la 1ere fois — TensorFlow / DeepFace sont volumineux)" -ForegroundColor DarkGray

$activateScript = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-ERR "Script d'activation du venv introuvable : $activateScript"
    exit 1
}
& $activateScript

$pipExe = ".\.venv\Scripts\pip.exe"
$pythonVenv = ".\.venv\Scripts\python.exe"

& $pythonVenv -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-ERR "Echec de la mise a jour de pip."
    exit 1
}

& $pipExe install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-ERR "Echec de l'installation des dependances (pip install -r requirements.txt)."
    Write-Host "    Verifie ta connexion internet et les erreurs ci-dessus." -ForegroundColor Red
    exit 1
}
Write-OK "Dependances installees"


# ─── [5/9] Creer .env depuis .env.example ────────────────────────────────────
Write-Step "5" "Initialisation de la configuration (.env)..."

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-WARN ".env cree depuis .env.example — remplis-le avec tes cles API !"
    } else {
        Write-WARN ".env.example introuvable — cree .env manuellement."
    }
} else {
    Write-OK ".env existe deja"
}


# ─── [6/9] Creer les repertoires necessaires ─────────────────────────────────
Write-Step "6" "Creation des repertoires necessaires..."

$dirs = @(
    "sources",
    "output",
    "assets\music",
    "assets\luts",
    "assets\branding"
)

foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-OK "Cree : $d"
    } else {
        Write-OK "Existe : $d"
    }
}


# ─── [7/9] Initialiser la base de donnees SQLite ─────────────────────────────
Write-Step "7" "Initialisation de la base de donnees SQLite..."

try {
    & $pythonVenv -c "from db.models import init_db; init_db()"
    if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
    Write-OK "Base de donnees initialisee"
} catch {
    Write-WARN "Echec de l'initialisation de la BDD : $_"
    Write-Host "    Tu pourras relancer : .venv\Scripts\python.exe -c `"from db.models import init_db; init_db()`"" -ForegroundColor Yellow
}


# ─── [8/9] Lancer les tests ───────────────────────────────────────────────────
Write-Step "8" "Lancement des tests (pytest tests/ -v)..."

$pytestExe = ".\.venv\Scripts\pytest.exe"
try {
    & $pytestExe tests/ -v
    if ($LASTEXITCODE -ne 0) {
        Write-WARN "Certains tests ont echoue (voir ci-dessus). Le pipeline peut quand meme fonctionner."
    } else {
        Write-OK "Tous les tests passent"
    }
} catch {
    Write-WARN "Impossible de lancer pytest : $_"
}


# ─── [9/9] Resume et prochaines etapes ───────────────────────────────────────
Write-Step "9" "Installation terminee !"
Write-Host ""
Write-Host "  Prochaines etapes :" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Edite .env et renseigne au moins GEMINI_API_KEY" -ForegroundColor White
Write-Host "     Obtenir une cle gratuite : https://aistudio.google.com/app/apikey" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  2. Place une video GoPro test dans sources\" -ForegroundColor White
Write-Host ""
Write-Host "  3. Place ton logo dans assets\branding\logo_dropzone.png" -ForegroundColor White
Write-Host ""
Write-Host "  4. Active le venv avant chaque session de dev :" -ForegroundColor White
Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  5. Lance le pipeline :" -ForegroundColor White
Write-Host "     .venv\Scripts\python.exe -m agent.pipeline sources\ta_video.mp4 'Prenom Passager'" -ForegroundColor DarkGray
Write-Host ""

if (-not $ffmpegOk) {
    Write-Host "  ATTENTION : FFmpeg n'est pas installe — installe-le avant d'utiliser le pipeline." -ForegroundColor Yellow
    Write-Host "              winget install ffmpeg" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================================
#  SkyDive Pro — Script de démo client (Windows PowerShell)
# ============================================================================
#  Usage :
#    .\demo.ps1                          # Mode rapide (clip 32s)
#    .\demo.ps1 -Long                    # Mode complet (saut 9 min → 3 min final)
#    .\demo.ps1 -Video "sources/X.mp4"   # Vidéo sur mesure
#
#  Ce script :
#   1. Vérifie le venv et FFmpeg
#   2. Affiche les infos système (encodeur AMD AMF actif)
#   3. Lance le pipeline avec timing visible
#   4. Ouvre le montage final dans le lecteur par défaut
# ============================================================================

[CmdletBinding()]
param(
    [string]$Video,
    [string]$Passager = "Démo Client",
    [string]$Dropzone = "SkyDive Pro",
    [string]$Site = "skydive-pro.fr",
    [int]$MaxDuration = 180,
    [switch]$Long,
    [switch]$NoOpen,
    [switch]$NoVision
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Join-Path $RootDir "skydive_pro"
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Stop-OnError {
    param([string]$Message)
    Write-Host "[ERREUR] $Message" -ForegroundColor Red
    exit 1
}

# ─── 1. Pré-flight checks ───────────────────────────────────────────────────
Write-Section "1/4  Vérifications environnement"

if (-not (Test-Path $VenvPython)) {
    Stop-OnError "Venv introuvable : $VenvPython. Lance setup.ps1 d'abord."
}
Write-Host "[OK] Venv Python : $VenvPython" -ForegroundColor Green

try {
    $ffmpegVersion = (& ffmpeg -version 2>&1 | Select-Object -First 1)
    Write-Host "[OK] $ffmpegVersion" -ForegroundColor Green
} catch {
    Stop-OnError "FFmpeg introuvable dans le PATH"
}

$envFile = Join-Path $ProjectDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[ATTENTION] $envFile manquant — vision Gemini désactivée" -ForegroundColor Yellow
}

# ─── 2. Choix de la vidéo ───────────────────────────────────────────────────
Write-Section "2/4  Sélection vidéo source"

if ($Video) {
    $videoPath = $Video
} elseif ($Long) {
    $videoPath = "sources/soren_complet.mp4"
    $MaxDuration = 210
} else {
    $videoPath = "sources/GX016030.MP4"
    $MaxDuration = 90
}

$absoluteVideo = Join-Path $ProjectDir $videoPath
if (-not (Test-Path $absoluteVideo)) {
    Stop-OnError "Vidéo source introuvable : $absoluteVideo"
}
$videoSize = [math]::Round((Get-Item $absoluteVideo).Length / 1MB, 1)
Write-Host "[OK] Vidéo : $videoPath ($videoSize MB)" -ForegroundColor Green
Write-Host "     Passager : $Passager"
Write-Host "     Dropzone : $Dropzone"
Write-Host "     Durée cible montage : $MaxDuration s"

# ─── 3. Lancement du pipeline ───────────────────────────────────────────────
Write-Section "3/4  Génération du montage"

$jobId = "demo-{0}" -f (Get-Date -Format "yyyyMMddHHmmss")
$useVision = if ($NoVision) { "False" } else { "True" }

$pythonScript = @"
import sys, json
sys.path.insert(0, '.')
from agent.pipeline import process_jump
r = process_jump(
    video_path=r'$videoPath',
    nom_passager=r'$Passager',
    date_saut='$(Get-Date -Format yyyy-MM-dd)',
    job_id='$jobId',
    use_vision=$useVision,
    keyframe_interval=30,
    max_duration_s=$MaxDuration,
    dropzone_nom=r'$Dropzone',
    dropzone_site=r'$Site',
)
print('---RESULT---')
print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False, default=str))
import sys as _s
_s.exit(0 if r.statut == 'succes' else 1)
"@

$startTime = Get-Date
Push-Location $ProjectDir
try {
    & $VenvPython -c $pythonScript
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
$elapsed = (Get-Date) - $startTime

if ($exitCode -ne 0) {
    Stop-OnError "Pipeline échec (exit $exitCode)"
}

# ─── 4. Ouverture du montage ────────────────────────────────────────────────
Write-Section "4/4  Montage prêt"

$videoStem = [System.IO.Path]::GetFileNameWithoutExtension($videoPath)
$outputFile = Join-Path $ProjectDir "output\${jobId}_${videoStem}_montage.mp4"

if (Test-Path $outputFile) {
    $sizeMB = [math]::Round((Get-Item $outputFile).Length / 1MB, 1)
    Write-Host "[OK] Fichier : $outputFile" -ForegroundColor Green
    Write-Host "     Taille  : $sizeMB MB"
    Write-Host "     Durée traitement : $([math]::Round($elapsed.TotalSeconds, 1)) s"
    if (-not $NoOpen) {
        Write-Host "Ouverture du montage..." -ForegroundColor Cyan
        Start-Process $outputFile
    }
} else {
    Stop-OnError "Fichier de sortie introuvable : $outputFile"
}

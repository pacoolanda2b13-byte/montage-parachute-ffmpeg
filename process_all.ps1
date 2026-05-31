# ============================================================================
#  SkyDive Pro — Traitement par lot (batch)
# ============================================================================
#  Workflow simple :
#
#    Pour 1 saut = 1 fichier déjà concaténé :
#       Mets le MP4 directement dans sources/
#       Ex: sources/saut_paul.mp4
#
#    Pour 1 saut = plusieurs chapitres GoPro (cas typique) :
#       Crée un sous-dossier au nom du passager
#       Mets-y tous les chapitres
#       Ex: sources/PAUL/GH015424.MP4
#           sources/PAUL/GH015425.MP4
#           sources/PAUL/GH015430.MP4
#
#  → Lance ce script
#  → Récupère les montages dans skydive_pro/output/
#
#  Usage :
#    .\process_all.ps1                       # Tout, avec vision Gemini
#    .\process_all.ps1 -NoVision             # Mode rapide (sans Gemini)
#    .\process_all.ps1 -Force                # Refait même les déjà traités
#    .\process_all.ps1 -DryRun               # Liste ce qu'il VA faire
#    .\process_all.ps1 -Dropzone "Lyon"      # Branding personnalisé
# ============================================================================

[CmdletBinding()]
param(
    [string]$Dropzone = "SkyDive Pro",
    [string]$Site = "skydive-pro.fr",
    [int]$MaxDuration = 320,
    [switch]$NoVision,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Join-Path $RootDir "skydive_pro"
$SourcesDir = Join-Path $ProjectDir "sources"
$OutputDir = Join-Path $ProjectDir "output"
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$MusicPath = Join-Path $ProjectDir "assets\music\ref_audio.m4a"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor Cyan
}
function Write-Info { param($Msg) Write-Host "[INFO] $Msg" -ForegroundColor Gray }
function Write-Ok   { param($Msg) Write-Host "[OK]   $Msg" -ForegroundColor Green }
function Write-Warn { param($Msg) Write-Host "[WARN] $Msg" -ForegroundColor Yellow }
function Write-Err  { param($Msg) Write-Host "[ERR]  $Msg" -ForegroundColor Red }

# ─── 1. PRÉ-FLIGHT CHECKS ──────────────────────────────────────────────────
Write-Section "1/5  Verifications environnement"

if (-not (Test-Path $VenvPython)) {
    Write-Err "Venv Python introuvable : $VenvPython"
    exit 1
}
Write-Ok "Venv Python OK"

try {
    $null = & ffmpeg -version 2>&1
    Write-Ok "FFmpeg OK"
} catch {
    Write-Err "FFmpeg introuvable dans le PATH"
    exit 1
}

if (-not (Test-Path $SourcesDir)) {
    Write-Err "Dossier sources introuvable : $SourcesDir"
    exit 1
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# ─── 2. INVENTAIRE ─────────────────────────────────────────────────────────
Write-Section "2/5  Inventaire"

# Sous-dossiers = 1 saut composé de N chapitres à concaténer
$subDirs = Get-ChildItem -Path $SourcesDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike ".*" -and $_.Name -notlike "wetransfer*" }

# Fichiers MP4 à plat (sauts déjà concaténés ou non-GoPro)
$flatVideos = @(Get-ChildItem -Path $SourcesDir -File `
    -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Extension -ieq ".mp4" -or $_.Extension -ieq ".mov") -and
        $_.Name -notlike "concat_*"
    })

if ($subDirs.Count -eq 0 -and $flatVideos.Count -eq 0) {
    Write-Warn "Aucune video trouvee dans $SourcesDir"
    Write-Host "       Mets tes videos dans ce dossier puis relance."
    Write-Host ""
    Write-Host "       Pour 1 saut = 1 fichier deja merge :"
    Write-Host "         sources/saut_paul.mp4"
    Write-Host ""
    Write-Host "       Pour 1 saut = plusieurs chapitres GoPro :"
    Write-Host "         sources/PAUL/GH015424.MP4"
    Write-Host "         sources/PAUL/GH015425.MP4"
    exit 0
}

Write-Info "Sous-dossiers (= 1 saut a concatener) : $($subDirs.Count)"
foreach ($d in $subDirs) {
    $mp4Count = (Get-ChildItem -Path $d.FullName -File |
        Where-Object { $_.Extension -ieq ".mp4" -or $_.Extension -ieq ".mov" }
        ).Count
    Write-Host "       - $($d.Name)/  ($mp4Count fichiers)"
}

Write-Info "Fichiers MP4 a plat (= 1 saut deja merge) : $($flatVideos.Count)"
foreach ($v in $flatVideos) {
    $sizeMB = [math]::Round($v.Length / 1MB, 1)
    Write-Host "       - $($v.Name)  ($sizeMB MB)"
}

# ─── 3. PRÉPARATION DES JOBS ──────────────────────────────────────────────
Write-Section "3/5  Preparation des jobs"

$jobs = @()

# Jobs venant de sous-dossiers : concatener + traiter
foreach ($d in $subDirs) {
    $chapters = @(Get-ChildItem -Path $d.FullName -File |
        Where-Object { $_.Extension -ieq ".mp4" -or $_.Extension -ieq ".mov" } |
        Sort-Object Name)
    if ($chapters.Count -eq 0) {
        Write-Warn "Sous-dossier $($d.Name) vide, ignore"
        continue
    }
    $jobs += [PSCustomObject]@{
        Type = "concat"
        Name = $d.Name
        Source = $d.FullName
        Chapters = $chapters
        OutputStem = "saut_$($d.Name.ToLower())"
    }
}

# Jobs venant de fichiers à plat : traiter directement
foreach ($v in $flatVideos) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($v.Name)
    $jobs += [PSCustomObject]@{
        Type = "direct"
        Name = $stem
        Source = $v.FullName
        Chapters = @($v)
        OutputStem = $stem
    }
}

if ($jobs.Count -eq 0) {
    Write-Warn "Aucun job a traiter."
    exit 0
}

Write-Info "Total : $($jobs.Count) jobs a traiter"

# ─── 4. TRAITEMENT ────────────────────────────────────────────────────────
Write-Section "4/5  Traitement"

# Helper : check si un montage existe déjà
function Test-AlreadyProcessed {
    param([string]$SourceStem)
    $pattern = "*${SourceStem}_montage.mp4"
    $existing = @(Get-ChildItem -Path $OutputDir -Filter $pattern -File `
        -ErrorAction SilentlyContinue)
    return $existing.Count -gt 0
}

# Helper : concat chapitres avec préservation GPMF
function Invoke-Concat {
    param([array]$ChapterFiles, [string]$OutputPath)
    $listFile = [System.IO.Path]::GetTempFileName() + ".txt"
    $lines = @()
    foreach ($c in $ChapterFiles) {
        $abs = $c.FullName.Replace("'", "'\''").Replace("\", "/")
        $lines += "file '$abs'"
    }
    # IMPORTANT : ecrire en UTF-8 SANS BOM (ffmpeg ne sait pas lire le BOM
    # et plante avec "unknown keyword '﻿ile'"). PS 5.1 Set-Content
    # -Encoding UTF8 ajoute un BOM, donc on passe par .NET directement.
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($listFile, $lines, $utf8NoBom)
    try {
        # Tentative 1 : avec mapping GPMF (stream 3 chez GoPro)
        & ffmpeg -y -v error -f concat -safe 0 -i $listFile `
            -map 0:v -map "0:a?" -map "0:3?" -c copy -copy_unknown `
            -movflags +faststart $OutputPath 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $OutputPath)) {
            # Fallback : sans mapping GPMF (vidéo non-GoPro)
            & ffmpeg -y -v error -f concat -safe 0 -i $listFile `
                -map 0:v -map "0:a?" -c copy `
                -movflags +faststart $OutputPath 2>&1 | Out-Null
        }
    } finally {
        Remove-Item $listFile -ErrorAction SilentlyContinue
    }
    return (Test-Path $OutputPath)
}

# Helper : pipeline Python
function Invoke-Pipeline {
    param(
        [string]$VideoRelPath, [string]$JobId, [string]$Passager,
        [bool]$UseVision, [string]$Date
    )
    $useVisionStr = if ($UseVision) { "True" } else { "False" }
    $musicLine = if (Test-Path $MusicPath) {
        "music_path=Path('assets/music/ref_audio.m4a'),"
    } else { "" }

    $script = @"
import sys
sys.path.insert(0, '.')
from pathlib import Path
from agent.pipeline import process_jump
r = process_jump(
    video_path=r'$VideoRelPath',
    nom_passager=r'$Passager',
    date_saut='$Date',
    job_id=r'$JobId',
    use_vision=$useVisionStr,
    keyframe_interval=15,
    max_duration_s=$MaxDuration,
    $musicLine
    dropzone_nom=r'$Dropzone',
    dropzone_site=r'$Site',
)
print('STATUT:', r.statut)
print('SIZE_MB:', r.taille_montage_mb)
print('FILE:', r.fichier_montage)
import sys as _s
_s.exit(0 if r.statut == 'succes' else 1)
"@

    Push-Location $ProjectDir
    try {
        # Out-Host : affiche le stdout Python directement au terminal,
        # sans le faire remonter dans la valeur de retour PowerShell
        # (sinon $exitCode = "STATUT: succes\n0" au lieu de juste 0)
        & $VenvPython -c $script | Out-Host
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = -1 }
        return [int]$code
    } finally {
        Pop-Location
    }
}

$results = @()
$jobIndex = 0

foreach ($job in $jobs) {
    $jobIndex++
    Write-Host ""
    Write-Host "── Job $jobIndex/$($jobs.Count) : $($job.Name) ──" -ForegroundColor Magenta

    # Skip si déjà traité ?
    if ((-not $Force) -and (Test-AlreadyProcessed $job.OutputStem)) {
        Write-Info "Deja traite (montage existe). Skip. (-Force pour refaire)"
        $results += [PSCustomObject]@{
            Saut = $job.Name; Status = "SKIP"; Detail = "deja traite"
        }
        continue
    }

    if ($DryRun) {
        if ($job.Type -eq "concat") {
            Write-Info "[DryRun] Concat $($job.Chapters.Count) chapitres -> $($job.OutputStem).mp4 puis pipeline"
        } else {
            Write-Info "[DryRun] Pipeline direct sur $($job.Name)"
        }
        $results += [PSCustomObject]@{
            Saut = $job.Name; Status = "DRYRUN"; Detail = "$($job.Chapters.Count) fichiers"
        }
        continue
    }

    # Concat si nécessaire
    $videoToProcess = $job.Source
    if ($job.Type -eq "concat") {
        $mergedPath = Join-Path $SourcesDir "$($job.OutputStem).mp4"
        if (-not (Test-Path $mergedPath)) {
            Write-Info "Concatenation de $($job.Chapters.Count) chapitres..."
            $concatStart = Get-Date
            $ok = Invoke-Concat $job.Chapters $mergedPath
            $concatDur = ((Get-Date) - $concatStart).TotalSeconds
            if (-not $ok) {
                Write-Err "Concat echouee"
                $results += [PSCustomObject]@{
                    Saut = $job.Name; Status = "ERR"; Detail = "concat echec"
                }
                continue
            }
            $sizeMB = [math]::Round((Get-Item $mergedPath).Length / 1MB, 0)
            Write-Ok "Concatene en $([math]::Round($concatDur,1))s ($sizeMB MB)"
        } else {
            Write-Info "Fichier concat deja present, on reprend"
        }
        $videoToProcess = $mergedPath
    }

    # Lancement pipeline
    $videoRel = "sources/" + (Split-Path $videoToProcess -Leaf)
    $jobId = "batch-{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), $job.Name
    $passager = $job.Name
    $date = (Get-Date -Format "yyyy-MM-dd")
    $useVision = -not $NoVision
    $modeStr = if ($useVision) { "vision Gemini" } else { "sans vision (rapide)" }
    Write-Info "Pipeline ($modeStr)..."
    $pipelineStart = Get-Date
    $exitCode = Invoke-Pipeline $videoRel $jobId $passager $useVision $date
    $pipelineDur = ((Get-Date) - $pipelineStart).TotalSeconds

    if ($exitCode -eq 0) {
        Write-Ok "Pipeline OK en $([math]::Round($pipelineDur,1))s"
        $results += [PSCustomObject]@{
            Saut = $job.Name; Status = "OK"
            Detail = "$([math]::Round($pipelineDur,0))s"
        }
    } else {
        Write-Err "Pipeline echec (exit $exitCode)"
        $results += [PSCustomObject]@{
            Saut = $job.Name; Status = "ERR"
            Detail = "pipeline exit $exitCode"
        }
    }
}

# ─── 5. RÉCAP ─────────────────────────────────────────────────────────────
Write-Section "5/5  Recap"

Write-Host ""
$results | Format-Table -AutoSize
Write-Host ""

$okCount = @($results | Where-Object { $_.Status -eq "OK" }).Count
$skipCount = @($results | Where-Object { $_.Status -eq "SKIP" }).Count
$errCount = @($results | Where-Object { $_.Status -eq "ERR" }).Count
$dryCount = @($results | Where-Object { $_.Status -eq "DRYRUN" }).Count

Write-Host "Total : $($results.Count) jobs" -ForegroundColor White
if ($okCount -gt 0)   { Write-Host "  Succes : $okCount" -ForegroundColor Green }
if ($skipCount -gt 0) { Write-Host "  Skip   : $skipCount" -ForegroundColor Gray }
if ($errCount -gt 0)  { Write-Host "  Echec  : $errCount" -ForegroundColor Red }
if ($dryCount -gt 0)  { Write-Host "  DryRun : $dryCount" -ForegroundColor Cyan }

if ($okCount -gt 0 -and -not $DryRun) {
    Write-Host ""
    Write-Host "Montages dans : $OutputDir" -ForegroundColor Cyan
}

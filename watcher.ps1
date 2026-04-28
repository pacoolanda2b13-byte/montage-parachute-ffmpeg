# ============================================================================
#  SkyDive Pro — Watcher automatique
# ============================================================================
#  Surveille en permanence skydive_pro/sources/ et lance automatiquement
#  process_all.ps1 dès qu'un nouveau saut est détecté et stable
#  (= copie terminée).
#
#  Usage :
#    .\watcher.ps1                  # Démarre le watcher (Ctrl+C pour arrêter)
#    .\watcher.ps1 -Interval 60     # Vérifie toutes les 60s (défaut: 30s)
#    .\watcher.ps1 -NoVision        # Mode rapide
#    .\watcher.ps1 -OpenWhenDone    # Ouvre le montage quand prêt
#
#  Comment ça marche :
#    1. Le watcher tourne en boucle (polling toutes les 30s par défaut)
#    2. À chaque tick, il liste sources/ et output/
#    3. Pour chaque saut potentiel (sous-dossier avec MP4 OU fichier MP4) :
#       - Vérifie que la taille n'a pas changé depuis 60s = copie finie
#       - Vérifie qu'il n'a pas déjà été traité (montage absent)
#       - Si OUI les 2 -> lance le pipeline, attend la fin
#    4. Notification + ouverture auto du montage (option)
#    5. Reprend la surveillance
#
#  Pour ARRÊTER : Ctrl+C dans la fenêtre PowerShell
# ============================================================================

[CmdletBinding()]
param(
    [int]$Interval = 30,           # Polling interval en secondes
    [int]$StableDelay = 60,        # Délai pour considérer un fichier "stable"
    [string]$Dropzone = "SkyDive Pro",
    [string]$Site = "skydive-pro.fr",
    [int]$MaxDuration = 320,
    [switch]$NoVision,
    [switch]$OpenWhenDone,
    [switch]$Force
)

$ErrorActionPreference = "Continue"  # ne PAS s'arrêter sur la moindre erreur
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Join-Path $RootDir "skydive_pro"
$SourcesDir = Join-Path $ProjectDir "sources"
$OutputDir = Join-Path $ProjectDir "output"
$ProcessAllScript = Join-Path $RootDir "process_all.ps1"

# Hash table : nom -> { lastSize, lastSeen, processed }
# On garde un historique pour détecter quand un fichier devient stable
$state = @{}

function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host ("█" * 78) -ForegroundColor Cyan
    Write-Host "  🪂 SkyDive Pro — Watcher automatique" -ForegroundColor Cyan
    Write-Host ("█" * 78) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Dossier surveillé : $SourcesDir" -ForegroundColor Gray
    Write-Host "  Polling          : toutes les $Interval s" -ForegroundColor Gray
    Write-Host "  Délai stable     : $StableDelay s" -ForegroundColor Gray
    $modeStr = if ($NoVision) { "Rapide (sans vision Gemini)" } else { "Qualité (avec vision Gemini)" }
    Write-Host "  Mode             : $modeStr" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  💡 Comment l'utiliser :" -ForegroundColor Yellow
    Write-Host "     Copie tes vidéos GoPro dans un sous-dossier de sources/" -ForegroundColor Yellow
    Write-Host "     Ex: sources/SOPHIE/GH015XXX.MP4" -ForegroundColor Yellow
    Write-Host "     Le watcher détecte, attend la fin de la copie, et traite." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ⏹️  ARRÊTER : Ctrl+C" -ForegroundColor Yellow
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkGray
}

function Get-FolderSize {
    param([string]$Path)
    $files = Get-ChildItem -Path $Path -File -Recurse -ErrorAction SilentlyContinue
    if (-not $files) { return 0 }
    return ($files | Measure-Object -Property Length -Sum).Sum
}

function Test-AlreadyProcessed {
    param([string]$Stem)
    $pattern = "*$Stem*_montage.mp4"
    $existing = @(Get-ChildItem -Path $OutputDir -Filter $pattern -File `
        -ErrorAction SilentlyContinue)
    return $existing.Count -gt 0
}

function Get-AllSauts {
    # Retourne la liste des "sauts" candidats : sous-dossiers + fichiers MP4
    $items = @()

    # Sous-dossiers avec au moins 1 MP4
    $subDirs = Get-ChildItem -Path $SourcesDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike ".*" -and $_.Name -notlike "wetransfer*" }
    foreach ($d in $subDirs) {
        $mp4Count = @(Get-ChildItem -Path $d.FullName -File `
            -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -ieq ".mp4" -or $_.Extension -ieq ".mov" }).Count
        if ($mp4Count -gt 0) {
            $size = Get-FolderSize $d.FullName
            $stem = "saut_$($d.Name.ToLower())"
            $items += [PSCustomObject]@{
                Type = "folder"
                Key = $d.Name
                Stem = $stem
                Size = $size
                MP4Count = $mp4Count
            }
        }
    }

    # Fichiers MP4 à plat
    $flatVideos = @(Get-ChildItem -Path $SourcesDir -File `
        -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Extension -ieq ".mp4" -or $_.Extension -ieq ".mov") -and
            $_.Name -notlike "concat_*" -and $_.Name -notlike "saut_client_*"
        })
    foreach ($v in $flatVideos) {
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($v.Name)
        $items += [PSCustomObject]@{
            Type = "file"
            Key = $v.Name
            Stem = $stem
            Size = $v.Length
            MP4Count = 1
        }
    }
    return $items
}

function Show-Status {
    param([array]$Sauts)
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host ""
    Write-Host "[$now] État actuel :" -ForegroundColor Cyan
    if ($Sauts.Count -eq 0) {
        Write-Host "       (sources/ vide — en attente)" -ForegroundColor DarkGray
        return
    }
    foreach ($s in $Sauts) {
        $sizeMB = [math]::Round($s.Size / 1MB, 0)
        $stKey = "{0}__{1}" -f $s.Type, $s.Key
        $entry = $state[$stKey]

        if (Test-AlreadyProcessed $s.Stem) {
            $statusEmoji = "✅"
            $statusText = "déjà traité"
            $color = "DarkGray"
        } elseif ($null -eq $entry) {
            $statusEmoji = "🆕"
            $statusText = "nouveau (analyse en cours)"
            $color = "Yellow"
        } elseif ($entry.LastSize -ne $s.Size) {
            $statusEmoji = "📥"
            $statusText = "copie en cours ($sizeMB MB)"
            $color = "Yellow"
        } else {
            $elapsed = ((Get-Date) - $entry.LastChange).TotalSeconds
            if ($elapsed -lt $StableDelay) {
                $remaining = [math]::Round($StableDelay - $elapsed, 0)
                $statusEmoji = "⏳"
                $statusText = "stabilisation ($remaining s restantes)"
                $color = "Yellow"
            } else {
                $statusEmoji = "🚀"
                $statusText = "PRÊT À TRAITER"
                $color = "Green"
            }
        }
        $typeIcon = if ($s.Type -eq "folder") { "📁" } else { "📄" }
        Write-Host ("       {0} {1} {2} ({3} MB) — {4}" -f `
            $statusEmoji, $typeIcon, $s.Key, $sizeMB, $statusText) -ForegroundColor $color
    }
}

function Update-State {
    param([array]$Sauts)
    foreach ($s in $Sauts) {
        $stKey = "{0}__{1}" -f $s.Type, $s.Key
        $entry = $state[$stKey]

        if ($null -eq $entry) {
            # Première détection
            $state[$stKey] = @{
                LastSize = $s.Size
                LastChange = Get-Date
                Processed = $false
            }
        } elseif ($entry.LastSize -ne $s.Size) {
            # Taille a changé : copie en cours, on reset le timer
            $entry.LastSize = $s.Size
            $entry.LastChange = Get-Date
        }
    }
    # Nettoyer les entries qui n'existent plus dans sources/
    $currentKeys = $Sauts | ForEach-Object { "$($_.Type)__$($_.Key)" }
    $toRemove = @($state.Keys | Where-Object { $_ -notin $currentKeys })
    foreach ($k in $toRemove) { $state.Remove($k) }
}

function Test-IsStable {
    param($Saut)
    $stKey = "{0}__{1}" -f $Saut.Type, $Saut.Key
    $entry = $state[$stKey]
    if ($null -eq $entry) { return $false }
    if ($entry.LastSize -ne $Saut.Size) { return $false }
    $elapsed = ((Get-Date) - $entry.LastChange).TotalSeconds
    return $elapsed -ge $StableDelay
}

function Start-PipelineFor {
    param($Saut)
    Write-Host ""
    Write-Host ("─" * 78) -ForegroundColor Magenta
    Write-Host "🎬 LANCEMENT DU PIPELINE pour $($Saut.Key)" -ForegroundColor Magenta
    Write-Host ("─" * 78) -ForegroundColor Magenta

    $startTime = Get-Date
    # On délègue à process_all.ps1 (qui sait gérer concat + skip + validation)
    $args = @()
    if ($NoVision) { $args += "-NoVision" }
    if ($Force) { $args += "-Force" }
    $args += @("-Dropzone", $Dropzone, "-Site", $Site,
                "-MaxDuration", $MaxDuration)

    & $ProcessAllScript @args

    $duration = ((Get-Date) - $startTime).TotalSeconds
    Write-Host ""
    Write-Host "✅ Traitement terminé en $([math]::Round($duration, 0))s" -ForegroundColor Green

    # Toast notification Windows
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
        $balloon = New-Object System.Windows.Forms.NotifyIcon
        $balloon.Icon = [System.Drawing.SystemIcons]::Information
        $balloon.BalloonTipTitle = "SkyDive Pro"
        $balloon.BalloonTipText = "Montage prêt : $($Saut.Key)"
        $balloon.Visible = $true
        $balloon.ShowBalloonTip(5000)
        Start-Sleep -Seconds 1
        $balloon.Dispose()
    } catch { }

    # Optionnel : ouvrir le montage
    if ($OpenWhenDone) {
        $pattern = "*$($Saut.Stem)*_montage.mp4"
        $latest = Get-ChildItem -Path $OutputDir -Filter $pattern -File `
            -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($latest) {
            Write-Host "📺 Ouverture du montage..." -ForegroundColor Cyan
            Start-Process $latest.FullName
        }
    }
}

# ─── BOUCLE PRINCIPALE ─────────────────────────────────────────────────────

# Pré-flight : vérifie process_all.ps1 existe
if (-not (Test-Path $ProcessAllScript)) {
    Write-Host "[ERR] $ProcessAllScript introuvable. Annulation." -ForegroundColor Red
    exit 1
}

Write-Header

$tickCount = 0
try {
    while ($true) {
        $tickCount++
        $sauts = @(Get-AllSauts)
        Update-State $sauts

        # Affiche l'état toutes les 5 ticks (sinon trop verbeux) ou au 1er tick
        if ($tickCount -eq 1 -or $tickCount % 5 -eq 0) {
            Show-Status $sauts
            $nextTick = (Get-Date).AddSeconds($Interval).ToString("HH:mm:ss")
            Write-Host "[INFO] Prochain check : $nextTick (Ctrl+C pour arrêter)" `
                -ForegroundColor DarkGray
        }

        # Détecte les sauts prêts à traiter
        $readyToProcess = @($sauts | Where-Object {
            (Test-IsStable $_) -and
            ((-not (Test-AlreadyProcessed $_.Stem)) -or $Force)
        })

        foreach ($saut in $readyToProcess) {
            Start-PipelineFor $saut
            # Marque le saut comme traité (évite re-traiter au prochain tick)
            $stKey = "{0}__{1}" -f $saut.Type, $saut.Key
            if ($state.ContainsKey($stKey)) {
                $state[$stKey].Processed = $true
            }
        }

        Start-Sleep -Seconds $Interval
    }
} finally {
    Write-Host ""
    Write-Host "🛑 Watcher arrêté." -ForegroundColor Yellow
    Write-Host ""
}

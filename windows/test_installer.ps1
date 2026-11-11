# Test de bout en bout sur Windows : installe en silence, lance l'app, la teste, la désinstalle.
# Usage : ./windows/test_installer.ps1 -Fixtures <dossier de fichiers de test>
param([Parameter(Mandatory)][string]$Fixtures)
$ErrorActionPreference = "Stop"
$setup = (Get-ChildItem dist\Anonymiseur-*-x64-setup.exe | Select-Object -First 1).FullName
$work = Join-Path $env:RUNNER_TEMP "e2e"; New-Item -ItemType Directory -Force "$work\sortie" | Out-Null
$dir = Join-Path $env:RUNNER_TEMP "Dossier d'essai Anonymiseur"      # volontairement avec des espaces et une apostrophe
$env:PYTHONUTF8 = "1"

function Check($ok, $msg) { if ($ok) { Write-Host "  ok  $msg" } else { Write-Host "  ECHEC $msg"; $script:failed = $true } }
$failed = $false

Write-Host "== Installation silencieuse dans '$dir'"
$p = Start-Process $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=sendto", "/DIR=`"$dir`"" -Wait -PassThru
Check ($p.ExitCode -eq 0) "l'installateur se termine sans erreur (code $($p.ExitCode))"
foreach ($f in "python\pythonw.exe", "python\python.exe", "launcher.pyw", "app\server.py", "bin\ffmpeg.exe", "bin\ffprobe.exe", "bin\exiftool.exe", "App.ico", "licenses\LICENSE", "unins000.exe") {
    Check (Test-Path (Join-Path $dir $f)) "installé : $f"
}
Check (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Anonymiseur.lnk") "raccourci du menu Démarrer"
Check (Test-Path "$env:APPDATA\Microsoft\Windows\SendTo\Anonymiseur.lnk") "raccourci « Envoyer vers »"

Write-Host "== Lancement (comme le raccourci)"
$env:ANONYMISEUR_TEST_DIALOG = (ConvertTo-Json @("$work\sortie") -Compress)
$env:ANONYMISEUR_ASSUME_YES = "1"
$env:ANONYMISEUR_E2E_OUT = "$work\sortie"
$app = Start-Process "$dir\python\pythonw.exe" -ArgumentList "`"$dir\launcher.pyw`"" -WorkingDirectory $dir -PassThru
$up = $false
for ($i = 0; $i -lt 90; $i++) { try { if ((Invoke-WebRequest http://127.0.0.1:48765/ping -UseBasicParsing -TimeoutSec 2).StatusCode -eq 204) { $up = $true; break } } catch {}; Start-Sleep 1 }
Check $up "le moteur répond sur 127.0.0.1:48765"
$edgeUp = $false
for ($i = 0; $i -lt 40; $i++) { if (Get-Process msedge -ErrorAction SilentlyContinue) { $edgeUp = $true; break }; Start-Sleep 1 }
Check $edgeUp "une fenêtre Edge est ouverte"
$logFile = Join-Path $env:LOCALAPPDATA "Anonymiseur\lanceur.log"
if (-not $edgeUp -and (Test-Path $logFile)) { Write-Host "--- lanceur.log :"; Get-Content $logFile | Select-Object -Last 15 }

if ($up) {
    Write-Host "== Batterie de tests complète, par HTTP, contre l'app installée"
    $env:PATH = "$dir\bin;$env:SystemRoot\System32;$env:SystemRoot"
    & "$dir\python\python.exe" tests\run_tests.py --http 48765 --dir $Fixtures
    Check ($LASTEXITCODE -eq 0) "batterie de tests (HTTP)"
    Write-Host "== Tests propres à Windows (jeton, Envoyer vers, corbeille, dates…)"
    & "$dir\python\python.exe" tests\e2e_windows.py $Fixtures $work
    Check ($LASTEXITCODE -eq 0) "tests de bout en bout Windows"

    Write-Host "== Capture d'écran de l'interface (Edge sans interface)"
    $shot = Join-Path (Get-Location) "dist\capture-windows.png"
    $edge = (Get-Command msedge.exe -ErrorAction SilentlyContinue).Source
    if (-not $edge) { $edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" }
    $prof = Join-Path $env:RUNNER_TEMP "edge-capture"
    $null = Start-Process $edge -ArgumentList "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--user-data-dir=`"$prof`"", "--window-size=1440,900", "--force-device-scale-factor=2", "--virtual-time-budget=4000", "--screenshot=`"$shot`"", "http://127.0.0.1:48765/" -PassThru -Wait -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not (Test-Path $shot); $i++) { Start-Sleep 1 }
    Check (Test-Path $shot) "capture d'écran produite"
}

Write-Host "== Arrêt puis désinstallation"
Get-Process pythonw, msedge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3
$u = Start-Process "$dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep 2
Check (-not (Test-Path "$dir\launcher.pyw")) "désinstallé : les fichiers ont disparu"
Check (-not (Test-Path "$env:APPDATA\Microsoft\Windows\SendTo\Anonymiseur.lnk")) "désinstallé : raccourci « Envoyer vers » retiré"
if ($failed) { throw "Des vérifications ont échoué" }
Write-Host "TOUT EST OK"

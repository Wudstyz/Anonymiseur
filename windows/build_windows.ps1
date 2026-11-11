# Construit l'installateur Windows d'Anonymiseur (Windows 10/11 64 bits) : dist\Anonymiseur-<version>-x64-setup.exe
# Les composants sont téléchargés puis vérifiés par SHA-256. Prérequis : Windows, PowerShell 7, MSYS2 (C:\msys64),
# Inno Setup 6. Sur GitHub Actions tout est déjà installé (voir .github/workflows/windows.yml).
param([string]$Version = "1.1", [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$deps = Join-Path $root ".deps-win"; $dl = Join-Path $deps "dl"
New-Item -ItemType Directory -Force $dl | Out-Null

function Get-Verified([string]$Url, [string]$Name, [string]$Sha) {
    $dest = Join-Path $dl $Name
    if ((Test-Path $dest) -and ((Get-FileHash $dest -Algorithm SHA256).Hash -eq $Sha.ToUpper())) { Write-Host "OK  $Name (déjà présent, empreinte vérifiée)"; return $dest }
    Write-Host "DL  $Name"
    & curl.exe -fL --retry 3 --silent --show-error -o $dest $Url
    if ($LASTEXITCODE -ne 0) { throw "Téléchargement impossible : $Url" }
    $got = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($got -ne $Sha.ToUpper()) { Remove-Item $dest -Force; throw "Empreinte SHA-256 incorrecte pour $Name (attendue $Sha, obtenue $got)" }
    Write-Host "OK  $Name : SHA-256 vérifié"
    return $dest
}

# Composants épinglés : adresse + SHA-256 attendu.
$py     = Get-Verified "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz" "cpython-3.13.18-windows-x64.tar.gz" "ebe90cc1dce2dd2d7afa1f0aa9b6c269c7c0174aeabdc6a801381602b7283424"
$pillow = Get-Verified "https://files.pythonhosted.org/packages/d7/ed/1b16fb66a37e1b9e41370b93b2c614c7da761a5b2a41dc333f7af4639962/pillow-13.0.0-cp313-cp313-win_amd64.whl" "pillow-13.0.0-cp313-cp313-win_amd64.zip" "9dda0788a9932776a75d8bcc020076edc308ce2508b51f6739a45e3158b3fc42"
$pypdf  = Get-Verified "https://files.pythonhosted.org/packages/d5/a9/ae11deef21eaac5113f8c3848da1c42423b7abeca0abc349bfec7abf4c4e/pypdf-7.0.1-py3-none-any.whl" "pypdf-7.0.1-py3-none-any.zip" "6131b764b046282357037309e7ef2a1b7679d4a5c53eed3db2bfbf7c673ddc2b"
$pdfium = Get-Verified "https://files.pythonhosted.org/packages/fe/7f/8aa446529fa14523e5c18f89e823afc95526689f76a75efe68a82a10d850/pypdfium2-5.15.2-py3-none-win_amd64.whl" "pypdfium2-5.15.2-py3-none-win_amd64.zip" "74d1bace34fb01c660d0b64344d5a4b7d276942b7c6623c88ab59ea21c5acfbd"
$heif   = Get-Verified "https://files.pythonhosted.org/packages/37/b5/42eda6f5a7894276592c2b499caad152b057f62b4e1dabab26d808cd0c71/pillow_heif-1.8.1-cp313-cp313-win_amd64.whl" "pillow_heif-1.8.1-cp313-cp313-win_amd64.zip" "f2110c6f9ec02efecf52a979addaf5734770e55ca29705ce0c3f0e588db5e6b5"
$exif   = Get-Verified "https://downloads.sourceforge.net/project/exiftool/exiftool-13.63_64.zip" "exiftool-13.63_64.zip" "7a4bff4b1d6ee15adef882837847f76c0ed23228d294feed285939b6c9b293bd"
$null   = Get-Verified "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz" "ffmpeg-9.0.2.tar.xz" "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"

# FFmpeg minimal, compilé depuis la source vérifiée (shell MSYS2).
if (-not (Test-Path "$deps\ffmpeg\bin\ffmpeg.exe")) {
    $msys = if ($env:MSYS2_ROOT) { $env:MSYS2_ROOT } else { "C:\msys64" }
    $env:MSYSTEM = "MINGW64"; $env:CHERE_INVOKING = "1"
    $unix = (& "$msys\usr\bin\cygpath.exe" -u $root).Trim()
    & "$msys\usr\bin\bash.exe" -lc "cd '$unix' && ./windows/build_ffmpeg.sh"
    if ($LASTEXITCODE -ne 0) { throw "Compilation de FFmpeg impossible" }
}

# Assemblage de dist\Anonymiseur
$out = Join-Path $root "dist\Anonymiseur"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null
& tar.exe -xzf $py -C $out            # crée $out\python
$site = Join-Path $out "python\Lib\site-packages"
foreach ($w in @($pillow, $pypdf, $pdfium, $heif)) { Expand-Archive -Path $w -DestinationPath $site -Force }
foreach ($d in "test", "idlelib", "turtledemo", "ensurepip", "lib2to3") { Remove-Item -Recurse -Force (Join-Path $out "python\Lib\$d") -ErrorAction SilentlyContinue }
Get-ChildItem $site -Directory -Filter "pip*" | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force (Join-Path $out "python\Scripts"), (Join-Path $out "python\include") -ErrorAction SilentlyContinue

# Outils : FFmpeg, ExifTool (exécutable officiel + son dossier exiftool_files)
$bin = Join-Path $out "bin"; New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item "$deps\ffmpeg\bin\ffmpeg.exe", "$deps\ffmpeg\bin\ffprobe.exe" $bin
$tmp = Join-Path $deps "exiftool"; if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $exif -DestinationPath $tmp -Force
$exe = Get-ChildItem $tmp -Recurse -Filter "exiftool*.exe" | Select-Object -First 1
$filesDir = Get-ChildItem $tmp -Recurse -Directory -Filter "exiftool_files" | Select-Object -First 1
if (-not $exe -or -not $filesDir) { throw "ExifTool : structure inattendue de l'archive" }
Copy-Item $exe.FullName (Join-Path $bin "exiftool.exe")
Copy-Item $filesDir.FullName (Join-Path $bin "exiftool_files") -Recurse

# Code de l'app, lanceur, icône, licences
$app = Join-Path $out "app"; New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item src\cleaners.py, src\server.py, src\index.html $app
Copy-Item windows\launcher.pyw, assets\App.ico $out
New-Item -ItemType Directory -Force (Join-Path $out "licenses") | Out-Null
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md (Join-Path $out "licenses")
& "$out\python\python.exe" -m compileall -q -j0 -s $out -p "C:\Program Files\Anonymiseur" "$out\python\Lib" $app
Write-Host "OK  dist\Anonymiseur assemblé ($([math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)) Mo)"

if ($SkipInstaller) { return }
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 introuvable (choco install innosetup)" }
& $iscc "/DAppVersion=$Version" "/DSourceDir=$out" windows\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a échoué" }
$setup = "dist\Anonymiseur-$Version-x64-setup.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  Anonymiseur-$Version-x64-setup.exe" | Set-Content -Encoding ascii "$setup.sha256"
Write-Host "OK  $setup ($([math]::Round((Get-Item $setup).Length / 1MB)) Mo)  SHA-256 $hash"

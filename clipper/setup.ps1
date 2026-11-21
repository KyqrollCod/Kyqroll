# clipper setup for Windows. Run from the clipper folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what に失敗しました (exit $LASTEXITCODE)" } }
function RealPython {
    # The Microsoft Store alias 'python' exists but is a stub that opens the Store.
    if (-not (Have "python")) { return $false }
    $v = & python --version 2>&1
    return ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3\.(1[0-9])")
}

if (-not (Have "winget")) { throw "winget がありません。Microsoft Store の 'アプリ インストーラー' を入れてください。" }
if (-not (Have "ffmpeg")) { winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements; Check "ffmpeg のインストール" }
if (-not (RealPython)) { winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements; Check "Python のインストール" }
# yt-dlp needs a JavaScript runtime for YouTube downloads.
if (-not (Have "deno")) { winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements; Check "Deno のインストール" }

# Refresh PATH for this session so the new tools are visible.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
# Japanese output on any console code page.
[System.Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
$env:PYTHONUTF8 = "1"

python -m pip install --upgrade pip; Check "pip の更新"
python -m pip install -r requirements.txt; Check "依存パッケージのインストール"

# NVIDIA GPU: CUDA libraries for faster-whisper (cuBLAS 12 + cuDNN 9).
if (Have "nvidia-smi") {
    python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"; Check "CUDA ライブラリのインストール"
    Write-Host "GPU を検出しました。文字起こしは CUDA で動きます。"
} else {
    Write-Host "GPU が見つかりません。文字起こしは CPU で動きます（遅くなります）。"
}

# Speaker colors: sherpa-onnx + wespeaker model (skipped gracefully by clipper if missing).
python -m pip install sherpa-onnx; Check "sherpa-onnx のインストール"
$model = Join-Path $PSScriptRoot "models\wespeaker_en_voxceleb_resnet34.onnx"
if (-not (Test-Path $model)) {
    New-Item -ItemType Directory -Force (Split-Path $model) | Out-Null
    curl.exe -sSL -o $model "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx"
    Check "話者モデルのダウンロード"
}

python -c "import clipper.cli; print('clipper OK')"; Check "clipper の読み込み"
ffmpeg -hide_banner -version | Select-Object -First 1

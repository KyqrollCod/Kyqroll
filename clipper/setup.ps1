# clipper setup for Windows. Run from the clipper folder:  ./setup.ps1
$ErrorActionPreference = "Stop"

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

if (-not (Have "winget")) { throw "winget がありません。Microsoft Store の 'アプリ インストーラー' を入れてください。" }
if (-not (Have "ffmpeg")) { winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements }
if (-not (Have "python")) { winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements }
# yt-dlp needs a JavaScript runtime for YouTube downloads.
if (-not (Have "deno")) { winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements }

# Refresh PATH for this session so the new tools are visible.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# NVIDIA GPU: CUDA libraries for faster-whisper (cuBLAS 12 + cuDNN 9).
if (Have "nvidia-smi") {
    python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
    Write-Host "GPU を検出しました。文字起こしは CUDA で動きます。"
} else {
    Write-Host "GPU が見つかりません。文字起こしは CPU で動きます（遅くなります）。"
}

python -c "import clipper.cli; print('clipper OK')"
ffmpeg -hide_banner -version | Select-Object -First 1

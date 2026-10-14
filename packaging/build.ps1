# builds dist/split from a clean locked environment and smoke-tests the result
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$ffmpegVersion = '9.0.2'
$ffmpegSha256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
$ffmpegUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$ffmpegVersion/ffmpeg-$ffmpegVersion-essentials_build.zip"
$ffmpegDir = Join-Path $root 'build\ffmpeg'

# a separate environment keeps dev tools out of the bundle and the dev venv intact
$env:UV_PROJECT_ENVIRONMENT = Join-Path $root 'build\venv'
$uv = if (Get-Command uv -ErrorAction SilentlyContinue) { @('uv') } else { @('py', '-3.13', '-m', 'uv') }

function Invoke-Uv {
  param([string[]]$Arguments)
  $command = $uv + $Arguments
  & $command[0] @($command | Select-Object -Skip 1)
  if ($LASTEXITCODE -ne 0) { throw "uv $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path (Join-Path $ffmpegDir 'ffmpeg.exe'))) {
  New-Item -ItemType Directory -Force $ffmpegDir | Out-Null
  $archive = Join-Path $env:TEMP "ffmpeg-$ffmpegVersion.zip"
  Invoke-WebRequest -Uri $ffmpegUrl -OutFile $archive
  $actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()
  if ($actual -ne $ffmpegSha256) { throw "ffmpeg archive hash mismatch: $actual" }
  $unpacked = Join-Path $env:TEMP "ffmpeg-$ffmpegVersion"
  Remove-Item -Recurse -Force $unpacked -ErrorAction SilentlyContinue
  Expand-Archive -Path $archive -DestinationPath $unpacked
  $inner = Join-Path $unpacked "ffmpeg-$ffmpegVersion-essentials_build"
  Copy-Item (Join-Path $inner 'bin\ffmpeg.exe') $ffmpegDir
  Copy-Item (Join-Path $inner 'LICENSE') $ffmpegDir
  Remove-Item -Recurse -Force $unpacked, $archive
}

Invoke-Uv @('sync', '--locked', '--python', '3.13', '--extra', 'desktop', '--group', 'build', '--no-default-groups')
Remove-Item -Recurse -Force (Join-Path $root 'dist\split') -ErrorAction SilentlyContinue
Invoke-Uv @('run', '--no-sync', 'pyinstaller', 'packaging\split.spec', '--noconfirm', '--clean',
  '--distpath', 'dist', '--workpath', 'build\pyinstaller')

$exe = Join-Path $root 'dist\split\split.exe'
$reportFile = Join-Path $env:TEMP 'split-self-test.json'
Remove-Item $reportFile -ErrorAction SilentlyContinue
$test = Start-Process -FilePath $exe -ArgumentList @('--self-test', $reportFile) -Wait -PassThru
if ($test.ExitCode -ne 0 -or -not (Test-Path $reportFile)) { throw "self-test failed with exit code $($test.ExitCode)" }
Write-Host "self-test: $(Get-Content -Raw $reportFile)"

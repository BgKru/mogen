[CmdletBinding()]
param(
    # Directory that compose.prod.yaml mounts at /etc/nginx/certs.
    [string]$CertDir,
    [string]$HostName = 'localhost',
    [int]$Days = 365
)

$ErrorActionPreference = 'Stop'

if (-not $CertDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $CertDir = Join-Path $scriptDir '..\certs'
}

# Same pinned Debian slim base as the backend image: it provides the OpenSSL
# CLI, so the host needs no certificates tooling.
$image = 'python:3.11-slim@sha256:65bd3d9f1d7fa268dd1909973ba7eb4bdf41f6dcf2cfbe76ba9528b170f3fd79'
$resolved = [System.IO.Path]::GetFullPath($CertDir)
New-Item -ItemType Directory -Force -Path $resolved | Out-Null

Write-Host "Generating a self-signed certificate for $HostName in $resolved"
docker run --rm -v "${resolved}:/certs" --entrypoint openssl $image `
    req -x509 -nodes -newkey rsa:2048 -sha256 -days $Days `
    -keyout /certs/tls.key -out /certs/tls.crt `
    -subj "/CN=$HostName" `
    -addext "subjectAltName=DNS:$HostName,IP:127.0.0.1"
if ($LASTEXITCODE -ne 0) {
    throw "openssl failed with exit code $LASTEXITCODE"
}

$cert = Join-Path $resolved 'tls.crt'
$key = Join-Path $resolved 'tls.key'
if (-not (Test-Path $cert) -or -not (Test-Path $key)) {
    throw "Expected tls.crt and tls.key in $resolved"
}

# Show the subject/SAN so the operator can confirm the certificate before use.
docker run --rm -v "${resolved}:/certs:ro" --entrypoint openssl $image `
    x509 -in /certs/tls.crt -noout -subject -dates -ext subjectAltName

Write-Host "Done. compose.prod.yaml mounts $resolved at /etc/nginx/certs."

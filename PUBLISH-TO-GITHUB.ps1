# Optional manual workaround if a connected app cannot write to the repository.
# Requires Git for Windows and GitHub sign-in via Git Credential Manager.
$ErrorActionPreference = 'Stop'
$remote = 'https://github.com/thongheo0806-byte/GenLogin-free.git'
$source = (Resolve-Path $PSScriptRoot).Path
Write-Host "This will publish this source tree to $remote" -ForegroundColor Cyan
$confirm = Read-Host 'Type PUBLISH to continue (no force push)'
if ($confirm -cne 'PUBLISH') { Write-Host 'Cancelled.'; exit 0 }
$target = Join-Path $env:TEMP ('AutumnGenLogin-Publish-' + [guid]::NewGuid().ToString('N'))
try {
    & git clone $remote $target
    if ($LASTEXITCODE -ne 0) { throw 'Git clone failed' }
    $items = Get-ChildItem -LiteralPath $source -Force | Where-Object {
        $_.Name -notin @('.git', '.venv', 'build', 'dist', '__pycache__') -and $_.Extension -ne '.zip'
    }
    foreach ($item in $items) {
        Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
    }
    & git -C $target add --all
    if ($LASTEXITCODE -ne 0) { throw 'Git add failed' }
    & git -C $target commit -m 'feat: initial AutumnGenLogin local desktop profile manager'
    if ($LASTEXITCODE -ne 0) { throw 'Git commit failed (or no changes to commit)' }
    & git -C $target push origin HEAD:main
    if ($LASTEXITCODE -ne 0) { throw 'Git push failed; check repository access and branch protection' }
    Write-Host 'Published. Check the GitHub Actions build results.' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}

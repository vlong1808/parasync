$RepoDir = "$HOME\repos\parasync"

# Clone or pull
if (Test-Path $RepoDir) {
    Set-Location $RepoDir
    git pull
} else {
    New-Item -ItemType Directory -Path "$HOME\repos" -Force | Out-Null
    git clone https://github.com/jguida941/parasync.git $RepoDir
    Set-Location $RepoDir
}

# Create venv if missing
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

# Always reinstall (catches updates)
.\.venv\Scripts\pip install -e . --quiet

Write-Host ""
Write-Host "Installed! Run with:"
Write-Host "  cd $RepoDir"
Write-Host "  .\.venv\Scripts\parasync-gui"

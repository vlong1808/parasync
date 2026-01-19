$RepoDir = "$HOME\repos\parasync"

# Clone or pull
if (Test-Path $RepoDir) {
    Write-Host "Updating existing repo..."
    Set-Location $RepoDir
    git pull
} else {
    Write-Host "Cloning repo..."
    New-Item -ItemType Directory -Path "$HOME\repos" -Force | Out-Null
    git clone https://github.com/jguida941/parasync.git $RepoDir
    Set-Location $RepoDir
}

# Create venv if missing
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

# Install package
Write-Host "Installing parasync..."
.\.venv\Scripts\pip install -e .

Write-Host "`nDone! Run the GUI with:"
Write-Host "  .\.venv\Scripts\parasync-gui"

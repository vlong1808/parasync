# ParaSync

Dead simple file sync between Windows and macOS over SSH. Built for Parallels.

## The Experience

1. **Launch the app**
2. **App auto-finds your Mac** (scans the Parallels network)
3. **Click "Setup Passwordless"** (one-time, enter Mac password once)
4. **Drag a folder** into the drop zone
5. **Click PUSH**

That's it. Your files are on the Mac.

---

## One-Time Setup

### On Mac: Enable Remote Login

**System Settings → General → Sharing → Remote Login → ON**

That's the only manual step. Everything else is automatic.

### On Windows: Install & Run

```powershell
cd C:\path\to\parasync
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\.venv\Scripts\parasync-gui
```

---

## What the App Does Automatically

| Task | How It's Automated |
|------|-------------------|
| Find Mac IP | Scans 10.211.55.x for SSH (port 22) |
| Create SSH key | Generates ed25519 key with no passphrase |
| Install key on Mac | Appends to ~/.ssh/authorized_keys |
| Create remote folder | `mkdir -p` before every push |
| Copy files | scp with recursive flag |

---

## GUI Features

- **Auto-detect Mac** - No typing IP addresses
- **Drag-and-drop** - Drop your build folder, click Push
- **One-click passwordless setup** - Never type password again
- **Watch mode** - Auto-push when files change (2-second debounce)
- **Remembers settings** - Saved to ~/.parasync/config.json

---

## CLI (Optional)

The GUI handles everything, but if you prefer command line:

```bash
# Test connection
parasync test --name default

# Push
parasync push --name default

# Pull
parasync pull --name default
```

---

## Visual Studio Post-Build (Optional)

Add to your project's post-build event to auto-push after every build:

```
"C:\path\to\.venv\Scripts\parasync.exe" push --name default
```

---

## Troubleshooting

### "No Mac found on network"
- Enable Remote Login on Mac (System Settings → Sharing)
- Check you're on Parallels shared network

### "Permission denied"
- Click "Setup Passwordless" to install SSH key
- Enter your Mac password when prompted

### SSH key already exists but not working
- Delete `~/.ssh/id_ed25519_parasync` and `~/.ssh/id_ed25519_parasync.pub`
- Click "Setup Passwordless" again

---

## How It Works

```
Windows                          Mac
   │                              │
   │  1. Scan 10.211.55.x:22     │
   │ ─────────────────────────▶  │  (finds Mac)
   │                              │
   │  2. ssh-keygen (local)      │
   │                              │
   │  3. ssh: append key         │
   │ ─────────────────────────▶  │  (passwordless setup)
   │                              │
   │  4. ssh: mkdir -p           │
   │ ─────────────────────────▶  │  (ensure folder)
   │                              │
   │  5. scp -r folder           │
   │ ─────────────────────────▶  │  (copy files)
   │                              │
```

---

## Files

- `~/.parasync/config.json` - Saved settings
- `~/.ssh/id_ed25519_parasync` - SSH private key
- `~/.ssh/id_ed25519_parasync.pub` - SSH public key

---

## License

MIT

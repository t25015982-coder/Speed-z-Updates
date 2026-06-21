# SPEED-Z Launcher — Setup Guide

## Current Versions
- **2.x Branch**: Current = 2.10 → Next = 2.15
- **1.x Branch**: Current = 1.0.6 → Next = 1.0.7

## Hosting Options

### Option 1: GitHub Pages (Recommended — Free)
1. Create a GitHub repo named `speed-z-updates`
2. Go to Settings → Pages → Enable on `main` branch
3. Upload your files to the repo

### Option 2: Limewire (File Storage Only)
- Upload your ZIP to Limewire
- Use the Limewire link in the manifest
- **Note**: Limewire links may not support direct download/resume

### Option 3: Any Static Host
- Netlify, Vercel, Cloudflare Pages, S3, etc.

## File Structure on Host
```
speed-z-updates/
├── manifest.json          (for 2.x branch)
├── manifest_1x.json       (for 1.x branch)
├── SPEED-Z-v2.15.zip      (your app payload)
└── SPEED-Z-v1.0.7.zip     (legacy payload)
```

## Step-by-Step Setup

### Step 1: Prepare Your Payload
1. Build your SPEED-Z application
2. ZIP it: `SPEED-Z-v2.15.zip`
3. Get SHA-256:
   ```powershell
   Get-FileHash -Path "SPEED-Z-v2.15.zip" -Algorithm SHA256
   ```

### Step 2: Upload to GitHub Pages
1. Create repo `speed-z-updates`
2. Upload `manifest.json` and `SPEED-Z-v2.15.zip`
3. Your manifest URL: `https://yourname.github.io/speed-z-updates/manifest.json`
4. Your download URL: `https://yourname.github.io/speed-z-updates/SPEED-Z-v2.15.zip`

### Step 3: Update the Launcher
Edit `speed_z_models.py`:
```python
server_endpoint: str = "https://yourname.github.io/speed-z-updates"
```

### Step 4: Compile
```batch
pip install pyinstaller
pyinstaller --onefile --windowed --name "SPEED-Z-Launcher" speed_z_launcher.py
```

### Step 5: Distribute
Share `dist/SPEED-Z-Launcher.exe`

## How It Works
1. User runs launcher
2. Launcher detects installed version (2.10 or 1.0.6)
3. Fetches manifest from your host
4. Compares versions
5. If update needed: downloads, verifies, installs, bumps version
6. Shows "Updated to v2.15" or "Updated to v1.0.7"
7. User clicks LAUNCH

## Version Bump Logic
After successful update, the launcher:
1. Reads new version from manifest (e.g., "2.15")
2. Updates `installation.json` with new version
3. Updates UI badge to show new version
4. Next launch: detects v2.15, checks manifest again

## For Limewire Users
If you want to use Limewire for the actual file:
1. Host `manifest.json` on GitHub Pages (small file, easy)
2. Put `download_url` in manifest pointing to your Limewire link
3. **Warning**: Limewire may not support resume/byte-range requests

# LegalPerigee — Installer Packages

## macOS

**For end users:** `installers/macos/LegalPerigee-1.0.dmg`

1. Double-click the `.dmg`
2. Drag **LegalPerigee** → **Applications**
3. Double-click **LegalPerigee** in Applications to launch

**To build the DMG (developers):**
```bash
bash installers/build_all.sh
# OR just the macOS part:
bash installers/macos/build_dmg.sh
```

---

## Windows

### Option A — Simple setup (recommended for most users)

1. Copy the entire `LegalPerigee` project folder to the Windows machine
2. Right-click `installers/windows/setup.ps1` → **Run with PowerShell**
3. The script installs Python (if needed), creates the venv, and installs all dependencies
4. A desktop shortcut is created automatically

After setup, double-click **LegalPerigee** on the Desktop to launch.

### Option B — Professional .exe installer (for distribution)

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php) installed on Windows.

1. Copy the project to a Windows machine
2. Open `installers/windows/installer.iss` in Inno Setup
3. Click **Build → Compile**
4. Distribute `installers/windows/Output/LegalPerigee-Setup.exe`

End users run `LegalPerigee-Setup.exe` — no technical knowledge required.

---

## System Requirements

| | macOS | Windows |
|---|---|---|
| OS | macOS 12+ (Monterey) | Windows 10/11 (64-bit) |
| Python | Bundled via `.venv` | Python 3.9+ (auto-installed) |
| RAM | 4 GB minimum | 4 GB minimum |
| Disk | ~500 MB (venv + deps) | ~500 MB (venv + deps) |
| Internet | Required for API calls | Required for API calls |
| ffmpeg | Auto-installed via Homebrew | Optional (for video analysis) |

## First Launch

After installing on either platform:
1. The app opens in a native window
2. Enter your **Anthropic API key** in the sidebar (get one at console.anthropic.com)
3. Click **🔌 Test Connection** to verify — the key saves to your system keychain
4. Use the **Sync Manager** in the Case Library tab to populate the database

## Optional API Keys (add to `.env`)

| Key | Source | Enables |
|---|---|---|
| `COURTLISTENER_API_TOKEN` | courtlistener.com/help/api/ | Higher rate limits + real-time alerts |
| `CONGRESS_API_KEY` | api.congress.gov | Legislative bill tracking |
| `OPENSTATES_API_KEY` | openstates.org/accounts/login | All 50 state legislatures |
| `REGULATIONS_GOV_KEY` | api.regulations.gov | Full regulatory dockets |

The `.env` file is at: `LegalPerigee/.env`

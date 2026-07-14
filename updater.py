"""
Minecraft Bedrock Dedicated Server updater.

Keeps a single Bedrock server up to date while preserving the world and config.
Requires only the Python standard library (no pip installs).

    python updater.py
"""

import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
import datetime
from pathlib import Path

# ----------------------------------------------------------------------
# Configuration
WORLD = "Cuernavaca"

API_URL = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
DOWNLOAD_KEY = "serverBedrockWindows"

# Files/folders that belong to the user and must survive an update.
PRESERVE = ["worlds", "server.properties", "allowlist.json", "permissions.json"]

# server.properties settings the updater always ensures (on both fresh installs
# and updates). Other settings in the file are left untouched.
ENFORCED_PROPERTIES = {
    "emit-server-telemetry": "true",
    "content-log-console-output-enabled": "true",
}

# These are set at runtime once the user picks the server folder (see main()).
SERVER_DIR = None
BACKUP_DIR = None
VERSION_FILE = None


# ----------------------------------------------------------------------
def print_folder_guide():
    """Show a generic diagram of which folder to pick."""
    print()
    print("-" * 60)
    print("WHICH FOLDER DO I PICK?")
    print("-" * 60)
    print("Pick the SERVER folder -- the one that directly contains")
    print("'bedrock_server.exe'. For example:")
    print()
    print("    ...\\Minecraft\\<your world>\\server\\   <-- PICK THIS FOLDER")
    print("        |-- bedrock_server.exe            (this file lives inside it)")
    print("        |-- server.properties")
    print("        |-- allowlist.json / permissions.json")
    print("        `-- worlds\\")
    print("            `-- <your world>\\             (your save -- do NOT pick this)")
    print()
    print("  * Do NOT pick the 'worlds\\<your world>' folder (that's just the save).")
    print("  * Do NOT pick a parent folder that only contains the server folder.")
    print("  * For a brand-new install, pick an empty folder instead.")
    print("-" * 60)


def select_server_folder():
    """Ask the user to pick the server folder (GUI dialog, with a typed fallback)."""
    print_folder_guide()
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select your Minecraft Bedrock server folder")
        root.destroy()
        if folder:
            return Path(folder).resolve()
    except Exception:
        pass  # no display / tkinter unavailable -> fall back to typing a path

    print("Enter the path to your Minecraft Bedrock server folder:")
    while True:
        path = input("Path: ").strip().strip('"')
        if not path:
            print("No path entered. Exiting.")
            sys.exit(1)
        p = Path(path).resolve()
        if p.exists():
            return p
        print("That path does not exist. Try again.")


# ----------------------------------------------------------------------
def get_latest():
    """Return (download_url, version) for the latest Windows Bedrock server."""
    print("Checking for the latest Bedrock server version...")
    req = urllib.request.Request(API_URL, headers={"User-Agent": "bedrock-updater"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    links = data.get("result", {}).get("links", [])
    url = next((l["downloadUrl"] for l in links if l.get("downloadType") == DOWNLOAD_KEY), None)
    if not url:
        print(f"Could not find a '{DOWNLOAD_KEY}' download link in the API response.", file=sys.stderr)
        sys.exit(1)

    # Filename looks like: bedrock-server-1.26.33.2.zip
    version = Path(url).stem.replace("bedrock-server-", "")
    return url, version


def get_installed_version():
    """Return the currently installed version string, or None if not installed."""
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return None


def download(url):
    """Download the zip to a temp file and return its path."""
    tmp = Path(tempfile.gettempdir()) / Path(url).name
    print(f"Downloading {Path(url).name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "bedrock-updater"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        shutil.copyfileobj(resp, f)
    print(f"Downloaded to {tmp}")
    return tmp


def backup_preserved(old_version):
    """Zip the current world and config into backups/ before overwriting."""
    items = [SERVER_DIR / name for name in PRESERVE]
    items = [p for p in items if p.exists()]
    if not items:
        print("Nothing to back up (no existing world/config found).")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    ver = old_version or "unknown"
    backup_path = BACKUP_DIR / f"{WORLD}_{ver}_{timestamp}.zip"

    print(f"Backing up world and config to {backup_path.name} ...")
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if item.is_dir():
                for file in item.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(SERVER_DIR))
            else:
                zf.write(item, item.relative_to(SERVER_DIR))
    print("Backup complete.")


def set_property(props_path, key, value):
    """Set key=value in a server.properties file, replacing or appending."""
    lines = props_path.read_text(encoding="utf-8").splitlines() if props_path.exists() else []
    prefix = f"{key}="
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(prefix):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    props_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def apply_update(zip_path, fresh, version):
    """Extract the zip and install it into SERVER_DIR."""
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        extract_dir = Path(tmpdir) / "extract"
        print("Extracting server files...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        if fresh:
            print(f"Installing fresh server into {SERVER_DIR} ...")
        else:
            print(f"Updating server binaries in {SERVER_DIR} (preserving world and config)...")

        for item in extract_dir.iterdir():
            # On an update, never overwrite the user's world/config.
            if not fresh and item.name in PRESERVE:
                continue
            dest = SERVER_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        # Ensure our required server.properties settings on both fresh and update.
        props = SERVER_DIR / "server.properties"
        if fresh:
            set_property(props, "level-name", WORLD)
        for key, value in ENFORCED_PROPERTIES.items():
            set_property(props, key, value)
        ensured = ", ".join(f"{k}={v}" for k, v in ENFORCED_PROPERTIES.items())
        print(f"Ensured server.properties settings: {ensured}")

    VERSION_FILE.write_text(version + "\n", encoding="utf-8")


def main():
    global SERVER_DIR, BACKUP_DIR, VERSION_FILE

    print("=" * 60)
    print("     Minecraft Bedrock Server Updater")
    print("=" * 60)
    print("Select the folder that contains (or will contain) your Bedrock server.")

    SERVER_DIR = select_server_folder()
    BACKUP_DIR = SERVER_DIR.parent / "backups"
    VERSION_FILE = SERVER_DIR / "version.txt"
    print(f"Server folder: {SERVER_DIR}")

    url, latest = get_latest()
    installed = get_installed_version()
    # A "fresh" install is one where there is no server binary in the chosen folder.
    fresh = not (SERVER_DIR / "bedrock_server.exe").exists()

    print(f"Installed: {installed or '(unknown)'}")
    print(f"Latest:    {latest}")

    if installed == latest:
        print("\nAlready up to date. Nothing to do.")
        return

    print()
    if fresh:
        print(f"This will install a fresh server into: {SERVER_DIR}")
    else:
        print("This will:")
        print(f"  - Back up the current world and config to {BACKUP_DIR}")
        print(f"  - Update the server binaries in {SERVER_DIR}")
        print(f"  - Preserve: {', '.join(PRESERVE)}")

    if input("\nProceed? (y/n): ").strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return

    zip_path = download(url)
    try:
        if not fresh:
            backup_preserved(installed)
        apply_update(zip_path, fresh, latest)
    finally:
        if zip_path.exists():
            zip_path.unlink()

    print("\n" + "=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)
    print(f"Server version {latest} is ready in: {SERVER_DIR}")
    print("Start it by running bedrock_server.exe from that folder.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)

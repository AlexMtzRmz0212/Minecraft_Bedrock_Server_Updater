from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import os, zipfile, shutil, subprocess, threading, sys, time
import datetime
import tkinter as tk
from tkinter import filedialog

# ----------------------------------------------------------------------
# Clear terminal
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')
# ----------------------------------------------------------------------
def select_working_directory():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(title="Select the Minecraft server working folder")
    root.destroy()
    if folder:
        return Path(folder).resolve()
    else:
        print("No folder selected. Please enter the path manually:")
        while True:
            path = input("Path: ").strip().strip('"')
            if path:
                p = Path(path).resolve()
                if p.exists():
                    return p
                else:
                    print("That path does not exist. Try again.")
            else:
                print("Empty path. Exiting.")
                sys.exit(1)

# ----------------------------------------------------------------------
clear_screen()
# Choose working folder
print("Please select the folder where your Minecraft server files are stored.")
BASE_DIR = select_working_directory()
WORLD = "Cuernavaca"
OUT_DIR = BASE_DIR / WORLD
URL = "https://www.minecraft.net/en-us/download/server/bedrock"

# ----------------------------------------------------------------------
# Helper: extract version string from a folder name like "bedrock-server-1.20.31"
def extract_version_from_filename(name: str) -> str:
    parts = name.split('-')
    if len(parts) > 1 and parts[-1].replace('.', '').isdigit():
        return parts[-1]
    return ""


# ----------------------------------------------------------------------
# Download the latest Bedrock server zip using Playwright
def browse() -> Path | None:
    print("Launching browser to download the latest Bedrock server...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)   # set headless=True for no UI
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="networkidle")
        except Exception:
            # Fallback to a more robust wait condition
            page.goto(URL, wait_until="load")

        # Accept the EULA checkbox if present
        try:
            page.check("input[type=checkbox]:not([disabled])", timeout=3000)
        except Exception:
            pass   # no checkbox – fine

        # Try various selectors until a download starts
        download = None
        selectors = [
            "a[href*='.zip']",               # most reliable
            "a[href*='.zip'].download",
            "button:has-text('Download')",
            "a:has-text('Download')",
        ]

        for sel in selectors:
            try:
                with page.expect_download(timeout=60000) as download_info:
                    page.click(sel, timeout=5000)
                download = download_info.value
                break
            except Exception:
                continue

        if not download:
            print("Could not trigger a download. The site structure may have changed.", file=sys.stderr)
            browser.close()
            return None

        # Save the file
        OUT_DIR.mkdir(exist_ok=True)
        target = OUT_DIR / download.suggested_filename
        print(f"Download destination folder: {OUT_DIR}")
        download.save_as(str(target))
        print(f"Downloaded: {target.name}")
        browser.close()
        return target

# ----------------------------------------------------------------------
# Extract a zip archive into a subfolder named after the zip (without extension)
def extract(zip_path: Path):
    if not zip_path:
        return
    try:
        extract_to = OUT_DIR / zip_path.stem
        print(f"Extracting to: {extract_to}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_to)
        print("Extraction complete.")
    except Exception as e:
        print(f"Failed to extract {zip_path.name}: {e}", file=sys.stderr)
        sys.exit(1)

# ----------------------------------------------------------------------
# Delete a file (the downloaded zip)
def delete(file_path: Path):
    try:
        if file_path and isinstance(file_path, Path) and file_path.exists():
            print(f"Deleting temporary file: {file_path}")
            file_path.unlink()
    except Exception as e:
        print(f"Warning: could not delete {file_path.name}: {e}", file=sys.stderr)

# ----------------------------------------------------------------------
# Run the server once to generate/update server.properties and test readiness
def first_execution():
    exe = Path("bedrock_server.exe")
    if not exe.exists():
        print(f"{exe} not found in {Path.cwd()}", file=sys.stderr)
        return

    print(f"Starting {exe.name} from {Path.cwd()} to initialise server files...")
    proc = subprocess.Popen(
        [str(exe)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    ready = threading.Event()

    def _reader():
        for line in proc.stdout:
            print(line, end="")
            if any(k in line.lower() for k in ("server started", "server listening",
                                               "server is running", "server ready",
                                               "finished loading")):
                ready.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    timeout = 120
    if ready.wait(timeout=timeout):
        print("Server reported ready.")
        time.sleep(5)   # brief grace period
    else:
        print(f"Timed out waiting for server ready after {timeout}s", file=sys.stderr)

    # Shut down gracefully
    if proc.poll() is None:
        print("Shutting down server...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print("Server process closed.")
    else:
        print(f"Server already exited with code {proc.returncode}.")

    # Update server.properties
    sp = Path("server.properties")
    sp_path = sp.absolute()
    try:
        # Ensure telemetry line is present (append if needed)
        with sp.open("a", encoding="utf-8") as f:
            f.write("emit-server-telemetry=true\n")
        print(f"Ensured emit-server-telemetry=true in {sp_path}")

        # Set the correct level-name
        text = sp.read_text(encoding="utf-8")
        lines = text.splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("level-name="):
                new_lines.append(f"level-name={WORLD}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"level-name={WORLD}")
        sp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Set level-name to {WORLD} in {sp_path}")
    except Exception as e:
        print(f"Failed to update {sp_path}: {e}", file=sys.stderr)

# ----------------------------------------------------------------------
def main():
    print("=" * 60)
    print("     Minecraft Bedrock Server Updater")
    print("=" * 60)
    print(f"Base directory: {BASE_DIR}")
    print(f"World name: {WORLD}")
    print(f"Working directory for servers: {OUT_DIR}")

    # Ensure the main world directory exists
    OUT_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Download latest server zip
    new_zip = browse()
    if not new_zip:
        print("Download failed. Exiting.")
        return

    # Detect version from filename
    version = extract_version_from_filename(new_zip.stem)
    if version:
        print(f"Detected version: {version}")
    else:
        print("(Could not extract version number from filename)")

    # ------------------------------------------------------------------
    # Step 2: Look for existing server folders (potential previous versions)
    existing = [d for d in OUT_DIR.iterdir() if d.is_dir() and d.name != new_zip.stem]
    previous_dir = None

    if existing:
        print("\nExisting server versions found in", OUT_DIR)
        for i, d in enumerate(existing, 1):
            v = extract_version_from_filename(d.name)
            v_str = f" (version {v})" if v else ""
            print(f"  {i}. {d.name}{v_str}  [full path: {d}]")

        # Ask if the user wants to upgrade from one of them
        answer = input("\nDo you want to upgrade from an existing version? (y/n): ").strip().lower()
        if answer in ('y', 'yes'):
            # Choose which previous version to use
            if len(existing) == 1:
                previous_dir = existing[0]
                print(f"Will upgrade from: {previous_dir.name}  ({previous_dir})")
            else:
                while True:
                    try:
                        choice = int(input("Enter the number of the version to upgrade from: "))
                        if 1 <= choice <= len(existing):
                            previous_dir = existing[choice-1]
                            print(f"Selected: {previous_dir.name}  ({previous_dir})")
                            break
                        else:
                            print(f"Please enter a number between 1 and {len(existing)}")
                    except ValueError:
                        print("Invalid input.")

            # Confirm the upgrade action
            print(f"\nYou are about to upgrade from {previous_dir.name} to {new_zip.stem}.")
            print("This will:")
            print("  - Backup the existing world")
            print("  - Move the world into the new server folder")
            print("  - Delete the old server folder")
            confirm = input("Proceed? (y/n): ").strip().lower()
            if confirm not in ('y', 'yes'):
                print("Upgrade cancelled.")
                delete(new_zip)
                return
        else:
            # User said no to upgrade – maybe they want a fresh install
            fresh = input("Do you want to extract the new version as a fresh installation? (y/n): ").strip().lower()
            if fresh not in ('y', 'yes'):
                print("Installation cancelled.")
                delete(new_zip)
                return
            # No previous version will be used
    else:
        # No existing folders at all
        print("\nNo existing server versions found in", OUT_DIR)
        proceed = input("Proceed with fresh installation? (y/n): ").strip().lower()
        if proceed not in ('y', 'yes'):
            print("Installation cancelled.")
            delete(new_zip)
            return

    # ------------------------------------------------------------------
    # Step 3: Extract the downloaded zip
    new_version_dir = OUT_DIR / new_zip.stem
    if new_version_dir.exists():
        overwrite = input(f"\nFolder {new_version_dir} already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite in ('y', 'yes'):
            print(f"Removing existing folder: {new_version_dir}")
            shutil.rmtree(new_version_dir)
        else:
            print("Extraction cancelled.")
            delete(new_zip)
            return

    extract(new_zip)
    if not new_version_dir.exists():
        print("Extraction failed – folder not found.")
        delete(new_zip)
        return

    # Delete the zip now that extraction succeeded
    delete(new_zip)

    # ------------------------------------------------------------------
    # Step 4: If upgrading, backup world and move it to the new server
    if previous_dir:
        world_folder_name = WORLD
        prev_world = previous_dir / "worlds" / world_folder_name

        if prev_world.exists() and prev_world.is_dir():
            # Create backup in a sibling "Worlds Backups" folder
            backup_root = BASE_DIR / "Worlds Backups" / WORLD
            backup_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            backup_dest = backup_root / f"{previous_dir.name}_{timestamp}"
            print(f"\nBacking up world from: {prev_world}")
            print(f"Backup destination: {backup_dest}")
            shutil.copytree(prev_world, backup_dest)
            print("Backup completed.")

            # Move world into new server's worlds folder
            new_worlds = new_version_dir / "worlds"
            new_worlds.mkdir(exist_ok=True)
            dest_world = new_worlds / world_folder_name
            if dest_world.exists():
                print(f"Destination world folder already exists, removing: {dest_world}")
                shutil.rmtree(dest_world)
            print(f"Moving world from {prev_world} to {dest_world}")
            shutil.move(str(prev_world), str(dest_world))
            print("World moved.")

            # Remove the old server folder entirely
            print(f"Removing old server folder: {previous_dir}")
            shutil.rmtree(previous_dir)
            print("Old server folder removed.")
        else:
            print(f"\nWarning: World folder not found in {previous_dir}. Skipping world migration.")
    else:
        print("\nFresh installation – no world migration performed.")

    # ------------------------------------------------------------------
    # Step 5: Run the server once to set up server.properties
    print("\n" + "-" * 50)
    print("Running server once to finalise configuration...")
    print("-" * 50)
    print(f"Changing working directory to: {new_version_dir}")
    os.chdir(new_version_dir)
    first_execution()

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)
    print(f"New server version is ready in: {new_version_dir}")
    print("You can now start bedrock_server.exe normally from that folder.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
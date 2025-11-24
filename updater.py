from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import os, zipfile, shutil, subprocess, threading, sys, time
import datetime

URL = "https://www.minecraft.net/en-us/download/server/bedrock"
WORLD = "Cuernavaca"
OUT_DIR = Path(__file__).parent.resolve() / WORLD


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def browse():
    print("Downloading...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # set headless=True to run without UI
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="networkidle")
        except Exception:
            # Some servers may trigger HTTP2 protocol errors when waiting for "networkidle";
            # retry using a more lenient "load" condition which is more robust.
            page.goto(URL, wait_until="load")

        # Try to check the first enabled checkbox (policy/eula)
        try:
            page.check("input[type=checkbox]:not([disabled])", timeout=3000)
        except PlaywrightTimeout:
            # no checkbox found quickly; continue
            pass
        except Exception:
            pass

        # Attempt several download selectors until one triggers a download
        download = None
        selectors = [
            # "text=Download",
            # "button:has-text('Download')",
            # "a:has-text('Download')",
            # "text=download",
            # "button[type=submit]",
            "a[href*='.zip']",
            # "a[href*='.zip'].download",
        ]

        for sel in selectors:
            try:
                with page.expect_download(timeout=60000) as download_info:
                    page.click(sel, timeout=5000)
                download = download_info.value
                break
            except PlaywrightTimeout:
                # timed out waiting for download after clicking or for click; try next selector
                continue
            except Exception:
                continue

        if not download:
            print("Download button not found or no download started.", file=sys.stderr)
            browser.close()
            sys.exit(1)

        target = OUT_DIR / download.suggested_filename
        download.save_as(str(target))
        print(f"Downloaded: {target}")
        browser.close()
        return target

def extract(zip):
    if zip:
        try:
            print(f"Extracting {zip.name}")
            with zipfile.ZipFile(zip, "r") as zf:
                zf.extractall(OUT_DIR / zip.stem)
            print("Extraction complete.")
        except Exception as e:
            print(f"Failed to extract {zip.name}: {e}", file=sys.stderr)
            sys.exit(1)

def delete(zip):
    try:
        if zip and isinstance(zip, Path) and zip.exists():
            zip.unlink()
            print(f"Deleted {zip.name}")
    except Exception as e:
        print(f"Failed to delete {zip.name}: {e}", file=sys.stderr)

def getPrev(new_update):
    for p in Path(WORLD).iterdir():
        print(p.name, p.is_dir(), new_update.stem)
        if p.is_dir() != new_update.stem:
            print(f"Previous update found: {p.name}")
            return p.name

def firstExecution():
    exe = Path("bedrock_server.exe")
    if not exe.exists():
        print(f"{exe} not found in {Path.cwd()}", file=sys.stderr)
    else:
        print(f"Starting {exe.name}...")
        proc = subprocess.Popen(
            [str(exe)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        ready = threading.Event()

        def _reader():
            # Read lines from the process stdout and look for indicators that the server is ready.
            # Print output so the user can see server logs.
            for line in proc.stdout:
                print(line, end="")
                l = line.lower()
                # Common readiness phrases; adjust if your server prints something different
                if any(k in l for k in ("server started", "server listening", "server is running", "server ready", "finished loading")):
                    ready.set()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        # Wait until the reader signals readiness or until timeout
        timeout_seconds = 120
        if ready.wait(timeout=timeout_seconds):
            print("Server reported ready.")
            # Give the server a small grace period to stabilize before shutdown
            stability_wait = 5
            time.sleep(stability_wait)
        else:
            print(f"Timed out waiting for server ready after {timeout_seconds}s", file=sys.stderr)

        # Shut down the server process gracefully, then force kill if needed
        print("Shutting down server...")
        # Only attempt to terminate if the process is still running
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            print("Server process closed.")
        else:
            print(f"Server process already exited with code {proc.returncode}.")
    sp = Path("server.properties")
    try:
        # "a" stands for Append
        with sp.open("a", encoding="utf-8") as f:
            f.write("emit-server-telemetry=true\n")
        print(f"Updated {sp}")
    except Exception as e:
        print(f"Failed to update {sp}: {e}", file=sys.stderr)
    try:
        if sp.exists():
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
            print(f"Set level-name to {WORLD} in {sp}")
        else:
            sp.write_text(f"level-name={WORLD}\n", encoding="utf-8")
            print(f"Created {sp} with level-name={WORLD}")
    except Exception as e:
        print(f"Failed to set level-name in {sp}: {e}", file=sys.stderr)

def main():
    clear_screen()
    
    new_update = browse()
    extract(new_update)
    delete(new_update)

    previous_update = getPrev(new_update)
            
    os.chdir(WORLD+"/" + new_update.stem)
    firstExecution()

    if previous_update:
        # /Minecraft/WORLD/newUpdate
        os.chdir("../")
        # /Minecraft/WORLD/
        if previous_update:
            src = Path(previous_update)
            backup_root = Path("..") / "Worlds Backups" / WORLD
            backup_root.mkdir(parents=True, exist_ok=True)
            dest = backup_root / src.name
            if dest.exists():
                dest = backup_root / f"{src.name}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copytree(src, dest)
            print(f"Copied {src} -> {dest}")
        os.chdir("../"+ WORLD + "/" + previous_update + "/worlds")
        # /Minecraft/WORLD/previousUpdate/worlds
        shutil.move(str(WORLD), str("../../" + new_update.stem + "/worlds/" + WORLD))
        os.chdir("../../")
        # /Minecraft/WORLD/
        shutil.rmtree(previous_update)
    
if __name__ == "__main__":
    main()
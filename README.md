# Minecraft Bedrock Server Updater

A small, dependency-free Python script that updates a Minecraft **Bedrock Dedicated
Server** while preserving your world and configuration.

It fetches the latest Windows server version directly from Minecraft's official
download API (no browser automation). You pick your server folder, and if you're
out of date it backs up your world/config, downloads the new server, and swaps in
the new binaries — leaving your world and settings untouched.

## Requirements

- Python 3.8+ (standard library only — **no `pip install` needed**)

## Usage

```
python updater.py
```

1. A folder picker opens — **select your server folder**:
   - your **existing** server folder (the one containing `bedrock_server.exe` and
     `worlds\`), to update it in place, **or**
   - an **empty** folder, to install a fresh server there.
   (If no GUI is available, it falls back to typing the path.)
2. It checks the installed version (from `version.txt` in that folder) against the
   latest. If already current, it exits.
3. Otherwise it shows what it will do and asks for a `y/n`, then backs up your
   world + config, downloads the latest server, and updates in place.

## What it preserves on update

When updating an existing server, these are never overwritten:

- `worlds/`
- `server.properties`
- `allowlist.json`
- `permissions.json`

Everything else (the executable, DLLs, default packs, etc.) is replaced with the
new version.

On **every** run, a few `server.properties` settings are ensured (see
`ENFORCED_PROPERTIES` in `updater.py`) without disturbing your other settings:

- `emit-server-telemetry=true`
- `content-log-console-output-enabled=true`

On a **fresh** install, `level-name` is also set to your world name (`Cuernavaca`).

## Backups & version tracking

- Before each update, your world + config are zipped into a `backups/` folder
  created **next to** your server folder:
  `backups/Cuernavaca_<oldversion>_<timestamp>.zip`.
- The installed version is recorded in `version.txt` inside the server folder, so
  the updater knows what you have and can skip when you're already current.
  (An existing server without this file is treated as "unknown version" and will
  be updated on the next run.)

## Configuration

Edit the constants at the top of `updater.py`:

- `WORLD` — your world/level name (default `Cuernavaca`).
- `PRESERVE` — files/folders kept across updates.

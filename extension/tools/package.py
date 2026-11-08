"""Create an unpacked-install ZIP or a Chrome Web Store upload ZIP."""
import argparse
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
SHARED_RULES = ROOT / "sjtu_tennis_toolkit" / "booking_rules.json"
FILES = ["manifest.json", "background.js", "controller.js", "booking-rules.js", "rules.js", "route.js", "probes.js", "content.js",
         "sidepanel.html", "sidepanel.js", "sidepanel.css", "offscreen.html", "offscreen.js",
         "icons/icon16.png", "icons/icon48.png", "icons/icon128.png", "sounds/alert.wav"]
INSTALL_DOCS = ["README.md", "VALIDATION.md", "PRIVACY.md", "CHROME_WEB_STORE.md"]


def sync_booking_rules():
    rules = json.loads(SHARED_RULES.read_text(encoding="utf-8"))
    target = EXT / "booking-rules.js"
    source = (
        "// Generated from sjtu_tennis_toolkit/booking_rules.json by tools/package.py.\n"
        f"globalThis.SJTU_BOOKING_RULES = {json.dumps(rules, ensure_ascii=False, indent=2)};\n"
    )
    if not target.exists() or target.read_text(encoding="utf-8") != source:
        target.write_text(source, encoding="utf-8", newline="\n")


def package(*, store=False):
    sync_booking_rules()
    version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    suffix = "-chrome-web-store" if store else ""
    path = out / f"sjtu-tennis-extension-{version}{suffix}.zip"
    prefix = "" if store else "sjtu-tennis-extension/"
    files = FILES if store else [*FILES, *INSTALL_DOCS]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            source = EXT / name
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError(f"Missing or empty package file: {name}")
            archive.write(source, prefix + name)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or archive.namelist() != [prefix + name for name in files]:
            raise ValueError("Package integrity check failed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(digest + "  " + path.name + "\n", encoding="ascii")
    print(path)
    print(f"{len(files)} files; {path.stat().st_size} bytes; SHA256 {digest}")
    return path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--store", action="store_true", help="put the manifest at the ZIP root for store upload")
    action.add_argument("--sync-rules", action="store_true", help="refresh the shared rules in the unpacked extension")
    args = parser.parse_args()
    if args.sync_rules:
        sync_booking_rules()
    else:
        package(store=args.store)

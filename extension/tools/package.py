"""Create the unpackable user package; development tools are not shipped."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
FILES = ["manifest.json", "background.js", "controller.js", "rules.js", "probes.js", "content.js",
         "sidepanel.html", "sidepanel.js", "sidepanel.css", "offscreen.html", "offscreen.js", "README.md", "VALIDATION.md",
         "icons/icon16.png", "icons/icon48.png", "icons/icon128.png", "sounds/alert.wav"]

def package():
    version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    path = out / f"sjtu-tennis-extension-{version}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            source = EXT / name
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError(f"Missing or empty package file: {name}")
            archive.write(source, "sjtu-tennis-extension/" + name)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(FILES):
            raise ValueError("Package integrity check failed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(digest + "  " + path.name + "\n", encoding="ascii")
    print(path)
    print(f"{len(FILES)} files; {path.stat().st_size} bytes; SHA256 {digest}")
    return path

if __name__ == "__main__":
    package()

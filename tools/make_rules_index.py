#!/usr/bin/env python3
"""Generate rules_index.json with SHA-256 checksums for all .md files in a rules version folder."""
import hashlib, json, pathlib, sys

# Get version from command line or default to latest
ver = sys.argv[1] if len(sys.argv) > 1 else "0.4.0"

# Path: tools -> labscpi -> src/labscpi/rules/<ver>
p = pathlib.Path(__file__).parents[1] / "src" / "labscpi" / "rules" / ver

def sha256(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for b in iter(lambda: f.read(1<<20), b""):
            h.update(b)
    return h.hexdigest()

if not p.exists():
    print(f"Error: Rules folder not found: {p}")
    sys.exit(1)

# Only index .md files
files = [f for f in p.iterdir() if f.is_file() and f.suffix == ".md"]
idx = {
    "driver_version": ver,
    "rules_version": ver,
    "files": [{"name": f.name, "sha256": sha256(f)} for f in sorted(files)],
}

# Write to src/labscpi/rules/rules_index.json
out_path = p.parent / "rules_index.json"
out_path.write_text(json.dumps(idx, indent=2))
print(f"wrote {out_path}")

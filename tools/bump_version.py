#!/usr/bin/env python3
"""
Bump package + rules version for labscpi. No git required.

Usage:
  python tools/bump_version.py 0.2.0
  python tools/bump_version.py 0.2.0 --from 0.1.0
"""
import argparse, pathlib, re, shutil, hashlib, json, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_INIT = ROOT / "src" / "labscpi" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
RULES_DIR = ROOT / "rules"

def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: pathlib.Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")

def get_current_versions() -> tuple[str,str]:
    # __version__ and __rules_version__ from __init__.py
    init = read(PKG_INIT)
    ver = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M).group(1)
    rver = re.search(r'^__rules_version__\s*=\s*"([^"]+)"', init, re.M).group(1)
    return ver, rver

def bump_pyproject(newver: str):
    s = read(PYPROJECT)
    s2, n = re.subn(r'(?m)^version\s*=\s*".*"', f'version = "{newver}"', s, count=1)
    if n != 1:
        print("error: could not update version in pyproject.toml", file=sys.stderr)
        sys.exit(2)
    write(PYPROJECT, s2)

def bump_init(newver: str, rulesver: str):
    s = read(PKG_INIT)
    s = re.sub(r'(?m)^__version__\s*=\s*".*"', f'__version__ = "{newver}"', s, count=1)
    s = re.sub(r'(?m)^__rules_version__\s*=\s*".*"', f'__rules_version__ = "{rulesver}"', s, count=1)
    write(PKG_INIT, s)

def copy_rules(from_ver: str, to_ver: str):
    src = RULES_DIR / from_ver
    dst = RULES_DIR / to_ver
    if not src.exists():
        print(f"error: rules/{from_ver} not found", file=sys.stderr)
        sys.exit(3)
    if dst.exists():
        print(f"note: rules/{to_ver} already exists, leaving as-is")
        return
    shutil.copytree(src, dst)

def sha256(fp: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()

def make_rules_index(ver: str):
    d = RULES_DIR / ver
    if not d.exists():
        print(f"error: rules/{ver} not found to index", file=sys.stderr)
        sys.exit(4)
    files = [f for f in d.iterdir() if f.is_file() and f.name != "rules_index.json"]
    idx = {
        "driver_version": ver,
        "rules_version": ver,
        "files": [{"name": f.name, "sha256": sha256(f)} for f in sorted(files, key=lambda p: p.name)],
    }
    (d / "rules_index.json").write_text(json.dumps(idx, indent=2), encoding="utf-8")

def detect_latest_rules_version() -> str | None:
    if not RULES_DIR.exists():
        return None
    vers = [p.name for p in RULES_DIR.iterdir() if p.is_dir()]
    return sorted(vers, key=lambda s: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s)])[-1] if vers else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("new_version", help="new X.Y.Z version for package and rules")
    ap.add_argument("--from", dest="from_ver", help="rules version to copy from (defaults to current __rules_version__ or latest in rules/)")
    args = ap.parse_args()

    newver = args.new_version
    cur_pkg_ver, cur_rules_ver = get_current_versions()

    from_ver = args.from_ver or cur_rules_ver or detect_latest_rules_version()
    if not from_ver:
        print("error: cannot determine source rules version; pass --from X.Y.Z", file=sys.stderr)
        sys.exit(1)

    print(f"package: {cur_pkg_ver} -> {newver}")
    print(f"rules:   {from_ver} -> {newver}")

    bump_pyproject(newver)
    bump_init(newver, newver)
    copy_rules(from_ver, newver)
    make_rules_index(newver)

    print("done.")
    print(f"- updated {PYPROJECT}")
    print(f"- updated {PKG_INIT}")
    print(f"- rules copied to rules/{newver} and indexed")

if __name__ == "__main__":
    main()

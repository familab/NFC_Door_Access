"""Import device_configs JSON files into the installed PinViz package.

Usage:
  python diagram/scripts/import_device_configs.py [--src diagram/device_configs] [--patch-schemas] [--validate-devices] [--dry-run]

Features:
- Copies all JSON device configs from the repo into the installed pinviz's device_configs directory.
- Optional: patch PinViz's schemas.py to auto-discover device IDs (--patch-schemas).
- Optional: run `pinviz validate-devices` after copying (--validate-devices).
- Safe and idempotent; exits with non-zero status on error.
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
import os
from pathlib import Path


def copy_device_configs(src: Path, dest: Path, dry_run: bool = False) -> int:
    if not src.exists():
        print(f"Source directory not found: {src}")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in src.rglob("*.json"):
        target = dest / p.name
        if dry_run:
            print(f"Would copy {p} -> {target}")
        else:
            shutil.copy(p, target)
            print(f"Copied {p} -> {target}")
        count += 1
    return count


def patch_schemas(pinviz_module_path: Path, dry_run: bool = False) -> bool:
    schemas = pinviz_module_path.parent / "schemas.py"
    marker = "# Local: auto-discover device configs"
    snippet = f"\n{marker}\ntry:\n    import json as _json\n    from pathlib import Path as _Path\n    _device_configs_dir = _Path(__file__).parent / \"device_configs\"\n    if _device_configs_dir.exists():\n        for _json_file in _device_configs_dir.rglob(\"*.json\"):\n            try:\n                _data = _json.loads(_json_file.read_text())\n                _type_id = _data.get(\"id\") or _data.get(\"type_id\") or _json_file.stem\n                VALID_DEVICE_TYPES.add(_type_id.lower())\n            except Exception:\n                continue\nexcept Exception:\n    pass\n"
    if not schemas.exists():
        print(f"Schemas file not found at {schemas}")
        return False
    text = schemas.read_text()
    if marker in text:
        print("schemas.py already patched")
        return True
    if dry_run:
        print("Would append discovery snippet to", schemas)
        return True
    schemas.write_text(text + "\n" + snippet)
    print("Patched", schemas)
    return True


def run_validate_devices() -> int:
    # Prefer calling the 'pinviz' console script if available on PATH
    pinviz_exe = shutil.which("pinviz")
    if pinviz_exe:
        print(f"Found pinviz executable: {pinviz_exe}")
        env = dict(os.environ)
        env.setdefault('PYTHONIOENCODING', 'utf-8')
        proc = subprocess.run([pinviz_exe, "validate-devices"], capture_output=True, text=False, env=env)
        out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        print(out)
        if proc.returncode != 0:
            print(err)
        return proc.returncode

    # Try to find pinviz next to the Python executable (venv Scripts/ bin)
    exec_dir = Path(sys.executable).parent
    candidates = [exec_dir / "pinviz", exec_dir / "pinviz.exe"]
    for c in candidates:
        if c.exists():
            print(f"Found pinviz at {c}")
            env = dict(os.environ)
            env.setdefault('PYTHONIOENCODING', 'utf-8')
            proc = subprocess.run([str(c), "validate-devices"], capture_output=True, text=False, env=env)
            out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
            err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
            print(out)
            if proc.returncode != 0:
                print(err)
            return proc.returncode

    # Fallback: try running as a module (may not be supported)
    env = dict(os.environ)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    proc = subprocess.run([sys.executable, "-m", "pinviz", "validate-devices"], capture_output=True, text=False, env=env)
    out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    print(out)
    if proc.returncode != 0:
        print(err)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=Path("diagram/device_configs"))
    ap.add_argument("--patch-schemas", action="store_true", help="Patch pinviz.schemas to auto-discover JSON ids")
    ap.add_argument("--validate-devices", action="store_true", help="Run `pinviz validate-devices` after copying")
    ap.add_argument("--dry-run", action="store_true", help="Show actions without modifying files")
    args = ap.parse_args()

    src = Path(args.src)

    try:
        import pinviz
    except Exception as e:
        print("Failed to import pinviz package. Ensure PinViz is installed in the active environment.", e)
        return 3

    dest = Path(pinviz.__file__).parent / "device_configs"

    count = copy_device_configs(src, dest, dry_run=args.dry_run)
    print(f"Copied {count} device configs into {dest}")

    if args.patch_schemas:
        ok = patch_schemas(Path(pinviz.__file__), dry_run=args.dry_run)
        if not ok:
            print("Failed to patch schemas.py")
            return 4

    if args.validate_devices:
        rc = run_validate_devices()
        if rc != 0:
            print(f"pinviz validate-devices failed with exit code {rc}")
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

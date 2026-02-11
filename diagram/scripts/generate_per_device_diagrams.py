"""Generate per-device PinViz diagrams and render SVGs.

Usage:
    python diagram/scripts/generate_per_device_diagrams.py [--outdir diagram/generated] [--include-neighbors]

By default this:
 - reads diagram/door_controller.yaml
 - creates per-device YAML files in diagram/generated/
 - renders SVGs using the venv pinviz executable at diagram/venv/Scripts/pinviz

Requirements: PyYAML available in the running Python environment.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
import re

try:
    import yaml
except Exception as e:
    print("PyYAML is required. Install in your environment: python -m pip install pyyaml")
    raise

ROOT = Path(__file__).resolve().parents[2]
DIAGRAM_YAML = ROOT / "diagram" / "door_controller.yaml"
OUTDIR = ROOT / "diagram" / "generated"
PINVIZ = ROOT / "diagram" / "venv" / "Scripts" / "pinviz"


def slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def write_yaml(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(obj, f, sort_keys=False)


def find_device_by_name(devices: list[dict], name: str) -> dict | None:
    for d in devices:
        # for predefined devices the 'name' field may be missing; skip those
        if d.get("name") == name:
            return d
    return None


def collect_component(connections: list[dict], seed: set[str]) -> set[str]:
    """Return the transitive closure (component) of devices connected to seed."""
    included = set(seed)
    changed = True
    while changed:
        changed = False
        for conn in connections:
            # normalized new-format connections
            if "from" in conn or "to" in conn:
                src = conn.get("from")
                tgt = conn.get("to")
                src_dev = src.get("device") if src else None
                tgt_dev = tgt.get("device") if tgt else None
                # if either endpoint in included, add the other endpoint(s)
                if src_dev and src_dev in included and tgt_dev and tgt_dev not in included:
                    included.add(tgt_dev)
                    changed = True
                if tgt_dev and tgt_dev in included and src_dev and src_dev not in included:
                    included.add(src_dev)
                    changed = True
            else:
                # legacy board_pin format (board_pin/device/device_pin)
                d = conn.get("device")
                if d and d in included:
                    # nothing to add (connection goes to board)
                    pass
    return included


def filter_connections(connections: list[dict], included_devices: set[str]) -> list[dict]:
    out = []
    for conn in connections:
        if "from" in conn or "to" in conn:
            src = conn.get("from")
            tgt = conn.get("to")
            src_dev = src.get("device") if src else None
            tgt_dev = tgt.get("device") if tgt else None
            if (src_dev and src_dev in included_devices) or (tgt_dev and tgt_dev in included_devices):
                out.append(conn)
        else:
            # legacy board_pin format
            d = conn.get("device")
            if d and d in included_devices:
                out.append(conn)
    return out


def build_per_device_yaml(cfg: dict, device_name: str, include_neighbors: bool) -> dict:
    devices = cfg.get("devices", [])
    connections = cfg.get("connections", [])

    included = {device_name}
    if include_neighbors:
        included = collect_component(connections, included)

    # gather device definitions (preserve the original object for each)
    out_devices = []
    for d in devices:
        name = d.get("name")
        if name and name in included:
            out_devices.append(d)
        elif not name:
            # predefined type-only devices with no name won't be included
            pass

    out_connections = filter_connections(connections, included)

    new_cfg = {
        "title": f"{cfg.get('title', 'Diagram')} — {device_name}",
        "board": cfg.get("board", "raspberry_pi_4"),
        "show_legend": True,
        "devices": out_devices,
        "connections": out_connections,
    }
    return new_cfg


def render_yaml(yaml_path: Path, svg_path: Path) -> None:
    cmd = [str(PINVIZ), "render", str(yaml_path), "-o", str(svg_path), "--show-legend"]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--include-neighbors", action="store_true", default=True)
    ap.add_argument("--render", action="store_true", default=True)
    ap.add_argument("--skip-render", dest="render", action="store_false")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cfg = load_yaml(DIAGRAM_YAML)
    devices = cfg.get("devices", [])

    # determine device names (only devices that have a name)
    device_names = [d.get("name") for d in devices if d.get("name")]

    svg_dir = outdir / "out"
    svg_dir.mkdir(parents=True, exist_ok=True)

    for name in device_names:
        per_cfg = build_per_device_yaml(cfg, name, args.include_neighbors)
        fname = slug(name) + ".yaml"
        yaml_path = outdir / fname
        svg_path = svg_dir / (slug(name) + ".svg")
        write_yaml(per_cfg, yaml_path)
        print("Wrote", yaml_path)
        if args.render:
            try:
                render_yaml(yaml_path, svg_path)
                print("Rendered", svg_path)
            except subprocess.CalledProcessError as e:
                print("Render failed for", yaml_path, e)


if __name__ == "__main__":
    main()

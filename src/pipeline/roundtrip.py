"""Round-trip validator for KiCad schematic parsing.

Compares our pipeline's parsed output against kicad-cli's netlist export
to validate that our parser sees the same components and net assignments
as KiCad's own toolchain.

Flow:
    1. Parse .kicad_sch with our hierarchy walker -> components, nets
    2. Export netlist from original file via kicad-cli (XML format)
    3. Parse the XML netlist
    4. Compare component sets and report mismatches
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .hierarchy import walk_hierarchy

logger = logging.getLogger(__name__)

KICAD_CLI = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"


def parse_kicad_netlist_xml(netlist_path: Path) -> dict:
    """Parse a kicad-cli XML netlist into a structured dict.

    Args:
        netlist_path: Path to the XML netlist file.

    Returns:
        Dict with "components" (list of dicts with ref, value, footprint)
        and "nets" (list of dicts with name, code, nodes).
    """
    tree = ET.parse(str(netlist_path))
    root = tree.getroot()

    components = []
    comps_elem = root.find("components")
    if comps_elem is not None:
        for comp in comps_elem.findall("comp"):
            ref = comp.get("ref", "")
            value_elem = comp.find("value")
            fp_elem = comp.find("footprint")
            components.append({
                "ref": ref,
                "value": value_elem.text if value_elem is not None and value_elem.text else "",
                "footprint": fp_elem.text if fp_elem is not None and fp_elem.text else "",
            })

    nets = []
    nets_elem = root.find("nets")
    if nets_elem is not None:
        for net in nets_elem.findall("net"):
            net_name = net.get("name", "")
            net_code = net.get("code", "")
            nodes = []
            for node in net.findall("node"):
                nodes.append({
                    "ref": node.get("ref", ""),
                    "pin": node.get("pin", ""),
                    "pinfunction": node.get("pinfunction", ""),
                    "pintype": node.get("pintype", ""),
                })
            nets.append({
                "name": net_name,
                "code": net_code,
                "nodes": nodes,
            })

    return {"components": components, "nets": nets}


def _export_netlist(sch_path: Path, output_dir: Path) -> Path | None:
    """Export a netlist from a .kicad_sch file using kicad-cli.

    Returns the path to the exported XML file, or None on failure.
    """
    kicad_cli = Path(KICAD_CLI)
    if not kicad_cli.is_file():
        logger.warning("kicad-cli not found at %s", KICAD_CLI)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{sch_path.stem}_netlist.xml"

    try:
        result = subprocess.run(
            [str(kicad_cli), "sch", "export", "netlist",
             "--format", "kicadxml",
             str(sch_path), "-o", str(out_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                "kicad-cli netlist export failed (rc=%d): %s",
                result.returncode, result.stderr,
            )
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("kicad-cli export error: %s", e)
        return None

    if not out_path.is_file() or out_path.stat().st_size == 0:
        logger.warning("kicad-cli produced empty or missing output: %s", out_path)
        return None

    return out_path


def validate_roundtrip(sch_path: Path, work_dir: Path | None = None) -> dict:
    """Validate our parser against kicad-cli's netlist export.

    Args:
        sch_path: Path to the root .kicad_sch file.
        work_dir: Directory for temporary netlist files. If None, uses
                  sch_path's parent directory.

    Returns:
        Dict with keys:
            success: bool — True if all our components match the netlist
            our_components: int — count of non-power components we parsed
            netlist_components: int — count of components in kicad-cli netlist
            matched: int — components found in both
            mismatched: list[str] — component refs that differ
            error: str (optional) — error message on failure
    """
    sch_path = Path(sch_path).resolve()
    if work_dir is None:
        work_dir = sch_path.parent

    # Error result template
    def _error(msg: str) -> dict:
        return {
            "success": False,
            "our_components": 0,
            "netlist_components": 0,
            "matched": 0,
            "mismatched": [],
            "error": msg,
        }

    if not sch_path.is_file():
        return _error(f"Schematic file not found: {sch_path}")

    # Step 1: Parse with our pipeline
    try:
        sheet_tree = walk_hierarchy(sch_path)
    except Exception as e:
        return _error(f"Hierarchy walker failed: {e}")

    # Collect all non-power components from our parser
    our_refs: dict[str, dict] = {}
    for sheet in sheet_tree.values():
        for comp in sheet.components:
            if comp.is_power:
                continue
            our_refs[comp.ref] = {
                "ref": comp.ref,
                "value": comp.value,
                "footprint": comp.footprint,
            }

    # Step 2: Export netlist with kicad-cli
    netlist_path = _export_netlist(sch_path, Path(work_dir))
    if netlist_path is None:
        return _error("kicad-cli netlist export failed")

    # Step 3: Parse the exported netlist
    try:
        netlist = parse_kicad_netlist_xml(netlist_path)
    except Exception as e:
        return _error(f"Netlist XML parsing failed: {e}")

    netlist_refs: dict[str, dict] = {}
    for comp in netlist["components"]:
        netlist_refs[comp["ref"]] = comp

    # Step 4: Compare component sets
    our_set = set(our_refs.keys())
    netlist_set = set(netlist_refs.keys())

    matched = our_set & netlist_set
    only_ours = our_set - netlist_set
    only_netlist = netlist_set - our_set

    mismatched = sorted(
        [f"+ours:{r}" for r in only_ours]
        + [f"+netlist:{r}" for r in only_netlist]
    )

    success = len(mismatched) == 0

    return {
        "success": success,
        "our_components": len(our_refs),
        "netlist_components": len(netlist_refs),
        "matched": len(matched),
        "mismatched": mismatched,
    }

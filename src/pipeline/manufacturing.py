"""Manufacturing integration — BOM, CPL, Gerber, drill, and 3D exports.

Wraps kicad-cli v9 for manufacturing output generation and provides
parts inventory management for LumenPNP pick-and-place workflow.

TASK-025: Parts inventory (load/save JSON)
TASK-026: BOM export and matching to inventory
TASK-027: CPL generation for LumenPNP
TASK-028: Gerber + drill export
TASK-029: 3D model export (STEP + VRML)
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

KICAD_CLI = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"
TIMEOUT = 120  # seconds


def _run_kicad_cli(args: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run a kicad-cli command, returning the CompletedProcess."""
    cmd = [KICAD_CLI] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# TASK-025: Parts inventory
# ---------------------------------------------------------------------------


@dataclass
class InventoryItem:
    """A single part in the local inventory."""

    mpn: str  # manufacturer part number
    description: str
    package: str  # e.g., "0402", "SOT-23-5"
    quantity_available: int
    feeder_slot: int | None  # LumenPNP feeder position


def load_inventory(inventory_path: Path) -> list[InventoryItem]:
    """Load parts inventory from a JSON file.

    Expected format: a JSON array of objects with keys matching
    InventoryItem fields.
    """
    inventory_path = Path(inventory_path)
    data = json.loads(inventory_path.read_text())
    items = []
    for entry in data:
        items.append(InventoryItem(
            mpn=entry["mpn"],
            description=entry["description"],
            package=entry["package"],
            quantity_available=entry["quantity_available"],
            feeder_slot=entry.get("feeder_slot"),
        ))
    return items


def save_inventory(items: list[InventoryItem], output_path: Path) -> None:
    """Save parts inventory to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(item) for item in items]
    output_path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# TASK-026: BOM matching
# ---------------------------------------------------------------------------


@dataclass
class BomEntry:
    """A single entry from a KiCad BOM export."""

    ref: str
    value: str
    footprint: str
    qty: int = 1
    dnp: bool = False
    mpn: str | None = None


@dataclass
class BomMatchResult:
    """Result of matching BOM entries to inventory."""

    matched: list[tuple[BomEntry, InventoryItem]] = field(default_factory=list)
    unmatched: list[BomEntry] = field(default_factory=list)
    missing_parts: list[BomEntry] = field(default_factory=list)


def _extract_package_size(footprint: str) -> str | None:
    """Extract package size from a KiCad footprint string.

    Examples:
        "Capacitor_SMD:C_0402_1005Metric" -> "0402"
        "Package_TO_SOT_SMD:SOT-23" -> "SOT-23"
        "Package_QFP:LQFP-64_10x10mm_P0.5mm" -> "LQFP-64"
    """
    # Try common SMD passive pattern: C_0402, R_0201, etc.
    m = re.search(r"[CR]_(\d{4})_", footprint)
    if m:
        return m.group(1)

    # Try SOT/SOD/QFP/etc pattern
    m = re.search(r"(SOT-\d+[-\w]*|SOD-\d+|LQFP-\d+|QFP-\d+|QFN-\d+|TQFP-\d+|BGA-\d+)", footprint)
    if m:
        return m.group(1)

    # Try package from footprint library name (after the colon)
    if ":" in footprint:
        fp_name = footprint.split(":")[-1]
        return fp_name

    return footprint


def export_bom(sch_path: Path, output_path: Path) -> list[BomEntry]:
    """Export BOM from a schematic using kicad-cli, parse the CSV output.

    Returns a list of BomEntry objects parsed from the CSV.

    Raises:
        RuntimeError: If the export fails.
    """
    sch_path = Path(sch_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = _run_kicad_cli([
        "sch", "export", "bom",
        str(sch_path),
        "-o", str(output_path),
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"BOM export failed: {result.stderr.strip()}")

    return _parse_bom_csv(output_path)


def _parse_bom_csv(csv_path: Path) -> list[BomEntry]:
    """Parse a KiCad BOM CSV file into BomEntry objects.

    KiCad BOM CSV columns: "Refs","Value","Footprint","Qty","DNP"
    """
    entries = []
    text = csv_path.read_text()
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        refs_raw = row.get("Refs", row.get("Reference", ""))
        value = row.get("Value", "")
        footprint = row.get("Footprint", "")
        parsed_qty = int(row.get("Qty", row.get("Quantity", "1")))
        dnp_str = row.get("DNP", "").strip().lower()
        dnp = dnp_str in ("yes", "true", "1", "dnp")

        # Refs can be comma-separated (grouped BOM) or single
        refs = [r.strip() for r in refs_raw.split(",") if r.strip()]

        per_ref_qty = max(1, parsed_qty // len(refs)) if refs else 1
        for ref in refs:
            entries.append(BomEntry(
                ref=ref,
                value=value,
                footprint=footprint,
                qty=per_ref_qty,
                dnp=dnp,
            ))

    return entries


def match_bom_to_inventory(
    bom: list[BomEntry],
    inventory: list[InventoryItem],
) -> BomMatchResult:
    """Match BOM entries to inventory items by package and value.

    Matching strategy:
    1. Extract package size from footprint
    2. Match against inventory by package (case-insensitive)
    3. If multiple matches, prefer exact value match
    4. Parts with insufficient quantity go to missing_parts
    """
    result = BomMatchResult()

    # Build inventory lookup by package (lowercase)
    inv_by_package: dict[str, list[InventoryItem]] = {}
    for item in inventory:
        key = item.package.lower()
        inv_by_package.setdefault(key, []).append(item)

    # Track remaining quantities
    remaining_qty: dict[str, int] = {item.mpn: item.quantity_available for item in inventory}

    for entry in bom:
        if entry.dnp:
            result.unmatched.append(entry)
            continue

        pkg = _extract_package_size(entry.footprint)
        if pkg is None:
            result.unmatched.append(entry)
            continue

        candidates = inv_by_package.get(pkg.lower(), [])
        if not candidates:
            result.unmatched.append(entry)
            continue

        # Find best match — prefer value match
        best = None
        for cand in candidates:
            if entry.value.lower() in cand.description.lower():
                best = cand
                break
        if best is None:
            best = candidates[0]

        if remaining_qty.get(best.mpn, 0) >= entry.qty:
            remaining_qty[best.mpn] -= entry.qty
            result.matched.append((entry, best))
        else:
            result.missing_parts.append(entry)

    return result


# ---------------------------------------------------------------------------
# TASK-027: CPL generation for LumenPNP
# ---------------------------------------------------------------------------


@dataclass
class CplEntry:
    """A single component placement entry."""

    ref: str
    x_mm: float
    y_mm: float
    rotation: float
    side: str  # "top" or "bottom"
    feeder_slot: int | None = None


def export_placement(pcb_path: Path, output_path: Path) -> list[CplEntry]:
    """Export component placement from PCB using kicad-cli pos export.

    Returns a list of CplEntry objects parsed from the CSV.

    Raises:
        RuntimeError: If the export fails.
    """
    pcb_path = Path(pcb_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = _run_kicad_cli([
        "pcb", "export", "pos",
        str(pcb_path),
        "-o", str(output_path),
        "--format", "csv",
        "--units", "mm",
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Position export failed: {result.stderr.strip()}")

    return _parse_pos_csv(output_path)


def _parse_pos_csv(csv_path: Path) -> list[CplEntry]:
    """Parse a KiCad position CSV file into CplEntry objects.

    KiCad pos CSV columns: Ref,Val,Package,PosX,PosY,Rot,Side
    """
    entries = []
    text = csv_path.read_text()
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        ref = row.get("Ref", "").strip().strip('"')
        x = float(row.get("PosX", "0"))
        y = float(row.get("PosY", "0"))
        rot = float(row.get("Rot", "0"))
        side = row.get("Side", "top").strip().lower()

        entries.append(CplEntry(
            ref=ref,
            x_mm=x,
            y_mm=y,
            rotation=rot,
            side=side,
        ))

    return entries


def generate_lumen_pnp_csv(cpl: list[CplEntry], output_path: Path) -> None:
    """Generate LumenPNP-compatible CSV from placement data.

    LumenPNP OpenPnP format:
    Designator,Val,Package,Mid X,Mid Y,Rotation,Layer
    Where Layer is "T" for top, "B" for bottom.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Designator", "Mid X", "Mid Y", "Rotation", "Layer", "Feeder",
        ])
        for entry in cpl:
            layer = "T" if entry.side == "top" else "B"
            feeder = entry.feeder_slot if entry.feeder_slot is not None else ""
            writer.writerow([
                entry.ref,
                f"{entry.x_mm:.6f}",
                f"{entry.y_mm:.6f}",
                f"{entry.rotation:.6f}",
                layer,
                feeder,
            ])


def assign_feeders(
    cpl: list[CplEntry],
    inventory: list[InventoryItem],
    bom: list[BomEntry],
) -> list[CplEntry]:
    """Assign feeder slots to CPL entries based on inventory.

    Looks up each CPL ref in the BOM, finds the matching inventory item,
    and assigns its feeder_slot to the CPL entry.
    """
    # Build ref -> BomEntry lookup
    bom_by_ref = {entry.ref: entry for entry in bom}

    # Build package -> inventory lookup
    inv_by_package: dict[str, list[InventoryItem]] = {}
    for item in inventory:
        key = item.package.lower()
        inv_by_package.setdefault(key, []).append(item)

    updated = []
    for entry in cpl:
        bom_entry = bom_by_ref.get(entry.ref)
        if bom_entry is not None:
            pkg = _extract_package_size(bom_entry.footprint)
            if pkg:
                candidates = inv_by_package.get(pkg.lower(), [])
                for cand in candidates:
                    if cand.feeder_slot is not None:
                        entry.feeder_slot = cand.feeder_slot
                        break

        updated.append(entry)

    return updated


# ---------------------------------------------------------------------------
# TASK-028: Gerber + drill export
# ---------------------------------------------------------------------------


@dataclass
class GerberOutput:
    """Result of a Gerber or drill export operation."""

    output_dir: Path
    gerber_files: list[Path] = field(default_factory=list)
    drill_files: list[Path] = field(default_factory=list)
    success: bool = True
    errors: list[str] = field(default_factory=list)


def export_gerbers(pcb_path: Path, output_dir: Path) -> GerberOutput:
    """Export Gerber files from a PCB using kicad-cli.

    Returns a GerberOutput with the list of generated files.
    """
    pcb_path = Path(pcb_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result_obj = GerberOutput(output_dir=output_dir)

    try:
        result = _run_kicad_cli([
            "pcb", "export", "gerbers",
            str(pcb_path),
            "-o", str(output_dir) + "/",
        ])

        if result.returncode != 0:
            result_obj.success = False
            result_obj.errors.append(result.stderr.strip())
            return result_obj

        # Collect generated Gerber files
        gerber_extensions = {
            ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo",
            ".gtp", ".gbp", ".gta", ".gba", ".gm1", ".gbr",
            ".g1", ".g2", ".g3", ".g4", ".g5", ".g6",
            ".g7", ".g8",
        }
        for f in sorted(output_dir.iterdir()):
            if f.suffix.lower() in gerber_extensions:
                result_obj.gerber_files.append(f)

    except subprocess.TimeoutExpired:
        result_obj.success = False
        result_obj.errors.append(f"Gerber export timed out after {TIMEOUT}s")
    except OSError as e:
        result_obj.success = False
        result_obj.errors.append(str(e))

    return result_obj


def export_drill(pcb_path: Path, output_dir: Path) -> GerberOutput:
    """Export drill files from a PCB using kicad-cli.

    Returns a GerberOutput with the list of generated drill files.
    """
    pcb_path = Path(pcb_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result_obj = GerberOutput(output_dir=output_dir)

    try:
        result = _run_kicad_cli([
            "pcb", "export", "drill",
            str(pcb_path),
            "-o", str(output_dir) + "/",
        ])

        if result.returncode != 0:
            result_obj.success = False
            result_obj.errors.append(result.stderr.strip())
            return result_obj

        # Collect generated drill files
        drill_extensions = {".drl", ".exc", ".xln"}
        for f in sorted(output_dir.iterdir()):
            if f.suffix.lower() in drill_extensions:
                result_obj.drill_files.append(f)

    except subprocess.TimeoutExpired:
        result_obj.success = False
        result_obj.errors.append(f"Drill export timed out after {TIMEOUT}s")
    except OSError as e:
        result_obj.success = False
        result_obj.errors.append(str(e))

    return result_obj


def export_manufacturing_package(
    pcb_path: Path,
    sch_path: Path,
    output_dir: Path,
) -> dict:
    """Export complete manufacturing package: Gerbers + drill + BOM + CPL + 3D.

    Creates subdirectories under output_dir:
        gerbers/   — Gerber files
        drill/     — Drill files
        bom.csv    — Bill of materials
        cpl.csv    — Component placement list (KiCad format)
        lumen_pnp.csv — LumenPNP-compatible placement
        board.step — STEP 3D model
        board.wrl  — VRML 3D model

    Returns a summary dict with keys: gerbers, drill, bom, cpl, step, vrml,
    success, errors.
    """
    pcb_path = Path(pcb_path)
    sch_path = Path(sch_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "gerbers": None,
        "drill": None,
        "bom_count": 0,
        "cpl_count": 0,
        "step": None,
        "vrml": None,
        "success": True,
        "errors": [],
    }

    # Gerbers
    gerber_dir = output_dir / "gerbers"
    gerber_result = export_gerbers(pcb_path, gerber_dir)
    summary["gerbers"] = {
        "count": len(gerber_result.gerber_files),
        "files": [str(f.name) for f in gerber_result.gerber_files],
        "success": gerber_result.success,
    }
    if not gerber_result.success:
        summary["success"] = False
        summary["errors"].extend(gerber_result.errors)

    # Drill
    drill_dir = output_dir / "drill"
    drill_result = export_drill(pcb_path, drill_dir)
    summary["drill"] = {
        "count": len(drill_result.drill_files),
        "files": [str(f.name) for f in drill_result.drill_files],
        "success": drill_result.success,
    }
    if not drill_result.success:
        summary["success"] = False
        summary["errors"].extend(drill_result.errors)

    # BOM
    bom_path = output_dir / "bom.csv"
    try:
        bom_entries = export_bom(sch_path, bom_path)
        summary["bom_count"] = len(bom_entries)
    except RuntimeError as e:
        summary["success"] = False
        summary["errors"].append(str(e))

    # CPL
    cpl_path = output_dir / "cpl.csv"
    try:
        cpl_entries = export_placement(pcb_path, cpl_path)
        summary["cpl_count"] = len(cpl_entries)

        # Generate LumenPNP CSV
        lumen_path = output_dir / "lumen_pnp.csv"
        generate_lumen_pnp_csv(cpl_entries, lumen_path)
    except RuntimeError as e:
        summary["success"] = False
        summary["errors"].append(str(e))

    # 3D models (STEP + VRML)
    step_path = output_dir / "board.step"
    step_result = export_step(pcb_path, step_path)
    summary["step"] = {
        "file": str(step_path.name),
        "size_bytes": step_result.file_size_bytes,
        "success": step_result.success,
    }
    if not step_result.success:
        summary["errors"].extend(step_result.errors)

    vrml_path = output_dir / "board.wrl"
    vrml_result = export_vrml(pcb_path, vrml_path)
    summary["vrml"] = {
        "file": str(vrml_path.name),
        "size_bytes": vrml_result.file_size_bytes,
        "success": vrml_result.success,
    }
    if not vrml_result.success:
        summary["errors"].extend(vrml_result.errors)

    return summary


# ---------------------------------------------------------------------------
# TASK-029: 3D model export (STEP + VRML)
# ---------------------------------------------------------------------------


@dataclass
class Model3dOutput:
    """Result of a 3D model export operation."""

    output_path: Path
    file_size_bytes: int = 0
    success: bool = True
    errors: list[str] = field(default_factory=list)


def export_step(
    pcb_path: Path,
    output_path: Path,
    *,
    board_only: bool = False,
    no_dnp: bool = False,
) -> Model3dOutput:
    """Export a STEP 3D model from a PCB using kicad-cli.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Path for the output .step file.
        board_only: If True, export only the PCB substrate (no components).
        no_dnp: If True, exclude "Do Not Populate" components.

    Returns:
        Model3dOutput with success status and file metadata.
    """
    pcb_path = Path(pcb_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_obj = Model3dOutput(output_path=output_path)

    args = [
        "pcb", "export", "step",
        str(pcb_path),
        "-o", str(output_path),
        "--force",
    ]
    if board_only:
        args.append("--board-only")
    if no_dnp:
        args.append("--no-dnp")

    try:
        result = _run_kicad_cli(args)

        if not output_path.exists() or output_path.stat().st_size == 0:
            result_obj.success = False
            stderr = result.stderr.strip()
            result_obj.errors.append(stderr or "STEP export produced no output")
            return result_obj

        result_obj.file_size_bytes = output_path.stat().st_size

    except subprocess.TimeoutExpired:
        result_obj.success = False
        result_obj.errors.append(f"STEP export timed out after {TIMEOUT}s")
    except OSError as e:
        result_obj.success = False
        result_obj.errors.append(str(e))

    return result_obj


def export_vrml(
    pcb_path: Path,
    output_path: Path,
    *,
    units: str = "in",
    no_dnp: bool = False,
) -> Model3dOutput:
    """Export a VRML 3D model from a PCB using kicad-cli.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Path for the output .wrl file.
        units: Output units — "in" (default), "mm", "m", or "tenths".
        no_dnp: If True, exclude "Do Not Populate" components.

    Returns:
        Model3dOutput with success status and file metadata.
    """
    pcb_path = Path(pcb_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_obj = Model3dOutput(output_path=output_path)

    args = [
        "pcb", "export", "vrml",
        str(pcb_path),
        "-o", str(output_path),
        "--force",
        "--units", units,
    ]
    if no_dnp:
        args.append("--no-dnp")

    try:
        result = _run_kicad_cli(args)

        if not output_path.exists() or output_path.stat().st_size == 0:
            result_obj.success = False
            stderr = result.stderr.strip()
            result_obj.errors.append(stderr or "VRML export produced no output")
            return result_obj

        result_obj.file_size_bytes = output_path.stat().st_size

    except subprocess.TimeoutExpired:
        result_obj.success = False
        result_obj.errors.append(f"VRML export timed out after {TIMEOUT}s")
    except OSError as e:
        result_obj.success = False
        result_obj.errors.append(str(e))

    return result_obj

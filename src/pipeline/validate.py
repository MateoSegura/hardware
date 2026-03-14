"""KiCad CLI validation — runs ERC, DRC, netlist export, and BOM export.

Wraps kicad-cli v9 commands with structured JSON output parsing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
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


def _file_hash(path: Path) -> str:
    """Short hash of a file path for temp file naming."""
    return hashlib.md5(str(path.resolve()).encode()).hexdigest()[:8]


def run_erc(schematic_path: Path) -> dict:
    """Run ERC on a .kicad_sch file, return structured results.

    Returns:
        Dict with keys: success, violations, errors, warnings, details, stderr.
    """
    schematic_path = Path(schematic_path)
    if not schematic_path.is_file():
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "details": [],
            "stderr": f"File not found: {schematic_path}",
        }

    with tempfile.NamedTemporaryFile(suffix=".json", prefix="erc_", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        result = _run_kicad_cli([
            "sch", "erc",
            str(schematic_path),
            "--format", "json",
            "--severity-all",
            "-o", str(output_path),
        ])

        if not output_path.exists() or output_path.stat().st_size == 0:
            return {
                "success": False,
                "violations": 0,
                "errors": 0,
                "warnings": 0,
                "details": [],
                "stderr": result.stderr.strip(),
            }

        data = json.loads(output_path.read_text())

        # Count violations across all sheets
        all_violations = []
        error_count = 0
        warning_count = 0

        for sheet in data.get("sheets", []):
            for v in sheet.get("violations", []):
                all_violations.append(v)
                if v.get("severity") == "error":
                    error_count += 1
                elif v.get("severity") == "warning":
                    warning_count += 1

        return {
            "success": True,
            "violations": len(all_violations),
            "errors": error_count,
            "warnings": warning_count,
            "details": all_violations,
            "stderr": result.stderr.strip(),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "details": [],
            "stderr": f"ERC timed out after {TIMEOUT}s",
        }
    except (json.JSONDecodeError, OSError) as e:
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "details": [],
            "stderr": str(e),
        }
    finally:
        output_path.unlink(missing_ok=True)


def run_drc(pcb_path: Path) -> dict:
    """Run DRC on a .kicad_pcb file, return structured results.

    Returns:
        Dict with keys: success, violations, errors, warnings, unconnected, details, stderr.
    """
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "unconnected": 0,
            "details": [],
            "stderr": f"File not found: {pcb_path}",
        }

    with tempfile.NamedTemporaryFile(suffix=".json", prefix="drc_", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        result = _run_kicad_cli([
            "pcb", "drc",
            str(pcb_path),
            "--format", "json",
            "--severity-all",
            "-o", str(output_path),
        ])

        if not output_path.exists() or output_path.stat().st_size == 0:
            return {
                "success": False,
                "violations": 0,
                "errors": 0,
                "warnings": 0,
                "unconnected": 0,
                "details": [],
                "stderr": result.stderr.strip(),
            }

        data = json.loads(output_path.read_text())

        violations = data.get("violations", [])
        unconnected = data.get("unconnected_items", [])

        error_count = sum(1 for v in violations if v.get("severity") == "error")
        warning_count = sum(1 for v in violations if v.get("severity") == "warning")

        return {
            "success": True,
            "violations": len(violations),
            "errors": error_count,
            "warnings": warning_count,
            "unconnected": len(unconnected),
            "details": violations,
            "stderr": result.stderr.strip(),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "unconnected": 0,
            "details": [],
            "stderr": f"DRC timed out after {TIMEOUT}s",
        }
    except (json.JSONDecodeError, OSError) as e:
        return {
            "success": False,
            "violations": 0,
            "errors": 0,
            "warnings": 0,
            "unconnected": 0,
            "details": [],
            "stderr": str(e),
        }
    finally:
        output_path.unlink(missing_ok=True)


def export_netlist(schematic_path: Path, output_path: Path) -> Path:
    """Export netlist from schematic.

    Returns:
        The output path if successful.

    Raises:
        RuntimeError: If the export fails.
    """
    schematic_path = Path(schematic_path)
    output_path = Path(output_path)

    result = _run_kicad_cli([
        "sch", "export", "netlist",
        str(schematic_path),
        "-o", str(output_path),
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"Netlist export failed: {result.stderr.strip()}"
        )

    return output_path


def export_bom(schematic_path: Path, output_path: Path) -> Path:
    """Export BOM from schematic as CSV.

    Returns:
        The output path if successful.

    Raises:
        RuntimeError: If the export fails.
    """
    schematic_path = Path(schematic_path)
    output_path = Path(output_path)

    result = _run_kicad_cli([
        "sch", "export", "bom",
        str(schematic_path),
        "-o", str(output_path),
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"BOM export failed: {result.stderr.strip()}"
        )

    return output_path


def validate_project(project_dir: Path) -> dict:
    """Run full validation on a project: ERC + DRC.

    Finds root schematic and PCB files, runs ERC and DRC, and returns
    a combined report.

    Returns:
        Dict with keys: project_dir, erc, drc, schematic, pcb.
    """
    project_dir = Path(project_dir)

    # Find files
    sch_files = sorted(project_dir.rglob("*.kicad_sch"))
    pcb_files = sorted(project_dir.rglob("*.kicad_pcb"))

    # Find root schematic (match .kicad_pro stem, or first .kicad_sch)
    root_sch = None
    pro_files = list(project_dir.rglob("*.kicad_pro"))
    if pro_files:
        pro_stem = pro_files[0].stem
        for sch in sch_files:
            if sch.stem == pro_stem:
                root_sch = sch
                break
    if root_sch is None and sch_files:
        root_sch = sch_files[0]

    # Pick first PCB
    pcb = pcb_files[0] if pcb_files else None

    report = {
        "project_dir": str(project_dir),
        "schematic": str(root_sch) if root_sch else None,
        "pcb": str(pcb) if pcb else None,
        "erc": None,
        "drc": None,
    }

    if root_sch:
        report["erc"] = run_erc(root_sch)

    if pcb:
        report["drc"] = run_drc(pcb)

    return report

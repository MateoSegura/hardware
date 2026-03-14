"""Discover all independent design units (PCB designs) within a repository directory."""

from __future__ import annotations

import re
from pathlib import Path

from .models import DesignUnit


def detect_version(path: Path) -> int | None:
    """Read first 500 bytes and extract (version NNNN) token."""
    try:
        text = path.read_text(errors="replace")[:500]
    except OSError:
        return None
    match = re.search(r"\(version\s+(\d+)\)", text)
    return int(match.group(1)) if match else None


def _has_hierarchy(sch_path: Path) -> bool:
    """Check if a .kicad_sch file contains hierarchical sheet references.

    Looks for (sheet (at which indicates a placed sub-sheet symbol.
    Reads the whole file because sheet blocks can appear anywhere.
    """
    try:
        text = sch_path.read_text(errors="replace")
    except OSError:
        return False
    # Match lines with (sheet followed by (at — the placement form.
    # Avoid matching (sheet_instances or (sheet_path.
    return bool(re.search(r"\(sheet\s+\(at\s", text))


def _has_local_libs(directory: Path) -> bool:
    """Check if a directory contains sym-lib-table with ${KIPRJMOD} paths."""
    sym_lib = directory / "sym-lib-table"
    fp_lib = directory / "fp-lib-table"
    for lib_table in (sym_lib, fp_lib):
        if lib_table.is_file():
            try:
                text = lib_table.read_text(errors="replace")
            except OSError:
                continue
            if "${KIPRJMOD}" in text:
                return True
    # Also check for local .kicad_sym files or .pretty directories
    if any(directory.glob("*.kicad_sym")):
        return True
    if any(p.is_dir() for p in directory.iterdir() if p.suffix == ".pretty"):
        return True
    # Check lib/ subdirectory
    lib_dir = directory / "lib"
    if lib_dir.is_dir():
        if any(lib_dir.glob("*.kicad_sym")):
            return True
    return False


def _find_files(repo_dir: Path, suffix: str) -> list[Path]:
    """Recursively find all files with given suffix. Handles spaces in paths."""
    return sorted(repo_dir.rglob(f"*{suffix}"))


def _best_version(paths: list[Path | None]) -> int | None:
    """Get version from the first file that yields a version."""
    for p in paths:
        if p is not None and p.is_file():
            v = detect_version(p)
            if v is not None:
                return v
    return None


def discover(repo_dir: Path) -> list[DesignUnit]:
    """Discover all independent design units in a repository directory.

    Returns a list of DesignUnit objects, one per independent PCB design found.
    """
    repo_dir = repo_dir.resolve()

    pro_files = _find_files(repo_dir, ".kicad_pro")
    pcb_files = _find_files(repo_dir, ".kicad_pcb")
    sch_files = _find_files(repo_dir, ".kicad_sch")

    # Track which PCB and SCH files have been claimed by a project
    claimed_pcbs: set[Path] = set()
    claimed_schs: set[Path] = set()

    units: list[DesignUnit] = []

    # Phase 1: .kicad_pro files → each is a design unit root
    for pro in pro_files:
        stem = pro.stem
        parent = pro.parent

        # Look for matching .kicad_sch and .kicad_pcb by stem in same directory
        sch = parent / f"{stem}.kicad_sch"
        pcb = parent / f"{stem}.kicad_pcb"

        root_sch = sch if sch.is_file() else None
        pcb_file = pcb if pcb.is_file() else None

        if root_sch:
            claimed_schs.add(root_sch.resolve())
        if pcb_file:
            claimed_pcbs.add(pcb_file.resolve())

        hierarchy = _has_hierarchy(root_sch) if root_sch else False
        version = _best_version([root_sch, pcb_file])
        local_libs = _has_local_libs(parent)

        units.append(DesignUnit(
            name=stem,
            root_dir=parent,
            root_schematic=root_sch,
            pcb_file=pcb_file,
            project_file=pro,
            kicad_version=version,
            has_hierarchy=hierarchy,
            has_local_libs=local_libs,
        ))

    # Phase 2: .kicad_pcb files not matched to a .kicad_pro
    for pcb in pcb_files:
        if pcb.resolve() in claimed_pcbs:
            continue

        stem = pcb.stem
        parent = pcb.parent

        # Look for matching .kicad_sch
        sch = parent / f"{stem}.kicad_sch"
        root_sch = sch if sch.is_file() else None

        if root_sch:
            claimed_schs.add(root_sch.resolve())
        claimed_pcbs.add(pcb.resolve())

        hierarchy = _has_hierarchy(root_sch) if root_sch else False
        version = _best_version([root_sch, pcb])
        local_libs = _has_local_libs(parent)

        units.append(DesignUnit(
            name=stem,
            root_dir=parent,
            root_schematic=root_sch,
            pcb_file=pcb,
            project_file=None,
            kicad_version=version,
            has_hierarchy=hierarchy,
            has_local_libs=local_libs,
        ))

    # Phase 3: .kicad_sch files not matched (schematic-only)
    for sch in sch_files:
        if sch.resolve() in claimed_schs:
            continue
        # Skip sub-sheets: a sub-sheet is referenced by a parent that IS claimed.
        # We can't easily detect this without parsing, so we skip .kicad_sch files
        # that live in a directory that already has a claimed root schematic.
        sch_dir = sch.parent.resolve()
        if any(cs.parent == sch_dir for cs in claimed_schs):
            continue

        stem = sch.stem
        parent = sch.parent
        claimed_schs.add(sch.resolve())

        hierarchy = _has_hierarchy(sch)
        version = _best_version([sch])
        local_libs = _has_local_libs(parent)

        units.append(DesignUnit(
            name=stem,
            root_dir=parent,
            root_schematic=sch,
            pcb_file=None,
            project_file=None,
            kicad_version=version,
            has_hierarchy=hierarchy,
            has_local_libs=local_libs,
        ))

    return units

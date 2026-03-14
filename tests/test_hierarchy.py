"""Tests for the hierarchy walker module.

Uses real pilot project data in data/raw/ — no mocks.
"""

import logging
from pathlib import Path

import pytest

from src.pipeline.hierarchy import walk_hierarchy


# ---------------------------------------------------------------------------
# 1. Flat schematic — no sub-sheets
# ---------------------------------------------------------------------------

def test_walk_flat_schematic(nrfmicro_sch):
    """nrfmicro: single sheet, no sub-sheets, components > 0."""
    tree = walk_hierarchy(nrfmicro_sch)
    assert len(tree) == 1

    sheet = list(tree.values())[0]
    assert sheet.sheet_name == "root"
    assert len(sheet.components) > 0
    assert len(sheet.sub_sheet_refs) == 0
    assert sheet.parent_path is None


# ---------------------------------------------------------------------------
# 2. Depth-1 hierarchy — STM32F7 FC
# ---------------------------------------------------------------------------

def test_walk_depth_1(stm32f7_root_sch):
    """STM32F7 FC: root + 4 sub-sheets = 5 total sheets."""
    tree = walk_hierarchy(stm32f7_root_sch)
    assert len(tree) == 5

    root = tree[str(stm32f7_root_sch.resolve())]
    assert root.sheet_name == "root"
    assert len(root.sub_sheet_refs) == 4

    sub_names = {ref.sheet_name for ref in root.sub_sheet_refs}
    assert sub_names == {"Power", "MCU", "Connectors", "Sensors & Peripherals"}


# ---------------------------------------------------------------------------
# 3. Depth-1 hierarchy — HackRF
# ---------------------------------------------------------------------------

def test_walk_depth_1_hackrf(hackrf_root_sch):
    """HackRF: root + 3 sub-sheets (mcu, baseband, frontend)."""
    tree = walk_hierarchy(hackrf_root_sch)
    assert len(tree) == 4

    root = tree[str(hackrf_root_sch.resolve())]
    assert len(root.sub_sheet_refs) == 3


# ---------------------------------------------------------------------------
# 4. Depth-1 hierarchy — Antmicro Jetson
# ---------------------------------------------------------------------------

def test_walk_depth_1_antmicro(antmicro_root_sch):
    """Antmicro Jetson: root + 7 sub-sheets = 8 total sheets."""
    tree = walk_hierarchy(antmicro_root_sch)
    assert len(tree) == 8

    root = tree[str(antmicro_root_sch.resolve())]
    assert len(root.sub_sheet_refs) == 7


# ---------------------------------------------------------------------------
# 5. Depth-2 hierarchy — MNT Reform motherboard30
# ---------------------------------------------------------------------------

def test_walk_depth_2(mnt_mb30_root_sch):
    """MNT motherboard30: root -> power -> (lpc, regulators, usb-c), max depth 2."""
    tree = walk_hierarchy(mnt_mb30_root_sch)

    # root (1) + 8 depth-1 sheets + power has 3 sub-sheets + usb has 1 sub-sheet = 13
    assert len(tree) >= 12  # at least root + 8 + 3 depth-2 sheets

    # Verify depth-2 sheets exist (children of power sub-sheet)
    sheet_names = {v.sheet_name for v in tree.values()}
    assert "Reform 2 LPC" in sheet_names
    assert "Reform 2 Regulators" in sheet_names
    assert "Reform 2 USB-C" in sheet_names

    # Verify max depth is 2
    def get_depth(sheet_path_str):
        sheet = tree[sheet_path_str]
        depth = 0
        parent = sheet.parent_path
        while parent and str(parent) in tree:
            depth += 1
            parent = tree[str(parent)].parent_path
        return depth

    max_depth = max(get_depth(k) for k in tree)
    assert max_depth == 2


# ---------------------------------------------------------------------------
# 6. Component count across all sheets
# ---------------------------------------------------------------------------

def test_components_from_all_sheets(stm32f7_root_sch):
    """STM32F7 FC: total components across all sheets should be ~233."""
    tree = walk_hierarchy(stm32f7_root_sch)
    total = sum(len(sheet.components) for sheet in tree.values())
    assert total == 233


# ---------------------------------------------------------------------------
# 7. Reference designator resolution — KiCad v6
# ---------------------------------------------------------------------------

def test_ref_designator_v6(hackrf_root_sch):
    """HackRF (KiCad 6): verify ref designators are resolved (not '?')."""
    tree = walk_hierarchy(hackrf_root_sch)
    all_comps = []
    for sheet in tree.values():
        all_comps.extend(sheet.components)

    assert len(all_comps) > 0
    unresolved = [c for c in all_comps if c.ref == "?"]
    assert len(unresolved) == 0, f"{len(unresolved)} unresolved refs found"

    # Spot-check some known refs
    refs = {c.ref for c in all_comps}
    assert any(r.startswith("U") for r in refs), "Expected at least one U* ref"
    assert any(r.startswith("R") for r in refs), "Expected at least one R* ref"


# ---------------------------------------------------------------------------
# 8. Reference designator resolution — KiCad v9
# ---------------------------------------------------------------------------

def test_ref_designator_v9(antmicro_root_sch):
    """Antmicro (KiCad 9): verify ref designators are resolved (not '?')."""
    tree = walk_hierarchy(antmicro_root_sch)
    all_comps = []
    for sheet in tree.values():
        all_comps.extend(sheet.components)

    assert len(all_comps) > 0
    unresolved = [c for c in all_comps if c.ref == "?"]
    assert len(unresolved) == 0, f"{len(unresolved)} unresolved refs found"


# ---------------------------------------------------------------------------
# 9. Labels extracted across sheets
# ---------------------------------------------------------------------------

def test_labels_extracted(stm32f7_root_sch):
    """Verify global labels found across sheets."""
    tree = walk_hierarchy(stm32f7_root_sch)
    all_globals = []
    for sheet in tree.values():
        all_globals.extend(sheet.global_labels)

    assert len(all_globals) > 0
    names = {gl.name for gl in all_globals}
    assert len(names) > 10, f"Expected many unique global labels, got {len(names)}"

    # All labels should have valid type
    for gl in all_globals:
        assert gl.label_type == "global"


# ---------------------------------------------------------------------------
# 10. Filename with ampersand
# ---------------------------------------------------------------------------

def test_filename_with_ampersand(stm32f7_root_sch):
    """STM32F7 FC: verify 'Sensors & Peripherals' sheet loads correctly."""
    tree = walk_hierarchy(stm32f7_root_sch)
    sheet_names = {v.sheet_name for v in tree.values()}
    assert "Sensors & Peripherals" in sheet_names

    # Find the sheet and verify it has components
    for sheet in tree.values():
        if sheet.sheet_name == "Sensors & Peripherals":
            assert len(sheet.components) > 0
            break


# ---------------------------------------------------------------------------
# 11. Missing sub-sheet — graceful handling
# ---------------------------------------------------------------------------

def test_missing_subsheet_graceful(tmp_path, caplog):
    """If a sub-sheet file doesn't exist, warn but don't crash."""
    # Create a minimal root schematic that references a non-existent sub-sheet
    root_sch = tmp_path / "root.kicad_sch"
    root_sch.write_text("""\
(kicad_sch (version 20211123) (generator eeschema)
  (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
  (paper "A4")
  (lib_symbols)
  (sheet (at 100 100) (size 20 10)
    (uuid "11111111-2222-3333-4444-555555555555")
    (property "Sheetname" "Missing" (at 0 0 0) (effects (font (size 1 1))))
    (property "Sheetfile" "does_not_exist.kicad_sch" (at 0 0 0) (effects (font (size 1 1))))
  )
)
""")

    with caplog.at_level(logging.WARNING):
        tree = walk_hierarchy(root_sch)

    # Should not crash; root sheet should be parsed
    assert len(tree) == 1
    root = list(tree.values())[0]

    # The sub-sheet ref should exist but marked as not found
    assert len(root.sub_sheet_refs) == 1
    assert root.sub_sheet_refs[0].exists is False
    assert root.sub_sheet_refs[0].resolved_path is None

    # Warning should have been logged
    assert any("does_not_exist" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 12. Power symbol detection
# ---------------------------------------------------------------------------

def test_power_symbol_detection(stm32f7_root_sch):
    """Verify VCC/GND symbols detected as power."""
    tree = walk_hierarchy(stm32f7_root_sch)

    all_power = []
    for sheet in tree.values():
        all_power.extend(sheet.power_symbols)

    assert len(all_power) > 0

    power_values = {p.value for p in all_power}
    assert "GND" in power_values, "GND should be detected as power"
    # Check at least one voltage rail
    assert any(v.startswith("+") for v in power_values), "Expected +V power symbols"

    # All power symbols should have is_power=True
    for p in all_power:
        assert p.is_power is True

    # Power symbols should also appear in components list
    for sheet in tree.values():
        power_refs = {p.ref for p in sheet.power_symbols}
        comp_refs = {c.ref for c in sheet.components}
        assert power_refs.issubset(comp_refs)

"""End-to-end integration tests for the unified pipeline.

Parses all 10 pilot projects through the full pipeline:
discovery -> hierarchy -> board -> nets -> export.

Uses real data in data/raw/ — no mocks.
"""

import json
from pathlib import Path

import pytest

from src.pipeline.export import export_project
from src.pipeline.parse_project import parse_project, parse_single


DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

ALL_PILOTS = sorted(DATA_RAW.iterdir()) if DATA_RAW.is_dir() else []


# ---------------------------------------------------------------------------
# 1. nrfmicro — simplest: flat schematic, 2-layer board
# ---------------------------------------------------------------------------

def test_parse_nrfmicro_e2e(nrfmicro_dir):
    proj = parse_single(nrfmicro_dir)
    assert proj is not None

    assert proj.design_unit.name == "nrfmicro"
    assert proj.root_sheet is not None
    assert proj.board is not None

    # Flat schematic — 1 sheet, no hierarchy
    assert proj.stats["total_sheets"] == 1
    assert proj.stats["has_hierarchy"] is False

    # Components
    assert proj.stats["total_components"] == 48
    assert proj.stats["non_power_components"] > 0
    assert proj.stats["unique_parts"] > 0

    # Board — 2-layer
    assert proj.stats["pcb_layers"] == 2
    assert proj.stats["pcb_footprints"] > 0
    assert proj.stats["pcb_tracks"] > 0

    # Nets
    assert proj.stats["total_nets"] > 0
    assert proj.stats["power_nets"] > 0


# ---------------------------------------------------------------------------
# 2. STM32F7 FC — 4 hierarchical sheets, 233 components, 8-layer board
# ---------------------------------------------------------------------------

def test_parse_stm32f7_fc_e2e(stm32f7_fc_dir):
    proj = parse_single(stm32f7_fc_dir)
    assert proj is not None

    assert proj.design_unit.name == "Flight_Controller"
    assert proj.stats["total_sheets"] == 5
    assert proj.stats["has_hierarchy"] is True
    assert proj.stats["total_components"] == 233

    # Board
    assert proj.board is not None
    assert proj.stats["pcb_layers"] == 8

    # Nets should include power
    assert proj.stats["power_nets"] > 0
    assert proj.stats["signal_nets"] > 0


# ---------------------------------------------------------------------------
# 3. HackRF — 3 sub-sheets, KiCad 6
# ---------------------------------------------------------------------------

def test_parse_hackrf_e2e(hackrf_dir):
    projects = parse_project(hackrf_dir)
    assert len(projects) >= 1

    # Find hackrf-one (the main board)
    hackrf_one = None
    for p in projects:
        if p.design_unit.name == "hackrf-one":
            hackrf_one = p
            break
    assert hackrf_one is not None

    assert hackrf_one.stats["total_sheets"] == 4  # root + 3 sub-sheets
    assert hackrf_one.stats["has_hierarchy"] is True
    assert hackrf_one.stats["total_components"] > 700  # 742 total

    # Board should exist
    assert hackrf_one.board is not None

    # All refs resolved (v6 format)
    unresolved = [c for c in hackrf_one.all_components if c.ref == "?"]
    assert len(unresolved) == 0


# ---------------------------------------------------------------------------
# 4. Antmicro — 7 sub-sheets, KiCad 9
# ---------------------------------------------------------------------------

def test_parse_antmicro_e2e(antmicro_dir):
    proj = parse_single(antmicro_dir)
    assert proj is not None

    assert proj.stats["total_sheets"] == 8  # root + 7 sub-sheets
    assert proj.stats["has_hierarchy"] is True
    assert proj.stats["total_components"] > 500

    assert proj.board is not None
    assert proj.design_unit.kicad_version >= 20250000  # KiCad 9

    # All refs resolved (v9 format)
    unresolved = [c for c in proj.all_components if c.ref == "?"]
    assert len(unresolved) == 0


# ---------------------------------------------------------------------------
# 5. MNT Reform — multiple design units, depth-2 hierarchy
# ---------------------------------------------------------------------------

def test_parse_mnt_reform_e2e():
    projects = parse_project(DATA_RAW / "mnt__reform")
    assert len(projects) >= 10  # many sub-projects

    # Find motherboard30 (has depth-2 hierarchy)
    mb30 = None
    for p in projects:
        if p.design_unit.name == "reform2-motherboard30":
            mb30 = p
            break
    assert mb30 is not None
    assert mb30.stats["total_sheets"] >= 12  # root + 8 + 3+ depth-2
    assert mb30.stats["total_components"] > 500
    assert mb30.board is not None


# ---------------------------------------------------------------------------
# 6. VESC — PCB-only project
# ---------------------------------------------------------------------------

def test_parse_vesc_e2e(vesc_dir):
    projects = parse_project(vesc_dir)
    assert len(projects) >= 1

    vesc = projects[0]
    assert vesc.design_unit.root_schematic is None
    assert vesc.board is not None
    assert vesc.stats["total_components"] == 0  # no schematic
    assert vesc.stats["total_sheets"] == 0
    assert vesc.stats["has_pcb"] is True


# ---------------------------------------------------------------------------
# 7. All 10 pilots — no crashes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pilot_dir", ALL_PILOTS, ids=[p.name for p in ALL_PILOTS])
def test_parse_all_pilots_no_crash(pilot_dir):
    """Every pilot project should parse without raising exceptions."""
    projects = parse_project(pilot_dir)
    assert isinstance(projects, list)
    assert len(projects) >= 1

    for proj in projects:
        assert proj.design_unit is not None
        assert isinstance(proj.stats, dict)


# ---------------------------------------------------------------------------
# 8. Export all pilots — valid JSON
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pilot_dir", ALL_PILOTS, ids=[p.name for p in ALL_PILOTS])
def test_export_all_pilots_valid_json(pilot_dir):
    """Parse + export each pilot; verify valid JSON output."""
    projects = parse_project(pilot_dir)
    for proj in projects:
        json_str = export_project(proj)
        data = json.loads(json_str)  # will raise if invalid
        assert "design_unit" in data
        assert "stats" in data
        assert "all_components" in data


# ---------------------------------------------------------------------------
# 9. Stats correctness
# ---------------------------------------------------------------------------

def test_stats_correctness(stm32f7_fc_dir):
    """Verify stats.total_components matches len(all_components)."""
    proj = parse_single(stm32f7_fc_dir)
    assert proj is not None

    assert proj.stats["total_components"] == len(proj.all_components)
    assert proj.stats["non_power_components"] == len(
        [c for c in proj.all_components if not c.is_power]
    )
    assert proj.stats["power_symbols"] == len(
        [c for c in proj.all_components if c.is_power]
    )
    assert proj.stats["total_sheets"] == len(proj.sheet_tree)
    assert proj.stats["total_nets"] == len(proj.all_nets)


# ---------------------------------------------------------------------------
# 10. Power nets detected
# ---------------------------------------------------------------------------

def test_power_nets_detected(stm32f7_fc_dir):
    """Verify power nets found in projects that have them."""
    proj = parse_single(stm32f7_fc_dir)
    assert proj is not None
    assert proj.stats["power_nets"] > 0

    power_net_names = {
        name for name, info in proj.all_nets.items()
        if info.net_type == "power"
    }
    # STM32F7 FC should have common power nets
    assert any("GND" in n for n in power_net_names)
    assert any("3" in n or "5" in n or "V" in n for n in power_net_names)

    # All power nets should have scope="global"
    for name in power_net_names:
        assert proj.all_nets[name].scope == "global"

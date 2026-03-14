"""Tests for JSON export against pilot data in data/raw/."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from src.pipeline.board import parse_board
from src.pipeline.export import export_project
from src.pipeline.models import DesignUnit, ParsedProject

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

NRFMICRO_PCB = DATA_DIR / "joric__nrfmicro" / "hardware" / "nrfmicro.kicad_pcb"
NRFMICRO_DIR = DATA_DIR / "joric__nrfmicro" / "hardware"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_project() -> ParsedProject:
    board = parse_board(NRFMICRO_PCB)
    du = DesignUnit(
        name="nrfmicro",
        root_dir=NRFMICRO_DIR,
        root_schematic=NRFMICRO_DIR / "nrfmicro.kicad_sch",
        pcb_file=NRFMICRO_PCB,
        project_file=None,
        kicad_version=board.kicad_version,
        has_hierarchy=False,
        has_local_libs=False,
    )
    return ParsedProject(
        design_unit=du,
        board=board,
        stats={
            "footprint_count": len(board.footprints),
            "track_count": board.track_count,
            "via_count": board.via_count,
            "zone_count": board.zone_count,
            "layer_count": len(board.layers),
            "net_count": board.net_count,
        },
    )


# ---------------------------------------------------------------------------
# Test 11: Export produces valid JSON
# ---------------------------------------------------------------------------

def test_export_json_valid(sample_project):
    json_str = export_project(sample_project)
    data = json.loads(json_str)  # raises if invalid
    assert isinstance(data, dict)
    assert "design_unit" in data
    assert "board" in data
    assert "stats" in data


# ---------------------------------------------------------------------------
# Test 12: No Path objects in JSON output
# ---------------------------------------------------------------------------

def test_export_paths_as_strings(sample_project):
    json_str = export_project(sample_project)
    data = json.loads(json_str)

    def check_no_paths(obj, path=""):
        """Recursively verify no PosixPath/WindowsPath strings leak through."""
        if isinstance(obj, str):
            assert "PosixPath(" not in obj, f"Path object leaked at {path}: {obj}"
            assert "WindowsPath(" not in obj, f"Path object leaked at {path}: {obj}"
        elif isinstance(obj, dict):
            for k, v in obj.items():
                check_no_paths(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                check_no_paths(v, f"{path}[{i}]")

    check_no_paths(data)

    # Verify specific path fields are plain strings
    assert isinstance(data["design_unit"]["root_dir"], str)
    assert isinstance(data["board"]["file_path"], str)
    assert isinstance(data["design_unit"]["root_schematic"], str)


# ---------------------------------------------------------------------------
# Test 13: Export roundtrip — export → load → verify key fields
# ---------------------------------------------------------------------------

def test_export_roundtrip(sample_project):
    json_str = export_project(sample_project)
    data = json.loads(json_str)

    # Verify design unit fields
    assert data["design_unit"]["name"] == "nrfmicro"
    assert data["design_unit"]["has_hierarchy"] is False

    # Verify board fields match original
    board_data = data["board"]
    original = sample_project.board
    assert len(board_data["footprints"]) == len(original.footprints)
    assert board_data["track_count"] == original.track_count
    assert board_data["via_count"] == original.via_count
    assert board_data["zone_count"] == original.zone_count
    assert board_data["net_count"] == original.net_count
    assert len(board_data["layers"]) == len(original.layers)

    # Verify stats
    assert data["stats"]["footprint_count"] == len(original.footprints)
    assert data["stats"]["track_count"] == original.track_count

    # Verify footprint structure
    fp = board_data["footprints"][0]
    assert "ref" in fp
    assert "lib_id" in fp
    assert "layer" in fp
    assert "position" in fp
    assert len(fp["position"]) == 3
    assert "pad_count" in fp

    # Verify nets are serialized (int keys become strings in JSON)
    nets = board_data["nets"]
    assert isinstance(nets, dict)
    assert len(nets) > 0

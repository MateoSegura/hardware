"""Tests for board parser against pilot data in data/raw/."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from src.pipeline.board import parse_board
from src.pipeline.models import ParsedBoard

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

STM32_PCB = DATA_DIR / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"
ANTMICRO_PCB = DATA_DIR / "antmicro__jetson-nano-baseboard" / "jetson-nano-baseboard.kicad_pcb"
HACKRF_PCB = DATA_DIR / "greatscottgadgets__hackrf" / "hardware" / "hackrf-one" / "hackrf-one.kicad_pcb"
NRFMICRO_PCB = DATA_DIR / "joric__nrfmicro" / "hardware" / "nrfmicro.kicad_pcb"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def stm32_board() -> ParsedBoard:
    return parse_board(STM32_PCB)


@pytest.fixture(scope="module")
def antmicro_board() -> ParsedBoard:
    return parse_board(ANTMICRO_PCB)


@pytest.fixture(scope="module")
def hackrf_board() -> ParsedBoard:
    return parse_board(HACKRF_PCB)


@pytest.fixture(scope="module")
def nrfmicro_board() -> ParsedBoard:
    return parse_board(NRFMICRO_PCB)


# ---------------------------------------------------------------------------
# Test 1: STM32F7 board — 8 layers, 133 footprints, tracks > 1000
# ---------------------------------------------------------------------------

def test_parse_stm32f7_board(stm32_board):
    assert len(stm32_board.layers) == 8
    assert len(stm32_board.footprints) == 133
    assert stm32_board.track_count > 1000
    assert stm32_board.via_count > 0
    assert stm32_board.zone_count > 0
    assert stm32_board.net_count > 0


# ---------------------------------------------------------------------------
# Test 2: Antmicro board — KiCad 9 format
# ---------------------------------------------------------------------------

def test_parse_antmicro_board(antmicro_board):
    assert antmicro_board.kicad_version is not None
    assert antmicro_board.kicad_version >= 20241229
    assert len(antmicro_board.footprints) > 0
    assert antmicro_board.track_count > 0


# ---------------------------------------------------------------------------
# Test 3: HackRF board — footprint count > 0
# ---------------------------------------------------------------------------

def test_parse_hackrf_board(hackrf_board):
    assert len(hackrf_board.footprints) > 0
    assert len(hackrf_board.footprints) == 437
    assert hackrf_board.track_count > 0
    assert hackrf_board.via_count > 0


# ---------------------------------------------------------------------------
# Test 4: nrfmicro — simple 2-layer board
# ---------------------------------------------------------------------------

def test_parse_nrfmicro_board(nrfmicro_board):
    assert len(nrfmicro_board.layers) == 2
    layer_names = [lyr.name for lyr in nrfmicro_board.layers]
    assert "F.Cu" in layer_names
    assert "B.Cu" in layer_names
    assert len(nrfmicro_board.footprints) == 25


# ---------------------------------------------------------------------------
# Test 5: Layer types — signal/power classification
# ---------------------------------------------------------------------------

def test_layer_types(stm32_board):
    for layer in stm32_board.layers:
        assert layer.layer_type in ("signal", "power", "mixed")
    # STM32F7 has both power and mixed (signal) layers
    layer_types = {lyr.layer_type for lyr in stm32_board.layers}
    assert "power" in layer_types
    assert "mixed" in layer_types


# ---------------------------------------------------------------------------
# Test 6: Track/via separation
# ---------------------------------------------------------------------------

def test_track_via_separation(stm32_board):
    # Tracks and vias must be counted separately
    assert stm32_board.track_count == 1094
    assert stm32_board.via_count == 205
    # They should not overlap
    assert stm32_board.track_count != stm32_board.via_count


# ---------------------------------------------------------------------------
# Test 7: Footprint reference designators
# ---------------------------------------------------------------------------

def test_footprint_refs(stm32_board):
    refs = [fp.ref for fp in stm32_board.footprints]
    # Should have actual reference designators, not empty strings
    non_empty = [r for r in refs if r]
    assert len(non_empty) > 100
    # Check typical ref patterns exist
    ref_set = set(refs)
    assert any(r.startswith("C") for r in ref_set), "Expected capacitor refs"
    assert any(r.startswith("R") for r in ref_set), "Expected resistor refs"


def test_footprint_refs_antmicro(antmicro_board):
    """KiCad 9 stores Reference in fp.properties dict."""
    refs = [fp.ref for fp in antmicro_board.footprints]
    non_empty = [r for r in refs if r]
    assert len(non_empty) > 100


# ---------------------------------------------------------------------------
# Test 8: Footprint positions are numeric
# ---------------------------------------------------------------------------

def test_footprint_positions(stm32_board):
    for fp in stm32_board.footprints:
        x, y, angle = fp.position
        assert isinstance(x, (int, float))
        assert isinstance(y, (int, float))
        assert isinstance(angle, (int, float))


# ---------------------------------------------------------------------------
# Test 9: Net list maps int → str
# ---------------------------------------------------------------------------

def test_net_list(stm32_board):
    assert isinstance(stm32_board.nets, dict)
    assert len(stm32_board.nets) == stm32_board.net_count
    for num, name in stm32_board.nets.items():
        assert isinstance(num, int)
        assert isinstance(name, str)


# ---------------------------------------------------------------------------
# Test 10: Board zones
# ---------------------------------------------------------------------------

def test_board_zones(stm32_board):
    assert stm32_board.zone_count == 17


def test_board_zones_hackrf(hackrf_board):
    assert hackrf_board.zone_count == 9


def test_board_zones_nrfmicro(nrfmicro_board):
    assert nrfmicro_board.zone_count == 3

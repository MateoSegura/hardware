"""Tests for subcircuit detection against pilot data in data/raw/."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from kiutils.board import Board

from src.pipeline.subcircuits import (
    IC_PIN_THRESHOLD,
    _get_ref_from_footprint,
    _is_passive,
    cluster_subcircuits,
    detect_subcircuits,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

STM32_PCB = DATA_DIR / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"
HACKRF_PCB = DATA_DIR / "greatscottgadgets__hackrf" / "hardware" / "hackrf-one" / "hackrf-one.kicad_pcb"
NRFMICRO_PCB = DATA_DIR / "joric__nrfmicro" / "hardware" / "nrfmicro.kicad_pcb"
ANTMICRO_PCB = DATA_DIR / "antmicro__jetson-nano-baseboard" / "jetson-nano-baseboard.kicad_pcb"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def stm32_subcircuits():
    return detect_subcircuits(STM32_PCB)


@pytest.fixture(scope="module")
def stm32_clusters(stm32_subcircuits):
    return cluster_subcircuits(stm32_subcircuits)


@pytest.fixture(scope="module")
def hackrf_subcircuits():
    return detect_subcircuits(HACKRF_PCB)


@pytest.fixture(scope="module")
def nrfmicro_subcircuits():
    return detect_subcircuits(NRFMICRO_PCB)


# ---------------------------------------------------------------------------
# Test 1: Detect subcircuits in STM32F7 FC
# ---------------------------------------------------------------------------

def test_detect_subcircuits_stm32f7(stm32_subcircuits):
    """STM32F7 FC should have subcircuits around the MCU, barometer, etc."""
    assert len(stm32_subcircuits) > 0

    centers = {sc.center_ref for sc in stm32_subcircuits}
    # U8 is the STM32F722 MCU (LQFP-64)
    assert "U8" in centers, f"MCU U8 not detected as subcircuit center. Got: {centers}"
    # U3 is BMP388 barometer
    assert "U3" in centers, f"Barometer U3 not detected. Got: {centers}"


# ---------------------------------------------------------------------------
# Test 2: Decoupling caps grouped with MCU
# ---------------------------------------------------------------------------

def test_decoupling_caps_grouped(stm32_subcircuits):
    """Caps connected to MCU power pins should be in the MCU's subcircuit."""
    mcu_sc = None
    for sc in stm32_subcircuits:
        if sc.center_ref == "U8":
            mcu_sc = sc
            break

    assert mcu_sc is not None, "MCU subcircuit not found"
    # MCU should have several supporting passives including capacitors
    assert len(mcu_sc.supporting_components) > 5
    cap_refs = [r for r in mcu_sc.supporting_components if r.startswith("C")]
    assert len(cap_refs) > 0, "No capacitors found in MCU subcircuit"


# ---------------------------------------------------------------------------
# Test 3: Passive-only components are NOT subcircuit centers
# ---------------------------------------------------------------------------

def test_passive_only_not_a_subcircuit(stm32_subcircuits):
    """A standalone passive (R, C, L) should never be a subcircuit center."""
    for sc in stm32_subcircuits:
        assert not sc.center_ref.startswith("R"), f"Resistor {sc.center_ref} is a center"
        assert not sc.center_ref.startswith("C"), f"Capacitor {sc.center_ref} is a center"
        assert not sc.center_ref.startswith("L"), f"Inductor {sc.center_ref} is a center"
        assert not sc.center_ref.startswith("FB"), f"Ferrite bead {sc.center_ref} is a center"


# ---------------------------------------------------------------------------
# Test 4: Fingerprint determinism
# ---------------------------------------------------------------------------

def test_fingerprint_deterministic():
    """Same subcircuit parsed twice should produce the same fingerprint."""
    scs1 = detect_subcircuits(STM32_PCB)
    scs2 = detect_subcircuits(STM32_PCB)

    fps1 = {sc.center_ref: sc.fingerprint for sc in scs1}
    fps2 = {sc.center_ref: sc.fingerprint for sc in scs2}
    assert fps1 == fps2


# ---------------------------------------------------------------------------
# Test 5: Clustering — identical topologies cluster together
# ---------------------------------------------------------------------------

def test_clustering(stm32_clusters):
    """Two TPS54335 LDOs (U6, U7) with same topology should cluster together."""
    # Find the cluster that contains U6 and U7
    ldo_cluster = None
    for cl in stm32_clusters:
        instance_refs = {inst.center_ref for inst in cl.instances}
        if "U6" in instance_refs and "U7" in instance_refs:
            ldo_cluster = cl
            break

    assert ldo_cluster is not None, (
        f"U6 and U7 should be in the same cluster. "
        f"Clusters: {[(cl.fingerprint[:8], [i.center_ref for i in cl.instances]) for cl in stm32_clusters]}"
    )
    assert ldo_cluster.count == 2


# ---------------------------------------------------------------------------
# Test 6: Every subcircuit center has pin_count > threshold
# ---------------------------------------------------------------------------

def test_subcircuit_has_center_ic(stm32_subcircuits):
    """Every subcircuit must have a center component with pad_count > IC_PIN_THRESHOLD."""
    board = Board.from_file(str(STM32_PCB))

    fp_pad_counts = {}
    for fp in board.footprints:
        ref = _get_ref_from_footprint(fp)
        if ref:
            fp_pad_counts[ref] = len(fp.pads)

    for sc in stm32_subcircuits:
        pad_count = fp_pad_counts.get(sc.center_ref, 0)
        assert pad_count > IC_PIN_THRESHOLD, (
            f"Center {sc.center_ref} has only {pad_count} pads "
            f"(threshold is {IC_PIN_THRESHOLD})"
        )


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------

def test_hackrf_subcircuits_detected(hackrf_subcircuits):
    """HackRF should detect subcircuits even with custom lib_ids."""
    assert len(hackrf_subcircuits) > 0
    # U23 is the LPC4320 MCU (LQFP-144)
    centers = {sc.center_ref for sc in hackrf_subcircuits}
    assert "U23" in centers, f"LPC4320 MCU not detected. Got: {centers}"


def test_hackrf_rf_switches_cluster(hackrf_subcircuits):
    """HackRF RF switches (U12, U14) should cluster together."""
    clusters = cluster_subcircuits(hackrf_subcircuits)
    for cl in clusters:
        refs = {inst.center_ref for inst in cl.instances}
        if "U12" in refs and "U14" in refs:
            assert cl.count >= 2
            return
    pytest.fail("RF switches U12 and U14 should cluster together")


def test_nrfmicro_subcircuits(nrfmicro_subcircuits):
    """nrfmicro should detect subcircuits around the nRF52840 module."""
    assert len(nrfmicro_subcircuits) > 0
    centers = {sc.center_ref for sc in nrfmicro_subcircuits}
    assert "U1" in centers, f"nRF52840 module not detected. Got: {centers}"


def test_subcircuit_has_fingerprint(stm32_subcircuits):
    """Every subcircuit should have a non-empty fingerprint."""
    for sc in stm32_subcircuits:
        assert sc.fingerprint, f"Subcircuit {sc.center_ref} has no fingerprint"
        assert len(sc.fingerprint) == 16, f"Fingerprint should be 16 hex chars"


def test_subcircuit_has_supporting_components(stm32_subcircuits):
    """Every subcircuit should have at least one supporting component."""
    for sc in stm32_subcircuits:
        assert len(sc.supporting_components) > 0, (
            f"Subcircuit {sc.center_ref} has no supporting components"
        )


def test_cluster_canonical_components(stm32_clusters):
    """Each cluster should have a non-empty canonical_components list."""
    for cl in stm32_clusters:
        assert len(cl.canonical_components) > 0
        # First entry should be the center IC's lib_id
        assert cl.canonical_components[0] != ""

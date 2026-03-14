"""Tests for KiCad project discovery against pilot data in data/raw/."""

from pathlib import Path

import pytest

from src.pipeline.discovery import detect_version, discover

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _names(units):
    return {u.name for u in units}


def _find_unit(units, name):
    matches = [u for u in units if u.name == name]
    assert matches, f"No unit named '{name}' found. Got: {_names(units)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mnt_units():
    return discover(DATA_DIR / "mnt__reform")


@pytest.fixture(scope="module")
def hackrf_units():
    return discover(DATA_DIR / "greatscottgadgets__hackrf")


@pytest.fixture(scope="module")
def nrfmicro_units():
    return discover(DATA_DIR / "joric__nrfmicro")


@pytest.fixture(scope="module")
def vesc_units():
    return discover(DATA_DIR / "vedderb__bldc-hardware")


@pytest.fixture(scope="module")
def tokay_units():
    return discover(DATA_DIR / "maxlab-io__tokay-lite-pcb")


@pytest.fixture(scope="module")
def cicada_units():
    return discover(DATA_DIR / "enaccess__cicada-gsm-hw")


@pytest.fixture(scope="module")
def stm32_units():
    return discover(DATA_DIR / "rishikesh2715__stm32f7-fc")


@pytest.fixture(scope="module")
def antmicro_units():
    return discover(DATA_DIR / "antmicro__jetson-nano-baseboard")


@pytest.fixture(scope="module")
def crazyflie_units():
    return discover(DATA_DIR / "bitcraze__crazyflie-electronics")


@pytest.fixture(scope="module")
def libresolar_units():
    return discover(DATA_DIR / "libresolar__mppt-2420-lc")


# ---------------------------------------------------------------------------
# 1. test_discover_mnt_reform — Must find multiple design units (18 sub-projects)
# ---------------------------------------------------------------------------

class TestDiscoverMntReform:
    def test_finds_multiple_units(self, mnt_units):
        # MNT Reform has at least 18 independent sub-projects
        assert len(mnt_units) >= 15, (
            f"Expected >=15 design units in MNT Reform, got {len(mnt_units)}: {_names(mnt_units)}"
        )

    def test_finds_motherboard_variants(self, mnt_units):
        names = _names(mnt_units)
        assert "reform2-motherboard25" in names or "reform2-motherboard25-pcb" in names \
               or any("motherboard25" in n for n in names)
        assert "reform2-motherboard30" in names or "reform2-motherboard30-pcb" in names \
               or any("motherboard30" in n for n in names)

    def test_finds_keyboard_variants(self, mnt_units):
        names = _names(mnt_units)
        keyboard_names = [n for n in names if "keyboard" in n.lower()]
        assert len(keyboard_names) >= 2, f"Expected >=2 keyboard boards, got {keyboard_names}"

    def test_batterypack_two_pcbs(self, mnt_units):
        # reform2-batterypack-pcb/ has TWO PCBs (upstream + regular)
        batt_units = [u for u in mnt_units if "batterypack" in u.name.lower()
                      and u.pcb_file is not None]
        pcb_names = {u.pcb_file.name for u in batt_units}
        assert len(pcb_names) >= 2, f"Expected >=2 batterypack PCBs, got {pcb_names}"


# ---------------------------------------------------------------------------
# 2. test_discover_hackrf — Must find multiple boards in hardware/ subdirs
# ---------------------------------------------------------------------------

class TestDiscoverHackrf:
    def test_finds_multiple_boards(self, hackrf_units):
        assert len(hackrf_units) >= 4, (
            f"Expected >=4 boards in HackRF, got {len(hackrf_units)}: {_names(hackrf_units)}"
        )

    def test_finds_hackrf_one(self, hackrf_units):
        unit = _find_unit(hackrf_units, "hackrf-one")
        assert unit.project_file is not None
        assert unit.root_schematic is not None
        assert unit.pcb_file is not None

    def test_finds_pcb_only_boards(self, hackrf_units):
        pcb_only = [u for u in hackrf_units if u.root_schematic is None and u.pcb_file is not None]
        assert len(pcb_only) >= 3, (
            f"Expected >=3 PCB-only boards in HackRF, got {len(pcb_only)}"
        )


# ---------------------------------------------------------------------------
# 3. test_discover_single_project — joric/nrfmicro should find exactly 1
# ---------------------------------------------------------------------------

class TestDiscoverSingleProject:
    def test_finds_one_unit(self, nrfmicro_units):
        assert len(nrfmicro_units) == 1

    def test_has_all_files(self, nrfmicro_units):
        unit = nrfmicro_units[0]
        assert unit.name == "nrfmicro"
        assert unit.project_file is not None
        assert unit.root_schematic is not None
        assert unit.pcb_file is not None


# ---------------------------------------------------------------------------
# 4. test_discover_pcb_only — VESC has PCB but no schematic
# ---------------------------------------------------------------------------

class TestDiscoverPcbOnly:
    def test_finds_pcb_only(self, vesc_units):
        assert len(vesc_units) >= 1
        unit = vesc_units[0]
        assert unit.pcb_file is not None
        assert unit.root_schematic is None

    def test_pcb_only_name(self, vesc_units):
        unit = vesc_units[0]
        assert "BLDC" in unit.name or "bldc" in unit.name.lower()


# ---------------------------------------------------------------------------
# 5. test_discover_no_kicad_pro — VESC, LibreSolar, Crazyflie have no .kicad_pro
# ---------------------------------------------------------------------------

class TestDiscoverNoKicadPro:
    def test_vesc_no_pro(self, vesc_units):
        for unit in vesc_units:
            assert unit.project_file is None

    def test_libresolar_no_pro(self, libresolar_units):
        for unit in libresolar_units:
            assert unit.project_file is None

    def test_crazyflie_no_pro(self, crazyflie_units):
        for unit in crazyflie_units:
            assert unit.project_file is None

    def test_crazyflie_finds_pcb(self, crazyflie_units):
        assert len(crazyflie_units) >= 1
        unit = crazyflie_units[0]
        assert unit.pcb_file is not None
        # Filename has spaces — verify it resolved correctly
        assert unit.pcb_file.exists()


# ---------------------------------------------------------------------------
# 6. test_discover_multi_revision — maxlab/tokay-lite has 6 revisions
# ---------------------------------------------------------------------------

class TestDiscoverMultiRevision:
    def test_finds_all_revisions(self, tokay_units):
        assert len(tokay_units) >= 6, (
            f"Expected >=6 revisions in Tokay, got {len(tokay_units)}: {_names(tokay_units)}"
        )

    def test_each_has_pcb_and_sch(self, tokay_units):
        for unit in tokay_units:
            assert unit.pcb_file is not None, f"{unit.name} missing PCB"
            assert unit.root_schematic is not None, f"{unit.name} missing schematic"
            assert unit.project_file is not None, f"{unit.name} missing .kicad_pro"


# ---------------------------------------------------------------------------
# 7. test_discover_deep_nesting — enaccess/cicada has files 5 dirs deep
# ---------------------------------------------------------------------------

class TestDiscoverDeepNesting:
    def test_finds_both_subprojects(self, cicada_units):
        assert len(cicada_units) >= 2, (
            f"Expected >=2 sub-projects in Cicada, got {len(cicada_units)}: {_names(cicada_units)}"
        )

    def test_deep_paths_resolve(self, cicada_units):
        for unit in cicada_units:
            if unit.pcb_file:
                assert unit.pcb_file.exists(), f"PCB file not found: {unit.pcb_file}"
            if unit.root_schematic:
                assert unit.root_schematic.exists(), f"SCH file not found: {unit.root_schematic}"

    def test_handles_spaces_in_filenames(self, cicada_units):
        # Filenames contain "P-1000010_Okra Cicada 2G PCBA"
        for unit in cicada_units:
            if unit.pcb_file:
                assert unit.pcb_file.exists()


# ---------------------------------------------------------------------------
# 8. test_hierarchy_detection — hierarchical projects detected
# ---------------------------------------------------------------------------

class TestHierarchyDetection:
    def test_stm32_has_hierarchy(self, stm32_units):
        unit = _find_unit(stm32_units, "Flight_Controller")
        assert unit.has_hierarchy is True

    def test_hackrf_one_has_hierarchy(self, hackrf_units):
        unit = _find_unit(hackrf_units, "hackrf-one")
        assert unit.has_hierarchy is True

    def test_antmicro_has_hierarchy(self, antmicro_units):
        unit = antmicro_units[0]
        assert unit.has_hierarchy is True

    def test_mnt_motherboard25_has_hierarchy(self, mnt_units):
        mb25 = [u for u in mnt_units if "motherboard25" in u.name]
        assert mb25, "motherboard25 unit not found"
        assert mb25[0].has_hierarchy is True

    def test_mnt_motherboard30_has_hierarchy(self, mnt_units):
        mb30 = [u for u in mnt_units if "motherboard30" in u.name]
        assert mb30, "motherboard30 unit not found"
        assert mb30[0].has_hierarchy is True


# ---------------------------------------------------------------------------
# 9. test_flat_detection — nrfmicro should show has_hierarchy=False
# ---------------------------------------------------------------------------

class TestFlatDetection:
    def test_nrfmicro_no_hierarchy(self, nrfmicro_units):
        unit = nrfmicro_units[0]
        assert unit.has_hierarchy is False

    def test_pcb_only_no_hierarchy(self, vesc_units):
        for unit in vesc_units:
            assert unit.has_hierarchy is False


# ---------------------------------------------------------------------------
# 10. test_version_detection — verify KiCad version detection
# ---------------------------------------------------------------------------

class TestVersionDetection:
    def test_antmicro_kicad9(self, antmicro_units):
        unit = antmicro_units[0]
        assert unit.kicad_version is not None
        assert unit.kicad_version >= 20241229, (
            f"Expected KiCad 9 version (>=20241229), got {unit.kicad_version}"
        )

    def test_hackrf_one_kicad6(self, hackrf_units):
        unit = _find_unit(hackrf_units, "hackrf-one")
        assert unit.kicad_version is not None
        assert 20211000 <= unit.kicad_version <= 20211231, (
            f"Expected KiCad 6 version, got {unit.kicad_version}"
        )

    def test_nrfmicro_kicad6(self, nrfmicro_units):
        unit = nrfmicro_units[0]
        assert unit.kicad_version is not None
        assert 20211000 <= unit.kicad_version <= 20211231

    def test_vesc_kicad4(self, vesc_units):
        unit = vesc_units[0]
        assert unit.kicad_version is not None
        assert unit.kicad_version == 4

    def test_crazyflie_kicad3(self, crazyflie_units):
        unit = crazyflie_units[0]
        assert unit.kicad_version is not None
        assert unit.kicad_version == 3

    def test_detect_version_function(self):
        # Test directly against known files
        antmicro_sch = DATA_DIR / "antmicro__jetson-nano-baseboard" / "jetson-nano-baseboard.kicad_sch"
        if antmicro_sch.exists():
            v = detect_version(antmicro_sch)
            assert v == 20250114

        hackrf_pcb = DATA_DIR / "greatscottgadgets__hackrf" / "hardware" / "hackrf-one" / "hackrf-one.kicad_pcb"
        if hackrf_pcb.exists():
            v = detect_version(hackrf_pcb)
            assert v == 20211014

        crazyflie_pcb = DATA_DIR / "bitcraze__crazyflie-electronics" / "ecad" / "Crazyflie contol board.kicad_pcb"
        if crazyflie_pcb.exists():
            v = detect_version(crazyflie_pcb)
            assert v == 3

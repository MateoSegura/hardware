"""Fixtures for kiutils test suite.

Provides paths to pilot project data in ~/hardware/data/raw/.
All paths are absolute and resolved from this file's location.
"""

import sys
from pathlib import Path

import pytest

# Ensure vendored kiutils is importable
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# Root of all pilot project data
DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


# ---------------------------------------------------------------------------
# Pilot project directory fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def data_raw() -> Path:
    """Root directory containing all pilot projects."""
    return DATA_RAW


@pytest.fixture
def nrfmicro_dir() -> Path:
    """joric/nrfmicro — flat KiCad 6 schematic."""
    return DATA_RAW / "joric__nrfmicro"


@pytest.fixture
def stm32f7_fc_dir() -> Path:
    """rishikesh2715/stm32f7-fc — hierarchical KiCad 6, 4 sub-sheets, 8-layer PCB."""
    return DATA_RAW / "rishikesh2715__stm32f7-fc"


@pytest.fixture
def antmicro_dir() -> Path:
    """antmicro/jetson-nano-baseboard — KiCad 9, hierarchical."""
    return DATA_RAW / "antmicro__jetson-nano-baseboard"


@pytest.fixture
def hackrf_dir() -> Path:
    """greatscottgadgets/hackrf — KiCad 6, hierarchical, v6 symbolInstances format."""
    return DATA_RAW / "greatscottgadgets__hackrf"


@pytest.fixture
def mnt_dir() -> Path:
    """mnt/reform — large multi-project repo with depth-2 hierarchy."""
    return DATA_RAW / "mnt__reform"


@pytest.fixture
def vesc_dir() -> Path:
    """vedderb/bldc-hardware — legacy KiCad 4 PCB-only."""
    return DATA_RAW / "vedderb__bldc-hardware"


# ---------------------------------------------------------------------------
# Specific file path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def nrfmicro_sch(nrfmicro_dir) -> Path:
    """Path to joric/nrfmicro flat schematic."""
    return nrfmicro_dir / "hardware" / "nrfmicro.kicad_sch"


@pytest.fixture
def stm32f7_root_sch(stm32f7_fc_dir) -> Path:
    """Path to STM32F7 FC root schematic."""
    return stm32f7_fc_dir / "Flight_Controller.kicad_sch"


@pytest.fixture
def stm32f7_power_sch(stm32f7_fc_dir) -> Path:
    """Path to STM32F7 FC Power sub-sheet."""
    return stm32f7_fc_dir / "FC_Power.kicad_sch"


@pytest.fixture
def stm32f7_pcb(stm32f7_fc_dir) -> Path:
    """Path to STM32F7 FC PCB board file."""
    return stm32f7_fc_dir / "Flight_Controller.kicad_pcb"


@pytest.fixture
def antmicro_root_sch(antmicro_dir) -> Path:
    """Path to Antmicro Jetson baseboard root schematic (KiCad 9)."""
    return antmicro_dir / "jetson-nano-baseboard.kicad_sch"


@pytest.fixture
def hackrf_root_sch(hackrf_dir) -> Path:
    """Path to HackRF One root schematic (KiCad 6)."""
    return hackrf_dir / "hardware" / "hackrf-one" / "hackrf-one.kicad_sch"


@pytest.fixture
def mnt_mb30_root_sch(mnt_dir) -> Path:
    """Path to MNT Reform motherboard30 root schematic (depth-2 hierarchy)."""
    return mnt_dir / "reform2-motherboard30-pcb" / "reform2-motherboard30.kicad_sch"


@pytest.fixture
def vesc_pcb(vesc_dir) -> Path:
    """Path to VESC BLDC 4 PCB (legacy KiCad 4)."""
    return vesc_dir / "design" / "BLDC_4.kicad_pcb"

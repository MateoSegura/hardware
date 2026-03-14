"""Round-trip validation tests.

Validates that our pipeline parser sees the same components as kicad-cli's
netlist export. For each pilot project:
  1. Parse with our hierarchy walker
  2. Export netlist with kicad-cli
  3. Compare component sets
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from src.pipeline.roundtrip import (
    parse_kicad_netlist_xml,
    validate_roundtrip,
)

KICAD_CLI = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"
HAS_KICAD_CLI = Path(KICAD_CLI).is_file()

skip_no_kicad = pytest.mark.skipif(
    not HAS_KICAD_CLI, reason="kicad-cli not available"
)


# ---------------------------------------------------------------------------
# Unit tests for netlist XML parsing
# ---------------------------------------------------------------------------


class TestParseNetlistXML:
    """Test the XML netlist parser in isolation."""

    def test_parse_nrfmicro_netlist(self, nrfmicro_sch, tmp_path):
        """Parse a kicad-cli XML netlist and extract components."""
        if not HAS_KICAD_CLI:
            pytest.skip("kicad-cli not available")

        out = tmp_path / "netlist.xml"
        subprocess.run(
            [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
             str(nrfmicro_sch), "-o", str(out)],
            check=True, capture_output=True,
        )

        result = parse_kicad_netlist_xml(out)

        assert "components" in result
        assert "nets" in result
        assert len(result["components"]) > 0
        # nrfmicro has known components: U1 (nRF52840), U4 (ATmega32U4), etc.
        refs = {c["ref"] for c in result["components"]}
        assert "U1" in refs
        assert "U4" in refs

    def test_parse_netlist_component_fields(self, nrfmicro_sch, tmp_path):
        """Each parsed component has ref, value, and footprint."""
        if not HAS_KICAD_CLI:
            pytest.skip("kicad-cli not available")

        out = tmp_path / "netlist.xml"
        subprocess.run(
            [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
             str(nrfmicro_sch), "-o", str(out)],
            check=True, capture_output=True,
        )

        result = parse_kicad_netlist_xml(out)
        for comp in result["components"]:
            assert "ref" in comp
            assert "value" in comp
            assert "footprint" in comp

    def test_parse_netlist_nets_have_nodes(self, nrfmicro_sch, tmp_path):
        """Each net has a name and at least one node."""
        if not HAS_KICAD_CLI:
            pytest.skip("kicad-cli not available")

        out = tmp_path / "netlist.xml"
        subprocess.run(
            [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
             str(nrfmicro_sch), "-o", str(out)],
            check=True, capture_output=True,
        )

        result = parse_kicad_netlist_xml(out)
        assert len(result["nets"]) > 0
        for net in result["nets"]:
            assert "name" in net
            assert "nodes" in net
            assert len(net["nodes"]) >= 1


# ---------------------------------------------------------------------------
# Round-trip validation on real pilot projects
# ---------------------------------------------------------------------------


class TestRoundtripNrfmicro:
    """Flat KiCad 6 project: joric/nrfmicro."""

    @skip_no_kicad
    def test_roundtrip_succeeds(self, nrfmicro_sch, tmp_path):
        result = validate_roundtrip(nrfmicro_sch, tmp_path)
        assert result["success"] is True
        assert result["our_components"] > 0
        assert result["netlist_components"] > 0
        assert result["matched"] > 0

    @skip_no_kicad
    def test_no_mismatched_components(self, nrfmicro_sch, tmp_path):
        result = validate_roundtrip(nrfmicro_sch, tmp_path)
        assert len(result["mismatched"]) == 0, (
            f"Mismatched components: {result['mismatched']}"
        )

    @skip_no_kicad
    def test_component_count_matches(self, nrfmicro_sch, tmp_path):
        result = validate_roundtrip(nrfmicro_sch, tmp_path)
        assert result["our_components"] == result["netlist_components"], (
            f"Our parser found {result['our_components']} components, "
            f"kicad-cli found {result['netlist_components']}"
        )


class TestRoundtripSTM32F7:
    """Hierarchical KiCad 6 project: rishikesh2715/stm32f7-fc."""

    @skip_no_kicad
    def test_roundtrip_succeeds(self, stm32f7_root_sch, tmp_path):
        result = validate_roundtrip(stm32f7_root_sch, tmp_path)
        assert result["success"] is True
        assert result["our_components"] > 0
        assert result["netlist_components"] > 0

    @skip_no_kicad
    def test_hierarchical_components_found(self, stm32f7_root_sch, tmp_path):
        result = validate_roundtrip(stm32f7_root_sch, tmp_path)
        # STM32F7 FC has 131 components across 5 sheets
        assert result["netlist_components"] > 50
        assert result["matched"] > 50

    @skip_no_kicad
    def test_no_mismatched_components(self, stm32f7_root_sch, tmp_path):
        result = validate_roundtrip(stm32f7_root_sch, tmp_path)
        assert len(result["mismatched"]) == 0, (
            f"Mismatched components: {result['mismatched']}"
        )


class TestRoundtripKicad9:
    """KiCad 9 project: imchipwood/dumbpad."""

    @pytest.fixture
    def dumbpad_sch(self, data_raw) -> Path:
        return data_raw / "imchipwood__dumbpad" / "combo_low_profile_oled" / "dumbpad.kicad_sch"

    @skip_no_kicad
    def test_roundtrip_succeeds(self, dumbpad_sch, tmp_path):
        result = validate_roundtrip(dumbpad_sch, tmp_path)
        assert result["success"] is True
        assert result["our_components"] > 0
        assert result["netlist_components"] > 0

    @skip_no_kicad
    def test_no_mismatched_components(self, dumbpad_sch, tmp_path):
        result = validate_roundtrip(dumbpad_sch, tmp_path)
        assert len(result["mismatched"]) == 0, (
            f"Mismatched components: {result['mismatched']}"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestRoundtripEdgeCases:
    """Edge case handling."""

    def test_nonexistent_file(self, tmp_path):
        result = validate_roundtrip(tmp_path / "nonexistent.kicad_sch", tmp_path)
        assert result["success"] is False
        assert "error" in result

    @skip_no_kicad
    def test_result_structure(self, nrfmicro_sch, tmp_path):
        """Validate the return dict has all required keys."""
        result = validate_roundtrip(nrfmicro_sch, tmp_path)
        required_keys = {"success", "our_components", "netlist_components",
                         "matched", "mismatched"}
        assert required_keys.issubset(result.keys())

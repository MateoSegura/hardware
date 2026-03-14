"""Tests for net connectivity tracing across schematic hierarchy."""

from pathlib import Path

import pytest

from src.pipeline.models import (
    LabelInfo,
    ParsedComponent,
    ParsedSheet,
    SheetPinInfo,
    SubSheetRef,
)
from src.pipeline.nets import trace_nets, _is_power_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sheet(
    name: str,
    path: str = "/fake",
    *,
    global_labels: list[LabelInfo] | None = None,
    local_labels: list[LabelInfo] | None = None,
    hierarchical_labels: list[LabelInfo] | None = None,
    sub_sheet_refs: list[SubSheetRef] | None = None,
    power_symbols: list[ParsedComponent] | None = None,
    parent_path: Path | None = None,
) -> ParsedSheet:
    return ParsedSheet(
        file_path=Path(path),
        sheet_name=name,
        sheet_uuid="uuid-" + name,
        parent_path=parent_path,
        kicad_version=20211123,
        global_labels=global_labels or [],
        local_labels=local_labels or [],
        hierarchical_labels=hierarchical_labels or [],
        sub_sheet_refs=sub_sheet_refs or [],
        power_symbols=power_symbols or [],
    )


def _make_label(name: str, label_type: str = "global", shape: str = "bidirectional") -> LabelInfo:
    return LabelInfo(name=name, label_type=label_type, shape=shape)


def _make_power(value: str) -> ParsedComponent:
    return ParsedComponent(
        ref="#PWR01",
        lib_id=f"power:{value}",
        value=value,
        footprint="",
        mpn="",
        sheet_path="/",
        sheet_name="root",
        unit=1,
        pin_count=1,
        is_power=True,
        is_in_bom=False,
        is_on_board=False,
        dnp=False,
    )


def _make_sub_ref(
    sheet_name: str,
    file_name: str,
    pins: list[tuple[str, str]] | None = None,
    resolved_path: Path | None = None,
) -> SubSheetRef:
    pin_list = [SheetPinInfo(name=n, direction=d) for n, d in (pins or [])]
    return SubSheetRef(
        sheet_name=sheet_name,
        file_name=file_name,
        resolved_path=resolved_path,
        uuid="uuid-ref-" + sheet_name,
        pins=pin_list,
    )


def _build_tree(*sheets: ParsedSheet) -> dict[str, ParsedSheet]:
    return {str(s.file_path): s for s in sheets}


# ---------------------------------------------------------------------------
# 1. test_global_labels_same_net
# ---------------------------------------------------------------------------

class TestGlobalLabelsSameNet:
    def test_same_global_label_on_two_sheets_is_one_net(self):
        sheet_a = _make_sheet(
            "Sheet A", "/a.kicad_sch",
            global_labels=[_make_label("SPI_CLK")],
        )
        sheet_b = _make_sheet(
            "Sheet B", "/b.kicad_sch",
            global_labels=[_make_label("SPI_CLK")],
        )
        nets = trace_nets(_build_tree(sheet_a, sheet_b))

        assert "SPI_CLK" in nets
        assert sorted(nets["SPI_CLK"].sheets) == ["Sheet A", "Sheet B"]

    def test_different_global_labels_are_different_nets(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            global_labels=[_make_label("SPI_CLK"), _make_label("SPI_MOSI")],
        )
        nets = trace_nets(_build_tree(sheet))

        assert "SPI_CLK" in nets
        assert "SPI_MOSI" in nets
        assert nets["SPI_CLK"].name != nets["SPI_MOSI"].name


# ---------------------------------------------------------------------------
# 2. test_power_symbols_as_global_nets
# ---------------------------------------------------------------------------

class TestPowerSymbolsAsGlobalNets:
    def test_vcc_creates_global_power_net(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            power_symbols=[_make_power("VCC")],
        )
        nets = trace_nets(_build_tree(sheet))

        assert "VCC" in nets
        assert nets["VCC"].net_type == "power"
        assert nets["VCC"].scope == "global"

    def test_power_on_multiple_sheets_is_one_net(self):
        sheet_a = _make_sheet(
            "Sheet A", "/a.kicad_sch",
            power_symbols=[_make_power("+3V3")],
        )
        sheet_b = _make_sheet(
            "Sheet B", "/b.kicad_sch",
            power_symbols=[_make_power("+3V3")],
        )
        nets = trace_nets(_build_tree(sheet_a, sheet_b))

        assert "+3V3" in nets
        assert nets["+3V3"].net_type == "power"
        assert nets["+3V3"].scope == "global"
        assert sorted(nets["+3V3"].sheets) == ["Sheet A", "Sheet B"]

    def test_gnd_is_power(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            power_symbols=[_make_power("GND")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["GND"].net_type == "power"


# ---------------------------------------------------------------------------
# 3. test_hierarchical_connection
# ---------------------------------------------------------------------------

class TestHierarchicalConnection:
    def test_parent_pin_connects_to_child_hlabel(self):
        child_path = Path("/child.kicad_sch")
        parent = _make_sheet(
            "Parent", "/parent.kicad_sch",
            sub_sheet_refs=[
                _make_sub_ref(
                    "ChildSheet", "child.kicad_sch",
                    pins=[("DATA", "bidirectional")],
                    resolved_path=child_path,
                ),
            ],
        )
        child = _make_sheet(
            "ChildSheet", str(child_path),
            hierarchical_labels=[_make_label("DATA", "hierarchical")],
            parent_path=Path("/parent.kicad_sch"),
        )
        nets = trace_nets(_build_tree(parent, child))

        assert "DATA" in nets
        assert "Parent" in nets["DATA"].sheets
        assert "ChildSheet" in nets["DATA"].sheets
        assert nets["DATA"].scope == "hierarchical"

    def test_unmatched_pin_no_crash(self):
        """Pin with no matching hierarchical label in child should not crash."""
        child_path = Path("/child.kicad_sch")
        parent = _make_sheet(
            "Parent", "/parent.kicad_sch",
            sub_sheet_refs=[
                _make_sub_ref(
                    "ChildSheet", "child.kicad_sch",
                    pins=[("MISSING_SIGNAL", "input")],
                    resolved_path=child_path,
                ),
            ],
        )
        child = _make_sheet(
            "ChildSheet", str(child_path),
            hierarchical_labels=[],
            parent_path=Path("/parent.kicad_sch"),
        )
        # Should not raise
        nets = trace_nets(_build_tree(parent, child))
        # The pin was added to parent sheet but no match in child
        # Still creates a net entry for parent side
        assert "MISSING_SIGNAL" not in nets or "ChildSheet" not in nets["MISSING_SIGNAL"].sheets

    def test_missing_child_sheet_no_crash(self):
        """SubSheetRef pointing to non-existent sheet should not crash."""
        parent = _make_sheet(
            "Parent", "/parent.kicad_sch",
            sub_sheet_refs=[
                _make_sub_ref(
                    "Ghost", "ghost.kicad_sch",
                    pins=[("SIG", "output")],
                    resolved_path=Path("/ghost.kicad_sch"),
                ),
            ],
        )
        # ghost sheet not in tree
        nets = trace_nets(_build_tree(parent))
        # Should not crash — just no connection resolved


# ---------------------------------------------------------------------------
# 4. test_power_net_classification
# ---------------------------------------------------------------------------

class TestPowerNetClassification:
    @pytest.mark.parametrize("name", [
        "VCC", "VDD", "VSS", "VEE",
        "GND", "AGND", "DGND", "PGND", "GNDREF",
        "+3V3", "+5V", "+12V", "-12V", "+1V8",
        "VBAT", "VBUS", "VIN", "VOUT", "VREF",
        "PWR_FLAG",
    ])
    def test_power_names_recognized(self, name):
        assert _is_power_name(name), f"{name} should be recognized as power"

    @pytest.mark.parametrize("name", [
        "SPI_MOSI", "UART_TX", "I2C_SDA", "RESET", "LED1",
        "DATA", "CLK", "EN", "CS", "nRST",
    ])
    def test_signal_names_not_power(self, name):
        assert not _is_power_name(name), f"{name} should NOT be recognized as power"

    def test_power_symbol_makes_net_power_type(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            power_symbols=[_make_power("+3V3")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["+3V3"].net_type == "power"


# ---------------------------------------------------------------------------
# 5. test_signal_net_classification
# ---------------------------------------------------------------------------

class TestSignalNetClassification:
    def test_signal_global_label(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            global_labels=[_make_label("SPI_MOSI")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["SPI_MOSI"].net_type == "signal"

    def test_signal_local_label(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            local_labels=[_make_label("UART_TX", "local")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["UART_TX"].net_type == "signal"


# ---------------------------------------------------------------------------
# 6. test_scope_classification
# ---------------------------------------------------------------------------

class TestScopeClassification:
    def test_global_label_scope(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            global_labels=[_make_label("NET_A")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["NET_A"].scope == "global"

    def test_local_label_scope(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            local_labels=[_make_label("LOCAL_NET", "local")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["LOCAL_NET"].scope == "local"

    def test_hierarchical_label_scope(self):
        sheet = _make_sheet(
            "child", "/child.kicad_sch",
            hierarchical_labels=[_make_label("H_NET", "hierarchical")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["H_NET"].scope == "hierarchical"

    def test_power_symbol_forces_global_scope(self):
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            power_symbols=[_make_power("VCC")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["VCC"].scope == "global"

    def test_power_name_without_symbol_still_signal(self):
        """A local label named 'VCC' without a power symbol is still local scope
        but classified as power type by name pattern."""
        sheet = _make_sheet(
            "root", "/root.kicad_sch",
            local_labels=[_make_label("VCC", "local")],
        )
        nets = trace_nets(_build_tree(sheet))
        assert nets["VCC"].net_type == "power"
        assert nets["VCC"].scope == "local"


# ---------------------------------------------------------------------------
# 7. test_net_appears_on_multiple_sheets
# ---------------------------------------------------------------------------

class TestNetOnMultipleSheets:
    def test_global_net_lists_all_sheets(self):
        sheets = [
            _make_sheet(f"Sheet{i}", f"/s{i}.kicad_sch",
                        global_labels=[_make_label("SHARED_NET")])
            for i in range(5)
        ]
        nets = trace_nets(_build_tree(*sheets))

        assert "SHARED_NET" in nets
        assert len(nets["SHARED_NET"].sheets) == 5
        assert sorted(nets["SHARED_NET"].sheets) == [
            "Sheet0", "Sheet1", "Sheet2", "Sheet3", "Sheet4"
        ]

    def test_power_net_lists_all_sheets(self):
        sheets = [
            _make_sheet(f"S{i}", f"/s{i}.kicad_sch",
                        power_symbols=[_make_power("GND")])
            for i in range(3)
        ]
        nets = trace_nets(_build_tree(*sheets))

        assert "GND" in nets
        assert len(nets["GND"].sheets) == 3


# ---------------------------------------------------------------------------
# Integration: multi-level hierarchy
# ---------------------------------------------------------------------------

class TestMultiLevelHierarchy:
    """Test a 3-level hierarchy: root → power → regulators."""

    def test_depth_2_hierarchy(self):
        reg_path = Path("/proj/regulators.kicad_sch")
        pwr_path = Path("/proj/power.kicad_sch")
        root_path = Path("/proj/root.kicad_sch")

        root = _make_sheet(
            "Root", str(root_path),
            global_labels=[_make_label("VBUS")],
            sub_sheet_refs=[
                _make_sub_ref(
                    "Power", "power.kicad_sch",
                    pins=[("VBUS", "input"), ("V3V3", "output")],
                    resolved_path=pwr_path,
                ),
            ],
        )
        power = _make_sheet(
            "Power", str(pwr_path),
            hierarchical_labels=[
                _make_label("VBUS", "hierarchical"),
                _make_label("V3V3", "hierarchical"),
            ],
            sub_sheet_refs=[
                _make_sub_ref(
                    "Regulators", "regulators.kicad_sch",
                    pins=[("V3V3_REG", "output")],
                    resolved_path=reg_path,
                ),
            ],
            parent_path=root_path,
        )
        regulators = _make_sheet(
            "Regulators", str(reg_path),
            hierarchical_labels=[
                _make_label("V3V3_REG", "hierarchical"),
            ],
            power_symbols=[_make_power("+3V3")],
            parent_path=pwr_path,
        )

        nets = trace_nets(_build_tree(root, power, regulators))

        # VBUS should span Root and Power
        assert "VBUS" in nets
        assert "Root" in nets["VBUS"].sheets
        assert "Power" in nets["VBUS"].sheets

        # V3V3 connects Root ↔ Power via hierarchical pin
        assert "V3V3" in nets
        assert "Root" in nets["V3V3"].sheets
        assert "Power" in nets["V3V3"].sheets

        # V3V3_REG connects Power ↔ Regulators
        assert "V3V3_REG" in nets
        assert "Power" in nets["V3V3_REG"].sheets
        assert "Regulators" in nets["V3V3_REG"].sheets

        # +3V3 power symbol in Regulators is a global power net
        assert "+3V3" in nets
        assert nets["+3V3"].net_type == "power"
        assert nets["+3V3"].scope == "global"

    def test_empty_tree(self):
        """Empty sheet tree returns no nets."""
        nets = trace_nets({})
        assert nets == {}

    def test_single_sheet_no_labels(self):
        """Sheet with no labels returns no nets."""
        sheet = _make_sheet("empty", "/e.kicad_sch")
        nets = trace_nets(_build_tree(sheet))
        assert nets == {}

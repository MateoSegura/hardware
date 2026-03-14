"""KiCad schematic generator — creates .kicad_sch files from component placements.

Generates valid KiCad 9 schematic files with placed components, net labels,
wires, and hierarchical sheet references. Uses direct S-expression string
generation (no kiutils dependency for schematics).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path


def _uuid() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Minimal lib_symbols stubs for common component types
# ---------------------------------------------------------------------------

_LIB_SYMBOL_STUBS: dict[str, str] = {
    "Device:R": """(symbol "Device:R"
      (pin_numbers (hide yes))
      (pin_names (offset 0))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Description" "Resistor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54)
          (stroke (width 0.254) (type default)) (fill (type none))))
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))))
      (embedded_fonts no))""",
    "Device:C": """(symbol "Device:C"
      (pin_numbers (hide yes))
      (pin_names (offset 0.254))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Footprint" "" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Description" "Unpolarized capacitor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "C_0_1"
        (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
          (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
          (stroke (width 0.508) (type default)) (fill (type none))))
      (symbol "C_1_1"
        (pin passive line (at 0 3.81 270) (length 2.794)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 2.794)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))))
      (embedded_fonts no))""",
    "Device:L": """(symbol "Device:L"
      (pin_numbers (hide yes))
      (pin_names (offset 1.016))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "L" (at -1.016 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "L" (at 1.016 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Description" "Inductor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "L_0_1"
        (arc (start 0 -2.54) (mid 0.6323 -1.905) (end 0 -1.27)
          (stroke (width 0) (type default)) (fill (type none)))
        (arc (start 0 -1.27) (mid 0.6323 -0.635) (end 0 0)
          (stroke (width 0) (type default)) (fill (type none)))
        (arc (start 0 0) (mid 0.6323 0.635) (end 0 1.27)
          (stroke (width 0) (type default)) (fill (type none)))
        (arc (start 0 1.27) (mid 0.6323 1.905) (end 0 2.54)
          (stroke (width 0) (type default)) (fill (type none))))
      (symbol "L_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))))
      (embedded_fonts no))""",
}


def _get_lib_symbol_stub(lib_id: str) -> str:
    """Get a lib_symbol stub for a given lib_id.

    Returns a known stub if available, or generates a minimal 2-pin stub.
    """
    if lib_id in _LIB_SYMBOL_STUBS:
        return _LIB_SYMBOL_STUBS[lib_id]

    # Generate a minimal 2-pin passive stub for unknown symbols
    safe_name = lib_id.replace('"', '\\"')
    ref_prefix = lib_id.split(":")[-1][0] if ":" in lib_id else "U"
    return f"""(symbol "{safe_name}"
      (pin_names (offset 1.016))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "{ref_prefix}" (at 0 1.27 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{safe_name}" (at 0 -1.27 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "{safe_name}_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))))
      (embedded_fonts no))"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ComponentPlacement:
    """A placed component in a schematic."""
    lib_id: str
    ref: str
    value: str
    footprint: str
    position: tuple[float, float]
    unit: int = 1


@dataclass
class NetConnection:
    """A net label placed in the schematic."""
    net_name: str
    label_type: str  # "local", "global", "power"
    position: tuple[float, float]


@dataclass
class SheetContent:
    """Content of a hierarchical sheet."""
    title: str
    components: list[ComponentPlacement]
    nets: list[NetConnection]
    hierarchical_labels: list[tuple[str, str]]  # (name, direction)


# ---------------------------------------------------------------------------
# S-expression generators
# ---------------------------------------------------------------------------

def _gen_property(key: str, value: str, prop_id: int, x: float, y: float,
                  hide: bool = False, justify: str = "") -> str:
    """Generate a property S-expression."""
    effects = '(effects (font (size 1.27 1.27))'
    if justify:
        effects += f' (justify {justify})'
    if hide:
        effects += ' (hide yes)'
    effects += ')'
    return f'\t\t(property "{key}" "{value}"\n\t\t\t(at {x} {y} 0)\n\t\t\t{effects}\n\t\t)'


def _gen_component(comp: ComponentPlacement, project_name: str,
                   root_uuid: str) -> str:
    """Generate a placed symbol S-expression."""
    x, y = comp.position
    sym_uuid = _uuid()

    pin_section = ""
    # Generate pin UUIDs — for known 2-pin components
    lib_base = comp.lib_id.split(":")[-1] if ":" in comp.lib_id else comp.lib_id
    if lib_base in ("R", "C", "L"):
        pin_section = (
            f'\t\t(pin "1"\n\t\t\t(uuid "{_uuid()}")\n\t\t)\n'
            f'\t\t(pin "2"\n\t\t\t(uuid "{_uuid()}")\n\t\t)'
        )
    else:
        pin_section = (
            f'\t\t(pin "1"\n\t\t\t(uuid "{_uuid()}")\n\t\t)\n'
            f'\t\t(pin "2"\n\t\t\t(uuid "{_uuid()}")\n\t\t)'
        )

    return f"""\t(symbol
\t\t(lib_id "{comp.lib_id}")
\t\t(at {x} {y} 0)
\t\t(unit {comp.unit})
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(fields_autoplaced yes)
\t\t(uuid "{sym_uuid}")
{_gen_property("Reference", comp.ref, 0, x + 2.54, y - 1.27, justify="left")}
{_gen_property("Value", comp.value, 1, x + 2.54, y + 1.27, justify="left")}
{_gen_property("Footprint", comp.footprint, 2, x, y, hide=True)}
{_gen_property("Datasheet", "~", 3, x, y, hide=True)}
{pin_section}
\t\t(instances
\t\t\t(project "{project_name}"
\t\t\t\t(path "/{root_uuid}"
\t\t\t\t\t(reference "{comp.ref}")
\t\t\t\t\t(unit {comp.unit})
\t\t\t\t)
\t\t\t)
\t\t)
\t)"""


def _gen_label(net: NetConnection) -> str:
    """Generate a net label S-expression."""
    x, y = net.position
    label_uuid = _uuid()

    if net.label_type == "global":
        return f"""\t(global_label "{net.net_name}"
\t\t(shape input)
\t\t(at {x} {y} 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify left)
\t\t)
\t\t(uuid "{label_uuid}")
\t\t(property "Intersheetref" "${{INTERSHEET_REFS}}"
\t\t\t(at 0 0 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(hide yes)
\t\t\t)
\t\t)
\t)"""
    elif net.label_type == "power":
        return f"""\t(power_port "{net.net_name}"
\t\t(at {x} {y} 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify left)
\t\t)
\t\t(uuid "{label_uuid}")
\t)"""
    else:
        # local label
        return f"""\t(label "{net.net_name}"
\t\t(at {x} {y} 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify left bottom)
\t\t)
\t\t(uuid "{label_uuid}")
\t)"""


def _gen_wire(x1: float, y1: float, x2: float, y2: float) -> str:
    """Generate a wire S-expression."""
    return f"""\t(wire
\t\t(pts
\t\t\t(xy {x1} {y1}) (xy {x2} {y2})
\t\t)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(uuid "{_uuid()}")
\t)"""


def _gen_hierarchical_label(name: str, direction: str) -> str:
    """Generate a hierarchical_label S-expression for a sub-sheet."""
    shape_map = {
        "input": "input",
        "output": "output",
        "bidirectional": "bidirectional",
        "passive": "passive",
    }
    shape = shape_map.get(direction, "bidirectional")
    return f"""\t(hierarchical_label "{name}"
\t\t(shape {shape})
\t\t(at 25.4 25.4 180)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify right)
\t\t)
\t\t(uuid "{_uuid()}")
\t)"""


def _gen_sheet_ref(filename: str, sheet_name: str,
                   pins: list[tuple[str, str]],
                   x: float, y: float,
                   project_name: str, root_uuid: str,
                   page: int) -> str:
    """Generate a sheet reference S-expression in the root schematic."""
    sheet_uuid = _uuid()
    width = 20.32
    height = max(10.16, (len(pins) + 1) * 2.54)

    pin_lines = []
    for i, (pin_name, pin_dir) in enumerate(pins):
        pin_y = y + 2.54 + i * 2.54
        pin_lines.append(
            f'\t\t(pin "{pin_name}" input\n'
            f'\t\t\t(at {x + width} {pin_y} 0)\n'
            f'\t\t\t(uuid "{_uuid()}")\n'
            f'\t\t\t(effects\n'
            f'\t\t\t\t(font\n'
            f'\t\t\t\t\t(size 1.27 1.27)\n'
            f'\t\t\t\t)\n'
            f'\t\t\t\t(justify right)\n'
            f'\t\t\t)\n'
            f'\t\t)'
        )

    pins_str = "\n".join(pin_lines)

    return f"""\t(sheet
\t\t(at {x} {y})
\t\t(size {width} {height})
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(fields_autoplaced yes)
\t\t(stroke
\t\t\t(width 0.1524)
\t\t\t(type solid)
\t\t)
\t\t(fill
\t\t\t(color 0 0 0 0.0000)
\t\t)
\t\t(uuid "{sheet_uuid}")
\t\t(property "Sheetname" "{sheet_name}"
\t\t\t(at {x} {y - 0.7} 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left bottom)
\t\t\t)
\t\t)
\t\t(property "Sheetfile" "{filename}"
\t\t\t(at {x} {y + height + 0.6} 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left top)
\t\t\t)
\t\t)
{pins_str}
\t\t(instances
\t\t\t(project "{project_name}"
\t\t\t\t(path "/{root_uuid}"
\t\t\t\t\t(page "{page}")
\t\t\t\t)
\t\t\t)
\t\t)
\t)"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_schematic(
    components: list[ComponentPlacement],
    nets: list[NetConnection],
    title: str = "Generated Schematic",
    paper_size: str = "A4",
) -> str:
    """Generate a .kicad_sch file content from component placements and net connections.

    Args:
        components: List of placed components.
        nets: List of net labels.
        title: Schematic title.
        paper_size: Paper size (A4, A3, etc.).

    Returns:
        String content of a valid .kicad_sch file.
    """
    root_uuid = _uuid()
    project_name = title.replace(" ", "_")

    # Collect unique lib_ids for lib_symbols section
    lib_ids = sorted({c.lib_id for c in components})
    lib_symbols = "\n\t\t".join(_get_lib_symbol_stub(lid) for lid in lib_ids)

    # Generate component placements
    comp_lines = "\n".join(
        _gen_component(c, project_name, root_uuid) for c in components
    )

    # Generate net labels
    label_lines = "\n".join(_gen_label(n) for n in nets)

    return f"""(kicad_sch
\t(version 20250114)
\t(generator "hardware-pipeline")
\t(generator_version "1.0")
\t(uuid "{root_uuid}")
\t(paper "{paper_size}")
\t(lib_symbols
\t\t{lib_symbols}
\t)
{label_lines}
{comp_lines}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""


def generate_hierarchical_project(
    sheets: dict[str, SheetContent],
    root_title: str = "Root",
) -> dict[str, str]:
    """Generate a complete hierarchical KiCad project.

    Creates a root schematic with sheet references and sub-sheet files
    with hierarchical labels.

    Args:
        sheets: Dict mapping filename (e.g., "power.kicad_sch") to content.
        root_title: Title for the root schematic.

    Returns:
        Dict mapping filename -> file content string for all sheets
        including the root.
    """
    root_uuid = _uuid()
    project_name = root_title.replace(" ", "_")

    # Collect all lib_ids across all sheets
    all_lib_ids: set[str] = set()
    for sc in sheets.values():
        for c in sc.components:
            all_lib_ids.add(c.lib_id)

    # Generate root schematic with sheet references
    sheet_refs = []
    x_offset = 50.8
    for page_num, (filename, sc) in enumerate(sheets.items(), start=2):
        pins = sc.hierarchical_labels
        ref = _gen_sheet_ref(
            filename, sc.title, pins,
            x_offset, 40.64,
            project_name, root_uuid,
            page_num,
        )
        sheet_refs.append(ref)
        x_offset += 30.48

    sheet_refs_str = "\n".join(sheet_refs)

    root_content = f"""(kicad_sch
\t(version 20250114)
\t(generator "hardware-pipeline")
\t(generator_version "1.0")
\t(uuid "{root_uuid}")
\t(paper "A4")
\t(lib_symbols)
{sheet_refs_str}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""

    result: dict[str, str] = {}
    root_filename = root_title.replace(" ", "_").lower() + ".kicad_sch"
    result[root_filename] = root_content

    # Generate sub-sheets
    for filename, sc in sheets.items():
        content = _generate_sub_sheet(sc, project_name, all_lib_ids)
        result[filename] = content

    return result


def _generate_sub_sheet(
    sc: SheetContent,
    project_name: str,
    all_lib_ids: set[str],
) -> str:
    """Generate a sub-sheet .kicad_sch file."""
    sheet_uuid = _uuid()

    # lib_symbols for components in this sheet
    sheet_lib_ids = sorted({c.lib_id for c in sc.components})
    lib_symbols = "\n\t\t".join(
        _get_lib_symbol_stub(lid) for lid in sheet_lib_ids
    )

    # Component placements
    comp_lines = "\n".join(
        _gen_component(c, project_name, sheet_uuid) for c in sc.components
    )

    # Net labels
    label_lines = "\n".join(_gen_label(n) for n in sc.nets)

    # Hierarchical labels
    hlabel_lines = "\n".join(
        _gen_hierarchical_label(name, direction)
        for name, direction in sc.hierarchical_labels
    )

    return f"""(kicad_sch
\t(version 20250114)
\t(generator "hardware-pipeline")
\t(generator_version "1.0")
\t(uuid "{sheet_uuid}")
\t(paper "A4")
\t(lib_symbols
\t\t{lib_symbols}
\t)
{hlabel_lines}
{label_lines}
{comp_lines}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""

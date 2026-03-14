#!/usr/bin/env python3
"""Validate circuit templates by instantiating them as KiCad schematics and running ERC.

For each template with passives:
  1. Creates ComponentPlacement objects for the center IC + all passives
  2. Creates NetConnection objects for power nets (VCC, GND)
  3. Generates a .kicad_sch file via generate_schematic()
  4. Runs kicad-cli ERC on the generated file
  5. Records: template name, ERC result (pass/fail/warnings)

Outputs a validation report to data/patterns/template_validation.json.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.pipeline.models import CircuitTemplate, TemplatePassive
from src.pipeline.schematic_gen import ComponentPlacement, NetConnection, generate_schematic
from src.pipeline.templates import (
    generate_all_templates,
    save_templates,
    template_from_dict,
)
from src.pipeline.validate import run_erc

logger = logging.getLogger(__name__)

_PATTERNS_DIR = _REPO_ROOT / "data" / "patterns"
_TEMPLATES_DIR = _PATTERNS_DIR / "templates"
_SUMMARY_PATH = _TEMPLATES_DIR / "templates_summary.json"
_VALIDATION_OUTPUT = _PATTERNS_DIR / "template_validation.json"

# Mapping from ref_prefix to KiCad lib_id for schematic generation
_PREFIX_LIB_ID = {
    "C": "Device:C",
    "R": "Device:R",
    "L": "Device:L",
}

# Grid spacing for component placement (mils converted to mm)
_X_START = 50.8
_Y_START = 50.8
_X_SPACING = 20.32
_Y_SPACING = 15.24


def _load_templates() -> list[CircuitTemplate]:
    """Load templates from summary JSON, or generate them if missing."""
    if _SUMMARY_PATH.is_file():
        with open(_SUMMARY_PATH) as f:
            summary = json.load(f)
        # Load full template files
        templates = []
        for entry in summary:
            tpl_path = _TEMPLATES_DIR / f"{entry['name']}.json"
            if tpl_path.is_file():
                with open(tpl_path) as f:
                    templates.append(template_from_dict(json.load(f)))
            else:
                logger.warning("Template file missing: %s", tpl_path)
        if templates:
            return templates

    # Generate and save templates
    logger.info("No templates_summary.json found, generating templates...")
    templates = generate_all_templates()
    if templates:
        save_templates(templates)
    return templates


def instantiate_template(template: CircuitTemplate) -> tuple[list[ComponentPlacement], list[NetConnection]]:
    """Convert a CircuitTemplate into ComponentPlacement and NetConnection lists.

    Places the center IC at the origin area, then arranges passives in a column
    to the right. Adds VCC and GND net labels near the passive pins.

    For schematic generation, the center IC is represented as a Device:R stub
    (a known 2-pin KiCad symbol) since the actual lib_id may not exist in the
    local KiCad symbol library. The validation focuses on structural ERC
    correctness, not symbol library resolution.
    """
    components: list[ComponentPlacement] = []
    nets: list[NetConnection] = []

    # Place center IC — always use a known KiCad symbol (Device:R) as a
    # structural stand-in. The real IC lib_id is recorded in the value field.
    components.append(ComponentPlacement(
        lib_id="Device:R",
        ref="U1",
        value=template.center_ic_lib_id,
        footprint=template.center_ic_footprint or "",
        position=(_X_START, _Y_START),
    ))

    # Place passives
    comp_idx = 1
    x_pos = _X_START + _X_SPACING
    y_pos = _Y_START

    for passive in template.passives:
        # Use known KiCad symbols; fall back to Device:R for unknown prefixes
        lib_id = _PREFIX_LIB_ID.get(passive.ref_prefix, "Device:R")
        for i in range(passive.count_in_template):
            ref = f"{passive.ref_prefix}{comp_idx}"
            comp_idx += 1

            components.append(ComponentPlacement(
                lib_id=lib_id,
                ref=ref,
                value=passive.typical_value or passive.ref_prefix,
                footprint=passive.typical_footprint or "",
                position=(x_pos, y_pos),
            ))

            y_pos += _Y_SPACING

    # Add power net labels — VCC above first passive, GND below last
    if template.passives:
        nets.append(NetConnection(
            net_name="VCC",
            label_type="global",
            position=(_X_START + _X_SPACING, _Y_START - _Y_SPACING),
        ))
        nets.append(NetConnection(
            net_name="GND",
            label_type="global",
            position=(_X_START + _X_SPACING, y_pos),
        ))

    return components, nets


def validate_template(template: CircuitTemplate) -> dict:
    """Instantiate a template as a schematic and run ERC.

    Returns a result dict with: name, has_passives, erc_success,
    erc_violations, erc_errors, erc_warnings, erc_stderr.
    """
    result = {
        "name": template.name,
        "description": template.description,
        "passive_count": len(template.passives),
        "source_count": template.source_count,
        "erc_success": False,
        "erc_violations": 0,
        "erc_errors": 0,
        "erc_warnings": 0,
        "erc_stderr": "",
    }

    if not template.passives:
        result["erc_stderr"] = "skipped: no passives"
        return result

    components, nets = instantiate_template(template)
    sch_content = generate_schematic(
        components=components,
        nets=nets,
        title=f"Template_{template.name}",
    )

    # Write to a temp file and run ERC
    with tempfile.TemporaryDirectory(prefix="tpl_erc_") as tmpdir:
        sch_path = Path(tmpdir) / f"{template.name}.kicad_sch"
        sch_path.write_text(sch_content)

        erc = run_erc(sch_path)
        result["erc_success"] = erc["success"]
        result["erc_violations"] = erc["violations"]
        result["erc_errors"] = erc["errors"]
        result["erc_warnings"] = erc["warnings"]
        result["erc_stderr"] = erc.get("stderr", "")

    return result


def validate_all_templates(
    templates: list[CircuitTemplate] | None = None,
) -> list[dict]:
    """Validate all templates with passives.

    Args:
        templates: Optional list of templates. If None, loads/generates them.

    Returns:
        List of validation result dicts.
    """
    if templates is None:
        templates = _load_templates()

    results = []
    templates_with_passives = [t for t in templates if t.passives]

    logger.info(
        "Validating %d templates with passives (of %d total)",
        len(templates_with_passives),
        len(templates),
    )

    for i, tpl in enumerate(templates_with_passives, 1):
        logger.info("[%d/%d] Validating: %s", i, len(templates_with_passives), tpl.name)
        result = validate_template(tpl)
        results.append(result)

        status = "PASS" if result["erc_success"] else "FAIL"
        if result["erc_success"] and result["erc_errors"] > 0:
            status = "ERRORS"
        elif result["erc_success"] and result["erc_warnings"] > 0:
            status = "WARNINGS"
        logger.info(
            "  %s — violations=%d errors=%d warnings=%d",
            status,
            result["erc_violations"],
            result["erc_errors"],
            result["erc_warnings"],
        )

    return results


def save_report(results: list[dict], output_path: Path | None = None) -> Path:
    """Save the validation report as JSON."""
    if output_path is None:
        output_path = _VALIDATION_OUTPUT

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(results)
    passed = sum(1 for r in results if r["erc_success"] and r["erc_errors"] == 0)
    with_warnings = sum(1 for r in results if r["erc_success"] and r["erc_warnings"] > 0)
    failed = sum(1 for r in results if not r["erc_success"])
    with_errors = sum(1 for r in results if r["erc_success"] and r["erc_errors"] > 0)

    report = {
        "summary": {
            "total_validated": total,
            "passed": passed,
            "with_warnings": with_warnings,
            "with_errors": with_errors,
            "failed": failed,
        },
        "results": results,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    logger.info("Report saved to %s", output_path)
    return output_path


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    templates = _load_templates()
    if not templates:
        logger.error("No templates found or generated. Check data/patterns/ files.")
        sys.exit(1)

    logger.info("Loaded %d templates", len(templates))

    results = validate_all_templates(templates)
    report_path = save_report(results)

    # Print summary
    total = len(results)
    passed = sum(1 for r in results if r["erc_success"] and r["erc_errors"] == 0)
    failed = sum(1 for r in results if not r["erc_success"])
    print(f"\n{'='*60}")
    print(f"Template ERC Validation Report")
    print(f"{'='*60}")
    print(f"  Templates validated: {total}")
    print(f"  Passed (no errors):  {passed}")
    print(f"  Failed:              {failed}")
    print(f"  Report:              {report_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

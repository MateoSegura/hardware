#!/usr/bin/env python3
"""Bulk parse all KiCad projects in data/raw/ and save to data/parsed/."""

import json
import sys
import time
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tools"))

from src.pipeline.parse_project import parse_project
from src.pipeline.export import export_project

def main():
    raw_dir = project_root / "data" / "raw"
    parsed_dir = project_root / "data" / "parsed"
    parsed_dir.mkdir(exist_ok=True)

    results = {"success": [], "failed": [], "skipped": []}

    projects = sorted(p for p in raw_dir.iterdir() if p.is_dir())
    total = len(projects)

    for i, project_dir in enumerate(projects, 1):
        name = project_dir.name
        output_dir = parsed_dir / name
        output_file = output_dir / "project.json"

        # Skip if already parsed
        if output_file.exists():
            results["skipped"].append(name)
            continue

        print(f"[{i}/{total}] Parsing {name}...", end=" ", flush=True)
        start = time.time()

        try:
            # parse_project returns list[ParsedProject], one per design unit
            parsed_list = parse_project(project_dir)

            if not parsed_list:
                elapsed = time.time() - start
                print(f"SKIPPED ({elapsed:.1f}s) — no design units found")
                results["skipped"].append(name)
                continue

            # Save each design unit as JSON
            output_dir.mkdir(parents=True, exist_ok=True)

            if len(parsed_list) == 1:
                # Single design unit — save as project.json
                json_str = export_project(parsed_list[0])
                output_file.write_text(json_str)
            else:
                # Multiple design units — save each individually + combined
                all_data = []
                for parsed in parsed_list:
                    unit_file = output_dir / f"{parsed.design_unit.name}.json"
                    json_str = export_project(parsed)
                    unit_file.write_text(json_str)
                    all_data.append(json.loads(json_str))
                # Also save combined project.json
                output_file.write_text(json.dumps(all_data, indent=2))

            elapsed = time.time() - start
            total_components = sum(p.stats.get("total_components", 0) for p in parsed_list)
            total_nets = sum(p.stats.get("total_nets", 0) for p in parsed_list)
            units = len(parsed_list)
            units_str = f", {units} units" if units > 1 else ""
            print(f"OK ({elapsed:.1f}s, {total_components} components, {total_nets} nets{units_str})")
            results["success"].append({"name": name, "time": round(elapsed, 1), "units": units})

        except Exception as e:
            elapsed = time.time() - start
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"FAILED ({elapsed:.1f}s) — {error_msg}")
            traceback.print_exc()
            results["failed"].append({"name": name, "error": error_msg})

    # Save report
    report_file = project_root / "data" / "parse_report.json"
    with open(report_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE: {len(results['success'])} success, {len(results['failed'])} failed, {len(results['skipped'])} skipped")
    total_parsed = len(results['success']) + len(results['failed'])
    if total_parsed:
        print(f"Success rate: {len(results['success'])}/{total_parsed}")
    if results["failed"]:
        print("\nFailed projects:")
        for f_item in results["failed"]:
            print(f"  {f_item['name']}: {f_item['error']}")
    print(f"\nReport saved to {report_file}")

if __name__ == "__main__":
    main()

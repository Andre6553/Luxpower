"""Extract Solar Assistant Grafana panel metadata."""
from __future__ import annotations

import json
from pathlib import Path

DASH = Path(__file__).resolve().parent / "solar_assistant_grafana_dashboard.json"


def main() -> None:
    data = json.loads(DASH.read_text(encoding="utf-8"))
    dash = data["dashboard"]
    print("title:", dash.get("title"))
    print("timezone:", dash.get("timezone"))
    print("graphTooltip:", dash.get("graphTooltip"))
    for panel in dash.get("panels", []):
        if panel.get("type") == "row":
            print(f"\n=== ROW: {panel.get('title')} ===")
            continue
        colors = panel.get("aliasColors") or {}
        targets = panel.get("targets") or []
        aliases = [t.get("alias") or t.get("measurement") for t in targets]
        unit = (
            panel.get("fieldConfig", {})
            .get("defaults", {})
            .get("unit", panel.get("yaxes", [{}])[0].get("format", ""))
        )
        print(
            f"- {panel.get('title')!r} "
            f"grid={panel.get('gridPos')} "
            f"colors={colors} "
            f"series={aliases} "
            f"unit={unit}"
        )


if __name__ == "__main__":
    main()

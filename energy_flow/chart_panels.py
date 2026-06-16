"""All Solar Assistant chart panels (layout reference only)."""
from __future__ import annotations

# Order and pairing matches SA Grafana dashboard `sa-charts`.
SA_CHART_PANELS = [
    {"id": "chartOverview", "title": "Overview", "full": True, "kind": "overview"},
    {"id": "chartLoadSources", "title": "Where your load comes from", "full": True, "kind": "load_sources"},
    {"id": "chartBatteryPower", "title": "Battery power", "full": True, "series": "battery", "unit": "W", "color": "#111111"},
    {"id": "chartBatterySoc", "title": "Battery state of charge", "full": True, "series": "soc", "unit": "%", "color": "#2ca02c", "ymin": 0, "ymax": 100},
    {"id": "chartMppt1Voltage", "title": "MPPT 1 voltage", "series": "vpv1", "unit": "V", "color": "#f2c200"},
    {"id": "chartMppt1Current", "title": "MPPT 1 current", "series": "ipv1", "unit": "A", "color": "#f2c200"},
    {"id": "chartMppt2Voltage", "title": "MPPT 2 voltage", "series": "vpv2", "unit": "V", "color": "#f2c200"},
    {"id": "chartMppt2Current", "title": "MPPT 2 current", "series": "ipv2", "unit": "A", "color": "#f2c200"},
    {"id": "chartMppt1Power", "title": "MPPT 1 power", "series": "ppv1", "unit": "W", "color": "#f2c200"},
    {"id": "chartMppt2Power", "title": "MPPT 2 power", "series": "ppv2", "unit": "W", "color": "#f2c200"},
    {"id": "chartMpptPowerAll", "title": "MPPT power & state of charge", "full": True, "kind": "mppt_power_combined", "unit": "W"},
    {"id": "chartAuxPvPower", "title": "Auxiliary PV power", "series": "ppvAux", "unit": "W", "color": "#f2c200"},
    {"id": "chartPvPower", "title": "PV power", "series": "pvTotal", "unit": "W", "color": "#f2c200"},
    {"id": "chartBatteryVoltage", "title": "Battery voltage", "series": "vbat", "unit": "V", "color": "#2ca02c"},
    {"id": "chartBatteryCurrent", "title": "Battery current", "series": "ibat", "unit": "A", "color": "#111111"},
    {"id": "chartInverterTemp", "title": "Inverter temperature", "series": "invTemp", "unit": "°C", "color": "#111111"},
    {"id": "chartBatteryTemp", "title": "Battery temperature", "series": "batTemp", "unit": "°C", "color": "#111111"},
    {"id": "chartGridVoltage", "title": "Grid voltage", "series": "vac", "unit": "V", "color": "#d62728"},
    {"id": "chartGridFrequency", "title": "Grid frequency", "series": "freq", "unit": "Hz", "color": "#d62728"},
    {"id": "chartAcOutputVoltage", "title": "AC output voltage", "series": "vacOut", "unit": "V", "color": "#1f77b4"},
    {"id": "chartLoadPower", "title": "Load power", "series": "load", "unit": "W", "color": "#1f77b4"},
]

SERIES_KEYS = sorted(
    {
        p["series"]
        for p in SA_CHART_PANELS
        if p.get("series") and p.get("kind") != "overview"
    }
    | {"ppv1", "ppv2", "pCharge", "pDischarge", "gridNet", "pToUser", "pToGrid"}
)

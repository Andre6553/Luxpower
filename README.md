# Luxpower Dashboard

This project lets any LuxPower user run the dashboard with their own inverter by updating only `.env` values (no code edits needed).

## How It Works For A New User

- The app reads user-specific settings from `.env`.
- Cloud data is fetched using the user's LuxPower credentials.
- Local live data is read from the user's inverter on their own LAN (`inverter_ip` + `dongle_sn`).
- The local dashboard runs on `http://127.0.0.1:8765/`.

## Setup Guide (New Users)

### 1) Download The Project

```bash
git clone https://github.com/Andre6553/Luxpower.git
cd Luxpower
```

Or download ZIP from GitHub and extract it.

Repository: [Andre6553/Luxpower](https://github.com/Andre6553/Luxpower.git)

### 2) Install Python Requirements

Use Python 3.10+.

```bash
pip install requests
```

If you use a virtual environment, activate it before installing.

### 3) Create Your Config File

Copy `.env.example` to `.env`.

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` with your own values.

### 4) Fill In `.env` Correctly

Required for LuxPower cloud:

- `username` = your LuxPower login username/email
- `password` = your LuxPower login password
- `station` = your station/plant name (exact or close match)
- `inverter_sn` = your inverter serial number

Required for local live inverter reads:

- `dongle_sn` = your dongle serial number
- `inverter_ip` = LAN IP of inverter/dongle (example `192.168.10.67`)

Optional (only for Solar Assistant scripts):

- `solarassistant_email`
- `cloudProxy`

### `.env` Field Reference

| Field | Required | Example | Where to find it |
|---|---|---|---|
| `username` | Yes | `user@example.com` | LuxPower app/portal login username |
| `password` | Yes | `your_password` | LuxPower app/portal login password |
| `station` | Yes | `My Home Plant` | Plant/station name in LuxPower portal |
| `inverter_sn` | Yes | `2453530335` | Device/inverter details page in LuxPower portal |
| `dongle_sn` | For local live data | `BA24401521` | Sticker on dongle or dongle details in portal |
| `inverter_ip` | For local live data | `192.168.10.67` | Router DHCP clients list / dongle local network page |
| `solarassistant_email` | Optional | `you@example.com` | Your Solar Assistant account email |
| `cloudProxy` | Optional | `https://name.za.solar-assistant.io` | Solar Assistant cloud URL |

### 5) Start The Dashboard

Run:

```bat
start-local-server.bat
```

Then open:

`http://127.0.0.1:8765/`

## First Run Checklist

- `.env` exists in project root.
- `username`, `password`, `inverter_sn` are set.
- Inverter IP is reachable on your LAN (for local data).
- Firewall allows local Python server on port `8765`.

## Common Problems

- **Server does not start**
  - Make sure Python is installed and available in PATH.
  - Run `python energy_flow/server.py` directly to see errors.

- **Cloud data missing**
  - Check `username`/`password` in `.env`.
  - Confirm correct LuxPower region/account access.

- **Live local data missing**
  - Verify `inverter_ip` and `dongle_sn`.
  - Confirm PC and inverter are on the same network.

## Security Notes

- Never commit your real `.env` file.
- `.env.example` is safe to share; it contains placeholder values only.

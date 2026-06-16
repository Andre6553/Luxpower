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

## Use AI To Help With Setup

If you use Cursor, Google Antigravity, or Claude on your PC, you can ask the AI to do most of the setup steps for you.

### AI-assisted quick start

1. Download/clone this repo.
2. Open the project folder in your AI coding tool.
3. Paste the prompt below.
4. Let the AI run commands, create `.env`, and verify the local server.

Prompt you can copy:

```text
Set up this Luxpower project so I can run the dashboard with my own inverter.

Please do the following:
1) Check Python is available.
2) Install required dependency: requests.
3) Copy .env.example to .env (if .env does not exist).
4) Ask me only for missing required values:
   - username
   - password
   - station
   - inverter_sn
   - dongle_sn
   - inverter_ip
5) Validate .env has all required fields.
6) Start the local server using start-local-server.bat (or python energy_flow/server.py).
7) Verify http://127.0.0.1:8765/ responds.
8) If something fails, fix it and explain exactly what to change.
```

### Tip

Tell the AI: "Do not hardcode my values in source code; keep everything in `.env`."

## Security Notes

- Never commit your real `.env` file.
- `.env.example` is safe to share; it contains placeholder values only.

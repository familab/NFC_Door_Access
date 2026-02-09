# Door Controller - RFID Access Control System

Python 3 Raspberry Pi Zero RFID door access control system with cloud-based badge management, health monitoring, and robust logging.

## Table of Contents
- [Features](#features)
- [Hardware Requirements](#hardware-requirements)
- [GPIO Pin Configuration](#gpio-pin-configuration)
- [Installation](#installation)
  - [Clone the Repository](#1-clone-the-repository)
  - [Set Up Python Virtual Environment](#2-set-up-python-virtual-environment)
  - [Install Dependencies](#3-install-dependencies)
  - [Configure Google Sheets API](#4-configure-google-sheets-api)
  - [Create Google Sheets](#5-create-google-sheets)
  - [Configure Application](#6-configure-application)
- [Running the Application](#running-the-application)
  - [Manual Execution](#manual-execution)
  - [Systemd Service (Production)](#systemd-service-production)
- [Health Monitoring](#health-monitoring)
- [Logging System](#logging-system)
- [Systemd Watchdog](#systemd-watchdog)
- [Testing](#testing)
- [Continuous Integration](#continuous-integration)
- [Deployment (production)](#deployment-production)
- [Additional Documentation](#additional-documentation)
- [Configuration Options](#configuration-options)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)
- [License](#license)
- [Support](#support)

## Features

- **NFC/RFID Badge Authentication**: PN532-based badge reader with Google Sheets integration
- **Physical Controls**: Manual unlock (1-hour) and lock buttons
- **Health Monitoring**: Web-based health dashboard with real-time system status
- **Robust Logging**: 7-day rotating local logs with Google Sheets failover
- **Systemd Integration**: Auto-restart on failure with watchdog heartbeat
- **Thread-Safe**: Concurrent button monitoring and RFID scanning
- **Failover Support**: Local CSV backup when Google Sheets unavailable

## Hardware Requirements

- Raspberry Pi Zero (or any Raspberry Pi with GPIO)
- PN532 NFC/RFID Reader (I2C)
- Relay module (for door latch control)
- 2x Push buttons (unlock/lock)
- Door latch/strike (controlled via relay)

## GPIO Pin Configuration

Default pin assignments (configurable via `config.py` or environment variables):

- **GPIO 17**: Relay control (door latch)
- **GPIO 27**: Unlock button (1-hour unlock)
- **GPIO 22**: Lock button (manual lock override)
- **I2C**: PN532 NFC reader (SDA/SCL)

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd badge_scanner
```

### 2. Set Up Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Linux/macOS
# or
venv\Scripts\activate  # On Windows
```

### 3. Install Dependencies

**For older Raspberry Pi models (Pi Zero, Pi 3, etc.):**

First upgrade pip to avoid dependency resolver issues:

```bash
pip install --upgrade pip setuptools wheel
```

Then install the project dependencies:

```bash
pip install -r requirements.txt
```

**If SSH connection times out during installation** (common on slower Pi models), run installation in background:

```bash
nohup pip install -r requirements.txt > install.log 2>&1 &
```

Monitor the installation progress:

```bash
tail -f install.log
```

Press `Ctrl+C` to stop monitoring (installation continues in background)

### 4. Configure Google Sheets API

1. Create a Google Cloud Project
2. Enable Google Sheets API and Google Drive API
3. Create a Service Account and download credentials
4. Save credentials as `creds.json` in the project directory
5. Share your Google Sheets with the service account email

### 5. Create Google Sheets

Create two Google Sheets:

1. **Badge List - Access Control**: Contains authorized badge UIDs (column 1)
2. **Access Door Log**: Logs all access attempts (timestamp, UID, status)

### 6. Configure Application

Edit `config.py` or set environment variables:

```bash
export DOOR_HEALTH_PORT=8080
export DOOR_HEALTH_USERNAME=admin
export DOOR_HEALTH_PASSWORD=changeme
```

### Development on Windows (no Raspberry Pi)

You can run the application locally on Windows for development without GPIO/PN532 hardware. The `start.py` script will automatically fall back to lightweight stubs if the hardware libraries are not available.

Recommended (optional): install a GPIO emulator package so code that imports `RPi.GPIO` still works.

Note: there is no single canonical emulator package on PyPI — names vary. The project includes local stubs (`lib/gpio_stub.py` and `lib/pn532_stub.py`) which are used automatically when real hardware packages are missing.

If you want to try an emulator, these are common candidates (may or may not exist on PyPI):

```bash
pip install fake-rpi      # or
pip install fake_rpi
```

If you prefer the convenience script, use:

```powershell
.\scripts\run_dev.ps1 -Install
```

The script will install a Windows-friendly subset (`requirements-windows.txt`) and will also try installing common emulator packages; if none are available it will fall back to the included stubs.

Development helper scripts:

- Windows PowerShell: `.\scripts\run_dev.ps1 -Install` (installs dependencies and runs `start.py`)
- Linux/macOS: `./scripts/run_dev.sh install` (installs dependencies and runs `start.py`)

## Running the Application

### Manual Execution

```bash
# Activate virtual environment
source venv/bin/activate

# Run application
python3 start.py
```

### Systemd Service (Production)

1. Copy the service file:

```bash
sudo cp door-app.service /etc/systemd/system/
```

2. Edit service file paths:

```bash
sudo nano /etc/systemd/system/door-app.service
```

Update `WorkingDirectory` and `ExecStart` paths to match your installation.

3. Enable and start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable door-app.service
sudo systemctl start door-app.service
```

4. Check status:

```bash
sudo systemctl status door-app.service
```

5. View logs:

```bash
sudo journalctl -u door-app.service -f
```

## Health Monitoring

The application provides a web-based health dashboard at:

```
http://<raspberry-pi-ip>:8080/health
```

**Default credentials**: `admin` / `changeme` (change in config!)

**API Documentation (Swagger UI)**: An interactive API documentation (Swagger UI) is served at:

```
http://<raspberry-pi-ip>:8080/docs
```

The raw OpenAPI JSON spec is available at `/openapi.json` (e.g., `http://<raspberry-pi-ip>:8080/openapi.json`). Access to the API docs is protected by the same Basic Auth credentials as the health page.

### Health Page Information

- Door status (OPEN/CLOSED)
- Last local log entry timestamp
- Last successful Google Sheets log
- Last badge list download
- Application uptime
- PN532 reader status (last success/error)
- Google Sheets status (last error)
- Log file size and disk space
- Auto-refreshes every 30 seconds

## Logging System

### Local Logs

- **Location**: `door_controller.log`
- **Rotation**: Daily, keeps 7 days
- **Content**: All door actions, badge scans, errors

### Google Sheets Logging

- **Best-effort**: Never crashes app on failure
- **Failover**: Falls back to local-only logging
- **Logged Events**:
  - Badge scans (granted/denied)
  - Manual unlock/lock actions
  - System errors

## Systemd Watchdog

The application uses two watchdog-related files:

- `logs/door_controller_watchdog-YYYY-MM-DD.txt` (dated): a daily rotating watchdog *log* file produced by the watchdog *logger*; retained per `LOG_RETENTION_DAYS`.
- `logs/door_controller_watchdog_heartbeat.txt` (no date): a single non-dated *heartbeat* file that records the last time the watchdog updated a timestamp. The watchdog writes the current timestamp to this file at the heartbeat interval and it can be monitored by systemd or other tools to detect liveness.

Configure systemd to monitor the (non-dated) heartbeat file:

```ini
[Service]
ExecStartPre=/bin/sh -c 'mkdir -p /tmp && echo "0" > /tmp/door_controller_watchdog.txt || true'
Restart=always
RestartSec=5
```

Systemd will auto-restart the service if it crashes or hangs.

## Testing

### Run Unit Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Run all tests
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run Specific Test Module

```bash
python -m unittest tests.test_logging_utils -v
```

### Test Coverage

```bash
pip install coverage
coverage run -m unittest discover -s tests
coverage report -m
coverage html  # Generates htmlcov/index.html
```

## Continuous Integration

GitHub Actions automatically runs tests on push/PR to main/develop branches.

See `.github/workflows/tests.yml` for CI configuration.

Tests run on Python 3.9, 3.10, and 3.11.

## Deployment (production)

This repository includes a deployment workflow that builds a ZIP artifact and deploys it to a self-hosted production agent.

## Additional Documentation

- [Optimizations](optimizations.md) — Performance and power optimizations for devices (Wi‑Fi power saving, etc.)
- [Quick Reference](QUICK_REFERENCE.md) — Short commands and common operations
- [Data Schema](data-schema.md) — Google Sheets structure and expected formats (badge list and access log)
- **API Docs** (`/docs`) — Interactive Swagger UI for exploring the HTTP API (OpenAPI JSON at `/openapi.json`)



Required repository secrets (set under Settings → Secrets):

- `CREDS_JSON` — (optional) the full Google Service Account JSON content (will be written to `creds.json` on the target host)
- `DOOR_HEALTH_USERNAME` — username for the health page (recommended to change from `admin`)
- `DOOR_HEALTH_PASSWORD` — password for the health page (set a strong value)
- `DOOR_HEALTH_PORT` — (optional) port for the health server (default 8080)
- `DEPLOY_DIR` — (optional) directory on the target host to deploy files (default: `/opt/door`)

Protection and approvals:

- The `deploy` job targets the `production` environment. Configure environment protection rules in GitHub to require approvals or checks before the workflow can proceed.

Behavior of the deployment workflow:

- Job 1 (`build_package`) creates a ZIP containing `README.md`, all `*.md` files, `*.service` files, `version*.txt`, `main.py`, the `lib/` package, and `requirements.txt`.
- Job 2 (`deploy`) runs on a **self-hosted** runner (an agent you own), downloads the ZIP, extracts it to `DEPLOY_DIR` (default `/opt/door`), writes the `creds.json` file if `CREDS_JSON` is provided, creates a systemd drop-in to export `DOOR_CREDS_FILE`, `DOOR_HEALTH_USERNAME`, and `DOOR_HEALTH_PASSWORD` into the service environment, then restarts `door-app.service`.

Notes & recommended follow-ups:

- Secrets are never committed to the repository; they are provided to the workflow via GitHub Secrets.
- The deployment writes the service account JSON to `creds.json` and sets `DOOR_CREDS_FILE` to point there. The service will read the config at startup.
- You may prefer to manage secrets via a secret management system or encrypted files on the target host.

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOOR_RELAY_PIN` | 17 | GPIO pin for relay |
| `DOOR_UNLOCK_PIN` | 27 | GPIO pin for unlock button |
| `DOOR_LOCK_PIN` | 22 | GPIO pin for lock button |
| `DOOR_UNLOCK_DURATION` | 3600 | Unlock duration (seconds) |
| `DOOR_HEALTH_PORT` | 8080 | Health server port |
| `DOOR_HEALTH_USERNAME` | admin | Health page username |
| `DOOR_HEALTH_PASSWORD` | changeme | Health page password |

### Config File

Create `config.json` to override defaults:

```json
{
  "RELAY_PIN": 17,
  "UNLOCK_DURATION": 3600,
  "HEALTH_SERVER_PORT": 8080
}
```

## Architecture

### Modules

- **`start.py`**: Main application entry point
- **`config.py`**: Configuration management
- **`logging_utils.py`**: Logging system (local + Google Sheets)
- **`door_control.py`**: Door status tracking and GPIO control
- **`health_server.py`**: HTTP health monitoring server
- **`watchdog.py`**: Systemd watchdog heartbeat

### Thread Model

- **Main thread**: Initialization and thread management
- **Button monitor thread**: Polls unlock/lock buttons
- **RFID monitor thread**: Reads PN532 and authenticates badges
- **Health server thread**: HTTP server (daemon)
- **Watchdog thread**: Heartbeat updates (daemon)

## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status door-app.service

# View detailed logs
sudo journalctl -u door-app.service -n 50
```

### Pip install fails on older Raspberry Pi

If you encounter dependency resolver errors or cryptography package issues on older Raspberry Pi models (Python 3.9 or earlier):

```bash
# Upgrade pip, setuptools, and wheel first
pip install --upgrade pip setuptools wheel

# Clear pip cache
pip cache purge

# Then install requirements
pip install -r requirements.txt
```

If issues persist, try using the legacy resolver:

```bash
pip install --no-cache-dir --use-deprecated=legacy-resolver -r requirements.txt
```

**If SSH connection times out during installation**, run in background:

```bash
nohup pip install -r requirements.txt > install.log 2>&1 &
tail -f install.log
```

### GPIO permissions

```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER

# Reboot required
sudo reboot
```

### PN532 not detected

```bash
# Check I2C devices
sudo i2cdetect -y 1

# Should show device at 0x24
```

### Google Sheets errors

- Verify `creds.json` is valid
- Check service account has access to sheets
- Ensure internet connectivity
- Check local logs: `tail -f door_controller.log`

### Health page not accessible

- Check firewall: `sudo ufw allow 8080`
- Verify port in config matches URL
- Check server started: `netstat -tuln | grep 8080`

## Security Considerations

1. **Change default health page credentials** immediately
2. Use HTTPS reverse proxy (nginx) for production health page
3. Restrict health page access via firewall rules
4. Keep `creds.json` secure (never commit to git)
5. Regularly rotate Google service account keys
6. Review access logs periodically

## License

[Your License Here]

## Support

[Your Support Information Here]

## check service
* systemctl cat door-app.service
* systemctl --type=service --state=running


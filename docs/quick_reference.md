# Door Controller - Quick Reference Guide

[← Back to README](../README.md)

## Table of Contents
- [Quick Start](#quick-start)
  - [Initial Setup](#1-initial-setup)
  - [Configure Credentials](#2-configure-credentials)
  - [Run Application](#3-run-application)
- [Common Commands](#common-commands)
  - [Service Management](#service-management)
  - [Testing](#testing)
  - [Logs](#logs)
- [Health Monitoring](#health-monitoring)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [File Structure](#file-structure)
- [Security Checklist](#security-checklist)
- [Maintenance Tasks](#maintenance-tasks)

## Quick Start

### 1. Initial Setup
```bash
cd badge_scanner
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Credentials
- Copy `creds.sample.json` to `creds.json`
- Add your Google Service Account credentials
- Share Google Sheets with service account email

### 3. Run Application
```bash
# Manual run (for testing)
source venv/bin/activate
python3 start.py

# Production (systemd)
sudo systemctl start door-app.service
```

## Common Commands

### Service Management
```bash
# Status
sudo systemctl status door-app.service

# Start/Stop/Restart
sudo systemctl start door-app.service
sudo systemctl stop door-app.service
sudo systemctl restart door-app.service

# Enable auto-start on boot
sudo systemctl enable door-app.service

# View logs
sudo journalctl -u door-app.service -f
sudo journalctl -u door-app.service -n 100
```

### Testing
```bash
# All tests
./run_tests.sh

# Verbose mode
./run_tests.sh verbose

# With coverage
./run_tests.sh coverage

# Single test module
./run_tests.sh single test_config
```

### Logs
```bash
# View local application logs
tail -f door_controller.log

# View systemd service logs
sudo journalctl -u door-app.service -f

# View last 50 lines
sudo journalctl -u door-app.service -n 50

# View logs since today
sudo journalctl -u door-app.service --since today
```

## Health Monitoring

### Access Health Page
```
http://<raspberry-pi-ip>:8080/health
```

Default credentials: `admin` / `changeme` (CHANGE THESE!)

### Health Page Shows
- Door status (OPEN/CLOSED)
- Last log entry timestamp
- Last Google Sheets sync
- Last badge download
- Application uptime
- PN532 status
- Google Sheets errors
- Disk space

### Useful Links
- [Optimizations](optimizations.md)
- [Data Schema](data-schema.md)
- [README](README.md)

## Configuration

### Environment Variables
```bash
export DOOR_RELAY_PIN=17
export DOOR_UNLOCK_PIN=27
export DOOR_LOCK_PIN=22
export DOOR_UNLOCK_DURATION=3600
export DOOR_HEALTH_PORT=8080
export DOOR_HEALTH_USERNAME=admin
export DOOR_HEALTH_PASSWORD=changeme
```

### Config File (config.json)
```json
{
  "RELAY_PIN": 17,
  "UNLOCK_DURATION": 3600,
  "HEALTH_SERVER_PORT": 8080,
  "HEALTH_SERVER_USERNAME": "admin",
  "HEALTH_SERVER_PASSWORD": "changeme"
}
```

## Troubleshooting

### Service Won't Start
```bash
# Check status and errors
sudo systemctl status door-app.service
sudo journalctl -u door-app.service -n 50

# Check Python path
which python3

# Check permissions
ls -l /home/pi/badge_scanner/start.py
```

### GPIO Errors
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER
sudo usermod -a -G i2c $USER

# Reboot
sudo reboot
```

### PN532 Not Detected
```bash
# Check I2C devices
sudo i2cdetect -y 1

# Enable I2C
sudo raspi-config
# Interface Options -> I2C -> Enable
```

### Google Sheets Errors
- Verify `creds.json` exists and is valid
- Check service account has access to sheets
- Test internet connection: `ping google.com`
- Check local logs: `tail -f door_controller.log`

### Health Page Not Accessible
```bash
# Check if server is running
netstat -tuln | grep 8080

# Check firewall
sudo ufw status
sudo ufw allow 8080

# Check service logs
sudo journalctl -u door-app.service -n 20
```

## File Structure

```
badge_scanner/
├── start.py                 # Main application
├── config.py                # Configuration management
├── logging_utils.py         # Logging system
├── door_control.py          # Door control logic
├── health_server.py         # Health monitoring server
├── watchdog.py              # Systemd watchdog
├── requirements.txt         # Python dependencies
├── door-app.service             # Systemd service file
├── creds.json              # Google credentials (secret!)
├── creds.sample.json       # Credentials template
├── tests/                   # Unit tests
│   ├── test_config.py
│   ├── test_logging_utils.py
│   ├── test_door_control.py
│   ├── test_health_server.py
│   └── test_watchdog.py
└── .github/
    └── workflows/
        └── tests.yml        # CI/CD configuration
```

## Security Checklist

- [ ] Changed default health page password
- [ ] Secured `creds.json` (chmod 600)
- [ ] Configured firewall rules
- [ ] Using HTTPS reverse proxy for health page
- [ ] Regular log review
- [ ] Google service account key rotation

## Maintenance Tasks

### Weekly
- Review access logs
- Check disk space
- Verify badge list is current

### Monthly
- Update dependencies: `pip install -U -r requirements.txt`
- Review and archive old logs
- Test backup/restore procedures

### Quarterly
- Rotate Google service account keys
- Security audit
- Performance review

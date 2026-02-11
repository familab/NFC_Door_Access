# Optimizations

[← Back to README](../README.md)

## Table of Contents
- [Disable Wi‑Fi Power Saving on Raspberry Pi Zero W](#disable-wi‑fi-power-saving-on-raspberry-pi-zero-w)
  - [Check current power‑saving status](#check-current-power‑saving-status)
  - [Disable power saving immediately (temporary)](#disable-power-saving-immediately-temporary)
  - [Disable power saving permanently (NetworkManager systems)](#disable-power-saving-permanently-networkmanager-systems)
  - [Disable power saving permanently (classic Raspberry Pi OS)](#disable-power-saving-permanently-classic-raspberry-pi-os)
  - [Confirm after reboot](#confirm-after-reboot)

## Disable Wi‑Fi Power Saving on Raspberry Pi Zero W

### Check current power‑saving status
```bash
iwconfig wlan0
```

---

### Disable power saving immediately (temporary)
```bash
sudo iwconfig wlan0 power off
```

---

### Disable power saving permanently (NetworkManager systems)
```bash
sudo nano /etc/NetworkManager/conf.d/wifi-powersave.conf
```

Add:
```
[connection]
wifi.powersave = 2
```

Reboot:
```bash
sudo reboot
```

---

### Disable power saving permanently (classic Raspberry Pi OS)
```bash
echo "options 8192cu rtw_power_mgnt=0 rtw_enusbss=0" | sudo tee /etc/modprobe.d/8192cu.conf
sudo reboot
```

---

### Confirm after reboot
```bash
iwconfig wlan0
```

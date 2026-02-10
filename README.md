# Door_Sysstem_2025
New Door Access System created in 2025

*Code was made by Adam who knows VERY little of python and utilized ChatGPT to get it done. Please feel free to suggest more efficient changes*

Hardware (wiring diagram coming soon):
- Raspberry Pi Zero W
- PN532 RFID Reader
- 12v Relay
- 12v to 5v buck converter
- 12v door latch
- 12v Power Suply
- 2 Generic Buttons
- 3D Printed case (will be added soon)

Main Functions:
- start.py contains all of the code and runs as a service in order to make sure it is running all of the time. The theory is if it crashes, the service can restart automatically. Also the service will start on reboot without having to wait on something like a cron job to restart it.
- When RFID is scanned the pi reaches out to a Sheets file on FamiLAB's Google Drive that contains all allowed IDs. If the ID is found it triggers the relay to unlock the door for 5 seconds and posts in another Google Sheets document. It posts the ID and "Granted" Or "Denied". This is used for logging and troubleshooting.
- Two buttons are also available. One is to unlock the door for 1 hour and the other is to override the unlock and set the door back to locked.

Credentials:
- The google doc is shared with a service account and credentials are saved to a local file. See https://docs.gspread.org/en/latest/oauth2.html for more information about how gspread works.

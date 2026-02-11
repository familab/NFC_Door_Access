import board
import busio
from adafruit_pn532.i2c import PN532_I2C

# Setup I2C for PN532
i2c = busio.I2C(board.SCL, board.SDA)
pn532 = PN532_I2C(i2c, debug=True)  # Enable debug to see more output

# Configure PN532 to read RFID tags
pn532.SAM_configuration()

print("Waiting for an NFC card...")

while True:
    uid = pn532.read_passive_target(timeout=0.5)
    if uid:
        print("Found card with UID:", [hex(i) for i in uid])
    else:
        print("No card detected")

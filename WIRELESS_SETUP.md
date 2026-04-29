# Wireless Camera Setup Guide

Since you are running this on a university network (**Cornell RedRover**), there are two strict network policies we have to work around:
1. **mDNS (`.local`) is blocked**: This is why `flipdot.local` cannot be found by your browser.
2. **UDP Broadcasting is blocked**: The Camera Pico is currently trying to shout its data to everyone on the network (`255.255.255.255`), but the university routers drop these packets immediately. 

To fix this and get everything running flawlessly, we must use **direct IP addressing**.

---

### Step 1: Find the Mirror Pico's IP Address
We need to know the exact IP address of the Mirror Pico so both your GUI and the Camera know exactly where to send data.

1. Plug your **Mirror Pico** (the one attached to the servos) into your computer via USB.
2. Open the **Arduino IDE**.
3. Open the **Serial Monitor** (magnifying glass icon in the top right). Set the baud rate to `115200`.
4. Press the **Reset button** on your Pico (or unplug it and plug it back in) so you can watch the boot sequence.
5. Look for a line that says:
   `[WIFI] Connected! IP: 10.48.X.X`
6. **Copy that IP address!**

---

### Step 2: Update the Camera Firmware
The Camera needs to be told to stop broadcasting and to send data directly to the Mirror's IP.

1. Open `RPI-Pico-Cam/rp2040_hm01b0/main.c`.
2. Find this line near the top (around line 13):
   `#define TARGET_IP "255.255.255.255"`
3. Change it to the IP address you found in Step 1. Example:
   `#define TARGET_IP "10.48.34.112"`
4. Rebuild the firmware (I can do this for you once you give me the IP).
5. Flash the new `arducam_firmware.uf2` to the **Camera Pico**.

---

### Step 3: Connect the GUI
1. Open `index.html` in your browser.
2. Select **"Wireless"** connection mode.
3. Paste the exact IP address of the Mirror Pico (e.g., `10.48.34.112`) into the box instead of `flipdot.local`.
4. Click **Connect WiFi**.

Once connected, your Mirror will receive the direct UDP packets from the Camera and instantly forward them to your GUI!

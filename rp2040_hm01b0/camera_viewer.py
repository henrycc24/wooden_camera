#!/usr/bin/env python3
"""
HM01B0 Camera Viewer
Receives 96x96 grayscale frames from the Pico over USB serial
and displays them in a live preview window.

Usage: python3 camera_viewer.py [port]
Default port: /dev/cu.usbmodem2101
"""

import serial
import sys
import time
import os

# Frame format: 0x55 0xAA + 96*96 bytes of grayscale
FRAME_WIDTH = 96
FRAME_HEIGHT = 96
FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT
HEADER = bytes([0x55, 0xAA])

def find_port():
    """Auto-detect the Pico serial port"""
    import glob
    ports = glob.glob('/dev/cu.usbmodem*')
    if ports:
        return ports[0]
    return None

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        print("No USB serial port found. Is the Pico connected?")
        sys.exit(1)

    print(f"Connecting to {port}...")
    ser = serial.Serial(port, 115200, timeout=1)
    print("Connected! Waiting for frames...")
    print("(Open the serial port to trigger camera init)")
    print("Press Ctrl+C to quit\n")

    # Try to use tkinter for display
    try:
        import tkinter as tk
        from tkinter import Canvas
        USE_TK = True
    except ImportError:
        USE_TK = False
        print("tkinter not available, saving frames as PNG instead")

    # Try PIL for image saving
    try:
        from PIL import Image
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False

    if USE_TK:
        root = tk.Tk()
        root.title("HM01B0 Camera - 96x96 Grayscale")

        SCALE = 4  # Scale up for visibility
        display_w = FRAME_WIDTH * SCALE
        display_h = FRAME_HEIGHT * SCALE

        canvas = Canvas(root, width=display_w, height=display_h, bg='black')
        canvas.pack()

        status_label = tk.Label(root, text="Waiting for frames...", fg='white', bg='black')
        status_label.pack()

        # PhotoImage for display
        photo = tk.PhotoImage(width=display_w, height=display_h)
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)

        frame_count = [0]
        fps_start = [time.time()]
        buf = [b'']

        def update():
            try:
                data = ser.read(ser.in_waiting or 1)
                if data:
                    buf[0] += data

                # Search for frame header
                while True:
                    idx = buf[0].find(HEADER)
                    if idx < 0:
                        # Keep last byte in case it's partial header
                        if len(buf[0]) > 1:
                            buf[0] = buf[0][-1:]
                        break

                    # Check if we have full frame
                    frame_start = idx + len(HEADER)
                    if len(buf[0]) < frame_start + FRAME_SIZE:
                        break  # Wait for more data

                    # Extract frame
                    frame_data = buf[0][frame_start:frame_start + FRAME_SIZE]
                    buf[0] = buf[0][frame_start + FRAME_SIZE:]

                    # Update display
                    frame_count[0] += 1

                    # Build PPM-style photo data (scaled up)
                    rows = []
                    for y in range(FRAME_HEIGHT):
                        row_pixels = []
                        for x in range(FRAME_WIDTH):
                            g = frame_data[y * FRAME_WIDTH + x]
                            color = f'#{g:02x}{g:02x}{g:02x}'
                            for _ in range(SCALE):
                                row_pixels.append(color)
                        row_str = '{' + ' '.join(row_pixels) + '}'
                        for _ in range(SCALE):
                            rows.append(row_str)

                    photo.configure(width=display_w, height=display_h)
                    for row_idx, row in enumerate(rows):
                        photo.put(row, to=(0, row_idx))

                    # FPS counter
                    elapsed = time.time() - fps_start[0]
                    if elapsed > 1.0:
                        fps = frame_count[0] / elapsed
                        status_label.config(text=f"Frame: {frame_count[0]} | FPS: {fps:.1f}")
                        frame_count[0] = 0
                        fps_start[0] = time.time()

            except serial.SerialException:
                status_label.config(text="Serial disconnected!")
            except Exception as e:
                status_label.config(text=f"Error: {e}")

            root.after(10, update)

        root.after(100, update)
        root.mainloop()

    else:
        # Fallback: just print frame info and save PNGs
        buf = b''
        frame_count = 0
        while True:
            try:
                data = ser.read(4096)
                if data:
                    buf += data

                while True:
                    idx = buf.find(HEADER)
                    if idx < 0:
                        if len(buf) > 1:
                            buf = buf[-1:]
                        break

                    frame_start = idx + len(HEADER)
                    if len(buf) < frame_start + FRAME_SIZE:
                        break

                    frame_data = buf[frame_start:frame_start + FRAME_SIZE]
                    buf = buf[frame_start + FRAME_SIZE:]
                    frame_count += 1

                    # Print stats
                    avg = sum(frame_data) / len(frame_data)
                    print(f"Frame {frame_count}: avg brightness={avg:.1f}")

                    # Save as PNG if PIL available
                    if HAS_PIL and frame_count <= 5:
                        img = Image.frombytes('L', (FRAME_WIDTH, FRAME_HEIGHT), frame_data)
                        img = img.resize((FRAME_WIDTH*4, FRAME_HEIGHT*4), Image.NEAREST)
                        fname = f"frame_{frame_count:04d}.png"
                        img.save(fname)
                        print(f"  Saved {fname}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                break

    ser.close()
    print("Done.")

if __name__ == '__main__':
    main()

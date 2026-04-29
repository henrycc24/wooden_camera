#!/usr/bin/env python3
"""
HM01B0 OpenCV Camera Viewer
Receives 96x96 grayscale frames from the Pico over USB serial
and displays them in an OpenCV window.

Usage: python3 cv2_viewer.py [port]
Default port: auto-detected
"""

import serial
import sys
import time
import cv2
import numpy as np

# Frame format: 0x55 0xAA + 96*96 bytes of grayscale
FRAME_WIDTH = 96
FRAME_HEIGHT = 96
FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT
HEADER = bytes([0x55, 0xAA])
SCALE = 4

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
    try:
        ser = serial.Serial(port, 115200, timeout=1)
    except Exception as e:
        print(f"Failed to open port {port}: {e}")
        sys.exit(1)
        
    print("Connected! Waiting for frames...")
    print("(Press 'q' or 'ESC' in the video window to quit)")

    # Create the window and show a placeholder immediately
    window_name = "HM01B0 Camera (OpenCV)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, FRAME_WIDTH * SCALE, FRAME_HEIGHT * SCALE)
    
    placeholder = np.zeros((FRAME_HEIGHT * SCALE, FRAME_WIDTH * SCALE), dtype=np.uint8)
    cv2.putText(placeholder, "Waiting for camera...", (20, FRAME_HEIGHT*SCALE//2), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,), 2)
    cv2.imshow(window_name, placeholder)
    cv2.waitKey(1)

    buf = b''
    frame_count = 0
    fps_start = time.time()
    last_data_time = time.time()

    while True:
        try:
            # Read whatever is available
            data = ser.read(max(1, ser.in_waiting))
            if data:
                buf += data
                last_data_time = time.time()
            elif time.time() - last_data_time > 3.0:
                print("Warning: No data received from Pico for 3 seconds...")
                last_data_time = time.time() # suppress warning for another 3s

            # Search for frame header
            idx = buf.find(HEADER)
            
            if idx > 0:
                # There is data before the header, it might be text/errors!
                text_data = buf[:idx]
                try:
                    text = text_data.decode('utf-8', errors='ignore').strip()
                    if text:
                        print(f"PICO: {text}")
                except:
                    pass
                # Discard the text data
                buf = buf[idx:]
                idx = 0

            if idx < 0:
                # No header found in buffer. 
                # Print it as text if it ends in newline
                if b'\n' in buf:
                    lines = buf.split(b'\n')
                    for line in lines[:-1]:
                        try:
                            text = line.decode('utf-8', errors='ignore').strip()
                            if text:
                                print(f"PICO: {text}")
                        except:
                            pass
                    buf = lines[-1]
                    
                # Keep last byte in case it's a partial header
                if len(buf) > 1:
                    buf = buf[-1:]
                continue

            # Check if we have a full frame
            frame_start = idx + len(HEADER)
            if len(buf) < frame_start + FRAME_SIZE:
                continue  # Wait for more data

            # Extract frame data
            frame_data = buf[frame_start:frame_start + FRAME_SIZE]
            buf = buf[frame_start + FRAME_SIZE:]

            # Convert to numpy array and reshape
            img_array = np.frombuffer(frame_data, dtype=np.uint8).reshape((FRAME_HEIGHT, FRAME_WIDTH))

            # Resize for display
            display_img = cv2.resize(img_array, (FRAME_WIDTH * SCALE, FRAME_HEIGHT * SCALE), interpolation=cv2.INTER_NEAREST)

            # Show image
            cv2.imshow(window_name, display_img)

            frame_count += 1
            print(f"Got frame {frame_count}")
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                cv2.setWindowTitle(window_name, f"HM01B0 Camera | FPS: {fps:.1f}")
                frame_count = 0
                fps_start = time.time()

            # Process OpenCV events and check for quit key
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # 'q' or ESC
                break

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
            break

    ser.close()
    cv2.destroyAllWindows()
    print("Done.")

if __name__ == '__main__':
    main()

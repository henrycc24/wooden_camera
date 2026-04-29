/**
 * ImageProcessor — converts a video frame or image into an 8×8 binary grid.
 *
 * Pipeline:
 *   1. Draw source (video/image) onto an offscreen canvas scaled to 8×8
 *   2. Read pixel data, convert each pixel to grayscale (luminance)
 *   3. Apply threshold to produce binary (0 = white, 1 = black)
 *
 * The result is an 8×8 2D array where grid[row][col] ∈ {0, 1}.
 *   0 → white tile (servo at 0°)
 *   1 → black tile (servo at 180°)
 */

class ImageProcessor {
  /**
   * @param {number} threshold — grayscale cutoff (0–255). Pixels darker than
   *   this become 1 (black). Default 128.
   */
  constructor(threshold = 128) {
    this.threshold = threshold;
    this.gridSize = 8;

    // Offscreen canvas for downscaling
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.gridSize;
    this.canvas.height = this.gridSize;
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
  }

  /**
   * Set the binary threshold (0–255).
   * @param {number} value
   */
  setThreshold(value) {
    this.threshold = Math.max(0, Math.min(255, Math.round(value)));
  }

  /**
   * Process a source (HTMLVideoElement, HTMLImageElement, HTMLCanvasElement)
   * into an 8×8 binary grid.
   *
   * @param {CanvasImageSource} source — the image/video to process
   * @returns {number[][]} 8×8 array of 0s and 1s
   */
  process(source) {
    // Draw the source scaled down to 8×8
    this.ctx.drawImage(source, 0, 0, this.gridSize, this.gridSize);

    // Read pixel data
    const imageData = this.ctx.getImageData(0, 0, this.gridSize, this.gridSize);
    const pixels = imageData.data; // RGBA flat array

    const grid = [];

    for (let row = 0; row < this.gridSize; row++) {
      const rowData = [];
      for (let col = 0; col < this.gridSize; col++) {
        const i = (row * this.gridSize + col) * 4;
        const r = pixels[i];
        const g = pixels[i + 1];
        const b = pixels[i + 2];

        // ITU-R BT.601 luminance
        const gray = 0.299 * r + 0.587 * g + 0.114 * b;

        // Below threshold → black (1), above → white (0)
        rowData.push(gray < this.threshold ? 1 : 0);
      }
      grid.push(rowData);
    }

    return grid;
  }

  /**
   * Convert an 8×8 grid to an array of 8 bytes (one per row).
   * Each byte encodes the row with MSB = col 0, LSB = col 7.
   *
   * @param {number[][]} grid — 8×8 binary grid
   * @returns {number[]} array of 8 bytes
   */
  static gridToBytes(grid) {
    const bytes = [];
    for (let row = 0; row < 8; row++) {
      let byte = 0;
      for (let col = 0; col < 8; col++) {
        if (grid[row][col]) {
          byte |= (1 << (7 - col));
        }
      }
      bytes.push(byte);
    }
    return bytes;
  }

  /**
   * Convert an array of 8 bytes back to an 8×8 grid.
   *
   * @param {number[]} bytes — array of 8 bytes
   * @returns {number[][]} 8×8 binary grid
   */
  static bytesToGrid(bytes) {
    const grid = [];
    for (let row = 0; row < 8; row++) {
      const rowData = [];
      for (let col = 0; col < 8; col++) {
        rowData.push((bytes[row] >> (7 - col)) & 1);
      }
      grid.push(rowData);
    }
    return grid;
  }

  /**
   * Process raw ImageData (for testing without a canvas source).
   *
   * @param {ImageData} imageData — 8×8 ImageData object
   * @returns {number[][]} 8×8 array of 0s and 1s
   */
  processImageData(imageData) {
    const pixels = imageData.data;
    const grid = [];

    for (let row = 0; row < this.gridSize; row++) {
      const rowData = [];
      for (let col = 0; col < this.gridSize; col++) {
        const i = (row * this.gridSize + col) * 4;
        const r = pixels[i];
        const g = pixels[i + 1];
        const b = pixels[i + 2];

        const gray = 0.299 * r + 0.587 * g + 0.114 * b;
        rowData.push(gray < this.threshold ? 1 : 0);
      }
      grid.push(rowData);
    }

    return grid;
  }
}

// Export for both browser and module contexts
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ImageProcessor;
}

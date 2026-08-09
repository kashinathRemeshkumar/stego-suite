# stego-suite

A multi-format steganography toolkit for hiding data inside images, audio, and video files using LSB (Least Significant Bit) manipulation. No encryption included.

## What is LSB Steganography?

Every file on your computer is just a sequence of bytes. Every byte is 8 bits. The least significant bit (the last bit) of each byte contributes almost nothing to the actual value — changing it shifts a number by only 1 out of 255. In an image, that difference is completely invisible to the human eye.

LSB steganography works by replacing those insignificant bits with the bits of your secret file:

```
Original pixel R channel:  10110100  (180)
After hiding a 1 bit:      10110101  (181)  ← difference of 1, invisible
```

The secret file is recovered by reading those bits back out and reassembling them into bytes.

## Modules

### ✅ Image (C++) — Working

Hides any file inside a PNG image using LSB manipulation on RGB channels.

**Capacity:**
```
1920×1080 PNG = 1920 × 1080 × 3 channels / 8 = ~760 KB
```

**Usage:**
```bash
# Encode — hide secret.txt (can be any file not just txt) inside cover.png
# only works on png jpeg compression corrupts the lsb data
./encoder cover.png secret.txt

# Decode — extract hidden file from output.png
./decoder output.png
```

**How it works:**
- Reads the cover PNG as a flat array of RGB bytes
- Prepends a header to the secret file containing magic bytes, file size, and filename
- Replaces the LSB of each RGB channel with one bit of the secret stream
- Saves the result as `output.png`
- Decoder reads LSBs back, parses the header, and reconstructs the original file

**Header format:**
```
[MAGIC 4B "STEG"][FILE_SIZE 4B][FILENAME_LEN 2B][FILENAME NB][DATA...]
```
The magic bytes `STEG` let the decoder confirm hidden data is actually present before attempting extraction.

**Dependencies:**
- [stb_image](https://github.com/nothings/stb) — header-only PNG loading
- [stb_image_write](https://github.com/nothings/stb) — header-only PNG saving

**Compile:**
```bash
g++ -std=c++17 -o encoder encoder.cpp
g++ -std=c++17 -o decoder decoder.cpp
```

---

### 🚧 Audio — Not yet finished

LSB steganography in audio files. Work in progress.

---

### 🚧 Video — Not yet finished

Steganography using video frames. Currently outputs a checker pattern as a placeholder. Work in progress.

---

## Limitations

### JPEG does not work — use PNG only

JPEG compression is lossy. When you save a JPEG, it approximates pixel values to reduce file size. This destroys the LSB data entirely:

```
You write:    10110101  (181)
JPEG saves:   10110110  (182)  ← compression changed the value
You read:     wrong bit — data is gone
```

The decoder will correctly report `"no hidden data found"` on any JPEG that has been re-compressed. This is expected behaviour, not a bug.

**PNG is lossless** — every pixel value is preserved exactly as written, so LSB data survives perfectly.

### WhatsApp — send as a document, not an image

WhatsApp re-compresses images when you send them normally, which destroys the hidden data just like JPEG does.

**Workaround:** Send the PNG file as a **document** instead of an image. WhatsApp does not re-compress files sent as documents, so the pixel values are preserved and the hidden data survives.


### Capacity

A standard 1920×1080 PNG holds roughly 760 KB of hidden data at 1 bit per channel. To hide larger files you need a larger cover image.

### No encryption

The hidden data is not encrypted. Anyone with this tool and the output PNG can extract the hidden file. If you need privacy, encrypt your secret file before hiding it.

---

## License

GPL-3.0

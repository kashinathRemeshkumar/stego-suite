import os
import subprocess
import numpy as np
from reedsolo import ReedSolomonError, RSCodec

try:
    import cupy as cp

    xp = cp
    GPU = True
    print("✓ CuPy found — using GPU for frame generation")
except ImportError:
    xp = np
    GPU = False
    print("✗ CuPy not found — falling back to CPU (NumPy)")

WIDTH, HEIGHT = 1920, 1080
CELL = 8
COLS = WIDTH // CELL  # 240
ROWS = HEIGHT // CELL  # 135
FPS = 24
BITS_PER_FRAME = COLS * ROWS  # 32,400 bits
MAGIC = b"STEG"

NSYM = 32
DATA_BLOCK_SIZE = 223  # 255 - 32
rsc = RSCodec(NSYM)


def detect_gpu_encoder():
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    )
    encoders = {
        "h264_nvenc": "NVIDIA (NVENC)",
        "h264_amf": "AMD (AMF)",
        "h264_qsv": "Intel (QuickSync)",
    }
    for codec, name in encoders.items():
        if codec in result.stdout:
            print(f"✓ GPU encoder found: {name} ({codec})")
            return codec
    print("✗ No GPU encoder found — falling back to libx264 (CPU)")
    return None


def bytes_to_bits(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def make_frames_batch(bits_chunk: np.ndarray, n_frames: int) -> np.ndarray:
    bits = xp.array(bits_chunk) if GPU else bits_chunk
    grids = bits.reshape(n_frames, ROWS, COLS)

    gray = xp.where(grids == 1, xp.uint8(235), xp.uint8(20)).astype(xp.uint8)
    scaled = xp.repeat(xp.repeat(gray, CELL, axis=1), CELL, axis=2)

    full = xp.full((n_frames, HEIGHT, WIDTH), xp.uint8(20), dtype=xp.uint8)
    full[:, : ROWS * CELL, : COLS * CELL] = scaled

    return cp.asnumpy(full) if GPU else full


def build_ffmpeg_cmd(out_path: str, gpu_encoder) -> list:
    QUALITY = "10"
    if gpu_encoder == "h264_nvenc":
        enc_args = [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p7",
            "-cq",
            QUALITY,
            "-profile:v",
            "high",
            "-b:v",
            "0",
        ]
    elif gpu_encoder == "h264_amf":
        enc_args = [
            "-c:v",
            "h264_amf",
            "-quality",
            "quality",
            "-qp_i",
            QUALITY,
            "-qp_p",
            QUALITY,
        ]
    elif gpu_encoder == "h264_qsv":
        enc_args = [
            "-c:v",
            "h264_qsv",
            "-preset",
            "veryslow",
            "-global_quality",
            QUALITY,
        ]
    else:
        enc_args = ["-c:v", "libx264", "-crf", QUALITY, "-preset", "fast"]

    return [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-color_range",
        "pc",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-pix_fmt",
        "yuv420p",
        "-color_range",
        "pc",
        *enc_args,
        out_path,
    ]


def write_video(
    input_file: str, out_path: str = "encoded.mp4", batch_size: int = 48
):
    if not os.path.exists(input_file):
        print(f"Error: file not found: {input_file}")
        return

    with open(input_file, "rb") as f:
        raw_data = f.read()

    filename = os.path.basename(input_file).encode("utf-8")
    filename_len = len(filename).to_bytes(2, "big")
    size_header = len(raw_data).to_bytes(8, "big")

    # 1. Build Direct Raw Data Payload
    data_payload = size_header + filename_len + filename + raw_data

    # Pad data payload to exact multiple of DATA_BLOCK_SIZE (223 bytes)
    remainder_bytes = len(data_payload) % DATA_BLOCK_SIZE
    if remainder_bytes != 0:
        pad_len = DATA_BLOCK_SIZE - remainder_bytes
        data_payload += b"\x00" * pad_len

    payload_rs = bytes(rsc.encode(data_payload))
    rs_payload_len = len(payload_rs)

    # 2. Build Fixed 255-Byte Header Block
    header_raw = (MAGIC + rs_payload_len.to_bytes(8, "big")).ljust(
        DATA_BLOCK_SIZE, b"\x00"
    )
    header_rs = bytes(rsc.encode(header_raw))  # Exactly 255 bytes

    full_payload = header_rs + payload_rs

    print(f"Input file size : {len(raw_data):,} bytes")
    print(f"RS Stream size  : {len(full_payload):,} bytes (Header + ECC)")

    bits = bytes_to_bits(full_payload)
    remainder = len(bits) % BITS_PER_FRAME
    if remainder:
        bits = np.concatenate(
            [bits, np.zeros(BITS_PER_FRAME - remainder, dtype=np.uint8)]
        )

    total_frames = len(bits) // BITS_PER_FRAME
    print(
        f"Total frames    : {total_frames}  ({total_frames / FPS:.1f} seconds)"
    )

    gpu_encoder = detect_gpu_encoder()
    cmd = build_ffmpeg_cmd(out_path, gpu_encoder)
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    try:
        for batch_start in range(0, total_frames, batch_size):
            batch_end = min(batch_start + batch_size, total_frames)
            n = batch_end - batch_start
            chunk = bits[
                batch_start * BITS_PER_FRAME : batch_end * BITS_PER_FRAME
            ]
            frames_cpu = make_frames_batch(chunk, n)
            proc.stdin.write(frames_cpu.tobytes())

            pct = batch_end / total_frames * 100
            print(
                f"\r  Encoding: {batch_end}/{total_frames} frames ({pct:.1f}%)",
                end="",
                flush=True,
            )
    finally:
        proc.stdin.close()
        proc.wait()

    print(f"\nDone → {out_path}")


if __name__ == "__main__":
    import sys

    input_f = sys.argv[1] if len(sys.argv) > 1 else "congradulation.mp4"
    output_vid = sys.argv[2] if len(sys.argv) > 2 else "encoded.mp4"
    write_video(input_f, output_vid)
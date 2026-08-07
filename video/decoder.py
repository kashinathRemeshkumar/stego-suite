from concurrent.futures import ProcessPoolExecutor
import hashlib
import multiprocessing
import os
import re
import subprocess
import numpy as np
from reedsolo import ReedSolomonError, RSCodec

try:
    import cupy as cp

    xp = cp
    GPU = True
except ImportError:
    xp = np
    GPU = False

if multiprocessing.current_process().name == "MainProcess":
    if GPU:
        print("✓ CuPy found — using GPU")
    else:
        print("✗ CuPy not found — using CPU")

ORIG_WIDTH = 1920
ORIG_HEIGHT = 1080
CELL = 8
COLS = ORIG_WIDTH // CELL  # 240
ROWS = ORIG_HEIGHT // CELL  # 135
FPS = 24
BITS_PER_FRAME = COLS * ROWS
MAGIC = b"STEG"

NSYM = 32
BLOCK_SIZE = 255
DATA_BLOCK_SIZE = 223  # 255 - 32


def _decode_single_rs_block(block: bytes) -> tuple[bytes, bool]:
    """Tries RS decoding. On error, drops parity bytes and returns raw bytes."""
    rsc_worker = RSCodec(NSYM)
    try:
        res = rsc_worker.decode(block)
        decoded = bytes(res[0] if isinstance(res, tuple) else res)
        return decoded, True
    except ReedSolomonError:
        # RS failed: drop parity bytes (32) and return raw payload (223)
        return block[:DATA_BLOCK_SIZE], False


def parallel_rs_decode(payload_bytes: bytes) -> tuple[bytes, int, int]:
    num_blocks = len(payload_bytes) // BLOCK_SIZE
    blocks = [
        payload_bytes[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]
        for i in range(num_blocks)
    ]

    num_workers = min(multiprocessing.cpu_count(), 16)
    chunksize = max(1, num_blocks // (num_workers * 4))

    print(
        f"  Parallel RS decoding on {num_workers} CPU cores ({num_blocks:,} blocks)..."
    )

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        results = list(
            executor.map(_decode_single_rs_block, blocks, chunksize=chunksize)
        )

    decoded_chunks = [r[0] for r in results]
    corrupted_count = sum(1 for r in results if not r[1])
    clean_count = len(results) - corrupted_count

    return b"".join(decoded_chunks), clean_count, corrupted_count


def get_video_info(video_path: str):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_packets",
            "-show_entries",
            "stream=width,height,nb_read_packets",
            "-of",
            "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        parts = result.stdout.strip().split("\n")[0].split(",")
        return (
            int(parts[0]),
            int(parts[1]),
            int(parts[2]) if len(parts) > 2 else None,
        )
    except Exception:
        return ORIG_WIDTH, ORIG_HEIGHT, None


def precompute_sample_coords(actual_w: int, actual_h: int):
    sx, sy = actual_w / ORIG_WIDTH, actual_h / ORIG_HEIGHT
    margin = max(1, CELL // 8)

    xs = np.arange(
        round(margin * sx),
        max(round((CELL - margin) * sx), round(margin * sx) + 1),
        dtype=np.int32,
    )
    ys = np.arange(
        round(margin * sy),
        max(round((CELL - margin) * sy), round(margin * sy) + 1),
        dtype=np.int32,
    )

    col_origins = np.round(np.arange(COLS) * CELL * sx).astype(np.int32)
    row_origins = np.round(np.arange(ROWS) * CELL * sy).astype(np.int32)

    x_idx = np.tile(
        (col_origins[:, None] + xs[None, :])[None, :, :], (ROWS, 1, 1)
    )
    y_idx = np.tile(
        (row_origins[:, None] + ys[None, :])[:, None, :], (1, COLS, 1)
    )

    return np.clip(y_idx, 0, actual_h - 1), np.clip(x_idx, 0, actual_w - 1)


def decode_batch(
    frames_cpu: np.ndarray, y_idx: np.ndarray, x_idx: np.ndarray
) -> np.ndarray:
    frames = xp.array(frames_cpu) if GPU else frames_cpu
    yi = xp.array(y_idx) if GPU else y_idx
    xi = xp.array(x_idx) if GPU else x_idx

    sampled = frames[:, yi[:, :, :, None], xi[:, :, None, :]].astype(xp.float32)
    cell_avg = sampled.mean(axis=(3, 4))

    min_val = cell_avg.min()
    max_val = cell_avg.max()
    threshold = (min_val + max_val) / 2.0

    bits = (cell_avg > threshold).astype(xp.uint8)
    return cp.asnumpy(bits.reshape(-1)) if GPU else bits.reshape(-1)


def sanitize_filename(name: str, fallback="corrupted_output.bin") -> str:
    clean = name.replace("\x00", "").strip()
    clean = os.path.basename(clean)
    clean = re.sub(r'[\\/*?:"<>|]', "_", clean)
    return clean if clean else fallback


def decode_video(video_path: str, out_path: str = None, batch_size: int = 96):
    if not os.path.exists(video_path):
        print(f"Error: file not found: {video_path}")
        return

    actual_w, actual_h, total_frames = get_video_info(video_path)
    y_idx, x_idx = precompute_sample_coords(actual_w, actual_h)
    FRAME_SIZE = actual_w * actual_h

    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-color_range",
        "pc",
        "-s",
        f"{actual_w}x{actual_h}",
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 1024 * 32,
    )

    all_bits = []
    frames_done = 0

    print(f"Decoding video frames ({total_frames or '?'} total)...")
    while True:
        batch_raw = []
        for _ in range(batch_size):
            raw = proc.stdout.read(FRAME_SIZE)
            if len(raw) < FRAME_SIZE:
                break
            batch_raw.append(
                np.frombuffer(raw, dtype=np.uint8).reshape(actual_h, actual_w)
            )

        if not batch_raw:
            break

        all_bits.append(decode_batch(np.stack(batch_raw), y_idx, x_idx))
        frames_done += len(batch_raw)
        pct = (frames_done / total_frames * 100) if total_frames else 0
        print(
            f"\r  Frames processed: {frames_done}/{total_frames or '?'} ({pct:.1f}%)",
            end="",
            flush=True,
        )

    proc.stdout.close()
    proc.wait()
    print()

    all_bits_arr = np.concatenate(all_bits)
    trim = len(all_bits_arr) - (len(all_bits_arr) % 8)
    raw_bytes = np.packbits(all_bits_arr[:trim]).tobytes()

    # Step 1: Best-Effort Header Decoding
    if len(raw_bytes) < BLOCK_SIZE:
        print("❌ Error: Extracted stream is too short to parse header.")
        return

    header_block = raw_bytes[:BLOCK_SIZE]
    try:
        rsc_header = RSCodec(NSYM)
        hdr_res = rsc_header.decode(header_block)
        header_decoded = bytes(
            hdr_res[0] if isinstance(hdr_res, tuple) else hdr_res
        )
    except ReedSolomonError:
        print("⚠️ Warning: Header RS correction failed. Using uncorrected raw header...")
        header_decoded = header_block[:DATA_BLOCK_SIZE]

    if header_decoded[:4] != MAGIC:
        print("⚠️ Warning: Magic bytes header corrupted. Attempting best-effort parse anyway...")

    rs_payload_len = int.from_bytes(header_decoded[4:12], byteorder="big")

    # Sanity check payload length to avoid infinite bounds error
    max_possible_payload = len(raw_bytes) - BLOCK_SIZE
    if rs_payload_len <= 0 or rs_payload_len > max_possible_payload:
        print(f"⚠️ Warning: Invalid RS payload length in header ({rs_payload_len:,}). Defaulting to full stream length.")
        rs_payload_len = max_possible_payload

    # Step 2: Parallel RS Payload Decoding (with Fallback)
    payload_rs_chunk = raw_bytes[BLOCK_SIZE : BLOCK_SIZE + rs_payload_len]
    data_payload, clean_blocks, corrupted_blocks = parallel_rs_decode(payload_rs_chunk)

    total_blocks = clean_blocks + corrupted_blocks
    loss_pct = (corrupted_blocks / total_blocks * 100) if total_blocks else 0
    print(f"  RS Results: {clean_blocks:,} clean blocks, {corrupted_blocks:,} unrecoverable blocks ({loss_pct:.2f}% block loss)")

    if corrupted_blocks > 0:
        print("⚠️ Proceeding with best-effort dump of corrupted data payload...")

    # Step 3: Extract File Data (with bounds protection)
    try:
        raw_file_size = int.from_bytes(data_payload[:8], byteorder="big")
        filename_len = int.from_bytes(data_payload[8:10], byteorder="big")
        
        # Clamp filename length if header was corrupted
        if filename_len > 256 or filename_len <= 0:
            filename_len = 12
            raw_name = "corrupted_output.bin"
        else:
            raw_name = data_payload[10 : 10 + filename_len].decode("utf-8", errors="ignore")
            
        embedded_filename = sanitize_filename(raw_name)

        # Slice payload safely
        payload_start = 10 + filename_len
        if raw_file_size <= 0 or raw_file_size > (len(data_payload) - payload_start):
            extracted_data = data_payload[payload_start:]
        else:
            extracted_data = data_payload[payload_start : payload_start + raw_file_size]

    except Exception as e:
        print(f"⚠️ Metadata header corrupted ({e}). Writing full raw payload to disk...")
        embedded_filename = "raw_recovered_dump.bin"
        extracted_data = data_payload

    print(f"  Embedded filename       : {embedded_filename}")
    print(f"  Output size             : {len(extracted_data):,} bytes")

    final_output_path = (
        out_path if out_path else f"restored_{embedded_filename}"
    )

    with open(final_output_path, "wb") as f:
        f.write(extracted_data)

    print(f"\n✓ Saved output to {final_output_path}")
    print(f"  SHA-256: {hashlib.sha256(extracted_data).hexdigest()}")


if __name__ == "__main__":
    import sys

    input_vid = sys.argv[1] if len(sys.argv) > 1 else "encoded.mp4"
    out_file = sys.argv[2] if len(sys.argv) > 2 else None
    decode_video(input_vid, out_file)
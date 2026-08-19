import subprocess
import wave
import struct
import numpy as np

HEADER_BITS = 80  # 32 (num secret samples) + 32 (secret sample rate) + 8 (K) + 8 (channels, unused/reserved)


def load_audio(path):
    """Decode any ffmpeg-readable audio file to (samples[int32, shape=(n, ch)], sample_rate)."""
    probe_named = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True, check=True,
    )
    fields = dict(line.split("=", 1) for line in probe_named.stdout.strip().splitlines() if "=" in line)
    sr, ch = int(fields["sample_rate"]), int(fields["channels"])

    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, check=True,
    )
    data = np.frombuffer(proc.stdout, dtype="<i2").astype(np.int32)
    data = data.reshape(-1, ch)
    return data, sr


def save_wav(path, samples, sample_rate):
    """Write int32 sample array (clipped to int16 range) as a 16-bit PCM WAV."""
    samples = np.clip(samples, -32768, 32767).astype("<i2")
    n_channels = samples.shape[1] if samples.ndim == 2 else 1
    with wave.open(path, "wb") as w:
        w.setnchannels(n_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())


def resample(x, sr_from, sr_to):
    if sr_from == sr_to:
        return x
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(sr_from, sr_to)
    up, down = sr_to // g, sr_from // g
    return resample_poly(x, up, down).astype(x.dtype)


def to_mid_side(stereo):
    L = stereo[:, 0].astype(np.int64)
    R = stereo[:, 1].astype(np.int64)
    M = L + R
    S = L - R
    return M, S


def from_mid_side(M, S):
    L = (M + S) // 2
    R = (M - S) // 2
    return np.stack([L, R], axis=1)



def _int_to_bits(value, n_bits):
    return [(value >> i) & 1 for i in range(n_bits - 1, -1, -1)]


def _bits_to_int(bits):
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def build_header(num_secret_samples, secret_sr, k_bits):
    bits = (
        _int_to_bits(num_secret_samples, 32)
        + _int_to_bits(secret_sr, 32)
        + _int_to_bits(k_bits, 8)
        + _int_to_bits(0, 8)  # reserved
    )
    assert len(bits) == HEADER_BITS
    return bits


def parse_header(bits):
    num_secret_samples = _bits_to_int(bits[0:32])
    secret_sr = _bits_to_int(bits[32:64])
    k_bits = _bits_to_int(bits[64:72])
    return num_secret_samples, secret_sr, k_bits


#encoder
def embed(cover_path, secret_path, out_wav_path, k_bits=4):
    """Hide secret_path's audio inside cover_path's Side channel; write a lossless stego WAV."""
    cover, cover_sr = load_audio(cover_path)
    if cover.shape[1] == 1:
        cover = np.repeat(cover, 2, axis=1)  # force stereo so there's an S channel to hide in

    secret, secret_sr = load_audio(secret_path)
    secret_mono = secret.mean(axis=1).astype(np.int32)  # downmix secret to mono
    secret_mono = resample(secret_mono, secret_sr, cover_sr).astype(np.int32)
    secret_mono = np.clip(secret_mono, -32768, 32767)

    n_secret = len(secret_mono)
    M, S = to_mid_side(cover)

    capacity = len(S) - HEADER_BITS
    if n_secret > capacity:
        raise ValueError(
            f"Secret ({n_secret} samples) does not fit in cover capacity "
            f"({capacity} samples at this sample rate). Cover must be at least as "
            f"long as the secret once both are at the same sample rate."
        )

    header_bits = build_header(n_secret, cover_sr, k_bits)

    #header
    S = S.copy()
    S[:HEADER_BITS] = (S[:HEADER_BITS] & ~1) | np.array(header_bits, dtype=np.int64)

    # 2) Quantise secret samples to top K bits, write into bottom K bits of S.
    secret_unsigned = (secret_mono.astype(np.int64) + 32768)  # 0..65535
    secret_top_k = secret_unsigned >> (16 - k_bits)           # 0..(2^K - 1)

    region = slice(HEADER_BITS, HEADER_BITS + n_secret)
    mask = ~np.int64((1 << k_bits) - 1)
    S[region] = (S[region] & mask) | secret_top_k

    stego = from_mid_side(M, S)
    save_wav(out_wav_path, stego, cover_sr)
    return {"secret_samples": n_secret, "cover_sr": cover_sr, "k_bits": k_bits}


def extract(stego_path, out_secret_wav_path):
    """Recover the hidden secret audio from a stego WAV/FLAC produced by embed()."""
    stego, sr = load_audio(stego_path)
    _, S = to_mid_side(stego)

    header_bits = (S[:HEADER_BITS] & 1).tolist()
    n_secret, secret_sr, k_bits = parse_header(header_bits)

    region = slice(HEADER_BITS, HEADER_BITS + n_secret)
    top_k = S[region] & ((1 << k_bits) - 1)
    secret_unsigned = top_k << (16 - k_bits)          # back to 0..65535 range (quantised)
    secret_signed = secret_unsigned.astype(np.int32) - 32768

    save_wav(out_secret_wav_path, secret_signed.reshape(-1, 1), secret_sr)
    return {"secret_samples": n_secret, "secret_sr": secret_sr, "k_bits": k_bits}

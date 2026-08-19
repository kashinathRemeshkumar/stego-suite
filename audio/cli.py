import argparse
import ms_stego


def main():
    p = argparse.ArgumentParser(description="M/S LSB audio steganography (hide secret audio inside cover audio)")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("embed", help="Hide secret inside cover -> lossless stego WAV")
    e.add_argument("cover", help="cover audio file (mp3/wav/etc, at least as long as secret)")
    e.add_argument("secret", help="secret audio file to hide")
    e.add_argument("out", help="output stego .wav path (must stay lossless!)")
    e.add_argument("--bits", type=int, default=4, help="LSBs used per sample, 1-8 (default 4). Higher = better secret quality, more audible artifacts in cover.")

    x = sub.add_parser("extract", help="Recover secret audio from a stego WAV")
    x.add_argument("stego", help="stego .wav file produced by 'embed'")
    x.add_argument("out", help="output recovered secret .wav path")

    args = p.parse_args()

    if args.cmd == "embed":
        info = ms_stego.embed(args.cover, args.secret, args.out, k_bits=args.bits)
        print(f"Embedded {info['secret_samples']} secret samples "
              f"({info['secret_samples']/info['cover_sr']:.2f}s) using {info['k_bits']} LSBs -> {args.out}")
    elif args.cmd == "extract":
        info = ms_stego.extract(args.stego, args.out)
        print(f"Recovered {info['secret_samples']} samples "
              f"({info['secret_samples']/info['secret_sr']:.2f}s) at {info['secret_sr']} Hz -> {args.out}")


if __name__ == "__main__":
    main()

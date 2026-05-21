#!/usr/bin/env python3
"""
Record audio samples for benchmarking voice commands.

Usage:
    python record_audio.py lights_on "Turn on the light"
    python record_audio.py factory_status --duration 5
    python record_audio.py maintenance_question --list-devices
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

try:
    import numpy as np
    import sounddevice as sd
except ImportError as err:
    print(f"Error: {err}", file=sys.stderr)
    print("Install sounddevice and numpy: pip install sounddevice numpy", file=sys.stderr)
    sys.exit(1)


AUDIO_DIR = Path(__file__).resolve().parent / "audio"
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


def record_command(
    command_id: str,
    prompt: str | None = None,
    duration: float = 5.0,
    device: int | None = None,
) -> Path:
    """Record audio and save as WAV file."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIO_DIR / f"{command_id}.wav"

    if prompt:
        print(f"\n🎤 Recording: {prompt}")
    else:
        print(f"\n🎤 Recording: {command_id}")

    print(f"   Duration: {duration}s")
    print(f"   Sample rate: {SAMPLE_RATE} Hz")
    print(f"   Channels: {CHANNELS}")
    print("   Press Enter to start...")
    input()

    print("   Recording... speak now!")

    try:
        audio_data = sd.rec(
            int(duration * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=np.int16,
            device=device,
        )
        sd.wait()
    except Exception as exc:
        print(f"❌ Recording failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio_data.tobytes())
    except Exception as exc:
        print(f"❌ Failed to write WAV: {exc}", file=sys.stderr)
        sys.exit(1)

    file_size_kb = output_path.stat().st_size / 1024
    print(f"✅ Saved: {output_path} ({file_size_kb:.1f} KB)")
    return output_path


def list_devices() -> None:
    """Print available audio devices."""
    print("\nAvailable audio devices:\n")
    try:
        devices = sd.query_devices()
        for idx, device in enumerate(devices):
            print(f"  [{idx}] {device['name']}")
            print(f"      Channels: {device['max_input_channels']} in, {device['max_output_channels']} out")
            if device.get('default_samplerate'):
                print(f"      Default sample rate: {device['default_samplerate']} Hz")
            print()
    except Exception as exc:
        print(f"❌ Failed to query devices: {exc}", file=sys.stderr)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record audio samples for LIVA benchmarking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Record a simple command
  python record_audio.py lights_on

  # Record with a prompt (shows during recording)
  python record_audio.py lights_on "Turn on the light"

  # Record with custom duration
  python record_audio.py factory_status "Show factory status" --duration 6

  # List available audio devices
  python record_audio.py --list-devices

  # Use a specific device
  python record_audio.py maintenance_question --device 1

  # Batch record from a list
  for cmd in lights_on factory_status maintenance_question; do
    python record_audio.py "$cmd"
  done
        """,
    )

    parser.add_argument(
        "command_id",
        nargs="?",
        help="Identifier for the command (becomes the filename)",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt to display during recording (the actual text to record)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Recording duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio device index (use --list-devices to see available devices)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    if not args.command_id:
        parser.print_help()
        return 1

    record_command(
        command_id=args.command_id,
        prompt=args.prompt,
        duration=args.duration,
        device=args.device,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

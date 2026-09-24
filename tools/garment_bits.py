#!/usr/bin/env python
"""Find which shift-register bit drives which sleeve channel. SPEC.md 12.4, 18.2.

A bring-up tool for the current prototype (the MOSFET array of `ttpa_touch_the_pain_away`),
run with someone watching the sleeve. It switches one bit on at a time, in order, so each
pulse is identifiable by its position: bit N is the (N - first + 1)th pulse. The watcher notes
which channel inflates on which pulse, and that mapping goes into `hardware.yaml`.

The prototype's own protocol, from its sketch: 115200 baud, newline-terminated,
`setstate:0x<mask>` sets every output at once, lower-case hex only. Opening the port resets
the Arduino, so the tool waits for it to boot before sending anything.

**Every output is zeroed before the scan and after it, whatever ends it** -- a normal finish,
Ctrl+C, or an error. Pressure is whatever the hand regulator is set to; the software cannot
see or limit it, which is why someone must be watching.

    conda run -n tatp-study-1 python tools/garment_bits.py --port COM3
"""

from __future__ import annotations

import argparse
import time

import serial

MASK_BITS = 32  # the sketch drives four 8-bit shift registers


def send(port: serial.Serial, command: str) -> None:
    port.write(f"{command}\n".encode("ascii"))
    port.flush()


def set_mask(port: serial.Serial, mask: int) -> None:
    send(port, f"setstate:0x{mask:x}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", required=True, help="serial port, e.g. COM3")
    parser.add_argument("--baud", type=int, default=115200, help="the sketch's Serial.begin")
    parser.add_argument("--first", type=int, default=0, help="first bit to pulse")
    parser.add_argument("--last", type=int, default=MASK_BITS - 1, help="last bit to pulse")
    parser.add_argument("--bits", type=int, nargs="+",
                        help="pulse these bits, in this order (overrides --first/--last)")
    parser.add_argument("--on-s", type=float, default=1.0, help="how long each bit is on")
    parser.add_argument("--off-s", type=float, default=2.0, help="gap between pulses")
    parser.add_argument("--boot-s", type=float, default=2.5,
                        help="wait after opening the port, which resets the Arduino")
    parser.add_argument("--lead-s", type=float, default=5.0,
                        help="countdown before the first pulse, for the watcher")
    args = parser.parse_args(argv)
    bits = args.bits if args.bits else list(range(args.first, args.last + 1))
    assert bits and all(0 <= bit < MASK_BITS for bit in bits), "bits run 0-31"

    with serial.Serial(args.port, args.baud, timeout=0.5) as port:
        time.sleep(args.boot_s)
        port.reset_input_buffer()
        set_mask(port, 0)
        # The prototype's Python expects a `hello` reply; the sketches in its repository have
        # none. Recorded, not required, so the tool works with either firmware.
        send(port, "hello")
        reply = port.readline().decode("ascii", errors="replace").strip()
        print(f"handshake: sent 'hello', reply {reply!r}", flush=True)
        try:
            print(f"first pulse in {args.lead_s:g} s", flush=True)
            time.sleep(args.lead_s)
            for pulse, bit in enumerate(bits, start=1):
                print(f"pulse {pulse}: bit {bit} ON", flush=True)
                set_mask(port, 1 << bit)
                time.sleep(args.on_s)
                set_mask(port, 0)
                time.sleep(args.off_s)
        finally:
            set_mask(port, 0)
            print("all outputs zeroed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

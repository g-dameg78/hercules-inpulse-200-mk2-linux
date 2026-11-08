#!/usr/bin/env python3
"""Bounded, read-only MIDI capture for the Hercules DJControl Inpulse 200 Mk2.

Input-only hardware acceptance tool:
  - NEVER enables controller output (no LED, no sysex, no handshake writes)
  - NEVER generates MIDI or audio playback
  - NEVER overwrites existing evidence files (fails closed with FileExistsError)
  - NEVER claims provisional/guessed mappings proven (clearly labels provenance)
  - Bounded duration with clean interrupt handling (Ctrl+C preserves captured evidence)
  - Supports guided step-by-step gesture capture and safe dry-run simulation

Usage:
  # Guided physical acceptance sequence (prompts for each control):
  python3 tools/midi_capture.py --guided --output evidence/hercules_acceptance.jsonl

  # Bounded freeform capture (e.g. 15 seconds):
  python3 tools/midi_capture.py --duration 15 --output evidence/controls.jsonl

  # Safe dry-run (verifies sequence without opening any MIDI port):
  python3 tools/midi_capture.py --dry-run --guided

  # Safe port listing:
  python3 tools/midi_capture.py --list-ports
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

DEVICE_TOKEN = "DJControl Inpulse 200 Mk2"

# Clear, structured sequence of real user gestures for Hercules Inpulse 200 Mk2
GESTURE_STEPS = [
    {
        "id": "deck_a_fader",
        "title": "Deck A Channel Fader",
        "prompt": "Move Deck A channel fader smoothly: minimum (bottom, 0%) -> maximum (top, 100%) -> minimum.",
        "duration": 6.0,
        "expected": ["A:volume"],
    },
    {
        "id": "deck_b_fader",
        "title": "Deck B Channel Fader",
        "prompt": "Move Deck B channel fader smoothly: minimum (bottom, 0%) -> maximum (top, 100%) -> minimum.",
        "duration": 6.0,
        "expected": ["B:volume"],
    },
    {
        "id": "crossfader",
        "title": "Crossfader",
        "prompt": "Move crossfader smoothly: full left (Deck A) -> full right (Deck B) -> center.",
        "duration": 6.0,
        "expected": ["crossfader"],
    },
    {
        "id": "deck_a_jog_touch",
        "title": "Deck A Jog Touch Sensor",
        "prompt": "Touch and hold top metal plate on Deck A jog wheel for 2 seconds, then release.",
        "duration": 5.0,
        "expected": ["A:jog_touch"],
    },
    {
        "id": "deck_a_jog_cw",
        "title": "Deck A Jog Wheel Turn CW",
        "prompt": "Rotate Deck A jog wheel clockwise (slow turn for 2s, then one quick spin).",
        "duration": 5.0,
        "expected": ["A:jog_top", "A:jog_rim"],
    },
    {
        "id": "deck_a_jog_ccw",
        "title": "Deck A Jog Wheel Turn CCW",
        "prompt": "Rotate Deck A jog wheel counter-clockwise (slow turn for 2s, then one quick spin).",
        "duration": 5.0,
        "expected": ["A:jog_top", "A:jog_rim"],
    },
    {
        "id": "deck_b_jog_touch",
        "title": "Deck B Jog Touch Sensor",
        "prompt": "Touch and hold top metal plate on Deck B jog wheel for 2 seconds, then release.",
        "duration": 5.0,
        "expected": ["B:jog_touch"],
    },
    {
        "id": "deck_b_jog_cw",
        "title": "Deck B Jog Wheel Turn CW",
        "prompt": "Rotate Deck B jog wheel clockwise (slow turn for 2s, then one quick spin).",
        "duration": 5.0,
        "expected": ["B:jog_top", "B:jog_rim"],
    },
    {
        "id": "deck_b_jog_ccw",
        "title": "Deck B Jog Wheel Turn CCW",
        "prompt": "Rotate Deck B jog wheel counter-clockwise (slow turn for 2s, then one quick spin).",
        "duration": 5.0,
        "expected": ["B:jog_top", "B:jog_rim"],
    },
    {
        "id": "deck_a_transport",
        "title": "Deck A Transport Buttons",
        "prompt": "Press and release Deck A buttons: Play/Pause, Cue, Sync, Vinyl, Loop In, Loop Out, PFL (Headphones).",
        "duration": 8.0,
        "expected": ["A:play", "A:cue", "A:sync", "A:vinyl", "A:loop_in", "A:loop_out", "A:pfl"],
    },
    {
        "id": "deck_b_transport",
        "title": "Deck B Transport Buttons",
        "prompt": "Press and release Deck B buttons: Play/Pause, Cue, Sync, Vinyl, Loop In, Loop Out, PFL (Headphones).",
        "duration": 8.0,
        "expected": ["B:play", "B:cue", "B:sync", "B:vinyl", "B:loop_in", "B:loop_out", "B:pfl"],
    },
    {
        "id": "navigation",
        "title": "Browser, Assistant & Deck Loads",
        "prompt": "Turn Browser knob CW and CCW, push Browser knob, press Load Deck A, press Load Deck B, press Assistant.",
        "duration": 8.0,
        "expected": ["browser_encoder", "browser_push", "A:load", "B:load", "assistant"],
    },
    {
        "id": "deck_a_knobs",
        "title": "Deck A EQ & Filter Knobs",
        "prompt": "Sweep Deck A Gain, High EQ, Low EQ, and Filter knobs from center to min, to max, and back to center.",
        "duration": 8.0,
        "expected": ["A:gain", "A:eq_high", "A:eq_low", "A:filter"],
    },
    {
        "id": "deck_b_knobs",
        "title": "Deck B EQ & Filter Knobs",
        "prompt": "Sweep Deck B Gain, High EQ, Low EQ, and Filter knobs from center to min, to max, and back to center.",
        "duration": 8.0,
        "expected": ["B:gain", "B:eq_high", "B:eq_low", "B:filter"],
    },
    {
        "id": "deck_a_tempo",
        "title": "Deck A Tempo / Pitch Fader",
        "prompt": "Move Deck A tempo slider: center -> top (+/faster) -> bottom (-/slower) -> center.",
        "duration": 6.0,
        "expected": ["A:pitch"],
    },
    {
        "id": "deck_b_tempo",
        "title": "Deck B Tempo / Pitch Fader",
        "prompt": "Move Deck B tempo slider: center -> top (+/faster) -> bottom (-/slower) -> center.",
        "duration": 6.0,
        "expected": ["B:pitch"],
    },
    {
        "id": "master_and_monitoring",
        "title": "Master & Headphone Knobs",
        "prompt": "Turn Master volume knob, Headphone volume knob, and toggle Master button (if present).",
        "duration": 6.0,
        "expected": ["master_volume", "headphone_volume", "master_button"],
    },
    {
        "id": "deck_a_pads",
        "title": "Deck A Performance Pads",
        "prompt": "Press Pad mode buttons (HotCue, Roll, FX, Sampler), then tap Pads 1, 2, 3, 4.",
        "duration": 8.0,
        "expected": ["A:pad1", "A:pad2", "A:pad3", "A:pad4"],
    },
    {
        "id": "deck_b_pads",
        "title": "Deck B Performance Pads",
        "prompt": "Press Pad mode buttons (HotCue, Roll, FX, Sampler), then tap Pads 1, 2, 3, 4.",
        "duration": 8.0,
        "expected": ["B:pad1", "B:pad2", "B:pad3", "B:pad4"],
    },
]


def choose_midi_port(names: list[str]) -> str:
    """Find the single matching Hercules DJControl Inpulse 200 Mk2 MIDI port name."""
    matches = [name for name in names if DEVICE_TOKEN.casefold() in name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {DEVICE_TOKEN} MIDI port; found {matches!r}")
    return matches[0]


def lookup_provisional_mapping(status: int, num: int) -> tuple[str | None, str | None, str]:
    """Look up prior mapping without claiming proof; returns (name, deck, source)."""
    try:
        from tools.inpulse_protocol import PRIOR_TABLE

        ctl = PRIOR_TABLE.get((status, num))
        if ctl:
            return ctl.name, ctl.deck, ctl.source
    except Exception:
        pass
    return None, None, "UNMAPPED"


def format_event_record(
    t_seconds: float,
    raw_bytes: list[int],
    msg_str: str,
    phase: str,
    prompt: str,
) -> dict[str, Any]:
    """Build standardized, timestamped evidence record with provenance annotation."""
    status, num, val = raw_bytes
    prov_name, prov_deck, prov_src = lookup_provisional_mapping(status, num)

    return {
        "t_seconds": round(t_seconds, 6),
        "bytes": raw_bytes,
        "channel": status & 0x0F,
        "status_hex": f"0x{status:02X}",
        "message": msg_str,
        "phase": phase,
        "prompt": prompt,
        "provisional_id": prov_name,
        "deck": prov_deck,
        "provenance": prov_src,
    }


def record(
    duration: float = 10.0,
    output: str | None = None,
    guided: bool = False,
    step_timeout: float | None = None,
    dry_run: bool = False,
    port_name: str | None = None,
) -> int:
    """Execute bounded read-only MIDI capture.
    
    Safe by design:
      - Uses only open_input (never opens outputs, never generates data)
      - Refuses to overwrite existing output files
      - Catches KeyboardInterrupt to preserve captured data up to termination
    """
    path = Path(output) if output else None
    if path:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite prior evidence: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("[DRY-RUN] Safe simulation mode: no MIDI port will be opened.", flush=True)
        print(f"[DRY-RUN] Target Device: {DEVICE_TOKEN}", flush=True)
        print(f"[DRY-RUN] Evidence Output: {path or 'stdout (no file)'}", flush=True)
        if guided:
            print(f"[DRY-RUN] Guided sequence contains {len(GESTURE_STEPS)} gesture steps:", flush=True)
            for idx, step in enumerate(GESTURE_STEPS, 1):
                t_step = step_timeout or step["duration"]
                print(f"  {idx:2d}. [{t_step:4.1f}s] {step['title']}: {step['prompt']}", flush=True)
        else:
            print(f"[DRY-RUN] Freeform capture duration: {duration}s", flush=True)
        print("[DRY-RUN] Simulated capture completed successfully. 0 events recorded.", flush=True)
        return 0

    import mido
    import mido.backends.rtmidi  # noqa: F401 -- ensure RtMidi backend is available

    if port_name:
        name = port_name
    else:
        name = choose_midi_port(mido.get_input_names())

    count = 0
    start = time.monotonic()
    print(f"READ_ONLY_MIDI_PORT={name!r} mode={'guided' if guided else 'freeform'}; firmware/audio unchanged", flush=True)

    try:
        with mido.open_input(name) as port:
            with path.open("x", encoding="utf-8") if path else open("/dev/null", "w") as stream:
                if guided:
                    total_steps = len(GESTURE_STEPS)
                    print("\n=======================================================", flush=True)
                    print("  HERCULES DJCONTROL INPULSE 200 MK2 HARDWARE ACCEPTANCE", flush=True)
                    print("  Safe, passive capture session with real user gestures", flush=True)
                    print("  (Press Ctrl+C at any time to finish cleanly)", flush=True)
                    print("=======================================================\n", flush=True)

                    for idx, step in enumerate(GESTURE_STEPS, 1):
                        step_time = step_timeout or step["duration"]
                        print(f"--- [Step {idx}/{total_steps}] {step['title']} ({step_time:.1f}s) ---", flush=True)
                        print(f"ACTION: {step['prompt']}", flush=True)
                        print("Recording... ", end="", flush=True)

                        step_start = time.monotonic()
                        step_events = 0
                        while time.monotonic() - step_start < step_time:
                            for msg in port.iter_pending():
                                raw = list(msg.bytes())
                                t_rel = time.monotonic() - start
                                event = format_event_record(
                                    t_rel, raw, str(msg), step["id"], step["title"]
                                )
                                line = json.dumps(event)
                                print(line, flush=True)
                                if path:
                                    stream.write(line + "\n")
                                    stream.flush()
                                count += 1
                                step_events += 1
                            time.sleep(0.01)

                        print(f"-> {step_events} events captured in this step.\n", flush=True)
                else:
                    while time.monotonic() - start < duration:
                        for msg in port.iter_pending():
                            raw = list(msg.bytes())
                            t_rel = time.monotonic() - start
                            event = format_event_record(
                                t_rel, raw, str(msg), "freeform", "Freeform capture"
                            )
                            line = json.dumps(event)
                            print(line, flush=True)
                            if path:
                                stream.write(line + "\n")
                                stream.flush()
                            count += 1
                        time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Capture stopped by user. Flushing and preserving recorded evidence.", flush=True)

    print(f"READ_ONLY_CAPTURE_COMPLETE events={count}", flush=True)
    return count


def list_ports() -> None:
    """Print available MIDI input ports safely without opening any."""
    import mido

    names = mido.get_input_names()
    print("Available MIDI input ports:")
    if not names:
        print("  (none detected)")
        return

    for n in names:
        is_target = DEVICE_TOKEN.casefold() in n.casefold()
        marker = " [TARGET HERCULES MK2]" if is_target else ""
        print(f"  - {n}{marker}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duration", type=float, default=10.0, help="Freeform capture duration in seconds (0 < d <= 300)")
    p.add_argument("--output", default=None, help="Output JSONL path (fails if file already exists)")
    p.add_argument("--guided", action="store_true", help="Run guided step-by-step gesture acceptance sequence")
    p.add_argument("--step-timeout", type=float, default=None, help="Override per-step duration in guided mode (seconds)")
    p.add_argument("--dry-run", action="store_true", help="Simulate capture prompts without opening any MIDI port")
    p.add_argument("--list-ports", action="store_true", help="List available MIDI ports safely and exit")
    p.add_argument("--port", default=None, help="Explicit port name (defaults to auto-discovering Hercules Mk2)")
    args = p.parse_args()

    if args.list_ports:
        list_ports()
        return 0

    if not 0 < args.duration <= 300:
        p.error("duration must be >0 and <=300 seconds")

    if args.step_timeout is not None and not (1.0 <= args.step_timeout <= 60.0):
        p.error("step-timeout must be between 1.0 and 60.0 seconds")

    try:
        record(
            duration=args.duration,
            output=args.output,
            guided=args.guided,
            step_timeout=args.step_timeout,
            dry_run=args.dry_run,
            port_name=args.port,
        )
        return 0
    except (ValueError, FileExistsError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Offline replay validator for Hercules DJControl Inpulse 200 Mk2 MIDI capture files.

Analyzes recorded JSONL evidence without opening any MIDI/audio port or device.
Verifies:
  1. Timestamp monotonicity and duration bounds
  2. Byte sequence integrity (valid 3-byte channel voice, no data byte high bits)
  3. No feedback / no loopback / no system real-time or SysEx pollution
  4. Ambiguous channel detection and cross-deck collisions
  5. Relative control delta analysis (jog wheels, browser encoder)
  6. 14-bit fader pairing (MSB/LSB continuity and full endpoint travel)
  7. Button press/release pairing (detection of stuck or unreleased buttons)
  8. Clean handling of device absence / empty captures and interrupted streams
  9. Strict provenance accounting: guessed mappings are never claimed proven

Usage:
  python3 tools/replay_validator.py evidence/capture.jsonl [--markdown] [--json] [--strict]
"""
import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from tools.inpulse_protocol import (
        ABS7,
        ABS14_LSB,
        ABS14_MSB,
        BUTTON,
        LIVE_AUG25,
        PRIOR_MK1,
        PRIOR_TABLE,
        REL7,
        SOURCE_AUG25,
        TIERS,
        Control,
        signed7,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.inpulse_protocol import (
        ABS7,
        ABS14_LSB,
        ABS14_MSB,
        BUTTON,
        LIVE_AUG25,
        PRIOR_MK1,
        PRIOR_TABLE,
        REL7,
        SOURCE_AUG25,
        TIERS,
        Control,
        signed7,
    )

# Known Hercules channel bounds (0-based nibble 0..7)
KNOWN_HERCULES_CHANNELS = {0, 1, 2, 3, 4, 5, 6, 7}


@dataclass
class FaderAnalysis:
    control_name: str
    deck: str | None
    msb_count: int = 0
    lsb_count: int = 0
    orphaned_lsb_count: int = 0
    min_position: int | None = None
    max_position: int | None = None
    samples_14bit: list[int] = field(default_factory=list)
    min_endpoint_reached: bool = False  # <= 128
    max_endpoint_reached: bool = False  # >= 16256


@dataclass
class RelativeAnalysis:
    control_name: str
    deck: str | None
    tick_count: int = 0
    cw_count: int = 0
    ccw_count: int = 0
    zero_ticks: int = 0
    max_cw_delta: int = 0
    max_ccw_delta: int = 0
    raw_values: list[int] = field(default_factory=list)
    absolute_ramp_detected: bool = False
    excessive_deltas: list[int] = field(default_factory=list)


@dataclass
class ButtonAnalysis:
    control_name: str
    deck: str | None
    press_count: int = 0
    release_count: int = 0
    stuck_unreleased: bool = False
    orphaned_release_count: int = 0


@dataclass
class ValidationReport:
    file_path: str
    valid: bool
    total_events: int
    duration_seconds: float
    fatal_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unique_channels: list[int] = field(default_factory=list)
    known_events_count: int = 0
    unknown_events_count: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    faders: dict[str, dict[str, Any]] = field(default_factory=dict)
    relatives: dict[str, dict[str, Any]] = field(default_factory=dict)
    buttons: dict[str, dict[str, Any]] = field(default_factory=dict)
    unknown_controls: dict[str, int] = field(default_factory=dict)
    gestures_detected: list[str] = field(default_factory=list)
    is_empty_or_absent: bool = False
    is_interrupted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReplayValidator:
    """Offline replay and integrity validator for MIDI capture evidence."""

    def __init__(self, table: dict[tuple[int, int], Control] | None = None):
        self.table = PRIOR_TABLE if table is None else table

    def validate_file(self, path: Path | str, strict: bool = False) -> ValidationReport:
        p = Path(path)
        if not p.exists():
            return ValidationReport(
                file_path=str(path),
                valid=False,
                total_events=0,
                duration_seconds=0.0,
                fatal_errors=[f"FILE_NOT_FOUND: {path}"],
                is_empty_or_absent=True,
            )

        content = p.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip()]

        if not lines:
            return ValidationReport(
                file_path=str(path),
                valid=True,
                total_events=0,
                duration_seconds=0.0,
                warnings=["DEVICE_ABSENT_OR_EMPTY: Capture file contains 0 events."],
                is_empty_or_absent=True,
            )

        fatal_errors: list[str] = []
        warnings: list[str] = []
        parsed_records: list[tuple[float, list[int], dict[str, Any]]] = []

        # 1. Parse JSONL & Byte Validity
        for lineno, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except Exception as exc:
                fatal_errors.append(f"MALFORMED_JSON: line {lineno}: {exc}")
                continue

            if "t_seconds" not in rec or "bytes" not in rec:
                fatal_errors.append(
                    f"MISSING_REQUIRED_FIELDS: line {lineno}: required 't_seconds' and 'bytes'"
                )
                continue

            t_sec = rec["t_seconds"]
            raw_bytes = rec["bytes"]

            if not isinstance(t_sec, (int, float)):
                fatal_errors.append(f"INVALID_TIMESTAMP_TYPE: line {lineno}: {type(t_sec)}")
                continue

            if not isinstance(raw_bytes, list) or len(raw_bytes) != 3:
                fatal_errors.append(
                    f"MALFORMED_BYTE_LENGTH: line {lineno}: expected 3 bytes, got {raw_bytes!r}"
                )
                continue

            parsed_records.append((float(t_sec), [int(b) for b in raw_bytes], rec))

        if fatal_errors:
            return ValidationReport(
                file_path=str(path),
                valid=False,
                total_events=len(parsed_records),
                duration_seconds=0.0,
                fatal_errors=fatal_errors,
                warnings=warnings,
            )

        # 2. Timestamp Monotonicity & Duration Checks
        prev_t = 0.0
        for lineno, (t_sec, raw_bytes, _) in enumerate(parsed_records, 1):
            if lineno == 1:
                if t_sec < 0.0:
                    fatal_errors.append(f"NEGATIVE_TIMESTAMP: line 1: {t_sec}s")
                prev_t = t_sec
                continue

            if t_sec < prev_t:
                delta = t_sec - prev_t
                fatal_errors.append(
                    f"TIMESTAMP_NON_MONOTONIC: line {lineno}: t={t_sec:.6f}s < prev={prev_t:.6f}s (delta: {delta:.6f}s)"
                )
            prev_t = t_sec

        start_time = parsed_records[0][0]
        end_time = parsed_records[-1][0]
        duration = max(0.0, end_time - start_time)

        if duration > 600.0:
            warnings.append(f"DURATION_EXCEEDS_RECOMMENDED_BOUNDS: duration={duration:.2f}s > 600s")

        # 3. Protocol, Feedback, and Channel Checks
        unique_channels: set[int] = set()
        by_source: dict[str, int] = {}
        known_events_count = 0
        unknown_events_count = 0
        unknown_controls: dict[str, int] = {}

        fader_state: dict[tuple[str | None, str], FaderAnalysis] = {}
        rel_state: dict[tuple[str | None, str], RelativeAnalysis] = {}
        btn_state: dict[tuple[str | None, str], ButtonAnalysis] = {}
        held_buttons: set[tuple[str | None, str]] = set()
        active_msb: dict[tuple[str | None, str], int] = {}

        for lineno, (t_sec, raw_bytes, rec) in enumerate(parsed_records, 1):
            status, num, val = raw_bytes

            # Check 3.1: No Feedback / No Output / No System Real-time
            if status >= 0xF0:
                msg_name = {
                    0xF0: "SysEx_Start",
                    0xF7: "SysEx_End",
                    0xF8: "MIDI_Clock",
                    0xFA: "MIDI_Start",
                    0xFB: "MIDI_Continue",
                    0xFC: "MIDI_Stop",
                    0xFE: "Active_Sensing",
                    0xFF: "System_Reset",
                }.get(status, f"System_0x{status:02X}")
                fatal_errors.append(
                    f"FORBIDDEN_FEEDBACK_OR_SYSTEM_MSG: line {lineno}: status 0x{status:02X} ({msg_name}) detected in passive capture"
                )
                continue

            # Check 3.2: Valid Channel Voice Range
            if status < 0x80:
                fatal_errors.append(f"INVALID_STATUS_BYTE: line {lineno}: status 0x{status:02X} < 0x80")
                continue

            # Check 3.3: Data bytes <= 127
            if num > 127 or val > 127:
                fatal_errors.append(
                    f"DATA_BYTE_HIGH_BIT_SET: line {lineno}: status=0x{status:02X} num={num} val={val}"
                )
                continue

            ch = status & 0x0F
            unique_channels.add(ch)

            # Check 3.4: Channel Ambiguity
            if ch not in KNOWN_HERCULES_CHANNELS:
                warnings.append(
                    f"AMBIGUOUS_UNEXPECTED_CHANNEL: line {lineno}: status 0x{status:02X} on unexpected MIDI channel {ch}"
                )

            # Normalize note-off (0x8N -> 0x9N with val=0)
            is_note_off = (status & 0xF0) == 0x80
            lookup_status = (0x90 | ch) if is_note_off else status
            lookup_val = 0 if is_note_off else val

            ctl = self.table.get((lookup_status, num))

            if ctl is None:
                unknown_events_count += 1
                key = f"0x{status:02X}/0x{num:02X}"
                unknown_controls[key] = unknown_controls.get(key, 0) + 1
                continue

            known_events_count += 1
            by_source[ctl.source] = by_source.get(ctl.source, 0) + 1

            ctl_key = (ctl.deck, ctl.name)

            # Check 3.5: Channel crossover check
            # Raw 0-based status channels: A normal/shift/pads = 1/4/6;
            # B normal/shift/pads = 2/5/7.  The previous check incorrectly
            # treated pad channel 6 as a crossover and accepted 6 on Deck B.
            expected_deck_channels = {"A": {1, 4, 6}, "B": {2, 5, 7}}
            if ctl.deck in expected_deck_channels and ch not in expected_deck_channels[ctl.deck]:
                warnings.append(
                    f"AMBIGUOUS_CHANNEL_CROSSOVER: line {lineno}: Deck {ctl.deck} control '{ctl.name}' emitted on channel {ch}"
                )

            # Check 3.6: 14-bit Faders
            if ctl.kind in (ABS14_MSB, ABS14_LSB):
                fader = fader_state.setdefault(
                    ctl_key, FaderAnalysis(control_name=ctl.name, deck=ctl.deck)
                )
                if ctl.kind == ABS14_MSB:
                    fader.msb_count += 1
                    active_msb[ctl_key] = val
                else:  # ABS14_LSB
                    fader.lsb_count += 1
                    msb = active_msb.get(ctl_key)
                    if msb is None:
                        fader.orphaned_lsb_count += 1
                        warnings.append(
                            f"ORPHANED_14BIT_LSB: line {lineno}: {ctl.deck}:{ctl.name} LSB {val} arrived without MSB"
                        )
                    else:
                        pos = (msb << 7) | val
                        fader.samples_14bit.append(pos)
                        if fader.min_position is None or pos < fader.min_position:
                            fader.min_position = pos
                        if fader.max_position is None or pos > fader.max_position:
                            fader.max_position = pos
                        if pos <= 128:
                            fader.min_endpoint_reached = True
                        if pos >= 16256:
                            fader.max_endpoint_reached = True

            # Check 3.7: Relative Controls
            elif ctl.kind == REL7:
                rel = rel_state.setdefault(
                    ctl_key, RelativeAnalysis(control_name=ctl.name, deck=ctl.deck)
                )
                rel.tick_count += 1
                rel.raw_values.append(val)
                delta = signed7(val)

                if delta == 0:
                    rel.zero_ticks += 1
                    warnings.append(
                        f"RELATIVE_ZERO_DELTA: line {lineno}: {ctl.deck}:{ctl.name} emitted delta 0"
                    )
                elif delta > 0:
                    rel.cw_count += 1
                    if delta > rel.max_cw_delta:
                        rel.max_cw_delta = delta
                    if delta > 32:
                        rel.excessive_deltas.append(delta)
                        warnings.append(
                            f"RELATIVE_DELTA_OUT_OF_BOUNDS: line {lineno}: {ctl.deck}:{ctl.name} excessive CW delta {delta}"
                        )
                else:
                    rel.ccw_count += 1
                    if abs(delta) > rel.max_ccw_delta:
                        rel.max_ccw_delta = abs(delta)
                    if abs(delta) > 32:
                        rel.excessive_deltas.append(delta)
                        warnings.append(
                            f"RELATIVE_DELTA_OUT_OF_BOUNDS: line {lineno}: {ctl.deck}:{ctl.name} excessive CCW delta {delta}"
                        )

            # Check 3.8: Buttons
            elif ctl.kind == BUTTON:
                btn = btn_state.setdefault(
                    ctl_key, ButtonAnalysis(control_name=ctl.name, deck=ctl.deck)
                )
                pressed = (lookup_val > 0) and not is_note_off
                if pressed:
                    btn.press_count += 1
                    held_buttons.add(ctl_key)
                else:
                    btn.release_count += 1
                    if ctl_key in held_buttons:
                        held_buttons.remove(ctl_key)
                    else:
                        btn.orphaned_release_count += 1
                        warnings.append(
                            f"ORPHANED_BUTTON_RELEASE: line {lineno}: {ctl.deck}:{ctl.name} released without press"
                        )

        # Check for absolute sweep progression on relative controls
        for ctl_key, rel in rel_state.items():
            if len(rel.raw_values) >= 4:
                vals = rel.raw_values
                # Check if values form an absolute ramp: 0, 32, 64, 96, 127
                is_ramp = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
                if is_ramp and (vals[-1] - vals[0] > 60):
                    rel.absolute_ramp_detected = True
                    warnings.append(
                        f"AMBIGUOUS_RELATIVE_ABSOLUTE_SWEEP: {rel.deck}:{rel.control_name} received absolute ramp values {vals!r}"
                    )

        # Check for stuck / unreleased buttons
        is_interrupted = False
        if held_buttons:
            is_interrupted = True
            for ctl_key in held_buttons:
                if ctl_key in btn_state:
                    btn_state[ctl_key].stuck_unreleased = True
                    warnings.append(
                        f"STUCK_BUTTON: {ctl_key[0]}:{ctl_key[1]} remained pressed at end of capture"
                    )

        # Check for incomplete / orphaned MSB at end
        for ctl_key, msb_val in active_msb.items():
            fader = fader_state.get(ctl_key)
            if fader and fader.msb_count > fader.lsb_count:
                is_interrupted = True
                warnings.append(
                    f"INTERRUPTED_14BIT_STREAM: {ctl_key[0]}:{ctl_key[1]} has uncompleted MSB={msb_val}"
                )

        # Detect Gestures
        gestures_detected: list[str] = []
        for ctl_key, fader in fader_state.items():
            deck_str = f"Deck {fader.deck}" if fader.deck else "Global"
            if fader.samples_14bit:
                gestures_detected.append(
                    f"{deck_str} {fader.control_name.capitalize()} (range {fader.min_position}..{fader.max_position})"
                )

        for ctl_key, rel in rel_state.items():
            deck_str = f"Deck {rel.deck}" if rel.deck else "Global"
            if rel.cw_count > 0:
                gestures_detected.append(f"{deck_str} {rel.control_name} Spin CW ({rel.cw_count} ticks)")
            if rel.ccw_count > 0:
                gestures_detected.append(f"{deck_str} {rel.control_name} Spin CCW ({rel.ccw_count} ticks)")

        for ctl_key, btn in btn_state.items():
            deck_str = f"Deck {btn.deck}" if btn.deck else "Global"
            if btn.press_count > 0:
                gestures_detected.append(f"{deck_str} {btn.control_name} Press ({btn.press_count}x)")

        # Serialize summaries
        faders_dict = {
            f"{k[0] or '-'}:{k[1]}": asdict(v) for k, v in fader_state.items()
        }
        rel_dict = {
            f"{k[0] or '-'}:{k[1]}": asdict(v) for k, v in rel_state.items()
        }
        btn_dict = {
            f"{k[0] or '-'}:{k[1]}": asdict(v) for k, v in btn_state.items()
        }

        is_valid = len(fatal_errors) == 0
        if strict and len(warnings) > 0:
            is_valid = False

        return ValidationReport(
            file_path=str(path),
            valid=is_valid,
            total_events=len(parsed_records),
            duration_seconds=round(duration, 4),
            fatal_errors=fatal_errors,
            warnings=warnings,
            unique_channels=sorted(unique_channels),
            known_events_count=known_events_count,
            unknown_events_count=unknown_events_count,
            by_source=by_source,
            faders=faders_dict,
            relatives=rel_dict,
            buttons=btn_dict,
            unknown_controls=unknown_controls,
            gestures_detected=gestures_detected,
            is_empty_or_absent=False,
            is_interrupted=is_interrupted,
        )


def format_markdown_report(rep: ValidationReport) -> str:
    """Format a comprehensive Markdown hardware acceptance report."""
    verdict = "PASS" if rep.valid else "FAIL"
    status_emoji = "PASS" if rep.valid else "FAIL"

    md = [
        f"# Hercules DJControl Inpulse 200 Mk2 Replay Acceptance Report",
        "",
        f"- **Evidence File:** `{rep.file_path}`",
        f"- **Status / Verdict:** **{verdict}**",
        f"- **Total Events:** {rep.total_events}",
        f"- **Duration:** {rep.duration_seconds:.3f} s",
        f"- **Unique Channels Observed:** {rep.unique_channels}",
        f"- **Known Events:** {rep.known_events_count}",
        f"- **Unknown / Unmapped Events:** {rep.unknown_events_count}",
        "",
        "## Integrity & Safety Verification",
        "",
        f"- **Timestamp Monotonicity:** {'PASS' if not any('TIMESTAMP' in e for e in rep.fatal_errors) else 'FAIL'}",
        f"- **No Feedback / No Output Pollution:** {'PASS' if not any('FEEDBACK' in e for e in rep.fatal_errors) else 'FAIL'}",
        f"- **Channel Ambiguity:** {'PASS' if not any('AMBIGUOUS' in w for w in rep.warnings) else 'WARNING'}",
        f"- **Interrupted Session / Stuck Buttons:** {'CLEAN' if not rep.is_interrupted else 'INTERRUPTED'}",
        "",
    ]

    if rep.fatal_errors:
        md.append("### Fatal Errors (Gating Rejection)")
        md.append("")
        for err in rep.fatal_errors:
            md.append(f"- [ERROR] {err}")
        md.append("")

    if rep.warnings:
        md.append("### Anomalies & Triage Warnings")
        md.append("")
        for w in rep.warnings[:25]:  # limit to first 25
            md.append(f"- [WARN] {w}")
        if len(rep.warnings) > 25:
            md.append(f"- ... and {len(rep.warnings) - 25} more warnings.")
        md.append("")

    # Faders Table
    md.append("## 14-bit Faders Analysis")
    md.append("")
    if rep.faders:
        md.append("| Control | Deck | MSB Count | LSB Count | Range | Min Reached | Max Reached |")
        md.append("|---|---|---|---|---|---|---|")
        for key, f in rep.faders.items():
            deck = f["deck"] or "Global"
            min_r = "YES" if f["min_endpoint_reached"] else "NO"
            max_r = "YES" if f["max_endpoint_reached"] else "NO"
            rng = f"{f['min_position']}..{f['max_position']}" if f["min_position"] is not None else "None"
            md.append(f"| `{f['control_name']}` | {deck} | {f['msb_count']} | {f['lsb_count']} | `{rng}` | {min_r} | {max_r} |")
        md.append("")
    else:
        md.append("No 14-bit fader events recorded.\n")

    # Relative Controls Table
    md.append("## Relative Controls Analysis (Jogs & Encoders)")
    md.append("")
    if rep.relatives:
        md.append("| Control | Deck | Total Ticks | CW Ticks | CCW Ticks | Max CW Delta | Max CCW Delta | Ramp Detected |")
        md.append("|---|---|---|---|---|---|---|---|")
        for key, r in rep.relatives.items():
            deck = r["deck"] or "Global"
            ramp = "YES (ANOMALY)" if r["absolute_ramp_detected"] else "NO"
            md.append(f"| `{r['control_name']}` | {deck} | {r['tick_count']} | {r['cw_count']} | {r['ccw_count']} | +{r['max_cw_delta']} | -{r['max_ccw_delta']} | {ramp} |")
        md.append("")
    else:
        md.append("No relative control events recorded.\n")

    # Buttons Table
    md.append("## Buttons Analysis")
    md.append("")
    if rep.buttons:
        md.append("| Button | Deck | Presses | Releases | Stuck / Unreleased |")
        md.append("|---|---|---|---|---|")
        for key, b in rep.buttons.items():
            deck = b["deck"] or "Global"
            stuck = "YES (STUCK)" if b["stuck_unreleased"] else "NO"
            md.append(f"| `{b['control_name']}` | {deck} | {b['press_count']} | {b['release_count']} | {stuck} |")
        md.append("")
    else:
        md.append("No button events recorded.\n")

    # Unknown Controls Triage
    if rep.unknown_controls:
        md.append("## Unmapped Controls Triage")
        md.append("")
        md.append("| Status/Number | Event Count |")
        md.append("|---|---|")
        for ctl_hex, count in sorted(rep.unknown_controls.items()):
            md.append(f"| `{ctl_hex}` | {count} |")
        md.append("")

    # Gestures Recognized
    if rep.gestures_detected:
        md.append("## Recognized Gestures")
        md.append("")
        for g in rep.gestures_detected:
            md.append(f"- {g}")
        md.append("")

    md.append("## Provenance Accountability")
    md.append("")
    md.append("> [!IMPORTANT]")
    md.append("> **Honesty Gate**: Guessed mappings are **NEVER** claimed proven.")
    md.append("> Only controls backed by verified physical capture evidence are marked as confirmed for Mk2.")
    md.append("")
    for source, count in sorted(rep.by_source.items()):
        md.append(f"- **{source}**: {count} events")
    md.append("")

    return "\n".join(md)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", help="Path to evidence JSONL file")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument("--strict", action="store_true", help="Fail if any warnings present")
    parser.add_argument("--output", "-o", default=None, help="Save report to file")
    args = parser.parse_args(argv[1:])

    validator = ReplayValidator()
    rep = validator.validate_file(args.evidence, strict=args.strict)

    if args.json:
        out = json.dumps(rep.to_dict(), indent=2)
    else:
        out = format_markdown_report(rep)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(out)

    return 0 if rep.valid else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

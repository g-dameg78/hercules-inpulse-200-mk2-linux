import io
import json
import tokenize
import unittest
from pathlib import Path

from tools.replay_validator import (
    ReplayValidator,
    format_markdown_report,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def code_names(path: Path) -> set[str]:
    """Extract identifier names from a Python source file, ignoring comments/docstrings."""
    toks = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
    return {t.string for t in toks if t.type == tokenize.NAME}


class ReplayValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = ReplayValidator()

    def test_clean_session_acceptance_passes_and_extracts_report(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_clean_acceptance.jsonl")
        self.assertTrue(rep.valid, f"Expected valid report; fatal errors: {rep.fatal_errors}")
        self.assertEqual(rep.fatal_errors, [])
        self.assertEqual(rep.total_events, 49)
        self.assertAlmostEqual(rep.duration_seconds, 8.0, places=3)

        # Faders analysis
        self.assertIn("A:volume", rep.faders)
        f_a = rep.faders["A:volume"]
        self.assertEqual(f_a["min_position"], 0)
        self.assertEqual(f_a["max_position"], 16383)
        self.assertTrue(f_a["min_endpoint_reached"])
        self.assertTrue(f_a["max_endpoint_reached"])

        self.assertIn("B:volume", rep.faders)
        f_b = rep.faders["B:volume"]
        self.assertEqual(f_b["min_position"], 0)
        self.assertEqual(f_b["max_position"], 16383)
        self.assertTrue(f_b["min_endpoint_reached"])
        self.assertTrue(f_b["max_endpoint_reached"])

        self.assertIn("-:crossfader", rep.faders)
        f_xf = rep.faders["-:crossfader"]
        self.assertEqual(f_xf["min_position"], 0)
        self.assertEqual(f_xf["max_position"], 16383)
        self.assertTrue(f_xf["min_endpoint_reached"])
        self.assertTrue(f_xf["max_endpoint_reached"])

        # Relative controls
        self.assertIn("A:jog_top", rep.relatives)
        r_a = rep.relatives["A:jog_top"]
        self.assertEqual(r_a["tick_count"], 4)
        self.assertEqual(r_a["cw_count"], 2)
        self.assertEqual(r_a["ccw_count"], 2)
        self.assertFalse(r_a["absolute_ramp_detected"])

        self.assertIn("B:jog_top", rep.relatives)
        r_b = rep.relatives["B:jog_top"]
        self.assertEqual(r_b["cw_count"], 1)
        self.assertEqual(r_b["ccw_count"], 1)

        self.assertIn("-:browser_encoder", rep.relatives)

        # Buttons
        for btn_key in ("A:play", "A:cue", "A:load", "B:play", "-:browser_push"):
            self.assertIn(btn_key, rep.buttons)
            self.assertEqual(rep.buttons[btn_key]["press_count"], 1)
            self.assertEqual(rep.buttons[btn_key]["release_count"], 1)
            self.assertFalse(rep.buttons[btn_key]["stuck_unreleased"])

        # Touch sensor
        self.assertEqual(rep.buttons["A:jog_touch"]["press_count"], 1)
        self.assertEqual(rep.buttons["A:jog_touch"]["release_count"], 1)

        # Report formatting
        md = format_markdown_report(rep)
        self.assertIn("Status / Verdict:** **PASS**", md)
        self.assertIn("14-bit Faders Analysis", md)
        self.assertIn("Relative Controls Analysis", md)
        self.assertIn("Honesty Gate", md)

        # JSON serializability
        d = rep.to_dict()
        dumped = json.dumps(d)
        self.assertIn("synthetic_clean_acceptance.jsonl", dumped)

    def test_published_and_captured_mk2_pad_channels_are_not_crossovers(self):
        # Actual Mk2 uses note channel 6 (status 0x96) for Deck A pads,
        # channel 7 (0x97) for Deck B. Verify both without opening hardware.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            capture = Path(d) / "pads.jsonl"
            samples = [
                (0.01, [0x96, 0, 127]), (0.02, [0x96, 0, 0]),
                (0.03, [0x97, 0, 127]), (0.04, [0x97, 0, 0]),
            ]
            capture.write_text("".join(
                json.dumps({"t_seconds": t, "bytes": raw}) + "\n"
                for t, raw in samples
            ))
            rep = self.validator.validate_file(capture)
            self.assertTrue(rep.valid)
            self.assertEqual(rep.total_events, 4)
            self.assertIn("A:pad1", rep.buttons)
            self.assertIn("B:pad1", rep.buttons)
            self.assertFalse(any("AMBIGUOUS_CHANNEL_CROSSOVER" in w for w in rep.warnings))

    def test_mk2_filter_and_eq_knobs_have_14bit_cc_pairs(self):
        from tools.inpulse_protocol import Decoder
        dec = Decoder()
        for status in (0xB1, 0xB2):
            for number in (1, 2, 4, 5):
                msb = dec.decode([status, number, 127])
                lsb = dec.decode([status, number + 32, 127])
                self.assertEqual(msb.control.name, lsb.control.name)
                self.assertEqual(lsb.position14, 16383)

    def test_non_monotonic_timestamps_detected(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_non_monotonic_time.jsonl")
        self.assertFalse(rep.valid)
        self.assertTrue(any("TIMESTAMP_NON_MONOTONIC" in err for err in rep.fatal_errors))

    def test_ambiguous_channel_detected(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_ambiguous_channel.jsonl")
        self.assertTrue(any("AMBIGUOUS_UNEXPECTED_CHANNEL" in w for w in rep.warnings))
        strict_rep = self.validator.validate_file(
            FIXTURES / "synthetic_ambiguous_channel.jsonl", strict=True
        )
        self.assertFalse(strict_rep.valid)

    def test_ambiguous_relative_sweep_and_excessive_delta_detected(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_ambiguous_relative.jsonl")
        self.assertTrue(any("AMBIGUOUS_RELATIVE_ABSOLUTE_SWEEP" in w for w in rep.warnings))
        self.assertTrue(any("RELATIVE_DELTA_OUT_OF_BOUNDS" in w for w in rep.warnings))
        self.assertTrue(rep.relatives["A:jog_top"]["absolute_ramp_detected"])

    def test_forbidden_feedback_or_system_msg_detected(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_feedback_pollution.jsonl")
        self.assertFalse(rep.valid)
        feedback_errors = [e for e in rep.fatal_errors if "FORBIDDEN_FEEDBACK_OR_SYSTEM_MSG" in e]
        self.assertEqual(len(feedback_errors), 2)
        self.assertTrue(any("Active_Sensing" in e for e in feedback_errors))
        self.assertTrue(any("MIDI_Clock" in e for e in feedback_errors))

    def test_interrupted_session_detects_stuck_buttons_and_orphaned_msb(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_interrupted_session.jsonl")
        self.assertTrue(rep.is_interrupted)
        self.assertTrue(any("STUCK_BUTTON" in w for w in rep.warnings))
        self.assertTrue(any("INTERRUPTED_14BIT_STREAM" in w for w in rep.warnings))
        self.assertTrue(rep.buttons["A:play"]["stuck_unreleased"])

    def test_clean_device_absence_and_empty_capture(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_empty_device_absence.jsonl")
        self.assertTrue(rep.valid)
        self.assertTrue(rep.is_empty_or_absent)
        self.assertEqual(rep.total_events, 0)
        self.assertTrue(any("DEVICE_ABSENT_OR_EMPTY" in w for w in rep.warnings))

    def test_unmapped_controls_triage_and_provenance_honesty(self):
        rep = self.validator.validate_file(FIXTURES / "synthetic_unmapped_controls.jsonl")
        self.assertIn("0xB0/0x03", rep.unknown_controls)
        self.assertIn("0xB1/0x03", rep.unknown_controls)
        md = format_markdown_report(rep)
        self.assertIn("Unmapped Controls Triage", md)
        self.assertIn("0xB0/0x03", md)
        self.assertIn("Guessed mappings are **NEVER** claimed proven.", md)

    def test_replay_validator_no_output_or_exec_tokens(self):
        names = code_names(ROOT / "tools/replay_validator.py")
        forbidden = names & {
            "mido",
            "rtmidi",
            "open_output",
            "send",
            "sendShortMsg",
            "sysex",
            "subprocess",
            "open_ioport",
        }
        self.assertFalse(forbidden, f"Forbidden output/execution tokens found: {forbidden}")


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.midi_capture import (
    DEVICE_TOKEN,
    GESTURE_STEPS,
    choose_midi_port,
    format_event_record,
    record,
)

ROOT = Path(__file__).resolve().parents[1]


def code_names(path: Path) -> set[str]:
    """Extract identifier names from a Python source file, ignoring comments/docstrings."""
    toks = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
    return {t.string for t in toks if t.type == tokenize.NAME}


class ChoosePortTest(unittest.TestCase):
    def test_identifies_mk2_and_not_mk1(self):
        self.assertEqual(
            choose_midi_port(["AKAI MPK mini 3", "DJControl Inpulse 200 Mk2 MIDI 36:0"]),
            "DJControl Inpulse 200 Mk2 MIDI 36:0",
        )

    def test_absent_fails_closed(self):
        with self.assertRaises(ValueError):
            choose_midi_port(["DJControl Inpulse 200 MIDI", "Felucca MIDI"])

    def test_duplicate_fails_closed(self):
        with self.assertRaises(ValueError):
            choose_midi_port(
                ["DJControl Inpulse 200 Mk2 MIDI 36:0", "DJControl Inpulse 200 Mk2 MIDI 37:0"]
            )


class CaptureSafetyTest(unittest.TestCase):
    def test_no_output_methods_or_forbidden_tokens(self):
        names = code_names(ROOT / "tools/midi_capture.py")
        self.assertIn("open_input", names)
        forbidden = names & {"open_output", "send", "open_ioport", "subprocess"}
        self.assertFalse(forbidden, f"Forbidden output/execution tokens found: {forbidden}")

    def test_refuses_to_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "evidence.jsonl"
            target.write_text("prior evidence\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                record(duration=1.0, output=str(target), dry_run=False)

    def test_dry_run_executes_safely_without_opening_port(self):
        # Dry-run must not invoke mido.open_input or touch any port
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "dry_run.jsonl"
            count = record(duration=5.0, output=str(target), guided=True, dry_run=True)
            self.assertEqual(count, 0)
            self.assertFalse(target.exists(), "Dry-run must not create evidence file")

    def test_gesture_steps_coverage(self):
        step_ids = {s["id"] for s in GESTURE_STEPS}
        required_steps = {
            "deck_a_fader",
            "deck_b_fader",
            "crossfader",
            "deck_a_jog_touch",
            "deck_a_jog_cw",
            "deck_a_jog_ccw",
            "deck_b_jog_touch",
            "deck_b_jog_cw",
            "deck_b_jog_ccw",
            "deck_a_transport",
            "deck_b_transport",
            "navigation",
            "deck_a_knobs",
            "deck_b_knobs",
            "deck_a_tempo",
            "deck_b_tempo",
            "master_and_monitoring",
            "deck_a_pads",
            "deck_b_pads",
        }
        for req in required_steps:
            self.assertIn(req, step_ids)

        for step in GESTURE_STEPS:
            self.assertTrue(len(step["title"]) > 0)
            self.assertTrue(len(step["prompt"]) > 0)
            self.assertTrue(step["duration"] > 0)
            self.assertTrue(len(step["expected"]) > 0)

    def test_format_event_record_fields_and_provenance(self):
        rec = format_event_record(
            t_seconds=1.234567,
            raw_bytes=[0xB1, 0x00, 127],
            msg_str="control_change channel=1 control=0 value=127",
            phase="deck_a_fader",
            prompt="Deck A Channel Fader",
        )
        self.assertEqual(rec["t_seconds"], 1.234567)
        self.assertEqual(rec["bytes"], [177, 0, 127])
        self.assertEqual(rec["channel"], 1)
        self.assertEqual(rec["status_hex"], "0xB1")
        self.assertEqual(rec["phase"], "deck_a_fader")
        self.assertEqual(rec["provisional_id"], "volume")
        self.assertEqual(rec["deck"], "A")
        self.assertEqual(rec["provenance"], "live-reported:gabi-midi-control-v0.1@2026-08-25")

    def test_keyboard_interrupt_clean_exit(self):
        mock_port = MagicMock()
        mock_port.iter_pending.side_effect = KeyboardInterrupt()
        mock_open = MagicMock(return_value=mock_port)
        mock_port.__enter__.return_value = mock_port
        mock_port.__exit__.return_value = False

        with patch("mido.open_input", mock_open):
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = Path(tmpdir) / "interrupted.jsonl"
                count = record(duration=10.0, output=str(out_path), port_name="Mock Port")
                self.assertEqual(count, 0)
                mock_port.__enter__.assert_called_once()
                mock_port.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()

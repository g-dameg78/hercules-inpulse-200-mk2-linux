import io
import tokenize
import unittest
from pathlib import Path

from tools import inpulse_protocol as p

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/SYNTHETIC_session.jsonl'


def code_names(path):
    """Identifiers in a source file, ignoring comments/docstrings."""
    toks = tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
    return {t.string for t in toks if t.type == tokenize.NAME}


class ParseTest(unittest.TestCase):
    def test_rejects_sysex_system_and_short(self):
        for bad in ([0xF0, 0x00, 0xF7], [0xF8, 0, 0], [0x91, 0x07], [0x07, 0x7F, 0x00],
                    [0x91, 0x80, 0x00], [0xE1, 0x00, 0x40]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                p.parse_short(bad)

    def test_signed7(self):
        self.assertEqual([p.signed7(v) for v in (1, 63, 64, 127)], [1, 63, -64, -1])


class DecodeTest(unittest.TestCase):
    def setUp(self):
        self.d = p.Decoder()

    def test_button_press_release_and_note_off(self):
        self.assertTrue(self.d.decode([0x91, 0x07, 0x7F]).pressed)
        self.assertFalse(self.d.decode([0x91, 0x07, 0x00]).pressed)
        ev = self.d.decode([0x81, 0x07, 0x40])
        self.assertEqual((ev.control.name, ev.control.deck, ev.pressed), ('play', 'A', False))

    def test_shift_layer_is_distinct_channel(self):
        ev = self.d.decode([0x95, 0x06, 0x7F])
        self.assertEqual((ev.control.name, ev.control.deck, ev.control.layer), ('cue', 'B', 'shift'))

    def test_jog_direction(self):
        self.assertEqual(self.d.decode([0xB2, 0x0A, 0x01]).delta, 1)
        self.assertEqual(self.d.decode([0xB2, 0x0A, 0x7F]).delta, -1)

    def test_pitch_14bit_pairs_per_deck(self):
        self.assertIsNone(self.d.decode([0xB1, 0x28, 0x10]).position14)  # LSB before any MSB
        self.d.decode([0xB1, 0x08, 0x7F])
        self.d.decode([0xB2, 0x08, 0x00])
        self.assertEqual(self.d.decode([0xB1, 0x28, 0x7F]).position14, 16383)
        self.assertEqual(self.d.decode([0xB2, 0x28, 0x01]).position14, 1)

    def test_channel_fader_14bit_live_aug25(self):
        self.d.decode([0xB1, 0x00, 0x7F])
        ev = self.d.decode([0xB1, 0x20, 0x7F])
        self.assertEqual((ev.control.name, ev.control.deck, ev.position14), ('volume', 'A', 16383))
        self.assertEqual(ev.control.source, p.LIVE_AUG25)
        self.assertFalse(ev.verified)  # historical report, no capture file in this repo

    def test_crossfader_and_browser_are_source_assumptions(self):
        self.d.decode([0xB0, 0x00, 0x40])
        xf = self.d.decode([0xB0, 0x20, 0x00])
        self.assertEqual((xf.control.name, xf.position14), ('crossfader', 8192))
        enc = self.d.decode([0xB0, 0x01, 0x7F])
        self.assertEqual((enc.control.name, enc.delta), ('browser_encoder', -1))
        self.assertEqual({xf.control.source, enc.control.source}, {p.SOURCE_AUG25})

    def test_unknown_is_preserved_not_dropped(self):
        ev = self.d.decode([0xB1, 0x03, 0x40])  # no EQ-mid in the Mk1 prior
        self.assertFalse(ev.known)
        self.assertEqual((ev.status, ev.number, ev.value), (0xB1, 0x03, 0x40))


class ProvenanceTest(unittest.TestCase):
    def test_nothing_claims_mk2_verification_without_evidence(self):
        for key, ctl in p.PRIOR_TABLE.items():
            with self.subTest(key=key):
                self.assertIn(ctl.source, p.TIERS)
                self.assertIsNone(ctl.evidence)

    def test_aug25_tiers_match_history_exactly(self):
        by_tier = {}
        for (status, num), c in p.PRIOR_TABLE.items():
            by_tier.setdefault(c.source, set()).add((status, num, c.name))
        self.assertEqual(by_tier[p.LIVE_AUG25], {
            (0xB1, 0x00, 'volume'), (0xB1, 0x20, 'volume'), (0x91, 0x08, 'jog_touch'),
            (0xB1, 0x0A, 'jog_top'), (0xB2, 0x00, 'volume'), (0xB2, 0x20, 'volume'),
            (0x92, 0x08, 'jog_touch'), (0xB2, 0x0A, 'jog_top')})
        self.assertEqual(by_tier[p.SOURCE_AUG25], {
            (0xB0, 0x00, 'crossfader'), (0xB0, 0x20, 'crossfader'), (0xB0, 0x01, 'browser_encoder'),
            (0xB1, 0x09, 'jog_rim'), (0xB2, 0x09, 'jog_rim')})

    def test_spot_check_against_mixxx_mk1_facts(self):
        expected = {(0x91, 0x07): ('play', 'A'), (0x92, 0x06): ('cue', 'B'),
                    (0xB0, 0x00): ('crossfader', None), (0xB1, 0x00): ('volume', 'A'),
                    (0x97, 0x03): ('pad4', 'B'), (0xB4, 0x0A): ('jog_top', 'A')}
        for key, (name, deck) in expected.items():
            self.assertEqual((p.PRIOR_TABLE[key].name, p.PRIOR_TABLE[key].deck), (name, deck))

    def test_both_decks_symmetric(self):
        a = {(c.layer, c.name, c.kind) for c in p.PRIOR_TABLE.values() if c.deck == 'A'}
        b = {(c.layer, c.name, c.kind) for c in p.PRIOR_TABLE.values() if c.deck == 'B'}
        self.assertEqual(a, b)

    def test_usb_identity(self):
        self.assertEqual(p.USB_VENDOR_PRODUCT, (0x06F8, 0xB130))


class AseqdumpImportTest(unittest.TestCase):
    """Lines copied from gabi-midi-control-v0.1 tests/test_hercules.py (GABI-owned).

    v0.1 read field 1 as its "ch1"/deck A and field 0 as "ch16"/global; raw bytes keep
    aseqdump's 0-based nibble, so the same semantics land on 0xB1 / 0xB0.
    """

    def test_raw_channel_nibble_is_preserved(self):
        conv = p.aseqdump_to_bytes
        self.assertEqual(conv(' 28:0   Control change          2, controller 32, value 101'),
                         bytes([0xB2, 32, 101]))
        self.assertEqual(conv(' 28:0   Note on                 1, note 8, velocity 127'),
                         bytes([0x91, 8, 127]))
        self.assertEqual(conv(' 28:0   Control change          0, controller 0, value 64'),
                         bytes([0xB0, 0, 64]))
        self.assertEqual(conv(' 28:0   Note off                2, note 8'), bytes([0x82, 8, 0]))
        self.assertIsNone(conv(' 28:0   Port subscribed            0:1 -> 128:0'))

    def test_v01_semantics_round_trip(self):
        d = p.Decoder()
        names = [(e.control.deck, e.control.name) for e in (
            d.decode(p.aseqdump_to_bytes(' 28:0   Control change          2, controller 32, value 101')),
            d.decode(p.aseqdump_to_bytes(' 28:0   Note on                 1, note 8, velocity 127')),
            d.decode(p.aseqdump_to_bytes(' 28:0   Control change          0, controller 0, value 64')))]
        self.assertEqual(names, [('B', 'volume'), ('A', 'jog_touch'), (None, 'crossfader')])


class CaptureReplayTest(unittest.TestCase):
    def test_synthetic_fixture_summary(self):
        s = p.summarize(p.decode_capture(FIXTURE))
        self.assertEqual(s['known']['A:normal:play'], 2)
        self.assertEqual(s['known']['A:normal:jog_rim'], 2)
        self.assertEqual(s['unknown'], {'0xB0/0x03': 1})
        self.assertEqual(s['by_source'], {p.PRIOR_MK1: 4, p.SOURCE_AUG25: 3})
        self.assertEqual(s['verified'], 0)

    def test_malformed_line_reports_location(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'bad.jsonl'
            f.write_text('{"t_seconds": 0, "bytes": [240, 1, 247]}\n')
            with self.assertRaisesRegex(ValueError, r'bad\.jsonl:1:'):
                p.decode_capture(f)


class NoOutputSafetyTest(unittest.TestCase):
    FORBIDDEN = {'mido', 'rtmidi', 'open_output', 'send', 'sendShortMsg', 'sysex', 'subprocess'}

    def test_decoder_has_no_midi_or_process_path(self):
        self.assertFalse(code_names(ROOT / 'tools/inpulse_protocol.py') & self.FORBIDDEN)

    def test_capture_tool_is_input_only(self):
        names = code_names(ROOT / 'tools/midi_capture.py')
        self.assertIn('open_input', names)
        self.assertFalse(names & {'open_output', 'send', 'open_ioport', 'subprocess'})


if __name__ == '__main__':
    unittest.main()

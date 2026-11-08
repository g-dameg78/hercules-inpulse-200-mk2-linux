#!/usr/bin/env python3
"""Offline, input-only decoder for Hercules DJControl Inpulse 200 Mk2 MIDI bytes.

Pure functions over byte triples / capture JSONL from tools/midi_capture.py.
This module never opens a MIDI port and has no output path (no LED, sysex or
"dump values" requests). Clean-room: the table below holds only status/number
facts; names and logic are our own.

Provenance of every table entry is explicit (strongest first):
  CAPTURED_MK2 confirmed by bounded read-only owner captures (2026-10-24 M5
              trial, 20110 events); Control.evidence cites the line-numbered
              excerpt tests/fixtures/MK2_CAPTURE_EXCERPTS.jsonl. Only MK2_TABLE
              carries evidence; PRIOR_TABLE stays unverified by design.
  SOURCE_MK2  model-specific public source CyrilGendarme/DJControl-Inpulse-200-
              Mk2-to-Rekordbox@bc57e55 (MIT): channel 1/2 = deck 1/2, 6/7 = pads,
              CC0 fader, CC1 filter (CFX), CC2 low, CC8 tempo, CC9/CC10 jog
              side/top, note 7 play. Its "EQ_HIGH=5 / EQ_MID=4" names target a
              3-band Pioneer layout; see MK2_WARNINGS.
  LIVE_AUG25  live Mk2 finding from GABI's own gabi-midi-control-v0.1
              (HERCULES_LIVE_TEST_REPORT.md, 2026-08-25). No raw capture file
              survives; that report itself says jog direction/rate were not yet
              physically proven, only deck A fader -> volume was owner-confirmed.
  SOURCE_AUG25 implemented in that project's src/hercules_adapter.py after the
              report, not physically verified (crossfader, browser, CC9 jog).
  PRIOR_MK1   status/number observed in Mixxx's public *Mk1* Inpulse 200 mapping
              (mixxxdj/mixxx@300bd8967c4e res/controllers/
              Hercules_DJControl_Inpulse_200.midi.xml, GPL-2.0-or-later project,
              author "DJ Phatso for Hercules Technical Support"). NOT verified on Mk2.

Channel numbering: gabi-midi-control-v0.1 read the Hercules via `aseqdump`,
which prints the raw 0-based channel, but labelled field N as "MIDI ch N" and
field 0 as "ch16". Its "deck A ch1 / deck B ch2 / global ch16" therefore means
raw status 0xB1/0x91, 0xB2/0x92 and 0xB0 here (high-confidence inference; one
deck-A fader capture settles it). This agrees with the Mk1 layout.
Usage: python3 tools/inpulse_protocol.py evidence/controls.jsonl
       python3 tools/inpulse_protocol.py --self-test   (replay Mk2 fixture, print warnings)
"""
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

USB_VENDOR_PRODUCT = (0x06F8, 0xB130)
_ASEQ_CC = re.compile(r'Control change\s+(\d+), controller (\d+), value (\d+)')
_ASEQ_NOTE = re.compile(r'Note (on|off)\s+(\d+), note (\d+)(?:, velocity (\d+))?', re.I)
PRIOR_MK1 = 'prior:mixxx-mk1@300bd8967c4e'
LIVE_AUG25 = 'live-reported:gabi-midi-control-v0.1@2026-08-25'
SOURCE_AUG25 = 'source:gabi-midi-control-v0.1/src/hercules_adapter.py'
SOURCE_MK2 = 'source:CyrilGendarme/DJControl-Inpulse-200-Mk2-to-Rekordbox@bc57e55'
TIERS = (SOURCE_MK2, LIVE_AUG25, SOURCE_AUG25, PRIOR_MK1)  # strongest first; CAPTURED adds evidence
MK2_FIXTURE = 'tests/fixtures/MK2_CAPTURE_EXCERPTS.jsonl'
CAPTURE_RUN = 'm5-trial-20261024/hardware-capture-20261024-220910-1642370'

# Control kinds
BUTTON = 'button'      # note on/off; value>0 pressed
ABS7 = 'abs7'          # absolute 0..127 CC
ABS14_MSB = 'abs14_msb'
ABS14_LSB = 'abs14_lsb'
REL7 = 'rel7'          # relative CC, 7-bit two's complement delta


@dataclass(frozen=True)
class Control:
    name: str
    kind: str
    deck: str | None   # 'A', 'B' or None (global)
    layer: str         # 'normal', 'shift', or a pad mode
    source: str
    evidence: str | None = None  # capture file once CAPTURED_MK2


@dataclass(frozen=True)
class Event:
    status: int
    number: int
    value: int
    control: Control | None   # None => unknown, kept rather than dropped
    pressed: bool | None = None
    delta: int | None = None
    position14: int | None = None  # 0..16383 once MSB+LSB pair seen

    @property
    def known(self):
        return self.control is not None

    @property
    def verified(self):
        return self.control is not None and self.control.evidence is not None


def _entries():
    """Yield ((status, number), Control) for the Mk1-derived prior table."""
    g, live, src = PRIOR_MK1, LIVE_AUG25, SOURCE_AUG25
    yield (0x90, 0x00), Control('browser_push', BUTTON, None, 'normal', g)
    yield (0x90, 0x03), Control('assistant', BUTTON, None, 'normal', g)
    yield (0x93, 0x00), Control('browser_push', BUTTON, None, 'shift', g)
    yield (0xB0, 0x00), Control('crossfader', ABS14_MSB, None, 'normal', src)
    yield (0xB0, 0x20), Control('crossfader', ABS14_LSB, None, 'normal', src)
    yield (0xB0, 0x01), Control('browser_encoder', REL7, None, 'normal', src)
    yield (0xB3, 0x01), Control('browser_encoder', REL7, None, 'shift', g)
    for deck, n in (('A', 1), ('B', 2)):
        note, shift_note, pads, cc, shift_cc = 0x90 + n, 0x93 + n, 0x95 + n, 0xB0 + n, 0xB3 + n
        for num, name in ((0x03, 'vinyl'), (0x05, 'sync'), (0x06, 'cue'), (0x07, 'play'),
                          (0x08, 'jog_touch'), (0x09, 'loop_in'), (0x0A, 'loop_out'),
                          (0x0C, 'pfl'), (0x0D, 'load')):
            tier = live if name == 'jog_touch' else g
            yield (note, num), Control(name, BUTTON, deck, 'normal', tier)
        for num, name in ((0x05, 'sync'), (0x06, 'cue'), (0x07, 'play'), (0x08, 'jog_touch'),
                          (0x09, 'loop_in'), (0x0A, 'loop_out')):
            yield (shift_note, num), Control(name, BUTTON, deck, 'shift', g)
        for base, mode in ((0x00, 'pad_hotcue'), (0x08, 'pad_hotcue_shift'), (0x10, 'pad_roll'),
                           (0x20, 'pad_fx'), (0x28, 'pad_fx_shift'), (0x30, 'pad_sampler')):
            for i in range(4):
                yield (pads, base + i), Control(f'pad{i + 1}', BUTTON, deck, mode, g)
        yield (cc, 0x00), Control('volume', ABS14_MSB, deck, 'normal', live)
        yield (cc, 0x20), Control('volume', ABS14_LSB, deck, 'normal', live)
        # Mk2 captured hardware transmits 14-bit pairs for the channel
        # filter, low EQ, high EQ and gain knobs, just like volume/pitch:
        # each MSB at CC n is followed by its LSB at CC (n+32).
        # This changes only decoding and offline reports; live knob control
        # still requires a separate explicit, bounded enablement.
        for num, name in ((0x01, 'filter'), (0x02, 'eq_low'),
                          (0x04, 'eq_high'), (0x05, 'gain')):
            yield (cc, num), Control(name, ABS14_MSB, deck, 'normal', g)
            yield (cc, num + 0x20), Control(name, ABS14_LSB, deck, 'normal', g)
        yield (cc, 0x08), Control('pitch', ABS14_MSB, deck, 'normal', g)
        yield (cc, 0x28), Control('pitch', ABS14_LSB, deck, 'normal', g)
        yield (cc, 0x09), Control('jog_rim', REL7, deck, 'normal', src)  # v0.1 "jog_outer"
        yield (cc, 0x0A), Control('jog_top', REL7, deck, 'normal', live)
        yield (cc, 0x0C), Control('pad_bend', REL7, deck, 'normal', g)
        yield (shift_cc, 0x0A), Control('jog_top', REL7, deck, 'shift', g)


def build_table():
    table = {}
    for key, ctl in _entries():
        if key in table:
            raise ValueError(f'duplicate mapping for {key}')
        table[key] = ctl
    return table


PRIOR_TABLE = build_table()

# Mk2 identity: (deck, layer, name) -> (source tier, capture evidence). Only
# controls present in BOTH an authoritative source and the owner capture.
_GUIDED = f'{CAPTURE_RUN} via {MK2_FIXTURE}'
_MK2 = {}
for _deck in ('A', 'B'):
    for _name, _tier in (('volume', SOURCE_MK2), ('filter', SOURCE_MK2), ('eq_low', SOURCE_MK2),
                         ('eq_high', PRIOR_MK1), ('gain', PRIOR_MK1), ('pitch', SOURCE_MK2),
                         ('jog_top', SOURCE_MK2), ('jog_rim', SOURCE_MK2), ('jog_touch', LIVE_AUG25),
                         ('play', SOURCE_MK2), ('cue', PRIOR_MK1)):
        _MK2[(_deck, 'normal', _name)] = (_tier, _GUIDED)
    for _i in range(4):
        _MK2[(_deck, 'pad_hotcue', f'pad{_i + 1}')] = (SOURCE_MK2, _GUIDED)
_MK2[('B', 'normal', 'pitch')] = (SOURCE_MK2, f'PARTIAL {_GUIDED}: brief touches 8845..10756, no full sweep')
_MK2[(None, 'normal', 'crossfader')] = (PRIOR_MK1, _GUIDED)


def build_mk2_table():
    table = dict(PRIOR_TABLE)
    for key, ctl in PRIOR_TABLE.items():
        hit = _MK2.get((ctl.deck, ctl.layer, ctl.name))
        if hit:
            table[key] = replace(ctl, source=hit[0], evidence=hit[1])
    return table


MK2_TABLE = build_mk2_table()

# Source-versus-capture disagreements; surfaced by the self-test, never silently resolved.
MK2_WARNINGS = (
    'SOURCE_MK2 names CC5 EQ_HIGH and CC4 EQ_MID (3-band Pioneer target); Hercules lists '
    '"Gain, 2-band EQ, Filter, volume" and Mixxx Mk1 has CC5 pregain / CC4 high. Using gain=5, high=4.',
    'Capture deck-b-tempo-confirmed-20261024-224927 ("RIGHT deck tempo") emitted B1 CC8, the LEFT '
    'deck per both sources and every other capture; treated as operator error. B2 CC8 has brief touches only.',
    'Guided-run phase labels lag gestures by about one step; identity comes from sources, not labels.',
    'Pitch direction (raw up = faster?) is settled by neither source nor capture; see bridge pitch_invert.',
    'Deck B jog rim was captured CW only; CCW (127) is inferred from the shared encoding.',
    'MK2_TABLE evidence is input-only; no LED/output behaviour is claimed.',
)


def bipolar14(position14, deadband=128):
    """0..16383 -> -1..1 with an exact centre null of +/-deadband counts."""
    offset = position14 - 8192
    if abs(offset) <= deadband:
        return 0.0
    span = (8192 if offset < 0 else 8191) - deadband
    return max(-1.0, min(1.0, (offset - deadband if offset > 0 else offset + deadband) / span))

# Physical Mk2 controls whose MIDI identity is UNKNOWN (no Mk1 prior and no capture).
# Mixxx docs say master/headphone knobs act on the built-in sound card directly.
UNKNOWN_CONTROLS = ('master_volume', 'headphone_volume', 'master_button',
                    'eq_mid_A', 'eq_mid_B', 'pad_modes_beyond_mk1', 'beatmatch_guide_toggle')


def signed7(value):
    return value - 128 if value >= 64 else value


def parse_short(data):
    """Validate one complete 3-byte channel voice message; return (status, number, value)."""
    data = bytes(data)
    if len(data) != 3:
        raise ValueError(f'expected 3-byte short message, got {len(data)} bytes')
    status, number, value = data
    if status < 0x80 or status >= 0xF0:
        raise ValueError(f'unsupported status 0x{status:02X} (sysex/system/running status)')
    if number > 0x7F or value > 0x7F:
        raise ValueError('data byte has high bit set')
    if status & 0xF0 not in (0x80, 0x90, 0xB0):
        raise ValueError(f'unsupported message type 0x{status & 0xF0:02X}')
    return status, number, value


class Decoder:
    """Stateful only for 14-bit MSB/LSB pairing; one instance per input stream."""

    def __init__(self, table=None):
        self.table = PRIOR_TABLE if table is None else table
        self._msb = {}

    def decode(self, data):
        status, number, value = parse_short(data)
        pressed = None
        if status & 0xF0 == 0x80:  # note off: map onto the note-on key, released
            status, pressed = 0x90 | (status & 0x0F), False
        ctl = self.table.get((status, number))
        if ctl is None:
            return Event(status, number, value, None, pressed=pressed)
        if ctl.kind == BUTTON:
            return Event(status, number, value, ctl, pressed=bool(value) if pressed is None else False)
        if ctl.kind == REL7:
            return Event(status, number, value, ctl, delta=signed7(value))
        if ctl.kind == ABS14_MSB:
            self._msb[(ctl.deck, ctl.name)] = value
            return Event(status, number, value, ctl, position14=value << 7)
        if ctl.kind == ABS14_LSB:
            msb = self._msb.get((ctl.deck, ctl.name))
            pos = None if msb is None else (msb << 7) | value
            return Event(status, number, value, ctl, position14=pos)
        return Event(status, number, value, ctl)


def aseqdump_to_bytes(line):
    """Raw bytes from one `aseqdump` note/CC line (offline import of old logs).

    aseqdump's channel field is the raw 0-based nibble, so field 1 -> 0xB1.
    Returns None for lines that are not note on/off or control change.
    """
    m = _ASEQ_CC.search(line)
    if m:
        ch, num, val = map(int, m.groups())
        return bytes((0xB0 | ch, num, val))
    m = _ASEQ_NOTE.search(line)
    if m:
        kind, ch, num, vel = m.groups()
        return bytes(((0x90 if kind.lower() == 'on' else 0x80) | int(ch), int(num), int(vel or 0)))
    return None


def decode_capture(path, decoder=None):
    """Decode a tools/midi_capture.py JSONL file; malformed lines raise with line number."""
    decoder = decoder or Decoder()
    events = []
    for lineno, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            events.append((record['t_seconds'], decoder.decode(record['bytes'])))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'{path}:{lineno}: {exc}') from exc
    return events


def summarize(events):
    """Counts per mapped control, plus unknown (status, number) pairs to triage."""
    known, unknown = {}, {}
    for _, ev in events:
        if ev.known:
            c = ev.control
            key = f'{c.deck or "-"}:{c.layer}:{c.name}'
            known[key] = known.get(key, 0) + 1
        else:
            key = f'0x{ev.status:02X}/0x{ev.number:02X}'
            unknown[key] = unknown.get(key, 0) + 1
    tiers = {}
    for _, ev in events:
        if ev.known:
            tiers[ev.control.source] = tiers.get(ev.control.source, 0) + 1
    return {'known': known, 'unknown': unknown, 'by_source': tiers,
            'verified': sum(1 for _, ev in events if ev.verified)}


# Controls the bridge may act on; the self-test requires each to decode verified.
MK2_REQUIRED = tuple(f'{d}:normal:{n}' for d in 'AB' for n in (
    'volume', 'filter', 'eq_low', 'eq_high', 'gain', 'pitch', 'jog_top', 'jog_rim', 'jog_touch',
    'play', 'cue')) + ('-:normal:crossfader',)


def mk2_self_test(path=None):
    """Replay the committed capture excerpt through MK2_TABLE; offline only.

    Each excerpt line is decoded in file order per source file (MSB/LSB rows
    are kept adjacent by the extractor). Returns a report; 'ok' is False when a
    required control is missing, unverified, or a 14-bit pair failed to pair.
    """
    path = Path(path) if path else Path(__file__).resolve().parents[1] / MK2_FIXTURE
    lines = path.read_text(encoding='utf-8').splitlines()
    sources = json.loads(lines[0])['_meta']
    decoders, seen, ranges, unpaired = {}, set(), {}, 0
    for line in lines[1:]:
        row = json.loads(line)
        ev = decoders.setdefault(row['file'], Decoder(MK2_TABLE)).decode(row['bytes'])
        if not ev.verified:
            continue
        c = ev.control
        key = f'{c.deck or "-"}:{c.layer}:{c.name}'
        seen.add(key)
        if c.kind == ABS14_LSB:
            if ev.position14 is None:
                unpaired += 1
            else:
                lo, hi = ranges.get(key, (16383, 0))
                ranges[key] = [min(lo, ev.position14), max(hi, ev.position14)]
    missing = [k for k in MK2_REQUIRED if k not in seen]
    return {'ok': not missing and not unpaired, 'missing': missing, 'unpaired_lsb': unpaired,
            'verified_controls': sorted(seen), 'ranges14': ranges, 'sources': sources,
            'warnings': list(MK2_WARNINGS)}


def main(argv):
    if argv[1:] == ['--self-test']:
        report = mk2_self_test()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report['ok'] else 1
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(summarize(decode_capture(argv[1])), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

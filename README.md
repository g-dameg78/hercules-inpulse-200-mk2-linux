# Hercules Inpulse 200 Mk2: Linux MIDI protocol research

Documented MIDI behavior, a Python decoder, and recorded evidence from a real
**Hercules DJControl Inpulse 200 Mk2** (USB `06f8:b130`).

I wanted to use this DJ controller as a general-purpose Linux control surface
for synthesizers and a DAW. This project documents what the controls send and
provides small tools for checking those findings. The work combines my physical
controller tests with AI-assisted implementation and independent review.

## What is here

- A [protocol reference](docs/PROTOCOL.md) covering faders, the mixer knobs,
  jog wheels, touch sensors, transport buttons, browser encoder and pad bytes.
- An offline Python decoder with explicit source and capture-evidence tags.
- A passive MIDI capture tool and a replay validator.
- [191 recorded-event excerpts](tests/fixtures/MK2_CAPTURE_EXCERPTS.jsonl), with
  original source hashes and line numbers, plus clearly labelled synthetic fixtures.
- Unit tests for decoding, capture behavior and replay validation.

The main guided hardware recording contains **20,110 events**, collected on
October 24, 2026. The public excerpt also includes later focused recordings.
The source hashes and all 191 selected rows were checked against the original
files before this publication. See [provenance and validation](docs/PROVENANCE.md).

This is a focused research snapshot. The larger experimental DJ application,
local studio routing and REAPER integration are separate projects. These tools
do not play audio or send MIDI. The capture command opens a MIDI input only;
the decoder and replay validator operate on files.

## Useful findings

The channel faders, crossfader and mixer knobs use **14-bit CC pairs**. For
example, the Deck A fader sends raw status `B1`, CC `0` followed by CC `32`.
Combining both data bytes gives `(MSB << 7) | LSB`, a position from 0 to 16,383.
Handling those messages as unrelated 7-bit knobs loses information and can
confuse automatic MIDI learning.

Raw status `B0` is global, `B1` is Deck A and `B2` is Deck B. In a user interface
that numbers MIDI channels from 1, those are channels **1, 2 and 3**. The channel
convention matters: some early notes used the raw channel number as the visible
channel label.

Jog top and rim movement use separate CCs. The recorded relative values `1`
and `127` represent `+1` and `-1`; touch arrives as a separate note event.

## Try it without a controller

Python 3.10 or later is required by the source syntax. The decoder and replay
validator use only the standard library. From the repository root:

```bash
python3 -m tools.inpulse_protocol --self-test
python3 -m tools.replay_validator tests/fixtures/synthetic_clean_acceptance.jsonl --json
python3 -m unittest tests.test_inpulse_protocol tests.test_replay_validator -v
```

The first command checks the committed real-event excerpt and prints its
limitations. The second uses a **synthetic** continuous recording. A replay
`PASS` describes the checks on that input; it is not an audible controller test.
The excerpt has a metadata header and several source timelines, so it must use
`--self-test`, not the ordinary single-recording decoder/validator entry point.

For the complete test suite and optional input capture:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

The capture tests mock the input port; running the tests does not require the
controller. Current verification results are in [VALIDATION.md](docs/VALIDATION.md).

## Record your own controls

Use module execution from the repository root so the capture tool can import
its provisional mapping table:

```bash
.venv/bin/python -m tools.midi_capture --dry-run --guided
.venv/bin/python -m tools.midi_capture --duration 15 --output captures/controls.jsonl
.venv/bin/python -m tools.replay_validator captures/controls.jsonl --json
```

The capture tool refuses to overwrite an existing file. Move one control at a
time and record its actual physical name. Guided prompts are a collection aid;
phase labels alone do not prove which control produced a message. Some original
sessions had gestures that ran beyond their prompt window.

## Evidence boundaries

- Deck B pitch messages were observed, but a full travel test and the physical
  speed direction remain unconfirmed.
- Deck B jog-rim reverse movement is inferred from the shared encoding; only
  positive rim ticks were recorded in that session.
- Both pad banks have recorded note bytes. Higher pad-mode function names in
  the inherited prior table remain provisional.
- Global CC pairs `3/35` and `4/36` were recorded, but their precise physical
  identities are unresolved in this publication.
- LED/output messages, firmware behavior and built-in audio performance are not
  established by these input recordings.
- The decoder's `verified` property means a capture reference is attached. It
  does not mean every range, direction, mode or audible behavior is validated.

## Sources, authorship and licensing

Work directed and physically tested by [Gabi / g-dameg78](https://github.com/g-dameg78),
with AI coding and review assistance. This project credits the existing
model-specific Rekordbox mapping, Mixxx's original Inpulse 200 mapping, and
Hercules documentation; the findings are not claimed as the first published
mapping of this controller. Exact references are in [PROVENANCE.md](docs/PROVENANCE.md).

No vendor binaries, firmware images, proprietary source code or third-party
music are included. No separate open-source license has been selected for this
research snapshot. Referenced upstream projects retain their own licenses.

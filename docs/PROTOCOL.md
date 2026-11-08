# Protocol reference

This document uses **hexadecimal status bytes** and **decimal CC/note numbers**.
The controller is the **Inpulse 200 Mk2**, USB `06f8:b130`.

## Channel numbering

| Group | Raw channel nibble | Note-on status | CC status | Human MIDI channel |
| --- | ---: | --- | --- | ---: |
| Global | 0 | `90` | `B0` | 1 |
| Deck A | 1 | `91` | `B1` | 2 |
| Deck B | 2 | `92` | `B2` | 3 |
| Deck A pad bank | 6 | `96` | — | 7 |
| Deck B pad bank | 7 | `97` | — | 8 |

The table names come from source comparison and capture review. A phase label
in a recording is not sufficient evidence of physical identity.

## Continuous controls and buttons

For the paired controls, the first CC holds the seven most significant bits;
the second holds the seven least significant bits.

| Control | Deck A / global bytes | Deck B bytes | Evidence and limits |
| --- | --- | --- | --- |
| Channel fader | `B1`, CC `0/32` | `B2`, CC `0/32` | Both full-range positions observed |
| Crossfader | `B0`, CC `0/32` | — | Full-range positions observed; global identity cross-checked |
| Filter | `B1`, CC `1/33` | `B2`, CC `1/33` | Paired bytes observed; Mk2 source comparison |
| Low EQ | `B1`, CC `2/34` | `B2`, CC `2/34` | Paired bytes observed; Mk2 source comparison |
| High EQ | `B1`, CC `4/36` | `B2`, CC `4/36` | Paired bytes observed; identity uses physical layout and Mk1 reference |
| Gain | `B1`, CC `5/37` | `B2`, CC `5/37` | Paired bytes observed; identity uses physical layout and Mk1 reference |
| Pitch / tempo | `B1`, CC `8/40` | `B2`, CC `8/40` | A full range; B only partial touches, 8845–10756 across retained evidence |
| Jog top | `B1`, CC `10` | `B2`, CC `10` | Both signed directions observed |
| Jog rim | `B1`, CC `9` | `B2`, CC `9` | A both directions; B positive direction only |
| Jog touch | `91`, note `8` | `92`, note `8` | Touch/release bytes observed |
| Play | `91`, note `7` | `92`, note `7` | Press/release bytes observed; Mk2 source comparison |
| Cue | `91`, note `6` | `92`, note `6` | Press/release bytes observed; Mk1 reference comparison |
| Browser encoder | `B0`, CC `1` | — | Main recording: 43 values of `1`, 39 of `127` |
| Pads 1–4 | `96`, notes `0–3` | `97`, notes `0–3` | Both banks observed, including the later B-bank retest; mode semantics remain separate |

The model-specific Rekordbox reference calls CC `5` EQ_HIGH and CC `4` EQ_MID
in its three-band target layout. Hercules' two-band physical layout and the
Mixxx reference support the gain/high labels used here. This naming difference
is recorded rather than silently treated as independent hardware proof.

## Decode a complete 14-bit pair

```python
from tools.inpulse_protocol import Decoder, MK2_TABLE

decoder = Decoder(MK2_TABLE)
decoder.decode([0xB1, 0, 64])
event = decoder.decode([0xB1, 32, 0])
assert event.control.deck == "A"
assert event.control.name == "volume"
assert event.position14 == 8192
```

A consumer applying positions should wait for the LSB of a complete pair.
The research decoder also exposes a coarse value on the MSB event; that is not
proof a complete position has arrived. Pairing state is cached. Create a fresh
decoder for a new stream, after reconnecting, or after a discontinuity. This
snapshot does not implement a live device reconnect or parameter-pickup policy.

The default `Decoder()` uses the inherited `PRIOR_TABLE`; use
`Decoder(MK2_TABLE)` to attach the Mk2 capture references. Unknown message pairs
are retained as unknown events instead of assigned a guessed function.

## Relative and button messages

For the observed relative encoding, `1` is one positive tick and `127` is one
negative tick. The implementation uses seven-bit two's complement:
`value - 128` for values at least 64, otherwise `value`.

Jog touch is separate from rotation. Note-on with nonzero velocity is a press;
note-on with velocity zero and a corresponding note-off are treated as release.
These are input-message interpretations, not commands to send back to the unit.

## Open questions

- Which exact physical controls produce global `B0` CC `3/35` and `4/36`? The
  bytes are present, but old reports disagree on their names.
- Global note `90/2` and other unidentified button messages need controlled
  naming checks. Previous reports disagree about their function.
- A recording labelled “right deck tempo” emitted `B1` pitch messages. Another
  B-pitch-labelled test emitted `B2` channel-fader messages. Those labels do not
  establish a full Deck B pitch sweep.
- Shift layers and higher pad-mode names inherited from the original Inpulse
  mapping require explicit Mk2 confirmation. Observing notes does not establish
  the selected application's pad behavior.
- No input recording establishes LED commands, output feedback, built-in audio
  quality, firmware internals or complete DAW integration.

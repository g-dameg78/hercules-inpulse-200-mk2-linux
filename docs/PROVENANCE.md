# Provenance and evidence

Publication prepared November 8, 2026. The controller recordings are from
October 24, 2026; they are dated observations rather than current device status.

## Source snapshot

The six exported Python implementation/test files and ten fixtures are copied
byte-for-byte from the project's authoritative Mk2-binding revision:
`fd97dc2e13f0969c98dbd3b8008ee48b9b807f50`.
The same binding work was integrated into the larger experimental project at
`0eff4096516b400372589a5c1b70a6393fc1936b`.
Those source commits are from local development history; they are not public
GitHub commit links. [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) records each
exported file's SHA-256. New public documentation and package initializers are
publication additions.

A later branch name or date did not necessarily contain the newer protocol
work. This snapshot was selected for its recorded Mk2 14-bit controls and
source-labelled capture evidence.

## Recorded evidence

[MK2_CAPTURE_EXCERPTS.jsonl](../tests/fixtures/MK2_CAPTURE_EXCERPTS.jsonl) contains
one metadata row and **191 event rows**. Each event retains its original file
name, line number, relative timestamp and MIDI bytes. The metadata stores the
original whole-file hashes and counts for four recordings:

| Recording | Original event rows | Interpretation |
| --- | ---: | --- |
| Guided hardware recording | 20,110 | Broad control exercise; some gesture/phase labels lag |
| Later Deck B pad test | 24 | `97` notes 0–3 and 16–19 observed |
| Recording labelled Deck B pitch | 4,424 | Actually contains Deck B channel-fader messages |
| Recording labelled right-deck tempo | 3,916 | Contains Deck A pitch messages |

All four original hashes/counts and all 191 excerpt rows were compared with the
original files before publication. The excerpt is public; the full originals
are not bundled in this focused snapshot. Synthetic fixtures are named
`SYNTHETIC_*` or `synthetic_*` and are not physical-device evidence.

Structural replay success establishes the checks applied to a capture, not a
complete mapping, a functioning DJ application or an audible hardware result.

## Primary references

- [Hercules Mk2 support and manuals](https://support.hercules.com/en/product/djcontrolinpulse200mk2-en/).
- [Hercules product description](https://www.hercules.com/en/product/djcontrol-inpulse-200-mk2/).
- [CyrilGendarme/DJControl-Inpulse-200-Mk2-to-Rekordbox](https://github.com/CyrilGendarme/DJControl-Inpulse-200-Mk2-to-Rekordbox),
  revision [`bc57e5500ac19f203cee140bb007424661be821d`](https://github.com/CyrilGendarme/DJControl-Inpulse-200-Mk2-to-Rekordbox/tree/bc57e5500ac19f203cee140bb007424661be821d),
  especially `djcontrol_specific/controller_notes.py` and `RekordJog_DJControl.py`.
  This model-specific reference has an [MIT license](https://github.com/CyrilGendarme/DJControl-Inpulse-200-Mk2-to-Rekordbox/blob/bc57e5500ac19f203cee140bb007424661be821d/LICENSE); its target EQ names are not
  silently treated as the Hercules panel labels.
- [Mixxx original Inpulse 200 mapping](https://github.com/mixxxdj/mixxx/blob/300bd8967c4edaea38af9e32949be510f07b94f9/res/controllers/Hercules_DJControl_Inpulse_200.midi.xml),
  revision `300bd8967c4edaea38af9e32949be510f07b94f9`, credited to
  DJ Phatso for Hercules Technical Support in the source mapping. Mixxx is a
  [GPL-2.0-or-later project](https://github.com/mixxxdj/mixxx/blob/300bd8967c4edaea38af9e32949be510f07b94f9/LICENSE), confirmed from the pinned license text. This is a **Mk1 reference**, not Mk2 confirmation.
- Earlier project controller code and an August 25, 2026 test report
  supplied historical leads. A historical report without retained raw bytes
  remains a weaker evidence tier.

The two pinned GitHub revisions were resolved through GitHub's API during this
publication check. Referenced projects retain their own authorship and licenses;
no upstream repository, proprietary vendor binary or third-party music is
redistributed here. No claim is made that these mappings were previously unknown.

## Collaboration

Gabi directed the work and performed the physical gestures. AI assistants
contributed implementation, source comparison and independent review. The public
package is a selective export of that work, with current offline tests and
explicit limits, rather than a claim of independently hand-written software or
commercial certification.

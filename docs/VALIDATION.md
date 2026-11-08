# Validation — November 8, 2026

The published package was checked on Linux with **Python 3.14.4**, **mido 1.3.3**
and **python-rtmidi 1.5.8**. Python 3.10 is the syntax minimum, not an independently
tested compatibility matrix.

| Check | Result |
| --- | --- |
| Complete exported unit suite | **40 tests passed**, 0 failures |
| Real-event excerpt self-test | PASS; no missing required controls or unpaired excerpt LSBs |
| Synthetic continuous-capture replay | Command completed successfully; synthetic data only |
| Guided capture dry-run | Completed; no MIDI port opened |
| Original capture hashes and counts | All four matched excerpt metadata |
| Excerpt provenance | All 191 event rows matched original time, bytes and phase |
| Exported source integrity | All 16 implementation/test/fixture files match the source manifest |

The capture interruption test uses a mocked input port. The tests and the
publication checks did not open physical MIDI or audio devices, alter firmware,
play sound, or modify the existing studio setup.

The original recordings predate publication. The excerpt self-test checks
recorded byte coverage and pairing; it does not establish complete control
travel, every mode/direction, audible operation, a complete DJ application,
LED feedback, or current device availability.

## Reproduce

After installing the optional capture dependencies, run from the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.inpulse_protocol --self-test
python3 -m tools.replay_validator tests/fixtures/synthetic_clean_acceptance.jsonl --json
python3 -m tools.midi_capture --dry-run --guided
```

The public excerpt SHA-256 is:

```text
c8f6227d8e3451608f56cfbe6d698bc81b0ae9b8bc467f11656bf694938bb34e
```

The full original recordings are not bundled. Their hashes and line references
remain in the excerpt metadata; the checked public rows are sufficient to run
the included self-test. See [PROTOCOL.md](PROTOCOL.md) for the unresolved cases.

# BandPilot product contract

This document is the current product source of truth. It replaces the separate
FretPilot, StickPilot, stream-separation, learning-loop and frontend PRDs. The
historical documents remain in `docs/archive/` for decision provenance.

## 1. Product vision

BandPilot converts a user's MIDI arrangement into a score and performance that
feel prepared by a musician rather than mechanically transcribed by software.

The output hierarchy is deliberate:

1. Produce a valid, practical and professional Guitar Pro score.
2. Export the same score through MusicXML without creating another score truth.
3. Render a humanized MIDI performance from that score.
4. Adapt the performance to Ample Guitar Eclipse, then add governed profiles
   for more virtual instruments.

The product is not a generic MIDI converter. Its differentiator is musical
realization: track roles, tuning, string/fret choice, hand position, voices,
techniques, drum notation, keyboard hands and performance phrasing.

## 2. Target users

- Guitarists and band musicians who receive AI-generated or programmed MIDI
  and need a score they can rehearse.
- Producers who need editable Guitar Pro, MusicXML or humanized MIDI output.
- Arrangers who want deterministic cleanup while retaining source intent.
- Dataset curators who evaluate approved professional scores and propose
  auditable knowledge updates.

## 3. Primary user journey

1. Upload one Standard MIDI File.
2. Review detected guitar, drum, bass, keys and generic tracks; correct a family
   when detection is wrong.
3. Choose `faithful`, `playable_arrangement` or `creative_rewrite`, MIDI
   fidelity and an optional guitar tuning override.
4. Start repair. The UI receives a job ID, polls durable state and can recover
   the completed result after refresh.
5. Review per-track outcomes, validation issues, unresolved source events and
   the AlphaTab score preview.
6. Export GP5 first; optionally export MusicXML, humanized band MIDI, Eclipse
   MIDI or humanized Eclipse MIDI.
7. For authorized corpus work, compare generated GP5 with the professional
   reference and create a candidate knowledge snapshot. Promotion requires an
   independent A/B evaluation and explicit governance gates.

## 4. Product modes

| Mode | Meaning |
|---|---|
| `faithful` | Preserve notes. LLM note rewrite decisions are not applied. |
| `playable_arrangement` | Permit bounded changes needed for practical performance. |
| `creative_rewrite` | Permit broader policy-bounded proposals while retaining validation and provenance. |

No mode may bypass hard musical validation. A disconnected client or an LLM
timeout does not cancel the server job. If the LLM is unavailable, deterministic
rules continue in degraded mode and the run records that fact.

## 5. Canonical outputs

| Format ID | User value | Contract |
|---|---|---|
| `gp5` | Guitar Pro score and TAB | Must open in Guitar Pro 8 and parse in AlphaTab/PyGuitarPro. |
| `musicxml` | Native notation interchange | Preferred for keyboard grand staff and notation applications. |
| `humanized_midi` | Multi-track band performance | Deterministic for the same SongIR, snapshot and profile. |
| `ample_eclipse_midi` | Eclipse keyswitch performance | Source-preserved performance mapping. |
| `humanized_ample_eclipse_midi` | Humanized Eclipse performance | Humanized layer followed by Eclipse mapping. |

`ample_midi` remains an API compatibility alias for `ample_eclipse_midi`.

## 6. Product invariants

- SongIR 2.0 is the only persisted editable score truth.
- Every source note is either represented or explicitly unresolved; silent
  deletion and fabricated physical realization are forbidden.
- Guitar/bass pitch must equal tuning plus fret on the assigned string.
- Simultaneous notes may not collide on a physical string or exceed approved
  hand/chord constraints.
- Linked techniques must reference valid, ordered and physically compatible
  notes.
- Exporters serialize validated meaning; they do not repair the score.
- Every run pins source hash, settings, application, schema, knowledge, model,
  prompt and validation state.
- LLM output is a proposal and never the authority for pitch, beat, string,
  fret or policy.
- Learned knowledge is traceable, licensed, split-safe, reversible and inactive
  until an independent no-regression gate passes.

## 7. Project status

| Status | Meaning |
|---|---|
| `processing` | A repair job has started and is not terminal. |
| `repaired` | Every note-bearing supported source track completed and validated. |
| `partial` | At least one track completed, while another failed or remained unresolved. |
| `failed` | No plugin completed or project-level processing failed. |

The project row is the latest-result projection. Durable repair jobs and
manifests retain execution history.

## 8. Success metrics

Metrics are evaluated separately; one composite score must not hide a musical
regression.

- Reliability: successful repair/export rate, recoverable jobs, parser
  compatibility and explicit failure rate.
- Score fidelity: note precision/recall, onset and duration agreement.
- Playability: hard-invariant pass rate, string/fret agreement, hand-position
  movement and chord-shape agreement.
- Musical detail: technique precision/recall/F1 by technique family.
- Instrument quality: separate guitar, bass, drum, keys and generic metrics.
- Operations: repair latency, LLM timeout/degraded rate and retry rate.
- Learning governance: licensed source coverage, split leakage count,
  candidate A/B evidence and rollback reproducibility.

The current values and milestone targets live only in
[`ROADMAP.md`](./ROADMAP.md).

## 9. Current limitations

- GP5 has no native keyboard representation equivalent to MusicXML grand
  staff; keys/generic parts use a pitch-preserving serialization view.
- Async jobs execute in the API process. A process restart can interrupt active
  work; distributed workers and cancellation are not implemented.
- Tuning inference is single-best plus user override, not per-track Top-K with
  calibrated confidence/capo inference.
- Professional fingering and technique recovery remain below the product's
  final quality target even though hard playability validation is enforced.
- Guitar performance priors now have a reproducible public GuitarSet baseline
  with performer-disjoint train/validation/test splits and CC BY 4.0
  attribution. Coverage is still limited to its five styles and two roles.
- The supplied GP corpus is hash-inventoried and usable for private evaluation,
  but cannot train or promote knowledge until rights, review tier and dataset
  split metadata are complete.
- PyGuitarPro cannot parse legacy Guitar Pro 2.21 `.gtp` files.
- Only Ample Guitar Eclipse has a production sound-profile exporter.

## 10. Non-goals for the next milestone

- Replacing deterministic score truth with end-to-end LLM generation.
- Adding many sound libraries before the GP5 quality and evaluation gates are
  trustworthy.
- Training a neural fingering model before the corpus is licensed, split and
  governed.
- Creating instrument-specific score copies outside SongIR.

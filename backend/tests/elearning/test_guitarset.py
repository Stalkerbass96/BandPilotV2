"""Tests for the rights-clear GuitarSet knowledge builder."""

from __future__ import annotations

import json

from fretpilot.elearning.guitarset import (
    GuitarSetExcerpt,
    GuitarSetNote,
    absolute_shape,
    aggregate_excerpts,
    build_kb2_asset,
    load_excerpt,
    relative_shape,
    split_name,
)


def test_performer_split_is_frozen_and_disjoint() -> None:
    assert {split_name(value) for value in ("00", "01", "02", "03")} == {"train"}
    assert split_name("04") == "validation"
    assert split_name("05") == "test"


def test_relative_shape_is_transposition_invariant() -> None:
    first = (
        GuitarSetNote(0, 1, 43, 6, 3),
        GuitarSetNote(0, 1, 50, 5, 5),
    )
    transposed = (
        GuitarSetNote(0, 1, 45, 6, 5),
        GuitarSetNote(0, 1, 52, 5, 7),
    )

    assert absolute_shape(first) != absolute_shape(transposed)
    assert relative_shape(first) == relative_shape(transposed) == "s5+2,s6+0"


def test_load_excerpt_maps_low_to_high_string_numbers(tmp_path) -> None:
    path = tmp_path / "00_Rock1-120-A_solo.jams"
    path.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "namespace": "note_midi",
                        "annotation_metadata": {"data_source": "0"},
                        "data": [{"time": 0.0, "duration": 0.5, "value": 42.0}],
                    },
                    {
                        "namespace": "note_midi",
                        "annotation_metadata": {"data_source": "5"},
                        "data": [{"time": 1.0, "duration": 0.5, "value": 64.0}],
                    },
                    {
                        "namespace": "tempo",
                        "annotation_metadata": {"data_source": ""},
                        "data": [{"time": 0.0, "duration": 2.0, "value": 120.0}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    excerpt = load_excerpt(path)

    assert excerpt.style == "rock"
    assert excerpt.role == "lead"
    assert [(note.string, note.fret) for note in excerpt.notes] == [(6, 2), (1, 0)]


def test_aggregation_never_builds_cross_excerpt_chords_or_transitions() -> None:
    excerpts = [
        GuitarSetExcerpt("one", "00", "rock", "lead", 120.0, (GuitarSetNote(0.0, 0.5, 40, 6, 0),)),
        GuitarSetExcerpt("two", "01", "rock", "lead", 120.0, (GuitarSetNote(0.0, 0.5, 76, 1, 12),)),
    ]

    observed = aggregate_excerpts(excerpts)

    assert observed["chord_onset_rate"] == 0.0
    assert observed["stable_transition_rate"] == 0.0
    assert observed["chord_shapes"] == {}


def test_complete_builder_creates_evaluated_style_role_profiles(tmp_path) -> None:
    document = {
        "annotations": [
            {
                "namespace": "note_midi",
                "annotation_metadata": {"data_source": "0"},
                "data": [{"time": 0.0, "duration": 0.5, "value": 40.0}],
            },
            {
                "namespace": "tempo",
                "annotation_metadata": {"data_source": ""},
                "data": [{"time": 0.0, "duration": 1.0, "value": 120.0}],
            },
        ]
    }
    for performer in range(6):
        for style in ("BN", "Funk", "Jazz", "Rock", "SS"):
            for role in ("comp", "solo"):
                for take in range(6):
                    path = tmp_path / f"{performer:02d}_{style}{take}-120-A_{role}.jams"
                    path.write_text(json.dumps(document), encoding="utf-8")

    asset = build_kb2_asset(tmp_path)
    empirical = [
        entry for entry in asset["entries"] if entry["provenance"]["source_type"] == "empirical"
    ]

    assert len(empirical) == 10
    assert all(entry["status"] == "approved" for entry in empirical)
    assert all(entry["evaluation"]["metrics"]["promotion_gate"]["passed"] for entry in empirical)

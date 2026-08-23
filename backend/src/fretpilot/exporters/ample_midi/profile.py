"""Ample Guitar profile model — loaded from JSON assets (v2 schema).

A profile describes a specific virtual guitar instrument's keyswitch mapping,
playable range, velocity layers, and supported articulations. The v2 schema
uses a nested structure with per-articulation keyswitch definitions, velocity
layers, string-force / capo-force / FX / control-switch tables.

New instruments = new JSON files; no code changes required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VelocityLayer:
    """A single velocity band within an articulation."""

    min: int
    max: int
    name: str


@dataclass(frozen=True, slots=True)
class ArticulationKS:
    """One articulation's keyswitch definition and behaviour metadata."""

    note: int
    label: str
    playable_min: int
    playable_max: int
    velocity_layers: tuple[VelocityLayer, ...] = ()
    persist: bool = False
    can_combine_with: str = ""
    poly_legato: bool = False
    requirements: tuple[str, ...] = ()
    revert_to: str = ""


@dataclass(frozen=True, slots=True)
class StringForceEntry:
    """A string-select keyswitch entry (MIDI note -> string number)."""

    note: int
    label: str
    string: int  # 1-6


@dataclass(frozen=True, slots=True)
class CapoForce:
    """Capo-force keyswitch block."""

    activate_note: int
    position_notes: tuple[int, ...]
    fret_min: int
    fret_max: int


@dataclass(frozen=True, slots=True)
class FXSound:
    """An FX sound keyswitch."""

    note: int
    label: str


@dataclass(frozen=True, slots=True)
class ControlSwitch:
    """A control-switch keyswitch (velocity-gated on/off)."""

    note: int
    label: str
    high_velocity: str = ""
    low_velocity: str = ""


# ---------------------------------------------------------------------------
# Articulation-type -> keyswitch-name mapping (Ample product family)
# ---------------------------------------------------------------------------

_ARTICULATION_TYPE_TO_KEY: dict[str, str] = {
    "hammer_on": "hammer_pull",
    "pull_off": "hammer_pull",
    "slide": "legato_slide",
    "palm_mute": "palm_mute",
    "natural_harmonic": "natural_harmonic",
    "slide_in": "slide_in_out",
    "slide_out": "slide_in_out",
    "sustain": "sustain",
    "tap": "tap",
    # SC-specific (not present in Eclipse profiles — keyswitch_note returns None)
    "pinch_harmonic": "pinch_harmonic",
    "slide_guitar": "slide_guitar",
}


# ---------------------------------------------------------------------------
# Main profile dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmpleGuitarProfile:
    """Virtual-instrument profile for Ample Guitar MIDI rendering (v2)."""

    profile_id: str
    product: str
    manufacturer: str
    kb_version: str
    octave_convention: str
    # Global parameters (flattened from the "global" sub-object).
    playable_min: int
    playable_max: int
    note_channel: int
    keyswitch_velocity: int
    note_off_velocity: int
    keyswitch_length_ticks: int
    legato_overlap_ticks: int
    keyswitch_preroll_ticks: int
    # Nested structures.
    articulations: dict[str, ArticulationKS]
    string_force: tuple[StringForceEntry, ...]
    capo_force: CapoForce | None
    fx_sounds: dict[str, FXSound]
    control_switches: dict[str, ControlSwitch]
    supported_articulations: frozenset[str]

    # -- construction --------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AmpleGuitarProfile":
        """Construct a profile from a v2 JSON-loaded dict."""
        global_block = data.get("global", {})
        if not isinstance(global_block, dict):
            raise ValueError("Profile 'global' block must be an object.")
        return cls(
            profile_id=str(data["profile_id"]),
            product=str(data["product"]),
            manufacturer=str(data.get("manufacturer", "")),
            kb_version=str(data.get("kb_version", "")),
            octave_convention=str(data.get("octave_convention", "")),
            playable_min=int(global_block.get("playable_min", 0)),
            playable_max=int(global_block.get("playable_max", 127)),
            note_channel=int(global_block.get("note_channel", 0)),
            keyswitch_velocity=int(global_block.get("keyswitch_velocity", 100)),
            note_off_velocity=int(global_block.get("note_off_velocity", 64)),
            keyswitch_length_ticks=int(global_block.get("keyswitch_length_ticks", 12)),
            legato_overlap_ticks=int(global_block.get("legato_overlap_ticks", 30)),
            keyswitch_preroll_ticks=int(global_block.get("keyswitch_preroll_ticks", 30)),
            articulations=_parse_articulations(data.get("articulations", {})),
            string_force=_parse_string_force(data.get("string_force")),
            capo_force=_parse_capo_force(data.get("capo_force")),
            fx_sounds=_parse_fx_sounds(data.get("fx_sounds", {})),
            control_switches=_parse_control_switches(data.get("control_switches", {})),
            supported_articulations=frozenset(
                str(a) for a in data.get("supported_articulations", [])
            ),
        )

    @classmethod
    def from_json_file(cls, path: Path | str) -> "AmpleGuitarProfile":
        """Load a profile from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Profile JSON {path} root must be an object.")
        return cls.from_dict(data)

    # -- queries -------------------------------------------------------------

    def articulation_def(self, articulation_type: str) -> ArticulationKS | None:
        """Return the ArticulationKS for an articulation type, or None."""
        key = _ARTICULATION_TYPE_TO_KEY.get(articulation_type, articulation_type)
        return self.articulations.get(key)

    def keyswitch_note(self, articulation_type: str) -> int | None:
        """Return the keyswitch note for an articulation type, or None."""
        art = self.articulation_def(articulation_type)
        return art.note if art is not None else None

    def keyswitch_for_articulation(self, articulation_type: str) -> int | None:
        """Deprecated alias for :meth:`keyswitch_note`."""
        return self.keyswitch_note(articulation_type)

    def playable_range_for(self, articulation_type: str) -> tuple[int, int]:
        """Return ``(min, max)`` playable range for an articulation type.

        Falls back to the global playable range when the articulation is not
        explicitly defined in the profile.
        """
        art = self.articulation_def(articulation_type)
        if art is not None:
            return (art.playable_min, art.playable_max)
        return (self.playable_min, self.playable_max)


# ---------------------------------------------------------------------------
# v2 JSON parsing helpers
# ---------------------------------------------------------------------------


def _parse_velocity_layers(raw: list[Any]) -> tuple[VelocityLayer, ...]:
    """Parse a list of velocity-layer dicts into VelocityLayer objects."""
    layers: list[VelocityLayer] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        layers.append(
            VelocityLayer(
                min=int(entry["min"]),
                max=int(entry["max"]),
                name=str(entry.get("name", "")),
            )
        )
    return tuple(layers)


def _parse_articulations(raw: dict[str, Any]) -> dict[str, ArticulationKS]:
    """Parse the nested 'articulations' object into ArticulationKS objects."""
    result: dict[str, ArticulationKS] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            continue
        ks = body.get("keyswitch", {})
        rng = body.get("playable_range", {})
        result[name] = ArticulationKS(
            note=int(ks.get("note", 0)),
            label=str(ks.get("label", "")),
            playable_min=int(rng.get("min", 0)),
            playable_max=int(rng.get("max", 127)),
            velocity_layers=_parse_velocity_layers(body.get("velocity_layers", [])),
            persist=bool(body.get("persist", False)),
            can_combine_with=str(body.get("can_combine_with", "")),
            poly_legato=bool(body.get("poly_legato", False)),
            requirements=tuple(str(r) for r in body.get("requirements", [])),
            revert_to=str(body.get("revert_to", "")),
        )
    return result


def _parse_string_force(raw: dict[str, Any] | None) -> tuple[StringForceEntry, ...]:
    """Parse the 'string_force' block into StringForceEntry objects."""
    if not raw or not isinstance(raw, dict):
        return ()
    entries: list[StringForceEntry] = []
    for item in raw.get("notes", []):
        if not isinstance(item, dict):
            continue
        entries.append(
            StringForceEntry(
                note=int(item["note"]),
                label=str(item.get("label", "")),
                string=int(item["string"]),
            )
        )
    return tuple(entries)


def _parse_capo_force(raw: dict[str, Any] | None) -> CapoForce | None:
    """Parse the 'capo_force' block into a CapoForce object."""
    if not raw or not isinstance(raw, dict):
        return None
    fret_range = raw.get("fret_range", {})
    return CapoForce(
        activate_note=int(raw.get("activate_note", 0)),
        position_notes=tuple(int(n) for n in raw.get("position_notes", [])),
        fret_min=int(fret_range.get("min", 0)),
        fret_max=int(fret_range.get("max", 0)),
    )


def _parse_fx_sounds(raw: dict[str, Any]) -> dict[str, FXSound]:
    """Parse the 'fx_sounds' object into FXSound objects."""
    result: dict[str, FXSound] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            continue
        result[name] = FXSound(
            note=int(body.get("note", 0)),
            label=str(body.get("label", "")),
        )
    return result


def _parse_control_switches(raw: dict[str, Any]) -> dict[str, ControlSwitch]:
    """Parse the 'control_switches' object into ControlSwitch objects.

    Handles both single-note switches (``note``/``label``) and multi-note
    switches such as ``poly_repeater`` (``notes``/``labels`` arrays) by
    using the first entry of the array.
    """
    result: dict[str, ControlSwitch] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            continue
        note = body.get("note")
        if note is None and "notes" in body:
            notes_list = body["notes"]
            note = notes_list[0] if notes_list else 0
        label = body.get("label")
        if label is None and "labels" in body:
            labels_list = body["labels"]
            label = labels_list[0] if labels_list else ""
        result[name] = ControlSwitch(
            note=int(note) if note is not None else 0,
            label=str(label) if label is not None else "",
            high_velocity=str(body.get("high_velocity", "")),
            low_velocity=str(body.get("low_velocity", "")),
        )
    return result


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_profile(profile_id: str, profiles_dir: Path | str | None = None) -> AmpleGuitarProfile:
    """Load a profile by ID from the profiles directory."""
    if profiles_dir is None:
        from fretpilot.config import get_settings

        profiles_dir = get_settings().profiles_dir
    profiles_dir = Path(profiles_dir)

    filename = f"{profile_id}.json"
    path = profiles_dir / filename
    if not path.exists():
        available = [p.stem for p in profiles_dir.glob("*.json")]
        raise ValueError(
            f"Unknown profile {profile_id!r}; available: {', '.join(sorted(available))}"
        )
    return AmpleGuitarProfile.from_json_file(path)


__all__ = [
    "AmpleGuitarProfile",
    "ArticulationKS",
    "CapoForce",
    "ControlSwitch",
    "FXSound",
    "StringForceEntry",
    "VelocityLayer",
    "load_profile",
]

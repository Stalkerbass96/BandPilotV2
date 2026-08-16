"""Exporter protocol and shared result type.

All exporters consume the IR contract (read-only) and produce an output file.
New formats = new Exporter implementation. Exporters never modify the IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from fretpilot.ir.models import GuitarProjectIR


@dataclass(slots=True)
class ExportResult:
    """Result of an export operation."""

    format_id: str
    path: str
    measure_count: int
    note_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "format_id": self.format_id,
            "path": self.path,
            "measure_count": self.measure_count,
            "note_count": self.note_count,
            "warnings": self.warnings,
        }


@runtime_checkable
class Exporter(Protocol):
    """Unified contract for all exporters."""

    format_id: str

    def export(self, ir: GuitarProjectIR, output_path: Path | str) -> ExportResult:
        """Consume IR and write the output file. Never modifies the IR."""
        ...


class UnsupportedGuitarIR(ValueError):
    """Raised when an exporter cannot represent an IR pattern."""


__all__ = ["ExportResult", "Exporter", "UnsupportedGuitarIR"]

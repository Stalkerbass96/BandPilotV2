"""CLI entry point for the e-learning module.

Usage::

    python -m fretpilot.elearning evaluate --input-dir <gp_dir> --output report.json
    python -m fretpilot.elearning evaluate --input <single.gp5> --output report.json
    python -m fretpilot.elearning learn --input-dir <gp_dir> --kb-root <knowledge_dir>
    python -m fretpilot.elearning kb list-versions [--kb-root <knowledge_dir>]
    python -m fretpilot.elearning kb rollback --version <version> [--kb-root <knowledge_dir>]
    python -m fretpilot.elearning kb diff --a <v1> --b <v2> [--kb-root <knowledge_dir>]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Run evaluation on a file or directory."""
    from fretpilot.elearning.evaluate import BatchEvaluator

    evaluator = BatchEvaluator(knowledge_dir=getattr(args, "knowledge_dir", None))

    if args.input:
        # Single file
        report = evaluator.evaluate_file(args.input)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Report saved: {args.output}")
        print(f"\nOverall Fingering Accuracy: {report.metrics.overall_fingering_accuracy:.1%}")
        print(f"String Match: {report.metrics.string_match_rate:.1%}")
        print(f"Fret Match:   {report.metrics.fret_match_rate:.1%}")
    elif args.input_dir:
        evaluator.evaluate_dir(
            args.input_dir,
            output_path=args.output,
            max_files=args.max_files,
        )
    else:
        print("Error: --input or --input-dir required")
        return 1
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """Run knowledge extraction + KB update."""
    from fretpilot.elearning.evaluate import BatchEvaluator
    from fretpilot.elearning.gp_reader import GPReader
    from fretpilot.elearning.stats_extractor import StatsExtractor
    from fretpilot.elearning.priors_deriver import PriorsDeriver
    from fretpilot.elearning.kb_writer import KBWriter

    # 1. Parse all GP files
    reader = GPReader()
    gp_files = []
    for ext in (".gp3", ".gp4", ".gp5"):
        gp_files.extend(Path(args.input_dir).rglob(f"*{ext}"))
    gp_files.sort()
    if args.max_files:
        gp_files = gp_files[: args.max_files]

    print(f"Parsing {len(gp_files)} GP files...")
    tabs = []
    for i, gp_path in enumerate(gp_files):
        try:
            tab = reader.parse(gp_path)
            tabs.append(tab)
        except Exception as exc:
            logging.warning("Skip %s: %s", gp_path.name, exc)

    print(f"Successfully parsed {len(tabs)} files")

    # 2. Extract statistics
    print("Extracting fingering statistics...")
    extractor = StatsExtractor()
    style_stats = extractor.extract(tabs)
    for style, stats in style_stats.items():
        print(f"  {style}: {stats.sample_count} files, {stats.total_notes} notes, "
              f"open_string_rate={stats.open_string_rate:.1%}")

    # 3. Derive priors
    print("Deriving empirical priors...")
    deriver = PriorsDeriver()
    source_ids_map = {style: [t.file_path for t in tabs if t.style_label == style] for style in style_stats}
    derived = deriver.derive(style_stats, source_ids_map)
    for d in derived:
        print(f"  {d.style_label}: {d.payload}")
        print(f"    confidence={d.confidence:.2f}, sources={len(d.source_ids)}")

    # 4. Write to KB
    print("Writing empirical priors to KB...")
    kb_root = args.kb_root or str(Path(__file__).resolve().parent.parent / "knowledge")
    writer = KBWriter(kb_root)
    new_version = writer.write(derived)
    print(f"New KB version: {new_version}")

    # 5. Run evaluation with new priors
    print("\nRunning evaluation with empirical priors...")
    evaluator = BatchEvaluator(knowledge_dir=str(writer.version_dir(new_version)))
    result = evaluator.evaluate_dir(
        args.input_dir,
        output_path=args.output,
        max_files=args.max_files,
    )

    # 6. A/B compare old vs new KB version (if a previous version exists)
    versions = writer.list_versions()
    if len(versions) >= 2:
        old_version = versions[-2]["version"]
        print(f"\nA/B comparing {old_version} -> {new_version}...")
        from fretpilot.elearning.kb_writer import ABComparator
        comparator = ABComparator(kb_root)
        ab_result = comparator.compare(args.input_dir, old_version, new_version)
        print(f"Assessment: {ab_result['assessment']}")
        acc_delta = ab_result["overall_delta"].get("overall_fingering_accuracy", 0.0)
        print(f"Overall accuracy delta: {acc_delta:+.4f}")
        for style, delta in ab_result.get("per_style_delta", {}).items():
            style_acc = delta.get("overall_fingering_accuracy", 0.0)
            print(f"  {style}: accuracy delta {style_acc:+.4f}")
    else:
        print("\nSkipping A/B comparison (need at least 2 versions)")

    return 0


def _default_kb_root() -> str:
    """Default knowledge base root (``src/fretpilot/knowledge``)."""
    return str(Path(__file__).resolve().parent.parent / "knowledge")


def cmd_kb(args: argparse.Namespace) -> int:
    """KB version management: list, rollback, diff."""
    from fretpilot.elearning.kb_writer import KBWriter

    kb_root = args.kb_root or _default_kb_root()
    writer = KBWriter(kb_root)

    if args.kb_action == "list-versions":
        versions = writer.list_versions()
        if not versions:
            print("No KB versions found.")
            return 0
        active = writer._load_manifest().get("active_version", "")
        print(f"Active version: {active or '(none)'}")
        print(f"{'VERSION':22s} {'SOURCE':10s} {'STYLES':18s} {'SOURCES':>8s} {'AVG_CONF':>9s}")
        for v in versions:
            styles = ",".join(v.get("styles_updated", [])) or "-"
            print(
                f"{v['version']:22s} {v.get('source_type', '-'):10s} "
                f"{styles:18s} {v.get('total_sources', 0):>8d} "
                f"{v.get('avg_confidence', 0.0):>9.3f}"
            )
        return 0

    if args.kb_action == "rollback":
        writer.rollback(args.version)
        print(f"Rolled back active KB to version {args.version}")
        return 0

    if args.kb_action == "diff":
        result = writer.diff_versions(args.a, args.b)
        print(f"Diff {result['version_a']} -> {result['version_b']}:")
        if not result["entry_diffs"]:
            print("  (no entry differences)")
        for kid, entry in result["entry_diffs"].items():
            src = f"{entry['source_type_a']} -> {entry['source_type_b']}"
            print(f"  {kid}  [{src}]")
            for key, delta in entry["payload_diff"].items():
                d = delta["delta"]
                d_str = f"{d:+.6f}" if d is not None else "-"
                print(f"    {key}: {delta['a']} -> {delta['b']}  (delta {d_str})")
        return 0

    print(f"Error: unknown kb action: {args.kb_action}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fretpilot.elearning",
        description="FretPilot Learning Loop — evaluation and knowledge extraction",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Run round-trip evaluation")
    eval_group = eval_parser.add_mutually_exclusive_group(required=True)
    eval_group.add_argument("--input", help="Single GP file path")
    eval_group.add_argument("--input-dir", help="Directory of GP files")
    eval_parser.add_argument("--output", help="Output JSON report path")
    eval_parser.add_argument("--max-files", type=int, help="Limit files (for testing)")
    eval_parser.add_argument("--knowledge-dir", help="KB version directory override")

    # learn
    learn_parser = subparsers.add_parser("learn", help="Extract knowledge + update KB")
    learn_parser.add_argument("--input-dir", required=True, help="Directory of GP files")
    learn_parser.add_argument("--kb-root", help="Knowledge base root directory")
    learn_parser.add_argument("--output", help="Output report path")
    learn_parser.add_argument("--max-files", type=int, help="Limit files (for testing)")

    # kb (version management)
    kb_parent = argparse.ArgumentParser(add_help=False)
    kb_parent.add_argument("--kb-root", help="Knowledge base root directory")
    kb_parser = subparsers.add_parser("kb", help="KB version management", parents=[kb_parent])
    kb_sub = kb_parser.add_subparsers(dest="kb_action", required=True)

    list_parser = kb_sub.add_parser("list-versions", parents=[kb_parent],
                                    help="List all KB versions")
    list_parser.set_defaults(kb_action="list-versions")

    rollback_parser = kb_sub.add_parser("rollback", parents=[kb_parent],
                                        help="Roll back active KB to a version")
    rollback_parser.add_argument("--version", required=True, help="Target version string")

    diff_parser = kb_sub.add_parser("diff", parents=[kb_parent],
                                    help="Compare priors between two versions")
    diff_parser.add_argument("--a", dest="a", required=True, help="Baseline version")
    diff_parser.add_argument("--b", dest="b", required=True, help="Comparison version")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "evaluate":
        return cmd_evaluate(args)
    elif args.command == "learn":
        return cmd_learn(args)
    elif args.command == "kb":
        return cmd_kb(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())

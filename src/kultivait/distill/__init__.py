"""The distillation pipeline package (spec #53, ADRs 0012-0017).

D1 ships the corpus foundations; generator/trainer/eval/export/shadow land
in their slices (D2-D6).
"""

from kultivait.distill.corpus import (
    Anchor,
    TrainingPair,
    assemble_pair,
    build_corpus,
    dry_run_report,
    extract_anchors,
    regress_fits,
    split_heldout,
    write_corpus,
)

__all__ = [
    "Anchor",
    "TrainingPair",
    "assemble_pair",
    "build_corpus",
    "dry_run_report",
    "extract_anchors",
    "regress_fits",
    "split_heldout",
    "write_corpus",
]

"""Record what a burned-area run read: the hash of each input file and each month's checks.

The record goes into result.json. `earthlab replay` compares it with the files on disk, so
a changed raster, manifest, case file or method file makes the replay fail.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from earthlab.agent.area_findings import AreaLedger
from earthlab.cases.loader import CaseFile
from earthlab.cases.tools import CaseLibrary
from earthlab.data.firms import detections_in_month
from earthlab.data.mcd64a1 import read_manifest
from earthlab.digest import file_digest
from earthlab.science.burned_area import QA_POLICY_FILE
from earthlab.tools.burned_area_tools import METHOD_FILE, month_report

_ERRORS = (ValueError, OSError, RuntimeError, StopIteration, KeyError)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def input_files(library: CaseLibrary, case_id: str) -> dict[str, str]:
    """Method file, case file, and every manifest and data file of the case's assets."""
    case_file = library.get(case_id)
    root = library.root
    paths = [root / METHOD_FILE, root / QA_POLICY_FILE]
    if case_id in library.files:
        paths.append(library.files[case_id])
    if case_file.case.data_dir is not None:
        folder = root / case_file.case.data_dir
        for asset_id in case_file.assets:
            manifest = folder / f"{asset_id}.manifest.json"
            if manifest.is_file():
                paths.append(manifest)
                paths += [folder / f["file"] for f in read_manifest(manifest)["files"]]
    return {_relative(p, root): file_digest(p) for p in paths}


def firms_asset_id(case_file: CaseFile) -> str | None:
    """The case's single pinned FIRMS asset, or None when it has none."""
    ids = [a.asset_id for a in case_file.assets.values() if a.product.startswith("FIRMS/")]
    data_ok = case_file.case.data_dir is not None and case_file.case.area.bbox is not None
    return ids[0] if len(ids) == 1 and data_ok else None


def _firms_count(case_file: CaseFile, root: Path, month: str) -> int | None:
    asset_id = firms_asset_id(case_file)
    if asset_id is None:
        return None
    assert case_file.case.data_dir is not None
    assert case_file.case.area.bbox is not None
    folder = root / case_file.case.data_dir
    return detections_in_month(folder, f"{asset_id}.manifest.json", case_file.case.area.bbox, month)


def month_record(library: CaseLibrary, case_id: str, month: str) -> dict[str, Any]:
    case_file = library.get(case_id)
    report = month_report(case_file, library.root, month)
    return {
        "case_id": case_id,
        "month": month,
        "area_ha": report["summary"]["primary_area_ha"],
        "valid_fraction": report["summary"]["valid_fraction"],
        "check": report["check"],
        "source_sha256": report["source"]["sha256"],
        "firms_detections": _firms_count(case_file, library.root, month),
    }


def month_or_error(library: CaseLibrary, case_id: str, month: str) -> dict[str, Any]:
    """The month record, or the read error as the record: either way it can be replayed."""
    try:
        return month_record(library, case_id, month)
    except _ERRORS as exc:
        return {"case_id": case_id, "month": month, "error": str(exc)}


def collect_evidence(library: CaseLibrary | None, ledger: AreaLedger) -> dict[str, Any] | None:
    """Hashes and checks for every (case, month) the run read or claimed; None if none."""
    claimed = [(r.claim.case_id, r.claim.month) for rnd in ledger.rounds for r in rnd]
    pairs = list(dict.fromkeys([*ledger.consulted, *claimed]))
    if library is None or not pairs:
        return None
    files: dict[str, str] = {}
    for case_id in dict.fromkeys(case_id for case_id, _ in pairs):
        with contextlib.suppress(*_ERRORS):  # an unknown case has no files; its month says why
            files.update(input_files(library, case_id))
    months = [month_or_error(library, case_id, month) for case_id, month in pairs]
    return {"files": dict(sorted(files.items())), "months": months}

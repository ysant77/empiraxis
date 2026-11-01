"""S4 measured: real chip facts go to the gate. No weights are loaded and nothing is scored.

Two requests use the same chip facts. One asks to score the model on the shipped chips. The
other asks for burn scars in the Kalimantan study box. The gate gives a verdict for each.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from earthlab.cases.models import BoundingBox
from earthlab.harness import gates
from earthlab.harness.chip_probe import ChipFacts, probe, survey, utm_to_lonlat
from earthlab.harness.segmentation_gate import (
    Imagery,
    ReferenceMasks,
    Resources,
    SegmentationGateV1,
    SegmentationRequestV1,
    Weights,
    gate,
)

KALIMANTAN = BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0)
WEIGHTS = "prithvi-burnscars-weights"
CARD_BANDS = gates.HLS_BANDS  # the dataset card order; the files carry no band names
NEEDED_BYTES = 2_000_000_000


def _footprint(chip: ChipFacts) -> BoundingBox:
    x0, y0 = chip.origin_xy or (0.0, 0.0)
    size = (chip.pixel_size or (30.0, 30.0))[0] * chip.shape[0]
    lon0, lat1 = utm_to_lonlat(x0, y0, 14)
    lon1, lat0 = utm_to_lonlat(x0 + size, y0 - size, 14)
    return BoundingBox(min_lon=lon0, min_lat=lat0, max_lon=lon1, max_lat=lat1)


def _requests(chip: ChipFacts, mask: ChipFacts, weights: Weights) -> list[SegmentationRequestV1]:
    foot = _footprint(chip)
    covered = 1 - chip.nodata_pixels / (chip.shape[0] * chip.shape[1])
    imagery = Imagery(
        bands=CARD_BANDS if chip.band_count == 6 else (), crs=chip.crs_name,
        resolution_m=(chip.pixel_size or (None,))[0], coverage_fraction=covered, footprint=foot,
        band_order_source="documentation",
    )  # fmt: skip
    masks = ReferenceMasks(
        present=mask.mask_values == (0, 1), source="annotation shipped with the dataset",
        derived_from=("dataset annotators",),
    )  # fmt: skip
    machine = Resources(
        free_disk_bytes=shutil.disk_usage(Path.home()).free, needed_bytes=NEEDED_BYTES,
        ram_bytes=os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"), device="mps",
    )  # fmt: skip
    base = dict(masks=masks, imagery=imagery, weights=weights, resources=machine)
    return [
        SegmentationRequestV1(
            request_id="s4-chips",
            question="Score the weights on the shipped chips.",
            aoi=foot,
            **base,
        ),
        SegmentationRequestV1(
            request_id="s4-kalimantan",
            question="Map burn scars in the Kalimantan box.",
            aoi=KALIMANTAN,
            **base,
        ),
    ]


def measure(assets: Path) -> dict[str, object]:
    folder = assets / "hls-burn-scars-1864285e"
    found = survey(folder / "hls_burn_scars.tar.gz", folder / "extracted-sample")
    sample = folder / "extracted-sample"
    chip = probe(sample / Path(found.sample_chip).name)
    mask = probe(sample / Path(found.sample_mask or "").name)
    prov = json.loads((assets / "prithvi-burnscars-a3f2c410/provenance.json").read_text("utf-8"))
    weights = Weights(asset_id=WEIGHTS, local_state="verified", permission="chat_only_unsigned")
    verdicts: dict[str, SegmentationGateV1] = {
        r.request_id: gate(r) for r in _requests(chip, mask, weights)
    }
    return {
        "archive": found.model_dump(), "chip": chip.model_dump(), "mask": mask.model_dump(),
        "footprint": _footprint(chip).model_dump(), "weights_authority": prov["authority"],
        "verdicts": {k: v.model_dump(mode="json") for k, v in verdicts.items()},
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S4 gate on real chip facts.")
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = measure(args.assets)
    args.out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    for name, verdict in result["verdicts"].items():  # type: ignore[attr-defined]
        print(name, verdict["outcome"], [r["detail"] for r in verdict["refusals"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

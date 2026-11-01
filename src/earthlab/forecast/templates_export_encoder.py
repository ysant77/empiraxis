"""The approved export template. It runs alone, in the isolated environment.

It reads one saved state dict with tensor-only loading and writes the recurrent weights of a
GRU as plain arrays in one NPZ. No generated code runs here, and nothing else is read or kept.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

PREFIX = "rnn."


def main() -> int:
    out = Path(sys.argv[1])
    job = json.loads((out / "job.json").read_text(encoding="utf-8"))
    state = torch.load(job["model"], weights_only=True)
    weights = {
        key[len(PREFIX) :]: value.double().numpy()
        for key, value in state.items()
        if key.startswith(PREFIX)
    }
    wanted = {
        f"{kind}_l{k}"
        for k in range(job["layers"])
        for kind in ("weight_ih", "weight_hh", "bias_ih", "bias_hh")
    }
    if set(weights) != wanted:
        raise SystemExit(f"the state dict does not hold a {job['layers']}-layer GRU")
    np.savez(out / "encoder.npz", allow_pickle=False, **weights)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

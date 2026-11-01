"""Data, feature and model engineering for the experiment harness.

The harness owns the lifecycle. This package owns versioned records: it validates data, fits
preprocessing on train spans only, and stores feature and model bundles by content digest.
Code executes every step. A proposal from a model is a value that code validates first.
"""

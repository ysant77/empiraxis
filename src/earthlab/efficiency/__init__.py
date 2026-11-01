"""Offline measurement tools for routing and prompt efficiency.

Nothing here calls a model, reads a credential or changes a workflow contract. The profiler
reads recorded runs, the reviewer reads prompt text, the router is a pure function, and the
compression forms are typed and reversible. No module claims a saving: only paired live
runs can show one.
"""

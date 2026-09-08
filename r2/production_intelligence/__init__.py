"""Reusable R2-M4 production-intelligence spine.

Provider-neutral routing, readiness, method selection, capability resolution,
admission, execution-decision locking, prompt planning, failure normalization and
telemetry projection. Runtime/artifact/cost truth stays in the Host; only
``host_integration`` reaches into ``server`` (the C04 budget guard), and nothing
here imports ``lib.db``.
"""

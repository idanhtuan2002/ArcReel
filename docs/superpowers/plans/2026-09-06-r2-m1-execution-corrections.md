# R2-M1 Execution Corrections

These are implementation-level corrections discovered during pre-execution review.
They do not change the approved R2-M1 architecture.

1. `ProductionReadiness.state`: the implementation must not use a serialized
   `@computed_field` in a way that breaks the required
   `model_dump(mode="json") -> model_validate()` round trip. Task 4 must use a
   serialized field whose value is derived/validated against requirements, or an
   equivalent representation that preserves both invariants.
2. Task 8 AST import-boundary check must use
   `name in ("server", "lib") or name.startswith(("server.", "lib."))`.
3. `ensure_json_value()` must reject non-finite floats (`NaN`, `Infinity`,
   `-Infinity`) because canonical JSON uses `allow_nan=False` and the design
   requires JSON-compatible reproducible values.

"""M6 dual-profile adaptation: pure evaluators, hashing, the append-only
adaptation-authority kernel, TakeDirector integration, and Golden B evidence.

Contracts live in ``r2.contracts.adaptation``, not here. Nothing here imports a
concrete repository, session, ORM row, or Canon/Production transaction service —
every adapter lives under ``lib.db`` / ``server.services`` and every dependency is
a structural port. Re-exports accumulate here as later tasks add modules.
"""

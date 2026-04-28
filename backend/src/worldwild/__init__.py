"""WorldWild ingest layer — secondary DB (Supabase) for external job-board API ingestion.

This package mirrors the architecture of ``inbox`` / ``analysis`` but writes to the
secondary database defined in ``..database.worldwild_db``. Promotion of curated
offers into the primary DB's ``job_analyses`` is an explicit user action, never
automatic — see PR #1 design notes.
"""

"""Inbox module: raw job paste ingestion from Chrome extension.

Receives raw pasted text from the browser extension, persists it as-is,
then async-triggers an analysis via the existing analyze_job pipeline.
"""

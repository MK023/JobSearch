"""Error-handling infrastructure shared across routers/services.

Centralises the "tag exceptions by ingestion source" contract so Sentry
issues can be filtered by flow (extension / cowork / api / mcp) instead
of showing a single firehose of errors no matter who triggered them.
"""

from .source_tagging import infer_source_from_path, tag_flow_source

__all__ = ["infer_source_from_path", "tag_flow_source"]

"""Markdown report builder for analytics output.

Converts the outputs of extractor/stats/discriminator into a readable
markdown report. Reusable by CLI script and future admin endpoint.

``build_report`` orchestrates 10 section builders (one per markdown ``##``
heading). Each builder consumes already-computed features/disc/bias data
and returns a self-contained markdown chunk — keeping the orchestrator
shallow and each section testable in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .discriminator import bias_signals, discriminant_features, score_vs_outcome
from .extractor import extract_features, feature_summary
from .stats import conversion_rate, counts_by_status, distribution, group_stats, top_categories

_ROLE_BUCKET_HEADER = "Role bucket"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a markdown table."""
    if not rows:
        return "_(empty)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join("---" for _ in headers) + " |\n"
    for row in rows:
        out += "| " + " | ".join(str(cell) if cell is not None else "" for cell in row) + " |\n"
    return out


def _section(title: str, body: str) -> str:
    return f"\n## {title}\n\n{body}\n"


def _pct(num: float, denom: float) -> str:
    """Format ``num/denom`` as a 1-decimal percentage (``0%`` if denom=0)."""
    if not denom:
        return "0%"
    return f"{round(100 * num / denom, 1)}%"


def _build_overview_section(summary: dict[str, Any]) -> str:
    overview = [
        f"- **Total analyses**: {summary['total']}",
        f"- **With status**: {summary['with_status']}",
        f"- **With score > 0**: {summary['with_score']}",
        f"- **With salary info**: {summary['with_salary']}",
        f"- **With interviews scheduled**: {summary['with_interviews']}",
        f"- **Date range**: {summary['date_range']['first']} → {summary['date_range']['last']}",
    ]
    return _section("Overview", "\n".join(overview))


def _build_status_funnel_section(features: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    status_counts = counts_by_status(features)
    rows = [[s, c, _pct(c, summary["total"])] for s, c in sorted(status_counts.items(), key=lambda x: -x[1])]
    return _section("Funnel (by status)", _table(["Status", "Count", "%"], rows))


def _build_role_distribution_section(features: list[dict[str, Any]]) -> str:
    rows = [[v, c] for v, c in top_categories(features, "role_bucket", n=20)]
    return _section("Role distribution", _table([_ROLE_BUCKET_HEADER, "Count"], rows))


def _build_score_by_role_section(features: list[dict[str, Any]]) -> str:
    role_stats = group_stats(features, "role_bucket", "score")
    rows = [
        [k, int(v["count"]), v["mean"], int(v["min"]), int(v["max"])]
        for k, v in sorted(role_stats.items(), key=lambda x: -x[1]["mean"])
    ]
    return _section(
        "Score by role bucket",
        _table([_ROLE_BUCKET_HEADER, "Count", "Mean score", "Min", "Max"], rows),
    )


def _build_conversion_section(features: list[dict[str, Any]]) -> str:
    conv_role = conversion_rate(features, "role_bucket")
    rows = [
        [
            k,
            int(v["applied"]),
            int(v["to_interview"]),
            int(v["to_offer"]),
            f"{round(v['interview_rate'] * 100, 1)}%",
            f"{round(v['offer_rate'] * 100, 1)}%",
        ]
        for k, v in sorted(conv_role.items(), key=lambda x: -x[1]["interview_rate"])
    ]
    return _section(
        "Conversion by role (applied → interview / offer)",
        _table(
            [_ROLE_BUCKET_HEADER, "Applied", "Interviews", "Offers", "Interview %", "Offer %"],
            rows,
        ),
    )


def _build_distributions_section(features: list[dict[str, Any]]) -> str:
    work_mode = _table(
        ["Work mode", "Count"],
        [[v or "(none)", c] for v, c in distribution(features, "work_mode").items()],
    )
    location = _table(
        ["Location", "Count"],
        [[v, c] for v, c in distribution(features, "location_bucket").items()],
    )
    return _section("Work mode distribution", work_mode) + _section(
        "Location bucket distribution",
        location,
    )


def _build_discriminant_section(disc: dict[str, Any]) -> str:
    intro = (
        f"**Kept (candidato/colloquio/offerta)**: {disc['kept_total']}  |  "
        f"**Rejected (scartato)**: {disc['rejected_total']}\n\n"
        "Lift > 1 means the value is more common in KEPT than in REJECTED (→ discriminant feature for YES).\n"
        "Lift < 1 means more common in REJECTED (→ discriminant feature for NO).\n"
    )
    out = _section("Discriminant analysis — kept vs rejected", intro)
    for key, rows in disc["categorical"].items():
        if not rows:
            continue
        out += f"\n### {key}\n\n"
        out += _table(
            ["Value", "Kept", "Rejected", "Kept %", "Rejected %", "Lift"],
            [
                [
                    r["value"],
                    r["kept_count"],
                    r["rejected_count"],
                    f"{r['kept_pct']}%",
                    f"{r['rejected_pct']}%",
                    r["lift"],
                ]
                for r in rows
            ],
        )
    return out


def _build_numeric_deltas_section(disc: dict[str, Any]) -> str:
    rows = [
        [key, data["kept_mean"], data["rejected_mean"], data["delta"], data["kept_n"], data["rejected_n"]]
        for key, data in disc["numeric"].items()
        if data is not None
    ]
    return _section(
        "Numeric differences (kept vs rejected)",
        _table(["Feature", "Kept mean", "Rejected mean", "Delta", "N kept", "N rejected"], rows),
    )


def _build_score_buckets_section(features: list[dict[str, Any]]) -> str:
    sv_outcome = score_vs_outcome(features)
    statuses_order = ["da_valutare", "candidato", "colloquio", "offerta", "scartato", "rifiutato"]
    rows = [[label, *(outcomes.get(s, 0) for s in statuses_order)] for label, outcomes in sv_outcome.items()]
    return _section(
        "Score vs outcome (bucketed)",
        _table(["Score range", *statuses_order], rows),
    )


def _build_bias_signals_section(features: list[dict[str, Any]]) -> str:
    bias = bias_signals(features)
    out = _section("Bias signals", "")
    out += f"\n### High-score rejected (score ≥ 85 but scartato) — {len(bias['high_score_rejected'])} analisi\n\n"
    out += _table(
        ["Company", "Role", "Score"],
        [[r["company"], r["role"], r["score"]] for r in bias["high_score_rejected"]],
    )
    out += f"\n### Low-score kept (score < 60 ma candidato/colloquio) — {len(bias['low_score_kept'])} analisi\n\n"
    out += _table(
        ["Company", "Role", "Score"],
        [[r["company"], r["role"], r["score"]] for r in bias["low_score_kept"]],
    )
    out += f"\n### Same company, different outcome — {len(bias['same_company_different_outcome'])} aziende\n\n"
    if bias["same_company_different_outcome"]:
        for c in bias["same_company_different_outcome"][:20]:
            out += f"\n**{c['company']}**  \n"
            out += "- Kept: " + ", ".join(f"{k['role']} ({k['score']})" for k in c["kept"]) + "\n"
            out += "- Rejected: " + ", ".join(f"{r['role']} ({r['score']})" for r in c["rejected"]) + "\n"
    else:
        out += "_(nessuno)_\n"
    return out


def _build_top_companies_section(features: list[dict[str, Any]]) -> str:
    return _section(
        "Top companies (by count)",
        _table(["Company", "Count"], [[v, c] for v, c in top_categories(features, "company", n=20)]),
    )


def build_report(analyses: list[dict[str, Any]]) -> str:
    """Generate a full markdown report from the exported analyses payload."""
    features = [extract_features(a) for a in analyses]
    summary = feature_summary(features)
    disc = discriminant_features(features)

    out = "# JobSearch — Data Analysis Report\n\n"
    out += f"Generated at: {datetime.now(UTC).isoformat()}\n\n"
    out += _build_overview_section(summary)
    out += _build_status_funnel_section(features, summary)
    out += _build_role_distribution_section(features)
    out += _build_score_by_role_section(features)
    out += _build_conversion_section(features)
    out += _build_distributions_section(features)
    out += _build_discriminant_section(disc)
    out += _build_numeric_deltas_section(disc)
    out += _build_score_buckets_section(features)
    out += _build_bias_signals_section(features)
    out += _build_top_companies_section(features)
    return out

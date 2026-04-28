"""Mirror of Marco's tech stack extracted from his master CV.

⚠️  This file is a **manual snapshot** of the canonical CV in
``~/Documents/GitHub/Atlas/career/cv-master.md`` (and the legacy
``~/Documents/GitHub/career-kit/cv/cv_IT.md``). The mirror lives in-repo
because:

1. The runtime (Render) cannot reach Atlas — the file system is the
   developer's local Mac, not a service the deployed app talks to.
2. Determinism: stack-match scoring needs the same ground-truth set
   regardless of when / where it runs (CI, prod, local, in tests).
3. Auditability: a code-reviewed change to "what Marco knows" is more
   useful than an opaque file read.

When the master CV changes (new project, new cert, new ramp), update
this set in a code review with a short note in the commit message.
The aim is NOT to be exhaustive — only **canonical tokens** Marco can
defend in a senior interview should be here.

The token names are the canonical keys produced by
``stack_extract._VOCABULARY``. Any token that doesn't exist there
won't match an extracted offer set, which is the right behaviour.
"""

from __future__ import annotations

# ── Tier 1: core skills, defended daily / strongest in current bucket
_CORE: frozenset[str] = frozenset(
    {
        "python",
        "fastapi",
        "kubernetes",
        "docker",
        "terraform",
        "aws",
        "postgres",
        "github_actions",
        "devops",
        "linux",
        "ci_cd",
        "rest_api",
        "git",
    }
)

# ── Tier 2: strong, recently or consistently used in production
_STRONG: frozenset[str] = frozenset(
    {
        "redis",
        "prometheus",
        "grafana",
        "sentry",
        "gcp",
        "helm",
        "mysql",
        "mongodb",
        "anthropic",
        "devsecops",
        "shell",
        "microservices",
        "sistemista",  # SmartAirway + Metropolitana experience
    }
)

# ── Tier 3: familiar, used in past projects or via study
_FAMILIAR: frozenset[str] = frozenset(
    {
        "django",
        "flask",
        "jenkins",
        "opentelemetry",
        "elasticsearch",
        "kafka",
        "huggingface",
        "pytorch",
        "active_directory",
        "graphql",
        "javascript",
        "typescript",
        "react",
    }
)

# Public surface: the union, used by stack_match.score_match() as the
# "Marco knows" reference set. Tier breakdown is reserved for a future
# weighted-score variant once we decide it's worth the complexity.
MARCO_CV_SKILLS: frozenset[str] = _CORE | _STRONG | _FAMILIAR

# Tier exposure for callers that want a weighted variant later.
CV_SKILLS_TIERED: dict[str, frozenset[str]] = {
    "core": _CORE,
    "strong": _STRONG,
    "familiar": _FAMILIAR,
}

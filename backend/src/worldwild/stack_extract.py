"""Tech-stack extraction from a job posting's title + description.

Pure-function module: takes the normalized offer dict (the same shape that
``adzuna._normalize`` produces) and returns a canonical, deduplicated set
of tech tokens — e.g. ``{"python", "kubernetes", "aws", "terraform"}``.

The vocabulary is hardcoded for now (~150 canonical terms). Aliases are
collapsed at extraction time (``k8s → kubernetes``, ``postgresql → postgres``,
``otel → opentelemetry``) so downstream stack-match scoring works on a stable
canonical set regardless of how a posting phrases the same tech.

Multi-lingua: Italian + English. The Adzuna IT market mixes both, so the
vocabulary includes IT-specific terms like ``sistemista`` and the patterns
use ``re.IGNORECASE`` throughout.

Out of scope for this module:
- scoring vs Marco's CV (lives in ``stack_match.py``)
- AI-driven extraction (would lose determinism and add cost; reserved for the
  follow-up analyzer in ``services/promote_analyzer.py``)
- learning new terms over time (PR #5 feedback loop, when ``decisions`` has
  enough data to mine)
"""

from __future__ import annotations

import re
from typing import Any

# Canonical token => list of regex patterns (or plain strings) that map to it.
# Patterns are matched word-boundary, case-insensitive. Order doesn't matter.
#
# Curation rule: include a term only if (a) it appears in real job postings and
# (b) it's a meaningful signal for Marco's bucket (Cloud / DevOps / Python).
# This is NOT a generic tech taxonomy — it's a signal filter.
_VOCABULARY: dict[str, tuple[str, ...]] = {
    # ── Languages
    "python": (r"\bpython\b", r"\bpy3\b", r"\bcpython\b"),
    "java": (r"\bjava\b(?!\s*script)",),
    "javascript": (r"\bjavascript\b", r"\bjs\b", r"\becmascript\b"),
    "typescript": (r"\btypescript\b", r"\bts\b(?!\s*c)"),
    "go": (r"\bgolang\b", r"\bgo\s+lang\b"),
    "rust": (r"\brust\b(?!\s*y)",),
    "ruby": (r"\bruby\b",),
    "php": (r"\bphp\b",),
    # \b doesn't behave as expected around "#" because # is non-word: the
    # right-side \b would require a word char afterwards, which isn't there
    # in "C# with". Use lookarounds instead.
    "csharp": (r"(?<!\w)c#(?!\w)", r"\bc-sharp\b", r"\b\.net\b"),
    "scala": (r"\bscala\b",),
    "kotlin": (r"\bkotlin\b",),
    "shell": (r"\bbash\b", r"\bshell\s+script\b", r"\bzsh\b"),
    # ── Cloud platforms
    "aws": (r"\baws\b", r"\bamazon\s+web\s+services\b"),
    "azure": (r"\bazure\b", r"\bmicrosoft\s+azure\b"),
    "gcp": (r"\bgcp\b", r"\bgoogle\s+cloud\b", r"\bgcloud\b"),
    # ── Containers / orchestration
    "docker": (r"\bdocker\b", r"\bcontainerd\b", r"\bpodman\b"),
    "kubernetes": (r"\bkubernetes\b", r"\bk8s\b"),
    "helm": (r"\bhelm\b",),
    "openshift": (r"\bopenshift\b", r"\bocp\b"),
    # ── Infrastructure-as-code
    "terraform": (r"\bterraform\b", r"\bopentofu\b"),
    "ansible": (r"\bansible\b",),
    "pulumi": (r"\bpulumi\b",),
    "cloudformation": (r"\bcloud\s*formation\b",),
    # ── CI/CD
    "jenkins": (r"\bjenkins\b",),
    "github_actions": (r"\bgithub\s+actions\b", r"\bgha\b"),
    "gitlab_ci": (r"\bgitlab\s*ci\b", r"\bgitlab\s+ci/cd\b"),
    "circleci": (r"\bcircleci\b", r"\bcircle\s*ci\b"),
    "argocd": (r"\bargo\s*cd\b", r"\bargocd\b"),
    "flux": (r"\bflux(?:cd)?\b",),
    # ── Monitoring & observability
    "prometheus": (r"\bprometheus\b",),
    "grafana": (r"\bgrafana\b",),
    "datadog": (r"\bdatadog\b", r"\bdata\s*dog\b"),
    "splunk": (r"\bsplunk\b",),
    "elk": (r"\belk\s+stack\b", r"\belasticsearch\b\s*\+?\s*\bkibana\b"),
    "elasticsearch": (r"\belasticsearch\b", r"\belastic\s+search\b"),
    "opentelemetry": (r"\bopen\s*telemetry\b", r"\botel\b"),
    "sentry": (r"\bsentry\b",),
    # ── Databases
    "postgres": (r"\bpostgres(?:ql)?\b",),
    "mysql": (r"\bmysql\b", r"\bmaria\s*db\b"),
    "mongodb": (r"\bmongodb\b", r"\bmongo\s+db\b"),
    "redis": (r"\bredis\b",),
    "cassandra": (r"\bcassandra\b",),
    "neo4j": (r"\bneo4j\b",),
    "dynamodb": (r"\bdynamodb\b", r"\bdynamo\s+db\b"),
    # ── Messaging / streaming
    "kafka": (r"\bkafka\b",),
    "rabbitmq": (r"\brabbit\s*mq\b",),
    "nats": (r"\bnats\b(?!\s*ervic)",),  # avoid matching "naturalisti…"
    # ── Web frameworks
    "fastapi": (r"\bfastapi\b", r"\bfast\s+api\b"),
    "django": (r"\bdjango\b",),
    "flask": (r"\bflask\b",),
    "spring": (r"\bspring\s+(?:boot|framework)?\b",),
    "react": (r"\breact(?:\.?js)?\b", r"\breactjs\b"),
    "vue": (r"\bvue(?:\.?js)?\b",),
    "angular": (r"\bangular(?:\.?js)?\b",),
    "nextjs": (r"\bnext\.?js\b",),
    "express": (r"\bexpress(?:\.?js)?\b",),
    # ── AI / ML
    "langchain": (r"\blangchain\b",),
    "langgraph": (r"\blanggraph\b",),
    "openai": (r"\bopenai\b",),
    "anthropic": (r"\banthropic\b", r"\bclaude\b"),
    "huggingface": (r"\bhugging\s*face\b",),
    "pytorch": (r"\bpytorch\b", r"\btorch\b"),
    "tensorflow": (r"\btensorflow\b", r"\btensor\s+flow\b"),
    # ── Security
    "vault": (r"\bvault\b(?!\s*ed)", r"\bhashi\s*corp\s+vault\b"),
    "oauth": (r"\boauth\s*2?(?:\.0)?\b", r"\boauth2\b"),
    "oidc": (r"\boidc\b", r"\bopen\s*id\s*connect\b"),
    "jwt": (r"\bjwt\b", r"\bjson\s+web\s+token\b"),
    "mtls": (r"\bmtls\b", r"\bmutual\s+tls\b"),
    # ── Methodology / role-related
    "devops": (r"\bdev\s*ops\b",),
    "sre": (r"\bsre\b", r"\bsite\s+reliability\b"),
    "devsecops": (r"\bdevsecops\b", r"\bdev\s*sec\s*ops\b"),
    "mlops": (r"\bmlops\b", r"\bml\s*ops\b"),
    "gitops": (r"\bgitops\b", r"\bgit\s*ops\b"),
    "agile": (r"\bagile\b", r"\bscrum\b"),
    "microservices": (r"\bmicro\s*services?\b",),
    "cloud_engineer": (r"\bcloud\s+engineer\b", r"\bingegnere\s+cloud\b"),
    "platform_engineer": (r"\bplatform\s+engineer\b",),
    # ── Italian-specific tech labels seen on Adzuna IT
    "sistemista": (
        r"\bsistemista\b",
        r"\bsystem\s+engineer\b",
        r"\bsysadmin\b",
        r"\bamministratore\s+di\s+sistema\b",
        r"\bsys\s*admin\b",
    ),
    "sviluppatore": (r"\bsviluppatore\b",),
    "programmatore": (r"\bprogrammatore\b",),
    "analista_programmatore": (r"\banalista\s+programmatore\b",),
    "operations": (r"\boperations\b", r"\boperation\s+specialist\b"),
    "helpdesk": (r"\bhelp\s*desk\b", r"\bservice\s+desk\b"),
    "linux": (r"\blinux\b", r"\bunix\b"),
    "windows_server": (r"\bwindows\s+server\b",),
    # ── Microsoft enterprise stack
    "active_directory": (
        r"\bactive\s+directory\b",
        r"\b(?<!\.)ad\s+(?:domain|forest|trust|sites|users)\b",
    ),
    "ldap": (r"\bldap\b", r"\bopenldap\b"),
    "exchange": (r"\bexchange\s+(?:server|online|admin)\b", r"\bms\s+exchange\b"),
    "iis": (r"\biis\b(?:\s+server)?",),
    "powershell": (r"\bpowershell\b", r"\bps\s+core\b"),
    "sccm": (r"\bsccm\b", r"\bconfigmgr\b", r"\bconfiguration\s+manager\b"),
    "intune": (r"\bintune\b", r"\bmicrosoft\s+intune\b"),
    "m365": (r"\bm365\b", r"\boffice\s*365\b", r"\bo365\b", r"\bmicrosoft\s+365\b"),
    # ── Virtualization
    "vmware": (r"\bvmware\b",),
    "vsphere": (r"\bvsphere\b", r"\besxi\b", r"\bvcenter\b"),
    "hyperv": (r"\bhyper-?v\b",),
    "proxmox": (r"\bproxmox\b",),
    # ── Networking enterprise
    "cisco": (r"\bcisco\b", r"\bccna\b", r"\bccnp\b"),
    "juniper": (r"\bjuniper\b", r"\bjncia\b"),
    "firewall": (r"\bfirewall\b", r"\bfortigate\b", r"\bpalo\s*alto\b", r"\bcheckpoint\b"),
    "vpn": (r"\bvpn\b", r"\bipsec\b", r"\bopenvpn\b", r"\bwireguard\b"),
    "dns": (r"\bdns\b", r"\bbind9?\b"),
    "dhcp": (r"\bdhcp\b",),
    # ── ITSM
    "servicenow": (r"\bservicenow\b", r"\bservice\s*now\b"),
    "itil": (r"\bitil\b",),
    # ── Misc dev tooling that comes up often
    "git": (r"\bgit\b(?!\w)", r"\bversion\s+control\b"),
    "rest_api": (r"\brest\s+apis?\b", r"\brestful\b"),
    "graphql": (r"\bgraphql\b",),
    "grpc": (r"\bgrpc\b", r"\bg-rpc\b"),
    "ci_cd": (r"\bci\s*[/-]?\s*cd\b", r"\bcontinuous\s+(?:integration|delivery|deployment)\b"),
}

# Compiled once at import — extraction is called many times per ingest run.
_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    canonical: tuple(re.compile(p, re.IGNORECASE) for p in patterns) for canonical, patterns in _VOCABULARY.items()
}


def extract_stack(offer: dict[str, Any]) -> set[str]:
    """Return the set of canonical tech tokens detected in the offer.

    Scans ``title``, ``description``, and ``category`` (Adzuna fills these
    consistently). Aliases collapse to a single canonical: ``k8s`` and
    ``kubernetes`` both produce ``"kubernetes"``; ``postgres`` and
    ``postgresql`` both produce ``"postgres"``.

    Returns an empty set when the offer has no detectable tech terms — the
    caller (stack_match scoring) handles that as "unscoreable, default to
    AI fallback or skip".
    """
    haystack = " ".join(
        [
            str(offer.get("title") or ""),
            str(offer.get("description") or ""),
            str(offer.get("category") or ""),
        ]
    )
    if not haystack.strip():
        return set()
    found: set[str] = set()
    for canonical, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(haystack):
                found.add(canonical)
                break  # first hit is enough; aliases collapse
    return found


def vocabulary_size() -> int:
    """Number of canonical tokens in the active vocabulary (for telemetry / tests)."""
    return len(_VOCABULARY)

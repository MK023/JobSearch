"""Tests for stack extraction: pure-function, no DB, no network.

The corpus mixes real Adzuna IT samples we observed during the WorldWild
ingest probe (28 Apr 2026) with synthetic edge cases tuned to lock the
alias-collapse + word-boundary behavior in place.
"""

from src.worldwild.stack_extract import (
    extract_stack,
    vocabulary_size,
)


class TestVocabulary:
    def test_vocabulary_is_non_trivial(self) -> None:
        # Sanity: we have a meaningful number of tokens. If someone strips
        # the vocabulary by accident, this fails loud.
        assert vocabulary_size() > 50


class TestRealisticSamples:
    """Samples taken from real Adzuna IT postings observed during PR #1 probe."""

    def test_devops_aws_milano(self) -> None:
        offer = {
            "title": "DevOps Engineer - AWS",
            "description": "Faboci Srl ricerca DevOps Engineer Milano. Stack: AWS, Kubernetes, Terraform, Ansible, GitHub Actions.",
            "category": "IT Jobs",
        }
        stack = extract_stack(offer)
        assert "devops" in stack
        assert "aws" in stack
        assert "kubernetes" in stack
        assert "terraform" in stack
        assert "ansible" in stack
        assert "github_actions" in stack

    def test_observability_engineer_roma(self) -> None:
        offer = {
            "title": "Observability Engineer",
            "description": "Setup Prometheus + Grafana + OpenTelemetry. Linux, Python, Kubernetes.",
            "category": "IT Jobs",
        }
        stack = extract_stack(offer)
        assert "prometheus" in stack
        assert "grafana" in stack
        assert "opentelemetry" in stack
        assert "linux" in stack
        assert "python" in stack
        assert "kubernetes" in stack

    def test_sistemista_linux_pordenone(self) -> None:
        offer = {
            "title": "Sistemista Linux & IT Specialist",
            "description": "Gestione server Linux, scripting bash, Active Directory, monitoraggio con Grafana.",
            "category": "Sistemista",
        }
        stack = extract_stack(offer)
        assert "sistemista" in stack
        assert "linux" in stack
        assert "shell" in stack
        assert "active_directory" in stack
        assert "grafana" in stack

    def test_python_backend_senior_remote(self) -> None:
        offer = {
            "title": "Senior Python Backend Engineer",
            "description": "FastAPI + Postgres + Redis. Async patterns, REST APIs, CI/CD with GitHub Actions, Sentry.",
            "category": "Software Development",
        }
        stack = extract_stack(offer)
        assert "python" in stack
        assert "fastapi" in stack
        assert "postgres" in stack
        assert "redis" in stack
        assert "rest_api" in stack
        assert "ci_cd" in stack
        assert "github_actions" in stack
        assert "sentry" in stack

    def test_ml_infra_engineer(self) -> None:
        offer = {
            "title": "Senior ML Infrastructure / DevOps Engineer",
            "description": "LangChain + LangGraph + Anthropic Claude in production. K8s deployment, Helm charts, OpenTelemetry tracing.",
            "category": "IT Jobs",
        }
        stack = extract_stack(offer)
        assert "langchain" in stack
        assert "langgraph" in stack
        assert "anthropic" in stack
        assert "kubernetes" in stack  # via "K8s" alias
        assert "helm" in stack
        assert "devops" in stack


class TestAliasCollapse:
    """Different phrasings of the same tech must collapse to the same canonical."""

    def test_k8s_collapses_to_kubernetes(self) -> None:
        a = extract_stack({"title": "Kubernetes Engineer", "description": ""})
        b = extract_stack({"title": "K8s Specialist", "description": ""})
        assert a == b == {"kubernetes"}

    def test_postgresql_collapses_to_postgres(self) -> None:
        a = extract_stack({"title": "DB Admin", "description": "Use postgresql 17."})
        b = extract_stack({"title": "DB Admin", "description": "Use postgres 17."})
        assert "postgres" in a and "postgres" in b

    def test_otel_collapses_to_opentelemetry(self) -> None:
        a = extract_stack({"title": "SRE", "description": "OTEL traces."})
        b = extract_stack({"title": "SRE", "description": "OpenTelemetry traces."})
        assert "opentelemetry" in a and "opentelemetry" in b

    def test_dev_ops_collapses_to_devops(self) -> None:
        a = extract_stack({"title": "DevOps Engineer", "description": ""})
        b = extract_stack({"title": "Dev Ops Lead", "description": ""})
        assert "devops" in a and "devops" in b

    def test_aws_full_name(self) -> None:
        a = extract_stack({"title": "Cloud Engineer", "description": "AWS expertise."})
        b = extract_stack({"title": "Cloud Engineer", "description": "Amazon Web Services expertise."})
        assert "aws" in a and "aws" in b


class TestEdgeCases:
    def test_empty_offer_returns_empty_set(self) -> None:
        assert extract_stack({"title": "", "description": "", "category": ""}) == set()

    def test_no_tech_terms_returns_empty_set(self) -> None:
        offer = {
            "title": "Receptionist",
            "description": "Accoglienza clienti, gestione telefonate, customer care.",
            "category": "Hospitality",
        }
        assert extract_stack(offer) == set()

    def test_word_boundary_no_false_positive_for_go_in_lego(self) -> None:
        # "go" must not match "lego", "ego", "going". Pattern uses \bgolang\b
        # specifically — bare "go" is not in vocabulary (too noisy).
        offer = {"title": "Engineer", "description": "We are going to launch."}
        assert "go" not in extract_stack(offer)

    def test_word_boundary_no_false_positive_for_java_in_javascript(self) -> None:
        # "java" pattern uses negative lookahead for "(?!\s*script)" so
        # "javascript" alone must NOT pull in "java".
        stack = extract_stack({"title": "JS Engineer", "description": "JavaScript only."})
        assert "javascript" in stack
        assert "java" not in stack

    def test_word_boundary_no_false_positive_for_git_in_github(self) -> None:
        # "git" is a separate token from "github_actions". A description that
        # only mentions GitHub Actions should not also pull plain "git".
        # Expected: the standalone \bgit\b(?!\w) pattern doesn't fire on "github".
        stack = extract_stack({"title": "DevOps", "description": "GitHub Actions for CI."})
        assert "github_actions" in stack
        assert "git" not in stack  # github does not contribute to bare "git"

    def test_csharp_aliases(self) -> None:
        a = extract_stack({"title": "Developer", "description": "C# with .NET 8."})
        assert "csharp" in a

    def test_returns_set_not_list_no_duplicates(self) -> None:
        # The same canonical mentioned via multiple aliases should appear once.
        offer = {
            "title": "Kubernetes / K8s Engineer",
            "description": "k8s + kubernetes + Kubernetes again.",
        }
        stack = extract_stack(offer)
        assert isinstance(stack, set)
        assert sum(1 for t in stack if t == "kubernetes") == 1


class TestMissingFieldsTolerance:
    def test_missing_description_is_ok(self) -> None:
        assert extract_stack({"title": "DevOps Engineer"}) == {"devops"}

    def test_missing_title_is_ok(self) -> None:
        assert extract_stack({"description": "Python developer"}) == {"python"}

    def test_none_values_are_treated_as_empty(self) -> None:
        assert extract_stack({"title": None, "description": None, "category": None}) == set()


class TestItalianRoles:
    """Italian IT job-role labels common in body-rental enterprise postings."""

    def test_sistemista_with_ms_admin_stack(self) -> None:
        offer = {
            "title": "Sistemista junior per gestione AD",
            "description": (
                "Cerchiamo amministratore di sistema per Active Directory, "
                "Exchange Server e Office 365 in azienda manifatturiera."
            ),
            "category": "IT Jobs",
        }
        stack = extract_stack(offer)
        assert "sistemista" in stack
        assert "active_directory" in stack
        assert "exchange" in stack
        assert "m365" in stack

    def test_sviluppatore_programmatore_csharp(self) -> None:
        offer = {
            "title": "Programmatore C# .NET",
            "description": "Sviluppatore senior per progetto enterprise. Analista programmatore con esperienza .NET.",
            "category": "Software Development",
        }
        stack = extract_stack(offer)
        assert "programmatore" in stack
        assert "sviluppatore" in stack
        assert "analista_programmatore" in stack
        assert "csharp" in stack

    def test_helpdesk_operations(self) -> None:
        offer = {
            "title": "Operations Specialist - Service Desk",
            "description": "Gestione ticket help desk, supporto operations L1/L2.",
        }
        stack = extract_stack(offer)
        assert "operations" in stack
        assert "helpdesk" in stack


class TestMicrosoftEnterpriseStack:
    """Microsoft enterprise stack — frequent on Reply / Capgemini / Hays postings."""

    def test_powershell_sccm_intune(self) -> None:
        offer = {
            "title": "Endpoint Engineer",
            "description": "PowerShell scripting, SCCM/ConfigMgr, Microsoft Intune deployment.",
        }
        stack = extract_stack(offer)
        assert "powershell" in stack
        assert "sccm" in stack
        assert "intune" in stack

    def test_iis_exchange_server(self) -> None:
        offer = {
            "title": "Windows Infrastructure",
            "description": "Manutenzione IIS server e Exchange Server in datacenter on-prem.",
        }
        stack = extract_stack(offer)
        assert "iis" in stack
        assert "exchange" in stack
        assert "windows_server" not in stack  # "Windows Infrastructure" is not "Windows Server"

    def test_ldap_standalone_does_not_match_active_directory(self) -> None:
        # LDAP alone (without "Active Directory") must NOT pull active_directory.
        offer = {"title": "Backend", "description": "OpenLDAP integration for auth."}
        stack = extract_stack(offer)
        assert "ldap" in stack
        assert "active_directory" not in stack

    def test_m365_aliases(self) -> None:
        a = extract_stack({"title": "Admin", "description": "Office 365 tenant admin."})
        b = extract_stack({"title": "Admin", "description": "Microsoft 365 tenant admin."})
        c = extract_stack({"title": "Admin", "description": "O365 tenant admin."})
        assert "m365" in a and "m365" in b and "m365" in c


class TestVirtualization:
    def test_vmware_vsphere_hyperv(self) -> None:
        offer = {
            "title": "Virtualization Engineer",
            "description": "VMware vSphere + ESXi cluster, vCenter management. Hyper-V on Windows Server.",
        }
        stack = extract_stack(offer)
        assert "vmware" in stack
        assert "vsphere" in stack
        assert "hyperv" in stack

    def test_proxmox(self) -> None:
        stack = extract_stack({"title": "Sysadmin", "description": "Proxmox VE cluster management."})
        assert "proxmox" in stack


class TestNetworkingEnterprise:
    def test_cisco_juniper_firewall(self) -> None:
        offer = {
            "title": "Network Engineer",
            "description": "Cisco CCNA certified. Juniper switches, FortiGate firewall, Palo Alto NGFW.",
        }
        stack = extract_stack(offer)
        assert "cisco" in stack
        assert "juniper" in stack
        assert "firewall" in stack

    def test_vpn_dns_dhcp(self) -> None:
        offer = {
            "title": "Network Specialist",
            "description": "IPSec VPN tunnels, DNS BIND9, DHCP scopes management.",
        }
        stack = extract_stack(offer)
        assert "vpn" in stack
        assert "dns" in stack
        assert "dhcp" in stack


class TestItsm:
    def test_servicenow_itil(self) -> None:
        offer = {
            "title": "ITSM Analyst",
            "description": "ServiceNow ITSM platform admin, ITIL v4 Foundation certified.",
        }
        stack = extract_stack(offer)
        assert "servicenow" in stack
        assert "itil" in stack


class TestDevopsCloudRoles:
    def test_mlops(self) -> None:
        stack = extract_stack({"title": "MLOps Engineer", "description": "ML pipeline ops."})
        assert "mlops" in stack

    def test_cloud_engineer_italian(self) -> None:
        a = extract_stack({"title": "Cloud Engineer", "description": "AWS infra."})
        b = extract_stack({"title": "Ingegnere Cloud", "description": "AWS infra."})
        assert "cloud_engineer" in a
        assert "cloud_engineer" in b

    def test_platform_engineer(self) -> None:
        stack = extract_stack({"title": "Platform Engineer", "description": "Internal developer platform."})
        assert "platform_engineer" in stack

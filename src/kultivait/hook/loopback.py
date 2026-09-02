"""Z4 (#122): transparent loopback redirection — OS-level socket interception.

The mechanism round table's outcome: application-level injection (Z1 run, Z2
hook, Z3 IDE patcher) is the zero-root standard; this module generates the
configuration for opt-in OS-level redirection (hosts entries + packet-filter
rules + TLS certificate instructions) for advanced users who want full
transparency. Nothing here executes with root privileges; the generators
produce the config for the user to review and apply.
"""

from __future__ import annotations

# The API endpoints to intercept
INTERCEPT_DOMAINS = [
    "api.anthropic.com",
    "api.openai.com",
]

# The loopback address kultivait serves on
LOOPBACK = "127.0.0.1"


def generate_hosts_entries(domains: "list[str] | None" = None) -> str:
    """Generate /etc/hosts entries routing the API domains to loopback."""
    domains = domains or INTERCEPT_DOMAINS
    lines = [
        "# --- kultivait transparent proxy (added by kultivait hook loopback) ---"
    ]
    for d in domains:
        lines.append(f"{LOOPBACK} {d}")
    lines.append("# --- end kultivait ---")
    return "\n".join(lines)


def generate_pf_rules(port: int = 443) -> str:
    """Generate macOS pf (packet filter) rules to redirect 443 to kultivait's listener."""
    rules = [
        "# --- kultivait pf rules (macOS: /etc/pf.anchors/kultivait) ---",
        "# redirect HTTPS from the intercepted domains to kultivait's TLS listener",
        f"rdr pass on lo0 proto tcp from any to {LOOPBACK} port 443 -> {LOOPBACK} port {port}",
        "# --- end kultivait pf ---",
    ]
    return "\n".join(rules)


def generate_cert_instructions(domains: "list[str] | None" = None) -> str:
    """Generate instructions for creating and trusting a self-signed cert."""
    domains = domains or INTERCEPT_DOMAINS
    san = ", ".join(f"DNS:{d}" for d in domains)
    return f"""# TLS certificate for transparent HTTPS interception
#
# kultivait needs a self-signed cert trusted by the OS to terminate HTTPS
# on the loopback interface. Generate it with:
#
#   openssl req -x509 -newkey rsa:2048 -keyout kultivait-proxy.key \\
#     -out kultivait-proxy.crt -days 365 -nodes \\
#     -subj "/CN=kultivait-proxy" \\
#     -addext "subjectAltName={san}"
#
# Then trust it (macOS):
#   sudo security add-trusted-cert -d -r trustRoot \\
#     -k /Library/Keychains/System.keychain kultivait-proxy.crt
#
# And configure kultivait serve to use it:
#   [tls] cert = "path/to/kultivait-proxy.crt"
#   [tls] key = "path/to/kultivait-proxy.key"
"""


def generate_uninstall(domains: "list[str] | None" = None) -> str:
    """Instructions for reverting the loopback setup."""
    domains = domains or INTERCEPT_DOMAINS
    domain_list = " ".join(domains)
    return f"""# To revert kultivait loopback redirection:
#
# 1. Remove the hosts entries:
#      sudo sed -i '' '/kultivait/d;/# --- kultivait/d' /etc/hosts
#      sudo sed -i '' '/{domain_list.replace(" ", "$/;d;/")}$/d' /etc/hosts
#
# 2. Remove the pf rules:
#      sudo rm -f /etc/pf.anchors/kultivait
#      sudo pfctl -f /etc/pf.conf
#
# 3. Remove the trusted cert:
#      sudo security delete-certificate -c kultivait-proxy
#
# 4. Or use: kultivait hook loopback --generate-uninstall
"""


def full_setup_guide(host: str = LOOPBACK, port: int = 4114) -> dict:
    """The complete setup output: hosts, pf, cert, and the trade-off record."""
    return {
        "hosts": generate_hosts_entries(),
        "pf_rules": generate_pf_rules(port=port),
        "cert_instructions": generate_cert_instructions(),
        "uninstall": generate_uninstall(),
        "trade_offs": (
            "WHY: application-level injection (kultivait run / hook / hook ide) "
            "is the zero-root standard — it requires no elevated privileges and "
            "respects the user's per-tool choice. Loopback redirection is the "
            "ADVANCED path: full transparency for any process on the machine, "
            "but it requires /etc/hosts modification, pf rules, a trusted "
            "self-signed certificate for HTTPS termination, and root to apply. "
            "The TLS MITM complexity (cert generation, trust-store injection, "
            "key rotation) is the primary cost. This module generates the "
            "configuration for review — nothing executes with root."
        ),
    }

"""
Self-signed TLS certificate management for LAN HTTPS pairing.

The Screen Wake Lock API (used to keep a paired phone's screen from
sleeping) is gated behind a secure context, which plain HTTP over a LAN
IP never satisfies. This generates and caches a self-signed certificate
so the server can offer HTTPS for LAN clients; the phone accepts a
one-time "connection isn't private" warning, after which the browser
treats the origin as secure.
"""

import ipaddress
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

CERT_DIR = Path.home() / ".assettogps" / "certs"

CERT_VALIDITY_DAYS = 365 * 5
RENEWAL_BUFFER_DAYS = 30


def _paths(cert_dir: Path) -> Tuple[Path, Path, Path]:
    return cert_dir / "cert.pem", cert_dir / "key.pem", cert_dir / "meta.json"


def _load_meta(meta_path: Path) -> Optional[dict]:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _needs_regeneration(hosts: List[str], cert_path: Path, key_path: Path, meta_path: Path) -> bool:
    if not cert_path.exists() or not key_path.exists():
        return True
    meta = _load_meta(meta_path)
    if meta is None:
        return True
    covered = set(meta.get("hosts", []))
    if not set(hosts) <= covered:
        return True
    not_after = meta.get("not_after")
    if not isinstance(not_after, (int, float)):
        return True
    return time.time() > not_after - RENEWAL_BUFFER_DAYS * 86400


def ensure_self_signed_certificate(hosts: List[str], cert_dir: Path = CERT_DIR) -> Tuple[Path, Path]:
    """Returns (cert_path, key_path) for a self-signed cert covering `hosts`.

    Cached under `cert_dir` (defaults to ~/.assettogps/certs) and reused
    across runs. Only regenerated when missing, near expiry, or missing a
    requested host — a subset check, not exact-set equality, so incidental
    LAN-adapter churn (VPN/Hyper-V/Docker interfaces coming and going)
    doesn't force every paired phone to re-accept a new certificate.
    """
    cert_path, key_path, meta_path = _paths(cert_dir)

    if not _needs_regeneration(hosts, cert_path, key_path, meta_path):
        return cert_path, key_path

    # Imported lazily: this native-extension dependency should not become a
    # hard startup requirement for code paths that never call this function
    # (e.g. the packaged .exe, which doesn't use HTTPS yet).
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_dir.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san_entries: List[x509.GeneralName] = []
    for host in hosts:
        if host == "localhost":
            san_entries.append(x509.DNSName(host))
            continue
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san_entries.append(x509.DNSName(host))

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    not_before = datetime.now(timezone.utc)
    not_after = not_before + timedelta(days=CERT_VALIDITY_DAYS)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass  # Best-effort; e.g. has limited effect on Windows filesystems.

    meta_path.write_text(
        json.dumps({"hosts": hosts, "not_after": not_after.timestamp()}),
        encoding="utf-8",
    )

    return cert_path, key_path

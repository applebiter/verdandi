"""
Certificate management and cryptographic utilities for mTLS.
"""

from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


class CertificateAuthority:
    """Fabric Certificate Authority for mTLS trust."""
    
    def __init__(self, ca_cert: x509.Certificate, ca_key: rsa.RSAPrivateKey):
        self.ca_cert = ca_cert
        self.ca_key = ca_key
    
    @classmethod
    def create_fabric_ca(
        cls,
        common_name: str = "Verdandi Fabric CA",
        validity_days: int = 3650,  # 10 years
    ) -> "CertificateAuthority":
        """Create a new Fabric CA with self-signed root certificate."""
        
        # Generate CA private key
        ca_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend(),
        )
        
        # Build CA certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Verdandi"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])
        
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=validity_days))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    key_encipherment=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256(), backend=default_backend())
        )
        
        return cls(ca_cert, ca_key)
    
    @classmethod
    def load_from_files(cls, cert_path: Path, key_path: Path) -> "CertificateAuthority":
        """Load CA from certificate and key files."""
        with open(cert_path, "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
        
        with open(key_path, "rb") as f:
            ca_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend(),
            )
        
        return cls(ca_cert, ca_key)
    
    def save_to_files(self, cert_path: Path, key_path: Path):
        """Save CA certificate and key to files."""
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save certificate
        with open(cert_path, "wb") as f:
            f.write(
                self.ca_cert.public_bytes(serialization.Encoding.PEM)
            )
        
        # Save private key (unencrypted for daemon use)
        with open(key_path, "wb") as f:
            f.write(
                self.ca_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        
        # Set restrictive permissions on key
        key_path.chmod(0o600)
    
    def issue_node_certificate(
        self,
        node_id: str,
        hostname: str,
        validity_days: int = 365,
    ) -> Tuple[x509.Certificate, rsa.RSAPrivateKey]:
        """Issue a certificate for a node."""
        
        # Generate node private key
        node_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        
        # Build node certificate
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Verdandi"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Node"),
            x509.NameAttribute(NameOID.COMMON_NAME, node_id),
        ])
        
        # Subject Alternative Names for flexibility
        san = x509.SubjectAlternativeName([
            x509.DNSName(hostname),
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ])
        
        node_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self.ca_cert.subject)
            .public_key(node_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=validity_days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    key_cert_sign=False,
                    crl_sign=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]),
                critical=True,
            )
            .add_extension(san, critical=False)
            .sign(self.ca_key, hashes.SHA256(), backend=default_backend())
        )
        
        return node_cert, node_key


class NodeCertificateManager:
    """Manages node certificates and keys."""
    
    def __init__(self, certs_dir: Optional[Path] = None):
        if certs_dir is None:
            from verdandi_codex.config import VerdandiConfig
            certs_dir = VerdandiConfig.get_config_dir() / "certificates"
        
        self.certs_dir = certs_dir
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        self.ca_cert_path = self.certs_dir / "ca.crt"
        self.ca_key_path = self.certs_dir / "ca.key"
        self.node_cert_path = self.certs_dir / "node.crt"
        self.node_key_path = self.certs_dir / "node.key"
    
    def ensure_ca_exists(self) -> CertificateAuthority:
        """Ensure Fabric CA exists, create if necessary."""
        if self.ca_cert_path.exists() and self.ca_key_path.exists():
            return CertificateAuthority.load_from_files(
                self.ca_cert_path,
                self.ca_key_path,
            )
        else:
            ca = CertificateAuthority.create_fabric_ca()
            ca.save_to_files(self.ca_cert_path, self.ca_key_path)
            return ca
    
    def ensure_node_certificate(self, node_id: str, hostname: str) -> bool:
        """Ensure node certificate exists, create if necessary."""
        if self.node_cert_path.exists() and self.node_key_path.exists():
            # TODO: Check if certificate is still valid and matches node_id
            return False
        
        # Load or create CA
        ca = self.ensure_ca_exists()
        
        # Issue node certificate
        node_cert, node_key = ca.issue_node_certificate(node_id, hostname)
        
        # Save node certificate and key
        with open(self.node_cert_path, "wb") as f:
            f.write(node_cert.public_bytes(serialization.Encoding.PEM))
        
        with open(self.node_key_path, "wb") as f:
            f.write(
                node_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        
        self.node_key_path.chmod(0o600)
        return True
    
    def get_certificate_paths(self) -> dict:
        """Get paths to certificate files."""
        return {
            "ca_cert": str(self.ca_cert_path),
            "node_cert": str(self.node_cert_path),
            "node_key": str(self.node_key_path),
        }
    
    def get_certificate_fingerprint(self) -> Optional[str]:
        """Get SHA256 fingerprint of node certificate."""
        if not self.node_cert_path.exists():
            return None
        
        with open(self.node_cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read(), default_backend())
        
        fingerprint = cert.fingerprint(hashes.SHA256())
        return fingerprint.hex()


# Add missing import
import ipaddress

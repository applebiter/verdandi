"""
Configuration management for Verdandi components.
"""

import os
import yaml
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    
    host: str = "karate"
    port: int = 5432
    username: str = "sysadmin"
    password: str = "nx8J33aY"
    database: str = "verdandi"
    
    @property
    def connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return (
            f"postgresql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass
class NodeIdentityConfig:
    """Node identity and personality configuration."""
    
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hostname: str = field(default_factory=lambda: os.uname().nodename)
    display_name: Optional[str] = None
    personality_name: Optional[str] = None
    persona_description: Optional[str] = None
    tags: list = field(default_factory=list)


@dataclass
class DaemonConfig:
    """Verdandi Engine daemon configuration."""
    
    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051
    enable_mdns: bool = True
    mdns_service_name: str = "_verdandi._tcp.local."
    
    # TLS/mTLS
    tls_enabled: bool = True
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    ca_cert_path: Optional[str] = None


@dataclass
class VoiceConfig:
    """Voice pipeline configuration."""
    
    enabled: bool = True
    wake_engine: str = "OPENWAKEWORD"
    wake_phrase: str = "hey verdandi"
    stt_backend: str = "VOSK"
    tts_backend: str = "PIPER"
    sensitivity: int = 50


@dataclass
class VerdandiConfig:
    """Complete Verdandi configuration."""
    
    node: NodeIdentityConfig = field(default_factory=NodeIdentityConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    
    @classmethod
    def get_config_dir(cls) -> Path:
        """Get the configuration directory path."""
        config_home = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        config_dir = Path(config_home) / "verdandi"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    
    @classmethod
    def get_data_dir(cls) -> Path:
        """Get the data directory path."""
        data_home = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        data_dir = Path(data_home) / "verdandi"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    
    @classmethod
    def get_config_file(cls) -> Path:
        """Get the main configuration file path."""
        return cls.get_config_dir() / "config.yaml"
    
    @classmethod
    def load(cls, config_file: Optional[Path] = None) -> "VerdandiConfig":
        """Load configuration from file, or create default."""
        if config_file is None:
            config_file = cls.get_config_file()
        
        if config_file.exists():
            with open(config_file, "r") as f:
                data = yaml.safe_load(f) or {}
            
            return cls(
                node=NodeIdentityConfig(**data.get("node", {})),
                database=DatabaseConfig(**data.get("database", {})),
                daemon=DaemonConfig(**data.get("daemon", {})),
                voice=VoiceConfig(**data.get("voice", {})),
            )
        else:
            # Return default configuration
            config = cls()
            config.save(config_file)
            return config
    
    def save(self, config_file: Optional[Path] = None):
        """Save configuration to file."""
        if config_file is None:
            config_file = self.get_config_file()
        
        data = {
            "node": asdict(self.node),
            "database": asdict(self.database),
            "daemon": asdict(self.daemon),
            "voice": asdict(self.voice),
        }
        
        with open(config_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "node": asdict(self.node),
            "database": asdict(self.database),
            "daemon": asdict(self.daemon),
            "voice": asdict(self.voice),
        }

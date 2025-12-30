"""
SQLAlchemy models for identity and node registry.
"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from verdandi_codex.database import Base


class Node(Base):
    """Represents a physical/VM host on the LAN."""
    
    __tablename__ = "nodes"
    
    node_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    ip_last_seen = Column(String(45), nullable=True)  # IPv4 or IPv6
    daemon_port = Column(Integer, default=50051)
    cert_fingerprint = Column(String(255), nullable=True)
    tags = Column(JSON, default=list)  # List of tags like ["kitchen", "gpu"]
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = Column(String(50), default="offline")  # online, offline, degraded
    
    # Relationships
    capabilities = relationship("NodeCapability", back_populates="node", uselist=False)
    service_endpoints = relationship("ServiceEndpoint", back_populates="node")
    wake_profiles = relationship("WakeProfile", back_populates="node")
    
    def __repr__(self):
        return f"<Node(node_id={self.node_id}, hostname={self.hostname}, status={self.status})>"


class NodeCapability(Base):
    """Time-varying and static capabilities of a node."""
    
    __tablename__ = "node_capabilities"
    
    capability_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.node_id"), nullable=False, unique=True)
    
    # Hardware
    cpu_arch = Column(String(50), nullable=True)
    cpu_cores = Column(Integer, nullable=True)
    ram_total_mb = Column(Integer, nullable=True)
    gpu_vendor = Column(String(100), nullable=True)
    gpu_model = Column(String(255), nullable=True)
    vram_mb = Column(Integer, nullable=True)
    
    # OS
    os_distro = Column(String(100), nullable=True)
    os_version = Column(String(100), nullable=True)
    
    # Service capabilities (boolean + details in JSON)
    supports_stt = Column(Boolean, default=False)
    stt_backends = Column(JSON, default=list)
    supports_tts = Column(Boolean, default=False)
    tts_backends = Column(JSON, default=list)
    supports_embeddings = Column(Boolean, default=False)
    embedding_models = Column(JSON, default=list)
    supports_comfyui = Column(Boolean, default=False)
    supports_mcp_server = Column(Boolean, default=False)
    supports_mcp_host = Column(Boolean, default=False)
    
    # Model availability (snapshot)
    ollama_models = Column(JSON, default=list)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    node = relationship("Node", back_populates="capabilities")
    
    def __repr__(self):
        return f"<NodeCapability(node_id={self.node_id}, cpu_cores={self.cpu_cores})>"


class ServiceEndpoint(Base):
    """Advertised services on a node."""
    
    __tablename__ = "service_endpoints"
    
    service_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.node_id"), nullable=False)
    service_type = Column(String(50), nullable=False)  # OLLAMA, COMFYUI, MCP, METRICS
    base_url = Column(String(500), nullable=False)
    metadata_json = Column(JSON, default=dict)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    node = relationship("Node", back_populates="service_endpoints")
    
    def __repr__(self):
        return f"<ServiceEndpoint(service_type={self.service_type}, node_id={self.node_id})>"


class WakeProfile(Base):
    """Per-node wake word configuration."""
    
    __tablename__ = "wake_profiles"
    
    wake_profile_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.node_id"), nullable=False)
    wake_engine = Column(String(100), default="OPENWAKEWORD")
    wake_phrase = Column(String(255), nullable=False)
    sensitivity = Column(Integer, default=50)  # 0-100
    enabled = Column(Boolean, default=True)
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    node = relationship("Node", back_populates="wake_profiles")
    
    def __repr__(self):
        return f"<WakeProfile(wake_phrase={self.wake_phrase}, node_id={self.node_id})>"

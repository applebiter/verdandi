"""
SQLAlchemy models for Fabric Graph configuration.
"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from verdandi_codex.database import Base


class LinkType(enum.Enum):
    """Types of fabric links."""
    AUDIO_JACKTRIP = "AUDIO_JACKTRIP"
    MIDI_RTP = "MIDI_RTP"


class LinkStatus(enum.Enum):
    """Link status states."""
    DESIRED_UP = "DESIRED_UP"
    DESIRED_DOWN = "DESIRED_DOWN"
    OBSERVED_UP = "OBSERVED_UP"
    OBSERVED_DOWN = "OBSERVED_DOWN"


class Directionality(enum.Enum):
    """Bundle directionality."""
    BIDIR = "BIDIR"
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"


class EndpointRole(enum.Enum):
    """Attachment endpoint role."""
    SOURCE = "SOURCE"
    SINK = "SINK"
    BOTH = "BOTH"


class FabricGraph(Base):
    """Versioned desired-state container for the fabric."""
    
    __tablename__ = "fabric_graphs"
    
    graph_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), default="Home", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    links = relationship("FabricLink", back_populates="graph")
    
    def __repr__(self):
        return f"<FabricGraph(name={self.name}, version={self.version})>"


class FabricLink(Base):
    """An edge between two nodes (audio or MIDI)."""
    
    __tablename__ = "fabric_links"
    
    link_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    graph_id = Column(UUID(as_uuid=True), ForeignKey("fabric_graphs.graph_id"), nullable=False)
    link_type = Column(Enum(LinkType), nullable=False)
    node_a_id = Column(UUID(as_uuid=True), nullable=False)
    node_b_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(Enum(LinkStatus), default=LinkStatus.DESIRED_UP)
    params_json = Column(JSON, default=dict)  # JackTrip settings, sample rates, etc.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    graph = relationship("FabricGraph", back_populates="links")
    bundles = relationship("FabricBundle", back_populates="link")
    
    def __repr__(self):
        return f"<FabricLink(link_type={self.link_type}, {self.node_a_id} <-> {self.node_b_id})>"


class FabricBundle(Base):
    """Named channel bundle carried by a link."""
    
    __tablename__ = "fabric_bundles"
    
    bundle_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id = Column(UUID(as_uuid=True), ForeignKey("fabric_links.link_id"), nullable=False)
    name = Column(String(255), nullable=False)  # voice_cmd, gibberlink, music_bus_1
    directionality = Column(Enum(Directionality), default=Directionality.BIDIR)
    channels = Column(Integer, default=2)  # For audio
    format = Column(String(50), default="float32")
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    link = relationship("FabricLink", back_populates="bundles")
    attachments = relationship("BundleAttachment", back_populates="bundle")
    
    def __repr__(self):
        return f"<FabricBundle(name={self.name}, channels={self.channels})>"


class BundleAttachment(Base):
    """Maps a bundle endpoint to a local JACK port or logical endpoint."""
    
    __tablename__ = "bundle_attachments"
    
    attachment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bundle_id = Column(UUID(as_uuid=True), ForeignKey("fabric_bundles.bundle_id"), nullable=False)
    node_id = Column(UUID(as_uuid=True), nullable=False)
    local_endpoint_type = Column(String(100), nullable=False)  # JACK_PORT, ALSA_MIDI, etc.
    local_endpoint_name = Column(String(500), nullable=False)
    role = Column(Enum(EndpointRole), default=EndpointRole.BOTH)
    enabled = Column(Boolean, default=True)
    
    # Relationships
    bundle = relationship("FabricBundle", back_populates="attachments")
    
    def __repr__(self):
        return f"<BundleAttachment(endpoint={self.local_endpoint_name}, node_id={self.node_id})>"

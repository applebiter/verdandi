"""
SQLAlchemy models for JackTrip hub tracking.
"""

from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from verdandi_codex.database import Base


class JackTripHub(Base):
    """Tracks which node is currently running as the JackTrip hub."""
    
    __tablename__ = "jacktrip_hub"
    
    id = Column(Integer, primary_key=True, default=1)  # Only one row
    hub_node_id = Column(UUID(as_uuid=True), nullable=True)  # NULL = no hub running
    hub_hostname = Column(String(255), nullable=True)
    hub_port = Column(Integer, default=4464)
    started_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<JackTripHub(hub_hostname={self.hub_hostname}, port={self.hub_port})>"

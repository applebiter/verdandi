"""
SQLAlchemy models for voice system and transcripts.
"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from verdandi_codex.database import Base


class VoiceSession(Base):
    """An interaction window initiated by wake or UI."""
    
    __tablename__ = "voice_sessions"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), nullable=False)  # The woken/executing node
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    trigger_type = Column(String(50), nullable=False)  # WAKE_WORD, UI, TASK
    speaker_id = Column(UUID(as_uuid=True), nullable=True)  # Best-effort, optional
    status = Column(String(50), default="active")
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    transcript_segments = relationship("TranscriptSegment", back_populates="session")
    
    def __repr__(self):
        return f"<VoiceSession(session_id={self.session_id}, trigger={self.trigger_type})>"


class TranscriptSegment(Base):
    """Streaming-friendly transcript persistence (no raw audio)."""
    
    __tablename__ = "transcript_segments"
    
    segment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("voice_sessions.session_id"), nullable=False)
    node_id = Column(UUID(as_uuid=True), nullable=False)  # Where ASR ran
    start_ms = Column(Integer, nullable=True)  # Relative to session start
    end_ms = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    is_final = Column(Boolean, default=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    session = relationship("VoiceSession", back_populates="transcript_segments")
    
    def __repr__(self):
        return f"<TranscriptSegment(text={self.text[:30]}..., is_final={self.is_final})>"


class SpeakerProfile(Base):
    """Personalization identity (optional, Phase 6)."""
    
    __tablename__ = "speaker_profiles"
    
    speaker_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = Column(String(255), nullable=False)
    tts_voice_preference = Column(String(255), nullable=True)
    routing_policy_preference = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<SpeakerProfile(display_name={self.display_name})>"

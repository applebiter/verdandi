"""
SQLAlchemy models for audit logging and events.
"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from verdandi_codex.database import Base


class EventLog(Base):
    """Append-only events for observability and audit."""
    
    __tablename__ = "event_logs"
    
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    node_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    severity = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    category = Column(String(50), nullable=False, index=True)  # DISCOVERY, FABRIC, VOICE, etc.
    message = Column(Text, nullable=False)
    data_json = Column(JSON, default=dict)
    
    # Optional correlation IDs for filtering
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    task_run_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    __table_args__ = (
        Index("idx_event_timestamp_category", "timestamp", "category"),
        Index("idx_event_node_category", "node_id", "category"),
    )
    
    def __repr__(self):
        return f"<EventLog(category={self.category}, severity={self.severity}, message={self.message[:50]})>"


class ToolCallLog(Base):
    """Audit log for tool executions."""
    
    __tablename__ = "tool_call_logs"
    
    tool_call_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    task_run_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    node_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tool_id = Column(String(255), nullable=False)
    tool_name = Column(String(255), nullable=False)
    args_json = Column(JSON, default=dict)
    result_summary = Column(Text, nullable=True)
    status = Column(String(50), nullable=False)  # SUCCESS, FAILED, DENIED
    error_text = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<ToolCallLog(tool_name={self.tool_name}, status={self.status})>"


class LLMCallLog(Base):
    """Audit and debugging record for LLM calls."""
    
    __tablename__ = "llm_call_logs"
    
    call_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    task_run_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    provider = Column(String(100), nullable=False)  # OLLAMA, OPENAI, etc.
    node_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    model_name = Column(String(255), nullable=False)
    prompt_hash = Column(String(64), nullable=True)  # SHA256 of prompt
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=False)
    error_text = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<LLMCallLog(provider={self.provider}, model={self.model_name}, status={self.status})>"

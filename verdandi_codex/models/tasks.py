"""
SQLAlchemy models for tasks and deterministic workflow execution.
"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, Text, Enum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from verdandi_codex.database import Base


class TaskCreator(enum.Enum):
    """Who created the task."""
    USER = "USER"
    LLM = "LLM"
    PLUGIN = "PLUGIN"


class TaskRunStatus(enum.Enum):
    """Task execution status."""
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class StepRunStatus(enum.Enum):
    """Step execution status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskDefinition(Base):
    """User-authored or generated workflow template."""
    
    __tablename__ = "task_definitions"
    
    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    definition_json = Column(JSON, nullable=False)  # DAG or linear steps; typed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Enum(TaskCreator), default=TaskCreator.USER)
    
    # Relationships
    runs = relationship("TaskRun", back_populates="definition")
    
    def __repr__(self):
        return f"<TaskDefinition(name={self.name}, created_by={self.created_by})>"


class TaskRun(Base):
    """A specific execution instance of a task."""
    
    __tablename__ = "task_runs"
    
    task_run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("task_definitions.task_id"), nullable=False)
    invoked_by = Column(String(50), nullable=False)  # VOICE, UI, SCHEDULE, TOOL
    node_id = Column(UUID(as_uuid=True), nullable=False)  # Executor node
    status = Column(Enum(TaskRunStatus), default=TaskRunStatus.RUNNING)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    current_step_index = Column(Integer, default=0)
    degraded_mode = Column(Boolean, default=False)
    
    # Relationships
    definition = relationship("TaskDefinition", back_populates="runs")
    step_runs = relationship("TaskStepRun", back_populates="task_run")
    
    def __repr__(self):
        return f"<TaskRun(task_run_id={self.task_run_id}, status={self.status})>"


class TaskStepRun(Base):
    """Execution record per step."""
    
    __tablename__ = "task_step_runs"
    
    step_run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_run_id = Column(UUID(as_uuid=True), ForeignKey("task_runs.task_run_id"), nullable=False)
    step_id = Column(String(255), nullable=False)  # From definition
    step_type = Column(String(100), nullable=False)  # LLM_CALL, MCP_TOOL_CALL, etc.
    inputs_json = Column(JSON, default=dict)
    outputs_json = Column(JSON, default=dict)
    status = Column(Enum(StepRunStatus), default=StepRunStatus.PENDING)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    error_text = Column(Text, nullable=True)
    
    # Relationships
    task_run = relationship("TaskRun", back_populates="step_runs")
    
    def __repr__(self):
        return f"<TaskStepRun(step_id={self.step_id}, status={self.status})>"

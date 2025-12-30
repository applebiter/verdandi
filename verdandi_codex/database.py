"""
Database configuration and session management.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from typing import Optional
import os

Base = declarative_base()


class DatabaseConfig:
    """Database connection configuration."""
    
    def __init__(
        self,
        host: str = "karate",
        port: int = 5432,
        username: str = "sysadmin",
        password: str = "nx8J33aY",
        database: str = "verdandi",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
    
    @property
    def connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return (
            f"postgresql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )
    
    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load configuration from environment variables."""
        return cls(
            host=os.getenv("VERDANDI_DB_HOST", "karate"),
            port=int(os.getenv("VERDANDI_DB_PORT", "5432")),
            username=os.getenv("VERDANDI_DB_USER", "sysadmin"),
            password=os.getenv("VERDANDI_DB_PASSWORD", "nx8J33aY"),
            database=os.getenv("VERDANDI_DB_NAME", "verdandi"),
        )


class Database:
    """Database connection manager."""
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig()
        self.engine = create_engine(
            self.config.connection_string,
            pool_pre_ping=True,  # Verify connections before using
            pool_size=10,
            max_overflow=20,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
    
    def create_all_tables(self):
        """Create all tables in the database."""
        Base.metadata.create_all(bind=self.engine)
    
    def drop_all_tables(self):
        """Drop all tables (use with caution)."""
        Base.metadata.drop_all(bind=self.engine)
    
    def get_session(self):
        """Get a new database session."""
        return self.SessionLocal()

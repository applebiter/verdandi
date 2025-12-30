"""
Database initialization and management utilities.
"""

import sys
from pathlib import Path
from verdandi_codex.database import Database, DatabaseConfig
from verdandi_codex.models import *  # Import all models to register them


def init_database(drop_existing: bool = False):
    """Initialize the database schema."""
    print("Initializing Verdandi database...")
    
    # Load configuration
    db_config = DatabaseConfig()
    print(f"Connecting to PostgreSQL at {db_config.host}:{db_config.port}/{db_config.database}")
    
    try:
        db = Database(db_config)
        
        if drop_existing:
            print("⚠️  Dropping all existing tables...")
            db.drop_all_tables()
        
        print("Creating tables...")
        db.create_all_tables()
        
        print("✓ Database schema initialized successfully")
        return True
        
    except Exception as e:
        print(f"✗ Error initializing database: {e}", file=sys.stderr)
        return False


def main():
    """Command-line entry point for database initialization."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize Verdandi database schema")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing tables before creating (DESTRUCTIVE)",
    )
    
    args = parser.parse_args()
    
    if args.drop:
        confirm = input("⚠️  This will DROP ALL TABLES. Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return
    
    success = init_database(drop_existing=args.drop)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

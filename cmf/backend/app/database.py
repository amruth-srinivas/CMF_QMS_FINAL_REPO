"""
Database configuration and session management.
Uses SQLAlchemy 2.x with async support.
Auto-creates tables on startup (no Alembic).
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
import logging
from typing import Generator
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine
# Using NullPool for better connection handling
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    echo=False,  # Set to True for SQL query logging
    future=True,  # Enable SQLAlchemy 2.0 style
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function to get database session.
    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database_exists():
    """
    Ensure the database exists. If not, create it.
    This function connects to the default 'postgres' database to create the target database.
    """
    try:
        # Parse the DATABASE_URL to extract database name
        db_url = settings.DATABASE_URL
        # Extract database name from URL (format: postgresql://user:pass@host:port/dbname)
        if "/" in db_url:
            db_name = db_url.split("/")[-1].split("?")[0]
            # Create a connection URL to the default 'postgres' database
            base_url = "/".join(db_url.split("/")[:-1])
            admin_url = f"{base_url}/postgres"
            
            # Try to create the database if it doesn't exist
            admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                # Check if database exists
                result = conn.execute(
                    text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
                )
                exists = result.fetchone()
                
                if not exists:
                    logger.info(f"Creating database: {db_name}")
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    logger.info(f"Database {db_name} created successfully")
                else:
                    logger.info(f"Database {db_name} already exists")
            
            admin_engine.dispose()
    except Exception as e:
        logger.warning(f"Could not ensure database exists: {e}. Assuming it exists.")


def init_db():
    """
    Initialize database: ensure it exists and create all tables.
    Called on FastAPI startup.
    """
    try:
        logger.info("Initializing database...")
        ensure_database_exists()
        
        # Import all models to ensure they're registered with Base
        from app.models import (
            item,
            bom,
            document,
            document_version,
            inspection_plan,
            measurement,
            lookup,
            report_config,
            bluetooth_device,
            instrument_setup,
            project,
            assembly,
            part,
            part_location,
            balloon,
        )
        
        # Create all tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


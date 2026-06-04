"""
FastAPI main application.
Initializes the app, creates database tables on startup, and registers all routers.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from app.core.config import settings
from app.database import init_db
from app.routers import project, assembly, part, document, balloon, pdf_annotation, note, view_region, bluetooth, report_config, measurement, report_template, instrument_setup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    Creates database tables on startup.
    """
    # Startup
    logger.info("Starting up FastAPI application...")
    
    # Initialize database and create tables
    try:
        init_db()
        logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    # Ensure blob storage directory exists
    blob_path = Path(settings.BLOB_STORAGE_PATH)
    blob_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Blob storage directory ensured: {blob_path}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down FastAPI application...")


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="QMS FastAPI Backend with PostgreSQL and blob storage",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount blob storage directory for file access (optional)
# This allows direct file access via HTTP if needed
blob_path = Path(settings.BLOB_STORAGE_PATH)
if blob_path.exists():
    app.mount("/blob", StaticFiles(directory=str(blob_path)), name="blob")

# Register routers
app.include_router(project.router, prefix=settings.API_V1_PREFIX)
app.include_router(assembly.router, prefix=settings.API_V1_PREFIX)
app.include_router(part.router, prefix=settings.API_V1_PREFIX)
app.include_router(document.router, prefix=settings.API_V1_PREFIX)
app.include_router(balloon.router, prefix=settings.API_V1_PREFIX)
app.include_router(measurement.router, prefix=settings.API_V1_PREFIX)
app.include_router(pdf_annotation.router, prefix=settings.API_V1_PREFIX)
app.include_router(note.router, prefix=settings.API_V1_PREFIX)
# app.include_router(report.router, prefix=settings.API_V1_PREFIX)
app.include_router(view_region.router, prefix=settings.API_V1_PREFIX)
app.include_router(bluetooth.router, prefix=settings.API_V1_PREFIX)
app.include_router(report_config.router, prefix=settings.API_V1_PREFIX)
app.include_router(report_template.router, prefix=settings.API_V1_PREFIX)
app.include_router(instrument_setup.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "QMS FastAPI Backend",
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Test database connection
        from app.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "database": "connected",
            "blob_storage": "available"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


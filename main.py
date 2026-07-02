from dotenv import load_dotenv
import os

load_dotenv()

# Paddle 3.x + OneDNN on Windows can fail OCR with PIR/onednn NotImplementedError.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn", "0")

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.middleware.cors import CORSMiddleware
from DB.database import engine, MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET_NAME, MINIO_SECURE
from DB.models import Base, scheduling
from DB.models import oms
from DB.minio_client import init_minio_client

from routers.products import router as products_router
from routers.assemblies import router as assemblies_router
from routers.part_types import router as part_types_router
from routers.parts import router as parts_router
from routers.operations import router as operations_router
from routers.documents import router as documents_router
from routers.tools import router as tools_router
from routers.orders import router as orders_router
from routers.order_documents import router as order_documents_router
from routers.machines import router as machines_router
from routers.operation_documents import router as operation_documents_router
from routers.access_control import router as access_control_router
from routers.out_source_parts_status import router as out_source_parts_status_router
from routers.scheduling import router as scheduling_router
from routers.pdf_annotation import router as pdf_annotation_router
from routers.quality import router as quality_router
from routers.qms_operator import router as qms_operator_router
from routers.report import router as reports_router

app = FastAPI(title="CMF QMS API")

# Frontend bases (e.g. qualityconfig.js) use .../api/v1 as the API root.
API_V1_PREFIX = "/api/v1"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5175",
        "http://172.18.100.98:5173",
        "http://172.18.100.98:5175",
        '*'
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    products_router,
    assemblies_router,
    part_types_router,
    parts_router,
    operations_router,
    documents_router,
    tools_router,
    orders_router,
    order_documents_router,
    machines_router,
    operation_documents_router,
    access_control_router,
    out_source_parts_status_router,
    scheduling_router,
    pdf_annotation_router,
    quality_router,
    qms_operator_router,
    reports_router,
):
    app.include_router(router, prefix=API_V1_PREFIX)


@app.on_event("startup")
async def startup_event():
    """
    Startup event handler
    - Creates database tables
    - Initializes MinIO client
    """
    print("=" * 60)
    print("Starting CMF Backend API...")
    print("=" * 60)

    # Create database tables
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ Database tables created/verified")
    except Exception as e:
        print(f"✗ Error creating database tables: {e}")

    # Initialize MinIO client
    try:
        init_minio_client(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            bucket_name=MINIO_BUCKET_NAME,
            secure=MINIO_SECURE
        )
        print("✓ MinIO client initialized")
        print(f"  - Endpoint: {MINIO_ENDPOINT}")
        print(f"  - Bucket: {MINIO_BUCKET_NAME}")
    except Exception as e:
        print(f"✗ Error initializing MinIO client: {e}")
        print("  Warning: Document upload functionality may not work")

    print("=" * 60)
    print("CMF Backend API is ready!")
    print(f"Documentation available at: http://localhost:8765/docs")
    print("=" * 60)







@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected",
        "minio": "connected"
    }




if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8989,
        log_level="info"
    )
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    allow_origins=["*"],
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

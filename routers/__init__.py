from .products import router as products_router

from .assemblies import router as assemblies_router

from .part_types import router as part_types_router

from .parts import router as parts_router

from .operations import router as operations_router

from .documents import router as documents_router

from .tools import router as tools_router

from .orders import router as orders_router

from .order_documents import router as order_documents_router

from .machines import router as machines_router

from .operation_documents import router as operation_documents_router

from .access_control import router as access_control_router

from .out_source_parts_status import router as out_source_parts_status_router
from .scheduling import router as scheduling_router

from .pdf_annotation import router as pdf_annotation_router

from .quality import router as quality_router

from .qms_operator import router as qms_operator_router

from .report import router as reports_router


__all__ = [

    "products_router",

    "assemblies_router",

    "part_types_router",

    "parts_router",

    "operations_router",

    "documents_router",

    "tools_router",

    "orders_router",

    "order_documents_router",

    "machines_router",

    "operation_documents_router",

    "access_control_router",

    "out_source_parts_status_router",

    "scheduling_router",

    "pdf_annotation_router",

    "quality_router",

    "qms_operator_router",
    
    "reports_router"

]
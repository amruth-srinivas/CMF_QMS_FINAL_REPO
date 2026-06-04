# QMS FastAPI Backend

A complete FastAPI backend for a Quality Management System (QMS) with PostgreSQL database and local blob storage.

## Tech Stack

- **Python 3.11+**
- **FastAPI** - Modern, fast web framework
- **SQLAlchemy 2.x** - ORM for database operations
- **Pydantic v2** - Data validation using Python type annotations
- **PostgreSQL** - Relational database (using psycopg2-binary)
- **Local Blob Storage** - Filesystem-based file storage

## Features

- ✅ Auto table creation on startup (no Alembic migrations)
- ✅ Blob storage abstraction for file handling
- ✅ Document versioning with automatic version numbering
- ✅ Recursive assembly structure
- ✅ Full CRUD APIs for all entities
- ✅ Constraint validation at database and API levels
- ✅ Health check endpoint
- ✅ Auto-generated API documentation

## Project Structure

```
backend/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   │   ├── blob_storage.py
│   │   ├── document_service.py
│   │   ├── view_extractor.py
│   │   └── pdf_annotation/      # PDF text/OCR, dimensions, GDT, drawing helpers
│   │       ├── text_extractor.py
│   │       ├── ocr_extractor.py
│   │       ├── dimension_parser.py
│   │       ├── gdt_detector.py
│   │       ├── drawing_boundary.py
│   │       └── dimension_clustering.py
│   ├── qms/
│   │   └── zone.py              # Drawing zone detection (used by pdf_annotation)
│   └── core/
│       └── config.py
├── others/                      # Not wired into the app (legacy / unused scripts)
├── migrations/
├── start.py                     # uvicorn entry (reload-friendly on Windows)
├── requirements.txt
└── README.md
```

## Database Models

### 1. Project
- `id` (PK)
- `name`
- `created_at`

### 2. Assembly (Recursive)
- `id` (PK)
- `name`
- `project_id` (FK → project.id)
- `parent_assembly_id` (FK → assembly.id, nullable)
- `created_at`

### 3. Part
- `id` (PK)
- `part_no` (unique)
- `name`
- `created_at`

### 4. PartLocation
- `id` (PK)
- `part_id` (FK → part.id)
- `project_id` (FK → project.id, nullable)
- `assembly_id` (FK → assembly.id, nullable)
- `quantity`
- **Constraint**: Exactly one of `project_id` or `assembly_id` must be non-null

### 5. Document
- `id` (PK)
- `assembly_id` (FK → assembly.id, nullable)
- `part_id` (FK → part.id, nullable)
- `doc_type` (Enum: '2D', '3D')
- `title`
- `created_at`
- **Constraint**: Exactly one of `assembly_id` or `part_id` must be non-null

### 6. DocumentVersion
- `id` (PK)
- `document_id` (FK → document.id)
- `version_no`
- `blob_path` (string, path in blob storage)
- `file_format`
- `is_current` (boolean)
- `uploaded_at`
- `uploaded_by`
- `change_note`

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Edit the `.env` file with your PostgreSQL connection details:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/qms_db
BLOB_STORAGE_PATH=./blob_data
```

### 3. Create PostgreSQL Database

Make sure PostgreSQL is running and create the database (or let the app create it automatically):

```sql
CREATE DATABASE qms_db;
```

### 4. Run the Application

**Recommended (Windows-friendly)**:
```bash
python start.py
```

**Or use uvicorn directly**:
```bash
uvicorn app.main:app --reload --reload-dir app
```

**Note**: On Windows, if you encounter socket errors during reload, use `start.py` which includes Windows-specific optimizations.

The application will:
- Automatically create the database if it doesn't exist
- Create all tables on startup
- Initialize blob storage directory
- Start the FastAPI server

### 5. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## API Endpoints

### Projects
- `POST /api/v1/projects` - Create project
- `GET /api/v1/projects` - List projects
- `GET /api/v1/projects/{id}` - Get project
- `PUT /api/v1/projects/{id}` - Update project
- `DELETE /api/v1/projects/{id}` - Delete project

### Assemblies
- `POST /api/v1/assemblies` - Create assembly
- `GET /api/v1/assemblies` - List assemblies (optional `project_id` filter)
- `GET /api/v1/assemblies/{id}` - Get assembly
- `PUT /api/v1/assemblies/{id}` - Update assembly
- `DELETE /api/v1/assemblies/{id}` - Delete assembly

### Parts
- `POST /api/v1/parts` - Create part
- `GET /api/v1/parts` - List parts
- `GET /api/v1/parts/{id}` - Get part
- `PUT /api/v1/parts/{id}` - Update part
- `DELETE /api/v1/parts/{id}` - Delete part

### Documents
- `POST /api/v1/documents` - Create document
- `GET /api/v1/documents` - List documents (optional filters: `assembly_id`, `part_id`, `doc_type`)
- `GET /api/v1/documents/{id}` - Get document
- `PUT /api/v1/documents/{id}` - Update document
- `DELETE /api/v1/documents/{id}` - Delete document

### Document Versions
- `POST /api/v1/documents/{id}/versions` - Upload new document version
- `GET /api/v1/documents/{id}/versions` - List all versions
- `GET /api/v1/documents/{id}/versions/current` - Get current version
- `GET /api/v1/documents/versions/{version_id}/download` - Download version file
- `DELETE /api/v1/documents/versions/{version_id}` - Delete version

## Document Upload

When uploading a new document version:

1. Previous versions automatically have `is_current` set to `false`
2. New version automatically has `is_current` set to `true`
3. `version_no` is auto-incremented if not provided
4. File is saved to blob storage (not in database)
5. Only the `blob_path` is stored in the database

Example upload:

```bash
curl -X POST "http://localhost:8000/api/v1/documents/1/versions" \
  -F "file=@document.pdf" \
  -F "file_format=pdf" \
  -F "uploaded_by=user@example.com" \
  -F "change_note=Initial version"
```

## Blob Storage

- Files are stored in the local filesystem (default: `./blob_data/`)
- Each file gets a unique UUID-based filename
- Files are organized in subfolders (e.g., `document_versions/`)
- Only the relative `blob_path` is stored in the database
- Files can be accessed via the download endpoint or directly from the filesystem

## Constraints

The following constraints are enforced:

1. **PartLocation**: Exactly one of `project_id` or `assembly_id` must be non-null
2. **Document**: Exactly one of `assembly_id` or `part_id` must be non-null
3. **DocumentVersion**: Only one version per document can have `is_current=true` (enforced at application level)
4. **Part**: `part_no` must be unique
5. **Assembly**: Parent assembly must belong to the same project

## Development

### Running in Development Mode

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Logging

Logging is configured to output to console with INFO level. Check logs for:
- Database initialization
- Table creation
- Blob storage operations
- API requests (if enabled)

## Production Considerations

1. **Database**: Use connection pooling and proper connection management
2. **Blob Storage**: Consider using cloud storage (S3, Azure Blob, etc.) instead of local filesystem
3. **CORS**: Update CORS settings to allow only specific origins
4. **Security**: Add authentication and authorization
5. **Error Handling**: Implement comprehensive error handling and logging
6. **Migrations**: Consider adding Alembic for production migrations
7. **Environment Variables**: Use secure secret management

## License

This project is part of the QMS system.


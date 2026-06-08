# CLAUDE.md - QRender Project Guidelines

## Build and Run Commands

### Local Development
- **Install Dependencies**: `python -m pip install -e .` (or `./run.sh install` on Linux/macOS)
- **Run Dev Server**: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` (or `./run.sh` on Linux/macOS)
- **Environment Setup**: Copy `.env.example` to `.env` and configure `ADMIN_SECRET` and `PUBLIC_BASE_URL`.

### Docker
- **Build & Run**: `docker compose up --build` (or `./docker-run.sh`)
- **Stop**: `docker compose down`

### Testing & Validation
- **Health Check**: `curl http://127.0.0.1:8000/health`
- **Manual UI Test**: Open `http://127.0.0.1:8000/` in browser.
- **API Docs**: Open `http://127.0.0.1:8000/docs` for interactive Swagger UI.

## Coding Style & Conventions

### Python Standards
- **Version**: Python 3.11+
- **Naming**: Use `snake_case` for functions, variables, and file names. Use `PascalCase` for classes.
- **Type Hints**: Always include type hints for function arguments and return values (e.g., `def func(attr: str) -> bool:`).
- **Private Members**: Prefix internal/helper functions with an underscore (e.g., `_helper_func()`).
- **Enums**: Prefer `typing.Literal` for fixed sets of string options instead of complex Enum classes where appropriate.

### Architecture
- **Web Framework**: FastAPI.
- **Image Processing**: Pillow (PIL) for image manipulation and `qrcode` for generation.
- **Persistence**: SQLite (located in `data/short_urls.sqlite3`).
- **Structure**:
  - `app/`: Main application logic.
  - `app/main.py`: Entry point and API routing.
  - `app/qr_art.py`: Core QR generation and artistic blending logic.
  - `app/short_redirect.py`: Short-link redirection and event logging.
  - `data/`: Persistent storage (SQLite DB, generated previews).
  - `scripts/`: Utility scripts for environment setup and standalone generation.

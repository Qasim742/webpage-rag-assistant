import os
from pathlib import Path

from dotenv import dotenv_values


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILES = (BACKEND_DIR / ".env", PROJECT_ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip() or None
ENV_FILE: Path | None = None

if GROQ_API_KEY is None:
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        candidate = dotenv_values(env_file).get("GROQ_API_KEY")
        if candidate and candidate.strip():
            GROQ_API_KEY = candidate.strip()
            os.environ["GROQ_API_KEY"] = GROQ_API_KEY
            ENV_FILE = env_file
            break

if ENV_FILE is None:
    ENV_FILE = next((path for path in ENV_FILES if path.is_file()), None)
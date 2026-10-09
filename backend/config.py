"""Explicit configuration; no credentials or production defaults in source."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('EDO_DATA_DIR', str(ROOT / 'data'))).resolve())
    secure_cookie: bool = field(default_factory=lambda: os.getenv('EDO_SECURE_COOKIE', '0') == '1')
    ai_enabled: bool = field(default_factory=lambda: os.getenv('EDO_AI_ENABLED', '0') == '1')
    api_key: str = field(default_factory=lambda: os.getenv('OPENAI_API_KEY', ''))
    ai_model: str = field(default_factory=lambda: os.getenv('OPENAI_MODEL', 'gpt-4o'))
    max_upload: int = 10 * 1024 * 1024
    session_seconds: int = 8 * 60 * 60

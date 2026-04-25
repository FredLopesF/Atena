APP_VERSION: str = "1.7"
APP_NAME: str = "Atena Emulation"

# Layout
DEFAULT_WIDTH: int = 1360
LOGO_ASSET_PATH: str = "assets/logo.png"
LOGO_WIDTH: int = 200
LOG_AREA_HEIGHT_PX: int = 90

# UI colours — all semantic values live in src/core/theme.py
from src.core.theme import (
    STATUS_COLOR_LOADING as STATUS_LOADING_COLOR,
    STATUS_COLOR_ERROR as STATUS_ERROR_COLOR,
    ACCENT_PRIMARY as DOWNLOAD_ACTIVE_COLOR,
    COLOR_DANGER as ATTENTION_COLOR,
    LIST_ROW_A as LIST_ROW_COLOR_A,
    LIST_ROW_B as LIST_ROW_COLOR_B,
)

# File paths (relative to app_dir)
CONFIG_FILE: str = "downloader_config.json"
CONSOLES_FILE: str = "consoles.json"
CACHE_DIR: str = "cache"
DOWNLOAD_DB_DIR: str = "downloads_db"

# Behaviour
CACHE_EXPIRY_DAYS: int = 7
STATUS_HISTORY_LENGTH: int = 10
LIST_POPULATION_BATCH_SIZE: int = 100
ITEMS_PER_PAGE: int = 50
MAX_URL_WORKERS: int = 5
MAX_DOWNLOAD_WORKERS: int = 4
DOWNLOAD_RETRIES: int = 3
RETRY_DELAY_S: int = 5

# ROM file extensions recognised during listing/filtering
ROM_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".zip", ".7z", ".chd", ".iso", ".bin", ".wua",
        ".cue", ".gdi", ".rvz", ".wbfs", ".cso", ".rar",
        ".mp4", ".cbr", ".pdf",
    }
)

# Keywords stripped by the "Try to Clean" filter
CLEAN_FILTER_KEYWORDS: tuple[str, ...] = (
    "pirate",
    "unl",
    "beta",
    "bios",
    "retro-bit",
    "proto",
    "virtual console",
    "limited run games",
    "sample",
)

# Archive.org URL templates
ARCHIVE_ORG_METADATA_URL: str = "https://archive.org/metadata/{identifier}"
ARCHIVE_ORG_DOWNLOAD_URL: str = "https://archive.org/download/{identifier}/{filename}"

import os
import re
from pathlib import Path


DATA_DIR = Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform"))
APP_DIR = Path(__file__).resolve().parent.parent
APP_ENTRY_PATH = APP_DIR / "app.py"
RES_DIR = APP_DIR / "res"
AI_PAGE_PATH = APP_DIR / "ai.html"
HOME_PAGE_PATH = APP_DIR / "index.html"
CAT_PAGE_PATH = APP_DIR / "cat.html"
CHANGELOG_PATH = APP_DIR / "CHANGELOG.md"
VERSION_PATH = APP_DIR / "VERSION"
BUILD_ID_PATH = APP_DIR / "BUILD_ID"
MARKDOWN_TEST_PATH = APP_DIR / "markdown-test.html"
DEV_MODE = os.environ.get("AI_PLATFORM_DEV_MODE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LISTEN = os.environ.get("AI_PLATFORM_LISTEN", ":8080")
DB_PATH = DATA_DIR / "ai-platform.db"
SECRETS_PATH = DATA_DIR / "secrets.json"
ADMIN_KEY_PATH = DATA_DIR / "admin.key"
FAMILY_PASSWORD_PATH = DATA_DIR / "family_password.txt"
LEGACY_CONFIG_PATH = DATA_DIR / "config.json"
SESSION_COOKIE = "ap_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
CAT_SESSION_COOKIE = "cat_session"
CAT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
CAT_OSS_DIR = "cat"
CAT_MAX_IMAGE_BYTES = 12 * 1024 * 1024
CHAT_IMAGE_OSS_DIR = "chat-images"
CHAT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
CHAT_IMAGE_MAX_COUNT = 5
CHAT_IMAGE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CHAT_IMAGE_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MEDIA_OSS_DIR = "tingwu"
TTS_OSS_DIR = "tts"
MEDIA_MAX_UPLOAD_BYTES = (
    int(os.environ.get("MEDIA_MAX_UPLOAD_MB", "500") or "500") * 1024 * 1024
)
MEDIA_ALLOWED_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
}
CAT_GUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
DEFAULT_AI_USER_ID = "default"

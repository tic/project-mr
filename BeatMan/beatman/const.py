from pathlib import Path

# Directories
BASE_DIR = Path(__file__).parent.parent
TEMP_DIR = BASE_DIR / "storage" / "unprocessed"
TEMP_DIR.mkdir(exist_ok=True)
STORAGE_DIR = BASE_DIR / "storage" / "processed"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Config files
PLAYLISTS_FILE = CONFIG_DIR / "playlists.json"
STATE_FILE = CONFIG_DIR / "state.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
DOWNLOADS_FILE = CONFIG_DIR / "downloads.json"

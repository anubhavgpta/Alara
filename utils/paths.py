from pathlib import Path


def get_alara_dir() -> Path:
    """Returns ~/.alara/, creating it if needed."""
    p = Path.home() / ".alara"
    p.mkdir(exist_ok=True)
    return p


def get_config_path() -> Path:
    return get_alara_dir() / "config.json"


def get_profile_path() -> Path:
    return get_alara_dir() / "profile.json"


def get_db_path() -> Path:
    return get_alara_dir() / "alara.db"


def get_log_path() -> Path:
    return get_alara_dir() / "alara.log"


def is_setup_complete() -> bool:
    return get_config_path().exists() and \
           get_profile_path().exists()

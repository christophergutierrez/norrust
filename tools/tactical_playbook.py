"""Load shared tactical instructions from their canonical maintained document."""
from pathlib import Path


PLAYBOOK_PATH = Path(__file__).resolve().parents[1] / "docs" / "LLM_TACTICAL_PLAYBOOK.md"


def load_tactical_playbook() -> str:
    """Resolve the playbook independently of the process working directory."""
    try:
        return PLAYBOOK_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            "model_prompt_error: canonical tactical playbook is missing or unreadable at "
            f"{PLAYBOOK_PATH}; restore docs/LLM_TACTICAL_PLAYBOOK.md"
        ) from exc


def load_combat_doctrine() -> str:
    """Select mode-independent tactics, excluding response/annotation instructions."""
    _, separator, remainder = load_tactical_playbook().partition("## Shared combat doctrine\n")
    doctrine = remainder.split("\n## ", 1)[0].strip()
    if not separator or not doctrine:
        raise RuntimeError("model_prompt_error: canonical tactical playbook lacks Shared combat doctrine")
    return doctrine

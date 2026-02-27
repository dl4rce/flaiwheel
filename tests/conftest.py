import pytest
from pathlib import Path
import tempfile
import shutil

from flaiwheel.config import Config
from flaiwheel.quality import KnowledgeQualityChecker
from flaiwheel.health import HealthTracker


@pytest.fixture
def tmp_docs(tmp_path):
    """Create a temporary docs directory with expected structure."""
    for d in ["architecture", "api", "bugfix-log", "best-practices", "setup", "changelog", "tests"]:
        (tmp_path / d).mkdir()
        (tmp_path / d / "README.md").write_text(
            f"# {d}\n\nThis directory contains {d} documentation managed by Flaiwheel.\n"
            f"Add .md files here or use the corresponding write tool.\n"
        )
    (tmp_path / "README.md").write_text(
        "# Project Knowledge Base\n\n"
        "This repository contains the project knowledge base managed by Flaiwheel. "
        "It organizes architecture decisions, API documentation, bugfix logs, best practices, "
        "setup guides, changelogs, and test cases into structured Markdown files.\n"
    )
    return tmp_path


@pytest.fixture
def config(tmp_docs, tmp_path):
    """Create a Config pointing at the tmp docs."""
    cfg = Config(
        docs_path=str(tmp_docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
    )
    return cfg


@pytest.fixture
def quality_checker(config):
    return KnowledgeQualityChecker(config)


@pytest.fixture
def health():
    return HealthTracker()

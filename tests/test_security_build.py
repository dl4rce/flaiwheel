"""Regression checks for the image's dependency security policy."""
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def test_security_floors_reject_vulnerable_brotli_bindings():
    requirements = {
        req.name.lower(): req
        for line in map(str.strip, (ROOT / "security-constraints.txt").read_text().splitlines())
        if line and not line.startswith("#")
        for req in [Requirement(line)]
    }
    assert "1.2.0.2" not in requirements["brotlicffi"].specifier
    assert "1.2.1.0" in requirements["brotlicffi"].specifier
    assert "1.2.0" not in requirements["brotli"].specifier
    assert "1.2.1" in requirements["brotli"].specifier


def test_image_applies_constraints_and_checks_runtime_dependencies():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY security-constraints.txt ./" in dockerfile
    assert "--constraint security-constraints.txt" in dockerfile
    assert "torch torchvision --no-deps --index-url https://download.pytorch.org/whl/cpu" in dockerfile
    assert "apt-get upgrade -y" in dockerfile
    assert "python -m pip check" in dockerfile

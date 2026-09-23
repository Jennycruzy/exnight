import re
from pathlib import Path

from exnight import doc_figures

ROOT = Path(__file__).resolve().parent.parent


def _text(name: str) -> str:
    return re.sub(r"\s+", " ", (ROOT / "docs" / name).read_text())


def test_m2_figures_regenerate_from_committed_inputs():
    text = _text("m2.md")
    for row in doc_figures.m2_rows() + [doc_figures.m2_robustness()]:
        assert re.sub(r"\s+", " ", row) in text, row


def test_v3_figures_regenerate_from_committed_inputs():
    text = _text("v3.md")
    for row in doc_figures.v3_rows():
        assert re.sub(r"\s+", " ", row) in text, row

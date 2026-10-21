"""
PDF tables, images and scanned pages (app/services/document_extraction.py),
run against small PDFs generated on the fly - no Qdrant or LLM needed; the
vision model is a stub.
"""
import io
import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

fitz = pytest.importorskip("fitz")
pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

from langchain_core.documents import Document
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.document_extraction import (
    build_table_chunks,
    expand_table_siblings,
    extract_pdf_images,
    extract_pdf_tables,
    format_context,
    load_pdf_text,
    pages_without_text,
    table_to_markdown,
    transcribe_scanned_pages,
)

TABLE_CFG = {"keep_whole_if_under_rows": 25, "rows_per_chunk": 15, "repeat_headers_on_split": True}
IMAGE_CFG = {"min_image_size_bytes": 100, "min_image_dimension_px": 50, "max_images_per_document": 25}


def _png(width=200, height=120, color=(0.2, 0.4, 0.8)):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, tuple(int(c * 255) for c in color))
    for x in range(0, width, 7):  # some detail so it doesn't compress to nothing
        for y in range(0, height, 5):
            pix.set_pixel(x, y, ((x * 3) % 255, (y * 5) % 255, 90))
    return pix.tobytes("png")


@pytest.fixture
def report_pdf(tmp_path):
    """Page 1: text + a 'Quarterly revenue' table + a chart image."""
    path = tmp_path / "report.pdf"
    styles = getSampleStyleSheet()
    data = [["Region", "Q1", "Q2"], ["North", "120", "135"], ["South", "98", "110"], ["West", "77", "81"]]
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(_png())
    SimpleDocTemplate(str(path), pagesize=A4).build([
        Paragraph("Sales were strong across regions this year.", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Quarterly revenue by region", styles["Normal"]),
        table,
        Spacer(1, 12),
        Image(str(image_path), width=200, height=120),
        Paragraph("Closing remarks follow.", styles["Normal"]),
    ])
    return str(path)


@pytest.fixture
def scanned_pdf(tmp_path):
    """Page 1 has text, page 2 is only a full-page picture (a scan)."""
    path = tmp_path / "scan.pdf"
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(_png(600, 800, (0.95, 0.95, 0.9)))
    styles = getSampleStyleSheet()
    SimpleDocTemplate(str(path), pagesize=A4).build([
        Paragraph("Cover page with a real text layer.", styles["Normal"]),
        PageBreak(),
        Image(str(image_path), width=400, height=530),
    ])
    return str(path)


def test_table_to_markdown_cleans_cells():
    md = table_to_markdown([["Name", "Note"], ["a|b", "line1\nline2"], ["c", None]])
    assert md.splitlines() == [
        "| Name | Note |",
        "|---|---|",
        "| a\\|b | line1 line2 |",
        "| c |  |",
    ]


def test_build_table_chunks_splits_with_header_and_shared_id():
    rows = [["Id", "Value"]] + [[str(i), str(i * 10)] for i in range(40)]
    chunks = build_table_chunks(rows, "DOC1", TABLE_CFG, source="pdf_table", page=2, caption="Ledger")
    assert len(chunks) == 3  # 40 rows > 25 -> pieces of 15
    assert len({c.metadata["table_id"] for c in chunks}) == 1
    for part, chunk in enumerate(chunks):
        assert chunk.page_content.startswith(f"Table 1 on page 3: Ledger (part {part + 1} of 3)")
        assert "| Id | Value |" in chunk.page_content
        assert chunk.metadata["table_part"] == part
        assert chunk.metadata["table_parts"] == 3
        assert chunk.metadata["chunk_type"] == "table"


def test_build_table_chunks_drops_empty_rows_and_columns():
    rows = [["A", "", "B"], ["1", None, "2"], ["", "", ""]]
    [chunk] = build_table_chunks(rows, "D", TABLE_CFG, source="docx_table")
    assert "| A | B |" in chunk.page_content
    assert "| 1 | 2 |" in chunk.page_content
    assert build_table_chunks([["only header"]], "D", TABLE_CFG, source="docx_table") == []


def test_pdf_table_is_extracted_and_removed_from_body_text(report_pdf):
    tables, bboxes = extract_pdf_tables(report_pdf, "DOC", TABLE_CFG)
    assert len(tables) == 1
    content = tables[0].page_content
    assert content.startswith("Table 1 on page 1: Quarterly revenue by region")
    assert "| Region | Q1 | Q2 |" in content
    assert "| North | 120 | 135 |" in content
    assert tables[0].metadata["page"] == 0

    [page] = load_pdf_text(report_pdf, bboxes)
    assert "Sales were strong" in page.page_content
    assert "Closing remarks" in page.page_content
    assert "North" not in page.page_content  # indexed once, as the table

    [unfiltered] = load_pdf_text(report_pdf)
    assert "North" in unfiltered.page_content


def test_pdf_images_are_described_once_with_page(report_pdf):
    calls = []

    def describe(b64, ext, prompt):
        calls.append(ext)
        return "Bar chart of revenue."

    chunks = extract_pdf_images(report_pdf, "DOC", IMAGE_CFG, describe)
    assert len(chunks) == 1 and calls == ["png"]
    assert chunks[0].page_content == "Image on page 1: Bar chart of revenue."
    assert chunks[0].metadata["chunk_type"] == "image"

    assert extract_pdf_images(report_pdf, "DOC", dict(IMAGE_CFG, min_image_dimension_px=1000), describe) == []
    assert extract_pdf_images(report_pdf, "DOC", IMAGE_CFG, describe, skip_pages=[0]) == []


def test_scanned_pages_are_detected_and_transcribed(scanned_pdf):
    assert pages_without_text(scanned_pdf) == [1]
    docs = transcribe_scanned_pages(scanned_pdf, [1], lambda b64, ext, prompt: "Invoice total: 4,200")
    assert len(docs) == 1
    assert docs[0].page_content == "Invoice total: 4,200"
    assert docs[0].metadata["page"] == 1
    assert docs[0].metadata["chunk_type"] == "scanned_page"


def test_expand_table_siblings_returns_whole_table_in_order():
    pieces = [Document(page_content=f"part {i}", metadata={"table_id": "T", "table_part": i, "table_parts": 3}) for i in range(3)]
    text = Document(page_content="intro", metadata={"chunk_type": "text"})
    docs = [pieces[1], text, pieces[2]]
    expanded = expand_table_siblings(docs, lambda tid: list(reversed(pieces)))
    assert [d.page_content for d in expanded] == ["part 0", "part 1", "part 2", "intro"]

    windowed = expand_table_siblings([pieces[2]], lambda tid: pieces, max_pieces=2)
    assert [d.page_content for d in windowed] == ["part 1", "part 2"]

    # A failed lookup keeps the original hit rather than dropping it.
    def boom(tid):
        raise RuntimeError("qdrant down")
    assert expand_table_siblings([pieces[0]], boom) == [pieces[0]]


def test_format_context_tags_type_and_page():
    ctx = format_context([
        Document(page_content="| a |", metadata={"chunk_type": "table", "page": 2}),
        Document(page_content="hello", metadata={}),
        Document(page_content="chart", metadata={"chunk_type": "image", "page": 0}),
    ])
    assert ctx == "[Table, page 3]\n| a |\n\n[Text]\nhello\n\n[Image description, page 1]\nchart"

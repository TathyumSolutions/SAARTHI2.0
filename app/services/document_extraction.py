"""
Structure-aware extraction for uploaded documents (PDF tables, images and
scanned pages), used by LLMService.process_to_embeddings.

A plain text loader flattens a PDF table into a run of cell values with
the row/column relationship lost, and drops images entirely - so a
question about a number in a table or a chart came back "not in the
documents". This module keeps them as their own chunks:

- tables -> markdown chunks (header repeated on every piece), labelled with
  their page and the caption line above them; their area is cut out of the
  page's body text so the same numbers aren't also indexed as garbled text;
- embedded images -> a vision-model description, labelled with its page;
- pages with no text layer (scans) -> a vision-model transcription of the
  rendered page, so a scanned PDF is searchable instead of indexing nothing.

Kept free of the Qdrant/LLM clients (the vision call is passed in) so it can
be unit tested on small generated PDFs.
"""
import base64
import uuid

from langchain_core.documents import Document

# Image formats the vision API accepts as-is; anything else (JPEG2000, JBIG2,
# TIFF, ...) is re-encoded to PNG before captioning.
_VISION_IMAGE_EXTS = {"png", "jpeg", "jpg", "gif", "webp"}

IMAGE_CAPTION_PROMPT = (
    "Describe this image from a business document in 2-5 sentences. If it is a "
    "chart or graph, say what it measures and list the key values, labels and "
    "trend. If it contains a table or readable text, transcribe the important "
    "figures and labels exactly. Skip decorative detail."
)

SCANNED_PAGE_PROMPT = (
    "This is a scanned page from a business document. Transcribe all of its text "
    "faithfully, in reading order. Reproduce any table as a markdown table with "
    "its header row. Describe any chart or figure in one or two sentences with its "
    "key values. Output only the transcription."
)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def _clean_cell(value):
    """One table cell as a single markdown-safe line."""
    if value is None:
        return ""
    return " ".join(str(value).split()).replace("|", "\\|")


def table_to_markdown(rows):
    """A list-of-rows table as a markdown table string (first row = header)."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [[_clean_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "|" + "|".join(["---"] * width) + "|"]
    lines.extend("| " + " | ".join(r) + " |" for r in padded[1:])
    return "\n".join(lines)


def _drop_empty_rows_and_columns(rows):
    rows = [list(r) for r in rows if any(_clean_cell(c) for c in r)]
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(_clean_cell(r[i]) for r in rows)]
    return [[r[i] for i in keep] for r in rows]


def build_table_chunks(rows, document_code, table_cfg, source, page=None, table_index=0, caption=None):
    """
    Split one table into markdown chunks of at most `rows_per_chunk` body
    rows, repeating the header on every piece (when configured) so each
    chunk can be read on its own. All pieces share a table_id so retrieval
    can pull the rest of the table back in (see expand_table_siblings).

    Each chunk opens with a short label ("Table 2 on page 4: <caption>") so
    the embedding - which only sees the first few hundred tokens - knows
    what the table is about, not just its first rows.
    """
    rows = _drop_empty_rows_and_columns(rows or [])
    if len(rows) < 2:
        return []

    keep_whole = int(table_cfg.get("keep_whole_if_under_rows", 25))
    group_size = max(1, int(table_cfg.get("rows_per_chunk", keep_whole)))
    repeat_headers = table_cfg.get("repeat_headers_on_split", True)

    header, body = rows[0], rows[1:]
    if len(body) <= keep_whole:
        groups = [body]
    else:
        groups = [body[i:i + group_size] for i in range(0, len(body), group_size)]

    label = f"Table {table_index + 1}"
    if page is not None:
        label += f" on page {page + 1}"
    if caption:
        label += f": {caption}"

    table_id = f"{document_code}_table_{'p%s_' % page if page is not None else ''}{table_index}_{uuid.uuid4().hex[:6]}"
    columns = [_clean_cell(c) for c in header]
    chunks = []
    for part, group in enumerate(groups):
        piece_rows = [header] + group if (repeat_headers or part == 0) else group
        part_label = label if len(groups) == 1 else f"{label} (part {part + 1} of {len(groups)})"
        metadata = {
            "document_code": document_code,
            "table_id": table_id,
            "source": source,
            "chunk_type": "table",
            "table_part": part,
            "table_parts": len(groups),
            "columns": columns,
        }
        if page is not None:
            metadata["page"] = page
        chunks.append(Document(page_content=f"{part_label}\n\n{table_to_markdown(piece_rows)}", metadata=metadata))
    return chunks


def _caption_above(page, bbox, max_chars=200):
    """The line of text just above a table (usually its title), if any."""
    x0, top, x1, _ = bbox
    if top <= 2:
        return None
    try:
        strip = page.crop((0, max(0, top - 30), page.width, top), strict=False)
        text = (strip.extract_text() or "").strip()
    except Exception:
        return None
    if not text:
        return None
    line = text.splitlines()[-1].strip()
    return line[:max_chars] or None


def extract_pdf_tables(file_path, document_code, table_cfg):
    """
    Every table pdfplumber can find, as chunks, plus the bounding box of
    each table per page ({page_index: [(x0, top, x1, bottom), ...]}) so the
    body text loader can leave those areas out.
    """
    import pdfplumber

    chunks, bboxes = [], {}
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            table_index = 0
            for table in page.find_tables():
                rows = table.extract()
                table_chunks = build_table_chunks(
                    rows, document_code, table_cfg, source="pdf_table", page=page_num,
                    table_index=table_index, caption=_caption_above(page, table.bbox),
                )
                if not table_chunks:
                    continue
                chunks.extend(table_chunks)
                bboxes.setdefault(page_num, []).append(tuple(table.bbox))
                table_index += 1
    return chunks, bboxes


# ---------------------------------------------------------------------------
# Body text
# ---------------------------------------------------------------------------

def _inside_any(rect, boxes, margin=2):
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(b[0] - margin <= cx <= b[2] + margin and b[1] - margin <= cy <= b[3] + margin for b in boxes)


def load_pdf_text(file_path, table_bboxes=None):
    """
    One Document per page with that page's text, leaving out text that sits
    inside an extracted table (it's indexed as a table chunk instead).
    Same metadata keys as langchain's PyMuPDFLoader (source, file_path,
    page, total_pages), plus chunk_type="text".
    """
    import fitz

    table_bboxes = table_bboxes or {}
    documents = []
    with fitz.open(file_path) as pdf:
        total = len(pdf)
        for page_num, page in enumerate(pdf):
            boxes = table_bboxes.get(page_num)
            if boxes:
                blocks = page.get_text("blocks", sort=True)
                text = "\n".join(
                    b[4].strip() for b in blocks
                    if b[6] == 0 and b[4].strip() and not _inside_any(b[:4], boxes)
                )
            else:
                text = page.get_text(sort=True).strip()
            if not text:
                continue
            documents.append(Document(page_content=text, metadata={
                "source": file_path, "file_path": file_path, "page": page_num,
                "total_pages": total, "chunk_type": "text",
            }))
    return documents


def pages_without_text(file_path, min_chars=20):
    """Page indexes with no usable text layer - i.e. scanned pages."""
    import fitz

    with fitz.open(file_path) as pdf:
        return [i for i, page in enumerate(pdf) if len(page.get_text().strip()) < min_chars]


# ---------------------------------------------------------------------------
# Images and scanned pages
# ---------------------------------------------------------------------------

def _image_for_vision(pdf, xref, base_image):
    """(bytes, ext) in a format the vision API accepts."""
    import fitz

    ext = (base_image.get("ext") or "png").lower()
    if ext in _VISION_IMAGE_EXTS:
        return base_image["image"], "jpeg" if ext == "jpg" else ext
    pix = fitz.Pixmap(pdf, xref)
    if pix.alpha or (pix.colorspace and pix.colorspace.n > 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("png"), "png"


def extract_pdf_images(file_path, document_code, image_cfg, describe, skip_pages=()):
    """
    Caption each distinct embedded image once (a logo repeated on every page
    is described once, not per page), skipping tiny ones and stopping at
    max_images_per_document. `describe(b64, ext, prompt)` returns the
    vision model's text or None.
    """
    import fitz

    min_bytes = int(image_cfg.get("min_image_size_bytes", 5000))
    min_dim = int(image_cfg.get("min_image_dimension_px", 100))
    max_images = int(image_cfg.get("max_images_per_document", 25))
    skip_pages = set(skip_pages)

    chunks, seen = [], set()
    with fitz.open(file_path) as pdf:
        for page_num, page in enumerate(pdf):
            if page_num in skip_pages:
                continue
            for img_index, img in enumerate(page.get_images(full=True)):
                if len(chunks) >= max_images:
                    return chunks
                xref, width, height = img[0], img[2], img[3]
                if xref in seen:
                    continue
                seen.add(xref)
                if width < min_dim or height < min_dim:
                    continue
                try:
                    base_image = pdf.extract_image(xref)
                    if not base_image or len(base_image["image"]) < min_bytes:
                        continue
                    image_bytes, ext = _image_for_vision(pdf, xref, base_image)
                except Exception as e:
                    print(f"⚠️ [RAG] Skipping unreadable image on page {page_num + 1}: {e}")
                    continue
                caption = describe(base64.b64encode(image_bytes).decode("utf-8"), ext, IMAGE_CAPTION_PROMPT)
                if not caption:
                    continue
                chunks.append(Document(
                    page_content=f"Image on page {page_num + 1}: {caption}",
                    metadata={
                        "document_code": document_code,
                        "image_id": f"{document_code}_image_p{page_num}_{img_index}_{uuid.uuid4().hex[:6]}",
                        "source": "pdf_image", "chunk_type": "image", "page": page_num,
                    },
                ))
    return chunks


def transcribe_scanned_pages(file_path, page_numbers, describe, dpi=150):
    """
    Render each page and have the vision model transcribe it. Returns
    Documents shaped like load_pdf_text's (chunk_type="scanned_page") so
    they're split and indexed like ordinary page text.
    """
    import fitz

    documents = []
    with fitz.open(file_path) as pdf:
        for page_num in page_numbers:
            try:
                png = pdf[page_num].get_pixmap(dpi=dpi).tobytes("png")
            except Exception as e:
                print(f"⚠️ [RAG] Could not render scanned page {page_num + 1}: {e}")
                continue
            text = describe(base64.b64encode(png).decode("utf-8"), "png", SCANNED_PAGE_PROMPT)
            if text:
                documents.append(Document(page_content=text, metadata={
                    "source": file_path, "file_path": file_path, "page": page_num,
                    "total_pages": len(pdf), "chunk_type": "scanned_page",
                }))
    return documents


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def expand_table_siblings(docs, fetch_table_pieces, max_pieces=8):
    """
    When a retrieved chunk is one piece of a split table, replace it with
    the table's pieces in order (up to max_pieces) so the answer sees the
    whole table rather than an arbitrary slice of its rows.
    fetch_table_pieces(table_id) returns that table's Documents.
    """
    expanded, done_tables = [], set()
    for doc in docs:
        meta = doc.metadata or {}
        table_id = meta.get("table_id")
        if not table_id or meta.get("table_parts", 1) <= 1:
            expanded.append(doc)
            continue
        if table_id in done_tables:
            continue
        done_tables.add(table_id)
        try:
            pieces = fetch_table_pieces(table_id) or []
        except Exception as e:
            print(f"⚠️ [RAG] Could not fetch sibling table pieces for {table_id}: {e}")
            pieces = []
        if not pieces:
            expanded.append(doc)
            continue
        pieces = sorted(pieces, key=lambda d: (d.metadata or {}).get("table_part", 0))
        hit_part = meta.get("table_part", 0)
        if len(pieces) > max_pieces:
            # Keep a window around the piece that actually matched.
            start = max(0, min(hit_part - max_pieces // 2, len(pieces) - max_pieces))
            pieces = pieces[start:start + max_pieces]
        expanded.extend(pieces)
    return expanded


def format_context(docs):
    """
    Retrieved chunks joined for the answer prompt, each tagged with what it
    is and where it came from, e.g. "[Table, page 3]" - so the model knows
    to read a markdown table by row/column and can cite the page.
    """
    kinds = {"table": "Table", "image": "Image description", "scanned_page": "Scanned page"}
    parts = []
    for doc in docs:
        meta = doc.metadata or {}
        tag = kinds.get(meta.get("chunk_type"), "Text")
        if isinstance(meta.get("page"), int):
            tag += f", page {meta['page'] + 1}"
        parts.append(f"[{tag}]\n{doc.page_content}")
    return "\n\n".join(parts)

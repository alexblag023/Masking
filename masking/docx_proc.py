"""Маскирование .docx: основной текст, таблицы, колонтитулы, текстовые поля, метаданные."""
import io

from docx import Document
from docx.oxml.ns import qn

from .masker import Masker

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _mask_paragraph(p_el, masker: Masker) -> None:
    # Работаем по w:t, а не по runs: так затрагиваются и гиперссылки, и поля.
    nodes = [t for t in p_el.iter(qn("w:t")) if t.text]
    if not nodes:
        return
    full = "".join(t.text for t in nodes)
    matches = masker.replacements(full)
    if not matches:
        return

    bounds, pos = [], 0
    for t in nodes:
        bounds.append((pos, pos + len(t.text)))
        pos += len(t.text)

    new_texts = [list(t.text) for t in nodes]
    for start, end, repl in reversed(matches):
        first = True
        for i, (b0, b1) in enumerate(bounds):
            if b1 <= start or b0 >= end:
                continue
            lo, hi = max(start, b0) - b0, min(end, b1) - b0
            new_texts[i][lo:hi] = list(repl) if first else []
            first = False
    for t, chars in zip(nodes, new_texts):
        t.text = "".join(chars)
        t.set(_XML_SPACE, "preserve")


def mask_docx(data: bytes, masker: Masker) -> bytes:
    doc = Document(io.BytesIO(data))

    roots = [doc.element.body]
    for section in doc.sections:
        for part in (
            section.header, section.footer,
            section.first_page_header, section.first_page_footer,
            section.even_page_header, section.even_page_footer,
        ):
            if not part.is_linked_to_previous:
                roots.append(part._element)

    seen = set()
    for root in roots:
        if id(root) in seen:
            continue
        seen.add(id(root))
        for p in root.iter(qn("w:p")):
            _mask_paragraph(p, masker)

    props = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "comments", "keywords"):
        if getattr(props, attr):
            setattr(props, attr, "")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()

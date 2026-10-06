"""Обработка .docx: основной текст, таблицы, колонтитулы, метаданные.

Работаем по узлам <w:t>, а не по runs: это захватывает гиперссылки и поля
и сохраняет форматирование — замена попадает в первый узел, где началось
совпадение, остальные затронутые узлы очищаются.
"""
import io
from typing import Callable

from docx import Document
from docx.oxml.ns import qn

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _process_paragraph(p_el, transform: Callable[[str], str]) -> None:
    nodes = [t for t in p_el.iter(qn("w:t")) if t.text]
    if not nodes:
        return
    full = "".join(t.text for t in nodes)
    new = transform(full)
    if new == full:
        return
    # Простейшая замена: кладём весь новый текст в первый узел, остальные
    # обнуляем. Форматирование первого узла сохраняется.
    nodes[0].text = new
    nodes[0].set(_XML_SPACE, "preserve")
    for t in nodes[1:]:
        t.text = ""


def _walk_roots(doc):
    """Все xml-корни, содержащие параграфы: тело + не наследуемые колонтитулы."""
    yield doc.element.body
    seen = {id(doc.element.body)}
    for section in doc.sections:
        for part in (
            section.header, section.footer,
            section.first_page_header, section.first_page_footer,
            section.even_page_header, section.even_page_footer,
        ):
            try:
                if part.is_linked_to_previous:
                    continue
            except Exception:
                pass
            el = part._element
            if id(el) in seen:
                continue
            seen.add(id(el))
            yield el


def _clear_metadata(doc) -> None:
    props = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "comments", "keywords"):
        try:
            if getattr(props, attr):
                setattr(props, attr, "")
        except Exception:
            pass


def transform_docx(data: bytes, worker) -> bytes:
    """Проходит по всем абзацам docx и применяет worker.

    worker: объект с методом .mask_text/.unmask_text; если есть .set_location,
    она вызывается перед обработкой каждого абзаца с меткой «docx:body/pN».
    """
    text_fn = (
        worker.mask_text if hasattr(worker, "mask_text")
        else worker.unmask_text if hasattr(worker, "unmask_text")
        else worker
    )
    set_loc = getattr(worker, "set_location", None)
    doc = Document(io.BytesIO(data))
    counter = 0
    for root in _walk_roots(doc):
        for p in root.iter(qn("w:p")):
            if set_loc:
                set_loc(f"docx:p{counter}")
                counter += 1
            _process_paragraph(p, text_fn)
    _clear_metadata(doc)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def mask_docx(data: bytes, masker) -> bytes:
    return transform_docx(data, masker)


def unmask_docx(data: bytes, unmasker) -> bytes:
    return transform_docx(data, unmasker)

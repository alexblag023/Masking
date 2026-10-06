"""Обработка .xlsx: значения ячеек, комментарии, метаданные. Формулы не трогаем."""
import io

from openpyxl import load_workbook


def _transform(data: bytes, worker, text_attr: str) -> bytes:
    fn = getattr(worker, text_attr)
    set_loc = getattr(worker, "set_location", None)
    wb = load_workbook(io.BytesIO(data))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    continue
                value = cell.value
                if isinstance(value, bool) or value is None:
                    continue
                if set_loc:
                    set_loc(f"xlsx:{ws.title}!{cell.coordinate}")
                if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
                    s = str(int(value))
                    masked = fn(s)
                    if masked != s:
                        cell.value = masked
                        cell.number_format = "@"
                elif isinstance(value, str) and value:
                    masked = fn(value)
                    if masked != value:
                        cell.value = masked
                if cell.comment is not None:
                    text = cell.comment.text
                    masked = fn(text)
                    if masked != text:
                        cell.comment.text = masked

    props = wb.properties
    props.creator = ""
    props.lastModifiedBy = ""
    props.title = props.subject = props.description = props.keywords = None

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def mask_xlsx(data: bytes, masker) -> bytes:
    return _transform(data, masker, "mask_text")


def unmask_xlsx(data: bytes, unmasker) -> bytes:
    return _transform(data, unmasker, "unmask_text")

"""Ленивая обёртка над slovnet NER + navec эмбеддингами.

Модель весит ~29 МБ, грузится ~1 с. Делаем это один раз и прячем за функцией,
чтобы `import masking` оставался быстрым.
"""
import threading
from typing import Iterable

from .paths import models_dir

_lock = threading.Lock()
_ner = None


def ner():
    """Возвращает загруженную модель NER. Потокобезопасно."""
    global _ner
    if _ner is not None:
        return _ner
    with _lock:
        if _ner is not None:
            return _ner
        from navec import Navec
        from slovnet import NER as _NER
        nav = Navec.load(str(models_dir() / "navec_news_v1_1B_250K_300d_100q.tar"))
        model = _NER.load(str(models_dir() / "slovnet_ner_news_v1.tar"))
        model.navec(nav)
        _ner = model
        return _ner


def spans(text: str, types: Iterable[str] = ("PER", "LOC")) -> list[tuple[int, int, str]]:
    """Возвращает [(start, end, 'PER'|'LOC'|'ORG')] для абзаца.

    AddrExtractor-подобный шаг (объединение частей адреса) делает уже вызывающий
    код — здесь только сырые спаны модели.
    """
    if not text or text.isspace():
        return []
    types = set(types)
    markup = ner()(text)
    return [(s.start, s.stop, s.type) for s in markup.spans if s.type in types]

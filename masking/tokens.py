"""Формат обратимых токенов и их устойчивый разбор.

Токен: [ФИО_1], [АДРЕС_3], с падежом: [ФИО_1:дат].
Разбор терпим к искажениям, которые вносят Word, человек или LLM:
пробелы, регистр, полноширинные скобки, дефис/подчёркивание как разделитель.
"""
import re

KINDS = {
    "ФИО":     "FIO",
    "АДРЕС":   "ADDR",
    "ТЕЛ":     "PHONE",
    "СНИЛС":   "SNILS",
    "ИНН":     "INN",
    "КАРТА":   "CARD",
    "ПАСПОРТ": "PASSPORT",
    "ДАТА":    "DATE",
    "EMAIL":   "EMAIL",
    "ЦИФ":     "DIGITS",
}
KIND_RU = {v: k for k, v in KINDS.items()}
# Какие типы несут падеж (только ФИО по-настоящему склоняются).
CASED_KINDS = {"FIO"}

# Коды падежей в токене -> коды pymorphy3.
CASE_RU2PM = {
    "им": "nomn", "род": "gent", "дат": "datv",
    "вин": "accs", "тв": "ablt", "пр": "loct",
}
CASE_PM2RU = {v: k for k, v in CASE_RU2PM.items()}

# Терпимое к искажениям регулярное выражение для поиска токенов в тексте.
_KIND_ALT = "|".join(sorted(KINDS, key=len, reverse=True))
TOKEN_RE = re.compile(
    rf"[\[［]\s*({_KIND_ALT})\s*[_\-–‑ ]\s*(\d{{1,6}})\s*"
    r"(?:[:：]\s*(им|род|дат|вин|тв|пр)\s*)?[\]］]",
    re.IGNORECASE,
)


def make_token(kind: str, seq: int, case_pm: str = "nomn") -> str:
    """Собирает токен. kind — 'FIO'|'ADDR', case_pm — код падежа pymorphy3."""
    ru = KIND_RU[kind]
    if kind == "ADDR" or case_pm == "nomn":
        return f"[{ru}_{seq}]"
    suffix = CASE_PM2RU.get(case_pm)
    return f"[{ru}_{seq}:{suffix}]" if suffix else f"[{ru}_{seq}]"


def parse_token(match: "re.Match") -> tuple[str, int, str]:
    """Из совпадения TOKEN_RE -> (kind 'FIO'|'ADDR', seq, case_pm)."""
    kind = KINDS[match.group(1).upper()]
    seq = int(match.group(2))
    case_pm = CASE_RU2PM.get((match.group(3) or "").lower(), "nomn")
    return kind, seq, case_pm


def strip_tokens(text: str) -> str:
    """Удаляет токены из текста (для нормализации при повторном маскировании)."""
    return TOKEN_RE.sub("", text)

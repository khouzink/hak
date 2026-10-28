"""Input guardrails: deterministic, auditable, independent of LLM provider."""
import re

MAX_USER_TEXT = 8000
_INJECTION = [
    re.compile(r'(?i)(ignore|disregard)\s+(all\s+)?(previous|prior|system|developer)\s+(instructions|prompts|rules)'),
    re.compile(r'(?i)(reveal|print|show|leak)\s+(the\s+)?(system\s+prompt|api\s*key|secret|developer\s+message)'),
    re.compile(r'(?i)(игнорируй|забудь|отмени)\s+(все\s+)?(предыдущие|системные|инструкции|правила)'),
    re.compile(r'(?i)(покажи|раскрой|выведи)\s+(системный\s+промпт|api.?ключ|секретный\s+ключ)'),
    re.compile(r'(?i)(обойди|подмени|измени)\s+(критерии\s+оценивания|проверку\s+жюри)'),
]

def validate_user_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Введи описание поездки')
    if len(value) > MAX_USER_TEXT:
        raise ValueError('Запрос слишком длинный (максимум 8000 символов)')
    if any(pattern.search(value) for pattern in _INJECTION):
        raise ValueError('Запрос содержит инструкции, не относящиеся к планированию поездки')
    return value.strip()

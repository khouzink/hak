"""Money said in words: «150 тыс», «1,5 млн», «150.000», «1 000 ₽». Shared by screen 2 (intake) and screen 6 (change)."""
import re

BUDGET_UNITS = {'тыс': 1_000, 'к': 1_000, 'млн': 1_000_000, 'миллион': 1_000_000}
MAX_BUDGET = 20_000_000  # FlowSpec limit
BUDGET = (r'бюджет\w*(?:\s+на\s+(?:всю\s+поездку|поездку|всех|вс[её]))?\s*(?:до|в)?\s*(\d[\d ]*(?:[.,]\d+)*)\s*(тыс|к\b|млн|миллион|000|₽|руб)?'
          r'(?!\s*(?:ноч|дн|сут|взросл|человек|звезд))')


def amount(number, unit):
    """«150.000» and «100,000» are thousands; «1,5 млн» is a decimal; a bare number is roubles."""
    digits = number.replace(' ', '')
    if not unit or unit in ('000', '₽', 'руб'):
        digits = re.sub(r'[.,](?=\d{3}(?!\d))', '', digits)
    return round(float(digits.replace(',', '.')) * BUDGET_UNITS.get(unit, 1))


def find_budget(t):
    """The total budget named after «бюджет», or None."""
    m = re.search(BUDGET, t)
    return amount(m[1], m[2]) if m and m[1].strip() else None

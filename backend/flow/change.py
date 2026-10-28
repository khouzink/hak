"""Screen 6: change the trip with one message. Proposes a diff; nothing applies without «Применить»."""
import re
from datetime import date, datetime, timedelta

from backend.flow import data
from backend.flow.amounts import MAX_BUDGET, find_budget
from backend.flow.engine import LATE_CHECKOUT, assess, leaves_before, breakdown, candidates, distances, district_of, fmt_range, money, price, rate_options, road, timeline
from backend.flow.intake import today
from backend.flow.model import WISHES, FlowSpec

NUM = {'один': 1, 'одна': 1, 'одну': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7}
WISH_WORDS = [('kids', r'детск|клуб|для детей'), ('pool', r'бассейн'), ('beach', r'к морю|пляж'), ('quiet', r'тих|тишин'),
              ('breakfast', r'завтрак'), ('all_inclusive', r'вс[её] включено'), ('sea_view', r'вид на море'), ('culture', r'музе|театр')]
HELP = 'Пока умею менять даты, бюджет, состав, животных, удобства, тариф, район и город, ранний заезд и поздний выезд.'
EXAMPLES = ['А если на два дня позже?', 'Бюджет меньше', 'С нами едет собака', 'Сэкономь, но детский клуб оставь', 'Можно поздний выезд?']


def _n(word):
    return int(word) if word.isdigit() else NUM[word]


def current_choice(spec: FlowSpec):
    """Hotel the trip currently holds: explicit choice, else the agent's best pick."""
    from backend.flow.screens import places
    dest = data.DEST.get(spec.destination or '')
    if not dest:
        return None
    if spec.hotel_id and data.hotel(spec.hotel_id):
        return spec.hotel_id
    p = places(spec)
    best = next((c for c in p['cards'] if c['slot'] == 'best'), None)
    return best['id'] if best else None


def _party_line(spec):
    kids = f' + дети {", ".join(map(str, spec.children_ages))}' if spec.children_ages else ''
    return f'{spec.adults} взр.' + kids + (' + питомец' if spec.pets else '')


EMPTY_TRIP = {'district': '—', 'hotel': 'нет подходящего', 'room': '—', 'rate': '—', 'road': '—', 'total': None, 'warnings': [], 'hotel_id': None}


def _warnings(s, h, dest, bd):
    road = [c['short'] for c in bd['timeline']['checks'] if c['status'] != 'ok']
    return road + [WISHES.get(v['wish'], v['wish']) + ': ' + v['reason'] for v in assess(s, h, dest)['violations']]


def summary(spec: FlowSpec):
    dest = data.DEST.get(spec.destination or '')
    hid = current_choice(spec)
    out = {'city': dest['name'] if dest else '—', 'dates': fmt_range(spec.check_in, spec.check_out), 'party': _party_line(spec)}
    if not dest or not hid:
        return {**out, **EMPTY_TRIP}
    h = data.hotel(hid)
    s = spec.model_copy(update={'hotel_id': hid})
    bd = breakdown(s, h, dest)
    p = bd['price']
    d = district_of(dest, h)
    return {**out, 'district': d['name'] if d else '—', 'hotel': h['name'], 'hotel_id': hid, 'room': p['room']['name'], 'rate': p['rate']['name'] + (', отмена бесплатно' if p['rate']['refundable'] else ', невозвратный'),
            'road': f'прилёт {bd["timeline"]["steps"][1]["time"]} по местному', 'total': bd['total'], 'warnings': _warnings(s, h, dest, bd)}


def _pick_hotel(spec: FlowSpec, prefer=None):
    """Keep the current hotel if it still fits; otherwise the best of the new selection."""
    from backend.flow.screens import places
    dest = data.DEST[spec.destination]
    if spec.hotel_id and ('hotel' in spec.locked or not [v for v in assess(spec, data.hotel(spec.hotel_id), dest)['violations']]):
        return spec.hotel_id
    p = places(spec.model_copy(update={'hotel_id': None}))
    cards = p['cards']
    if prefer:
        cards = sorted(cards, key=prefer)
    best = next((c for c in cards if c['slot'] == 'best'), None) if not prefer else (cards[0] if cards else None)
    return best['id'] if best else None


MONTH_STEMS = ['январ', 'феврал', 'март', 'апрел', 'мая', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр']
EXTRA_WORDS = [('late_checkout', r'поздн\w* выезд|выехать позже|выезд позже'), ('early_checkin', r'ранн\w* заезд|заселиться раньше'),
               ('storage', r'камер\w* хранени|оставить багаж')]
RATE_WORDS = [('bb', r'с завтрак'), ('ai', r'вс[её] включено'), ('nr', r'без питани|только номер')]
LOCK_TARGETS = {'отел': 'hotel', 'дат': 'dates', 'район': 'district', 'город': 'destination'}


# ---------- phrase → operations: one small rule per kind of request ----------

def _days(count, unit):
    """«две недели» → 14, «день» → 1."""
    return _n(count or '1') * (7 if (unit or '').startswith('недел') else 1)


def _rule_relative_dates(t, spec):
    """«на 2 дня позже», «на день дольше», «на две недели раньше»: a count (default one) of days or weeks."""
    m = re.search(r'на\s+(?:(\d+|' + '|'.join(NUM) + r')\s+)?(дн\w*|день|сут\w*|недел\w*)?\s*(позже|раньше|больше|меньше|дольше|короче)', t)
    if not m or not (m[1] or m[2]):
        return []
    n = _days(m[1], m[2])
    if m[3] in ('позже', 'раньше'):
        return [{'op': 'shift', 'days': n if m[3] == 'позже' else -n}]
    return [{'op': 'length', 'days': n if m[3] in ('больше', 'дольше') else -n}]


def _rule_exact_dates(t, spec):
    m = re.search(r'(?:с\s*)?(\d{1,2})\s*(?:по|[-–—])\s*(\d{1,2})\s*(' + '|'.join(MONTH_STEMS) + ')', t)
    if not m:
        return []
    month = MONTH_STEMS.index(m[3]) + 1
    first = today()
    year = first.year + (date(first.year, month, int(m[1])) < first)  # the next such dates, never a past year
    return [{'op': 'dates', 'check_in': date(year, month, int(m[1])), 'check_out': date(year, month, int(m[2]))}]


def _rule_budget(t, spec):
    value = find_budget(t)
    if value is not None:
        return [{'op': 'budget', 'value': value}]
    return [{'op': 'cheaper'}] if re.search(r'бюджет\w* меньше|подешевле|дешевле', t) else []


def _rule_save(t, spec):
    if not re.search(r'сэконом|экономн', t):
        return []
    keep = [w for w, rx in WISH_WORDS if re.search(r'(?:оставь|сохрани|но с|но чтобы|только с)[^.]*' + rx, t)]
    return [{'op': 'save', 'keep': keep}]


def _rule_pets(t, spec):
    if re.search(r'без (?:собак|кошк|питом)', t):
        return [{'op': 'pets', 'value': False}]
    return [{'op': 'pets', 'value': True}] if re.search(r'собак|кошк|питом|пес\b|пса\b', t) else []


def _rule_party(t, spec):
    ops = []
    m = re.search(r'(?:еще|ещё|с нами|плюс|\+)\s*(?:едет|поедет)?\s*(?:ребен\w*|сын\w*|доч\w*)\s*(\d{1,2})', t)
    if m:
        ops.append({'op': 'child', 'age': int(m[1])})
    if re.search(r'(?:добав\w*|ещ[её]|плюс)\s+(?:одного|один|1)?\s*взросл', t):
        return ops + [{'op': 'adults', 'value': spec.adults + len(spec.children_ages) + 1}]
    m = re.search(r'нас (?:будет )?(\d{1,2}|двое|трое|четверо)', t)
    if m:
        ops.append({'op': 'adults', 'value': {'двое': 2, 'трое': 3, 'четверо': 4}.get(m[1]) or int(m[1])})
    return ops


def _rule_rate(t, spec):
    ops = [{'op': 'rate', 'value': rate} for rate, rx in RATE_WORDS if re.search(rx, t)][:1]
    if re.search(r'бесплатн\w* отмен|возвратн|можно отменить', t) and not re.search(r'невозвратн', t):
        ops.append({'op': 'refundable'})
    return ops


def _rule_wishes(t, spec):
    if re.search(r'сэконом|экономн', t):
        return []  # «сэкономь, но оставь X» keeps X; it is not a new requirement
    return [{'op': 'wish', 'wish': w, 'level': 'must'} for w, rx in WISH_WORDS
            if w not in ('breakfast', 'all_inclusive') and re.search(r'(?:нужен|нужна|нужно|хочу|важ\w*|чтобы был\w*|с\s)[^.]{0,20}' + rx, t)]


def _rule_place(t, spec, text=''):
    ops = []
    if re.search(r'ближе к мор|у моря|первая линия', t):
        ops.append({'op': 'near', 'trait': 'beach'})
    elif re.search(r'ближе к центр|в центре', t):
        ops.append({'op': 'near', 'trait': 'center'})
    dest = data.DEST.get(spec.destination or '') or {}
    ops += [{'op': 'district', 'value': d['id']} for d in dest.get('districts', []) if d['name'].casefold().split()[0][:5] in t]
    did = data.find_destination(t)
    if did and did != spec.destination:
        ops.append({'op': 'city', 'value': did})
    return ops


def _rule_extras(t, spec):
    """Early check-in, storage, late check-out — the latter with a named hour («до 18:00») becomes late_until."""
    ops = [{'op': 'extra', 'value': extra} for extra, rx in EXTRA_WORDS if re.search(rx, t)]
    until = re.search(r'(?:выезд\w*|выехать)\s+(?:позже\s+)?(?:до|в)\s+(\d{1,2})(?::(\d{2}))?', t)
    if until and any(op['value'] == 'late_checkout' for op in ops):
        ops = [op for op in ops if op['value'] != 'late_checkout'] + [{'op': 'late_until', 'value': f'{int(until[1]):02d}:{until[2] or "00"}'}]
    return ops


def _rule_stay(t, spec):
    ops = _rule_extras(t, spec)
    m = re.search(r'(?:прилета\w*|прилечу|прибыва\w*|буду)\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?\s*(утра|вечера|дня|ночи)?', t)
    if m:
        hour = int(m[1]) + (12 if m[3] in ('вечера', 'дня') and int(m[1]) < 12 else 0)
        ops.append({'op': 'arrival', 'value': f'{hour % 24:02d}:{m[2] or "00"}'})
    m = re.search(r'(закрепи|зафиксируй|открепи|сними замок)\s*(?:с\s*)?(отел|дат|район|город)', t)
    if m:
        ops.append({'op': 'lock' if m[1] in ('закрепи', 'зафиксируй') else 'unlock', 'value': LOCK_TARGETS[m[2]]})
    return ops


RULES = [_rule_relative_dates, _rule_exact_dates, _rule_budget, _rule_save, _rule_pets, _rule_party, _rule_rate, _rule_wishes, _rule_place, _rule_stay]


def parse_ops(text, spec: FlowSpec):
    t = text.casefold().replace('ё', 'е')
    return [op for rule in RULES for op in rule(t, spec)]


# ---------- operations → new spec: one handler per operation ----------

class Change:
    """Working state of one message: the draft spec, what to say, what was refused, how to pick the hotel."""

    def __init__(self, spec):
        self.spec, self.d = spec, spec.model_dump()
        self.dest = data.DEST.get(spec.destination or '')
        self.replies, self.blocked, self.prefer = [], [], None

    def say(self, text):
        self.replies.append(text)

    def refuse(self, text):
        self.blocked.append(text)

    def current_hotel(self):
        return self.spec.hotel_id or current_choice(self.spec)


def _locked(c, what, message):
    if what in c.spec.locked:
        c.refuse(message)
        return True
    return False


def _set_dates(c, check_in, check_out, say):
    """One place that decides whether new dates are possible: not locked, in the future, at least one night, at most 30."""
    if _locked(c, 'dates', 'Даты закреплены 🔒 — сначала сними замок'):
        return
    if check_in < today():
        c.refuse('Эти даты уже прошли — выбери будущие')
    elif not 1 <= (check_out - check_in).days <= 30:
        c.refuse('Так нельзя: поездка должна быть от 1 до 30 ночей')
    else:
        c.d['check_in'], c.d['check_out'] = check_in, check_out
        c.say(say.format(fmt_range(check_in, check_out)))


def _op_shift(c, op):
    step = timedelta(days=op['days'])
    _set_dates(c, c.d['check_in'] + step, c.d['check_out'] + step, 'Сдвинул на {}')


def _op_length(c, op):
    _set_dates(c, c.d['check_in'], c.d['check_out'] + timedelta(days=op['days']), 'Теперь {}')


def _op_dates(c, op):
    _set_dates(c, op['check_in'], op['check_out'], 'Новые даты: {}')


def _op_budget(c, op):
    if op['value'] > MAX_BUDGET:
        c.d['budget'], c.d['nightly_budget'] = None, None
        c.say(f'Бюджет больше {money(MAX_BUDGET)} — считаю, что ограничения нет')
        return
    c.d['budget'], c.d['nightly_budget'] = op['value'], None
    c.say(f'Бюджет на всё — {money(op["value"])}')


def _cheapest_trip(spec, dest):
    """The smallest total budget that still fits one hotel here (hotel + road + two transfers, as hotel_budget counts)."""
    hotels = [a['price']['total'] for a in candidates(spec.model_copy(update={'hotel_id': None, 'budget': None, 'nightly_budget': None}), dest)['ok']]
    return int(-(-(min(hotels) + road(spec, dest)['total'] + 2 * 2500) // 1000) * 1000) if hotels else None


def _op_cheaper(c, op):
    current = summary(c.spec)['total']
    if not current:
        return
    floor = _cheapest_trip(c.spec, c.dest) if c.dest else None
    target = max(int(round(current * 0.85, -3)), floor or 0)
    if floor and floor >= current:
        c.say('Дешевле этой поездки в направлении вариантов нет — это уже самый дешёвый')
        return
    c.d.update(budget=target, nightly_budget=None, cheap=True)
    c.say(f'Снизил бюджет до {money(target)}')
    c.prefer = 'cheapest'


def _op_save(c, op):
    hid = c.current_hotel()
    rate = price(c.spec, data.hotel(hid), c.dest, c.spec.room_id, c.spec.rate_id)['rate']['id'] if hid and c.dest else None
    c.d['hotel_id'] = hid
    if rate == 'ai':
        c.d['rate_id'] = 'bb'
        kept = (' с ' + ', '.join(WISHES[w].lower() for w in op['keep'])) if op['keep'] else ''
        c.say(f'Оставил отель{kept}, сменил тариф на «Завтрак»')
    else:
        c.prefer = ('save', op['keep'], hid, rate)


def _op_pets(c, op):
    c.d['pets'] = op['value']
    if op['value']:
        c.d['priorities']['pets'] = 'must'
    else:
        c.d['priorities'].pop('pets', None)
    c.say('Учёл питомца' if op['value'] else 'Без питомца')


def _op_child(c, op):
    c.d['children_ages'] = c.d['children_ages'] + [op['age']]
    c.d['priorities'].setdefault('kids', 'want')
    c.say(f'Добавил ребёнка {op["age"]} лет')


def _op_adults(c, op):
    c.d['adults'] = max(1, op['value'] - len(c.d['children_ages']))
    c.say(f'Теперь взрослых: {c.d["adults"]}')


RATE_SAYS = {'bb': 'Тариф с завтраком', 'ai': 'Тариф «всё включено»', 'nr': 'Тариф без питания'}


def _op_rate(c, op):
    if c.dest and op['value'] not in [r['id'] for r in rate_options(c.dest)]:
        c.say('«Всё включено» в этом направлении не предлагаем')
        return
    c.d['rate_id'] = op['value']
    c.d['priorities'][{'ai': 'all_inclusive'}.get(op['value'], 'breakfast')] = 'skip' if op['value'] == 'nr' else 'want'
    c.say(RATE_SAYS[op['value']])


def _op_refundable(c, op):
    if c.d.get('rate_id') in (None, 'nr'):
        c.d['rate_id'] = 'bb'
    c.say('Тариф с бесплатной отменой')


def _op_wish(c, op):
    c.d['priorities'][op['wish']] = op['level']
    c.say(f'«{WISHES[op["wish"]]}» — обязательно')


def _nearer_sea(c):
    """No hotel-to-sea distance in the data: say so, and let the beach wish rank confirmed beaches higher."""
    if c.dest['kind'] != 'sea':
        c.say(f'{c.dest["name"]} — не у моря, ближе к морю здесь некуда. Скажи «а в …?», чтобы сменить город')
        return
    level = c.d['priorities'].get('beach')
    c.d['priorities'] = {**c.d['priorities'], 'beach': 'must' if level == 'must' else 'want'}
    c.say('В открытых данных расстояния до моря нет — точнее «ближе» не подберу. Отметил «Близко к морю»: '
          'отели с подтверждённым пляжем будут выше')


def _op_near(c, op):
    districts = [x for x in (c.dest or {}).get('districts', []) if op['trait'] in x['traits']]
    if districts:
        c.d['district'] = districts[0]['id']
        c.say(f'Перенёс в район «{districts[0]["name"]}»')
    elif c.dest and op['trait'] == 'center':
        c.prefer = 'center'
        c.say('Ищу ближе к центру')
    elif c.dest:
        _nearer_sea(c)


def _op_district(c, op):
    if not _locked(c, 'district', 'Район закреплён 🔒'):
        c.d['district'] = op['value']
        c.say(f'Район «{next(x["name"] for x in c.dest["districts"] if x["id"] == op["value"])}»')


def _op_city(c, op):
    if not _locked(c, 'destination', 'Город и отель закреплены 🔒') and not _locked(c, 'hotel', 'Город и отель закреплены 🔒'):
        c.d.update(destination=op['value'], district=None, hotel_id=None, room_id=None)
        c.say(f'Смотрю {data.DEST[op["value"]]["name"]}')


EXTRA_SAYS = {'early_checkin': 'Добавил ранний заезд', 'storage': 'Добавил камеру хранения', 'late_checkout': 'Добавил поздний выезд'}


def _op_extra(c, op):
    hid = c.current_hotel() if op['value'] == 'late_checkout' and c.dest else None
    tl = timeline(c.spec, data.hotel(hid), c.dest) if hid else None
    steps = {s['code']: s for s in tl['steps']} if tl else {}
    if steps and leaves_before(datetime.fromisoformat(steps['pickup']['iso']), c.spec.check_out, LATE_CHECKOUT):  # nothing to sell before 14:00
        c.say(f'Поздний выезд до {LATE_CHECKOUT} не успеете использовать: трансфер в аэропорт в {steps["pickup"]["time"]} (рейс в {steps["return"]["time"]}). '
              'Не добавляю. Вещи можно оставить в камере хранения бесплатно')
        return
    if op['value'] not in c.d['extras']:
        c.d['extras'] = c.d['extras'] + [op['value']]
    if not tl:
        c.say(EXTRA_SAYS[op['value']])
        return
    c.say(f'Выезжать в аэропорт нужно в {steps["pickup"]["time"]}: рейс в {steps["return"]["time"]}, дорога {tl["transfer"]["minutes"]} мин, '
          f'в аэропорту за 3 ч. Добавил поздний выезд до 14:00 — {money(tl["half_night"])}; камера хранения — бесплатно')


def _op_late_until(c, op):
    """A late check-out to a named hour: only up to 14:00 and only if the airport transfer leaves after it."""
    hid = c.current_hotel() if c.dest else None
    if not hid:
        _op_extra(c, {'value': 'late_checkout'})
        return
    tl = timeline(c.spec, data.hotel(hid), c.dest)
    steps = {s['code']: s for s in tl['steps']}
    pickup, flight = steps['pickup']['time'], steps['return']['time']
    if op['value'] > LATE_CHECKOUT or leaves_before(datetime.fromisoformat(steps['pickup']['iso']), c.spec.check_out, op['value']):
        c.say(f'Выезд в {op["value"]} не сходится: трансфер в аэропорт в {pickup} (рейс в {flight}), а поздний выезд отель даёт максимум до {LATE_CHECKOUT}. '
              f'Могу оставить вещи в камере хранения бесплатно — скажи «нужна камера хранения» — или поставить вечерний рейс в «Перелёты»')
        return
    _op_extra(c, {'value': 'late_checkout'})


def _op_arrival(c, op):
    c.d['arrival_time'] = op['value']
    c.say(f'Прилёт в {op["value"]} по местному — пересчитал заселение')


def _op_lock(c, op):
    c.d['locked'] = list(dict.fromkeys(c.d['locked'] + [op['value']]))
    if op['value'] == 'hotel' and not c.d.get('hotel_id'):
        c.d['hotel_id'] = current_choice(c.spec)
    c.say('Закрепил 🔒')


def _op_unlock(c, op):
    c.d['locked'] = [x for x in c.d['locked'] if x != op['value']]
    c.say('Снял замок')


HANDLERS = {'shift': _op_shift, 'length': _op_length, 'dates': _op_dates, 'budget': _op_budget, 'cheaper': _op_cheaper, 'save': _op_save,
            'pets': _op_pets, 'child': _op_child, 'adults': _op_adults, 'rate': _op_rate, 'refundable': _op_refundable, 'wish': _op_wish,
            'near': _op_near, 'district': _op_district, 'city': _op_city, 'extra': _op_extra, 'arrival': _op_arrival, 'late_until': _op_late_until, 'lock': _op_lock, 'unlock': _op_unlock}


def apply_ops(spec: FlowSpec, ops):
    """Returns (new_spec, reply_parts, blocked, how_to_pick_the_hotel)."""
    c = Change(spec)
    for op in ops:
        HANDLERS[op['op']](c, op)
    return FlowSpec.model_validate(c.d), c.replies, c.blocked, c.prefer


def _cheaper_keeping(probe, dest, current, keep, hid):
    """The best hotel at least 3 % cheaper that is no worse on every wish the user asked to keep."""
    from backend.flow.engine import STATUS_SCORE, candidates
    pool = candidates(probe.model_copy(update={'hotel_id': None, 'district': None}), dest)['ok']
    now = assess(probe, current['hotel'], dest)['rows']

    def keeps(a):
        rows = assess(probe, a['hotel'], dest)['rows']
        return all(STATUS_SCORE[rows[w]['status']] >= STATUS_SCORE[now[w]['status']] for w in keep)
    cheaper = [a for a in pool if a['price']['total'] < current['price']['total'] * 0.97 and a['hotel']['id'] != hid and keeps(a)]
    return max(cheaper, key=lambda a: (a['score'], -a['price']['total'])) if cheaper else None


def _save(spec, new, dest, keep, hid, rate):
    """Cheaper trip that keeps what the user named at least as well as the current hotel."""
    current = assess(new, data.hotel(hid), dest) if hid else None
    kept = ', '.join(WISHES[w].lower() for w in keep)
    probe = new.model_copy(update={'priorities': {**new.priorities, **{w: new.priorities.get(w, 'want') for w in keep}}})
    pick = _cheaper_keeping(probe, dest, current, keep, hid) if current and 'hotel' not in new.locked else None
    if pick:
        return new.model_copy(update={'hotel_id': pick['hotel']['id'], 'district': pick['hotel'].get('district')}), f'Нашёл дешевле{" и оставил " + kept if kept else ""}: «{pick["hotel"]["name"]}»'
    if rate == 'bb':
        return new.model_copy(update={'rate_id': 'nr'}), f'Отель тот же{" — " + kept + " на месте" if kept else ""}. Сменил тариф на «Без питания»: дешевле, но без завтрака и без возврата при отмене'
    return new, 'Дешевле с теми же условиями не нашёл'


def _choose_hotel(spec, new, prefer, replies):
    """Keep the hotel if it still fits, or pick by what the message asked for (cheapest, nearer, saving)."""
    dest = data.DEST[new.destination]
    free = 'hotel' not in new.locked
    if isinstance(prefer, tuple):
        new, msg = _save(spec, new, dest, *prefer[1:])
        replies.append(msg)
        return new
    if prefer == 'cheapest' and free:
        hid = _pick_hotel(new.model_copy(update={'hotel_id': None}), prefer=lambda c: c['total'])
    elif prefer == 'center' and free:
        hid = _pick_hotel(new.model_copy(update={'hotel_id': None}), prefer=lambda c: next((x['km'] for x in distances(new, data.hotel(c['id']), dest) if x['kind'] == 'center'), 99))
    else:
        hid = _pick_hotel(new)
    return new.model_copy(update={'hotel_id': hid})


def _pet_places():
    return [x['name'] for x in data.DESTINATIONS if x.get('pets_ok') and any(h['evidence'].get('pets', {}).get('value') for h in data.hotels(x['id']))]


def _pet_notes(spec, new, before, after):
    """Explain a hotel swap caused by a pet, or say honestly that no hotel there takes animals."""
    if not new.pets:
        return []
    if not after.get('hotel_id'):
        alts = _pet_places()
        place = data.DEST[new.destination]['name'] if new.destination else 'этом месте'
        return [f'В {place} ни один отель не подтверждает размещение с животными.' + (f' Подтверждено в: {", ".join(alts[:3])} — скажи «а в {alts[0]}?»' if alts else '')]
    if not spec.pets and before.get('hotel_id') and after['hotel_id'] != before['hotel_id']:
        return [f'В «{before["hotel"]}» с животными не подтверждено. Предлагаю «{after["hotel"]}»: размещение с питомцем подтверждено источником']
    return []


DIFF_FIELDS = [('city', 'Город', 'destination'), ('district', 'Район', 'district'), ('hotel', 'Отель', 'hotel'), ('room', 'Номер', None),
               ('rate', 'Тариф', None), ('dates', 'Даты', 'dates'), ('party', 'Кто', None), ('road', 'Дорога', None)]


def _diff(before, after, locked):
    return [{'field': key, 'title': title, 'before': before.get(key), 'after': after.get(key), 'changed': before.get(key) != after.get(key),
             'locked': lock in locked} for key, title, lock in DIFF_FIELDS]


def _delta_text(before, after):
    delta = after['total'] - before['total']
    same = before.get('hotel_id') == after.get('hotel_id') and before['room'] == after['room']
    return delta, ('. Отель и номер те же' if same else '') + f' · {"+" if delta >= 0 else "−"}{money(abs(delta))}'


def _changed_warnings(before, after):
    return {'warnings_added': [w for w in after['warnings'] if w not in before['warnings']],
            'warnings_removed': [w for w in before['warnings'] if w not in after['warnings']]}


def _reply(spec, new, before, after, said):
    """What the agent says: pet notes, then each change and refusal, then «same hotel · ±price» when both prices exist."""
    reply = '. '.join(_pet_notes(spec, new, before, after) + said)
    if after['total'] is None or before['total'] is None:
        return reply, None
    delta, tail = _delta_text(before, after)
    return reply + tail, delta


def propose(spec: FlowSpec, text: str, llm_ops=None):
    ops = parse_ops(text, spec) or (llm_ops or [])
    if not ops:
        return {'status': 'unknown', 'reply': HELP, 'examples': EXAMPLES}
    before = summary(spec)
    new, replies, blocked, prefer = apply_ops(spec, ops)
    if blocked and not replies:
        return {'status': 'blocked', 'reply': ' '.join(blocked), 'examples': EXAMPLES}
    if new.destination:
        new = _choose_hotel(spec, new, prefer, replies)
    after = summary(new)
    reply, delta = _reply(spec, new, before, after, replies + blocked)
    return {'status': 'proposal' if after['hotel_id'] or not new.destination else 'no_match', 'reply': reply, 'ops': ops, 'before': before, 'after': after,
            'diff': _diff(before, after, new.locked), 'delta': delta, **_changed_warnings(before, after), 'spec': new.model_dump(mode='json')}

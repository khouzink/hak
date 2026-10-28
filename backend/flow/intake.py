"""Screen 2: what the agent understood. Rules first; an LLM may only fill gaps."""
import os
import re
from datetime import date, timedelta

from backend.application.hotel_agent import parse_local
from backend.flow import data
from backend.flow.amounts import find_budget
from backend.flow.engine import Trace, fmt_party, fmt_range, money
from backend.flow.model import WISHES, FlowSpec

EXAMPLES = [
    'Хочу к тёплому морю в ноябре, недорого, с ребёнком 5 лет, без долгих перелётов',
    'Казань 12–14 ноября, командировка, до 6 тыс за ночь, рядом с Экспо',
    'С собакой в Калининград на неделю с 14 ноября',
    'Хочу отдохнуть',
]
EN_MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}
SEASONS = {'летом': (7, 'летом — взял июль'), 'зимой': (1, 'зимой — взял январь'), 'весной': (4, 'весной — взял апрель'), 'осенью': (9, 'осенью — взял сентябрь')}
RELATIVES = r'бабушк|дедушк|мам\w*|пап\w*|тещ|свекров|сестр|брат|подруг|друг\w*|коллег|муж\w*|жен(?:ой|а)\b|парн|девушк'
MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'мае': 5, 'мая': 5, 'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12}
TRIP_WORDS = (r'отдох|отпуск|каникул|поезд|поех|съезд|слета|лететь|отел|гостиниц|мор[еюя]|пляж|гор[ыах]|город|командиров|выходн|праздник|путешеств|тепл|'
              r'ед[уе]м?\b|хочу|недорог|дешев|ребен|собак|ночей|ноч[ьи]|недел|куда|поездк|тур\b|сияни|лыж|'
              r'trip|travel|vacation|holiday|beach|hotel|warm|sea\b|weekend|' + '|'.join(MONTHS) + '|' + '|'.join(EN_MONTHS) + '|'
              + '|'.join(re.escape(a) for a in data.ALIASES) + '|' + '|'.join(re.escape(a) for a in data.UNKNOWN_PLACES) + '|' + '|'.join(re.escape(a) for a in data.COUNTRIES))
OFFTOPIC = r'реши.*уравнен|системн\w* промпт|игнорируй.*инструкц|напиши (код|стих|эссе)|анекдот|рецепт'

QUESTIONS = {
    'where': {'title': 'Куда тянет?', 'options': [('auto', 'Подбери сам'), ('sea', 'К морю'), ('city', 'В город'), ('nature', 'На природу')]},
    'when': {'title': 'Когда?', 'options': [('auto', 'Подбери сам'), ('weekend', 'Ближайшие выходные'), ('next_month', 'Через месяц на неделю'), ('december', 'В декабре на неделю')]},
    'who': {'title': 'Кто едет?', 'options': [('auto', 'Подбери сам'), ('solo', 'Один'), ('couple', 'Вдвоём'), ('family', 'С ребёнком до 6 лет'), ('family_school', 'С ребёнком 7–12 лет')]},
}


def today():
    return date.fromisoformat(os.getenv('TODAY_OVERRIDE') or date.today().isoformat())


def _month_dates(month, t, ref):
    year = ref.year + (month < ref.month)
    start = date(year, month, 1)
    saturdays = [start + timedelta(days=(5 - start.weekday()) % 7 + 7 * i) for i in range(3)]
    start = saturdays[2]  # third Saturday: after the first week of the month, time to book
    if start <= ref:
        start = ref + timedelta(days=14)
    nights = _nights(t) or 7
    return start, start + timedelta(days=nights)


def _nights(t):
    m = re.search(r'на\s+(\d{1,2})\s+(?:ноч|дн|сут)', t)
    if m:
        return int(m[1])
    if re.search(r'на неделю', t):
        return 7
    if re.search(r'на две недели', t):
        return 14
    return None


GROUP_WORDS = {'двое': 2, 'трое': 3, 'четверо': 4, 'пятеро': 5, 'шестеро': 6, 'два': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'вдвоем': 2, 'втроем': 3, 'вчетвером': 4, 'впятером': 5, 'two': 2, 'three': 3, 'four': 4}
KIDS = r'(?<![а-я])(?:ребен|реб[её]нк|дет(?:и|ей|ск|ьми)|сын|доч|малыш|младен|грудн|подрост)'
TEEN_AGE = r'подрост\w*\s*(\d{1,2})\s*(?:лет|год)'
ADULT_WORDS = r'(двое|трое|четверо|пятеро|шестеро|два|три|четыре|пять|шесть)\s+взросл'
KIDS_LIST = r'(?:дет(?:и|ей|ьми)|ребят\w*)\s*:?\s*((?:\d{1,2}\s*(?:,|и)\s*)+\d{1,2})\s*(?:лет|год)'  # «дети 2 и 9 лет», «детьми 3, 6 и 10 лет»
ADULTS_AND_KIDS = r'(?:нас|едем|поедем)\s+(?:двое|трое|четверо|пятеро|шестеро|\d{1,2})\s*(?:и|\+|плюс|,)\s*(?:дет|реб|сын|доч|малыш)'
ORIGIN = r'(?:^|[\s,(])из\s+([А-ЯЁ][а-яё-]{2,})'  # «из Москвы», «из Екатеринбурга»
MOSCOW = r'(?<![а-я])м[ао]с+кв'
# Hidden requirements: (words, spec fields, priorities, chip «from → to»). One decision lives in one row.
HIDDEN_RULES = [
    (r'собак|кошк|питом|пес\b|пса\b|щен', {'pets': True}, {'pets': 'must'}, ('с собакой', 'животных пускают в отель, перевозка на всём пути')),
    (r'лестниц|коляск|ступен|пожил|бабушк\w* \d{2}|дедушк\w* \d{2}', {}, {'accessible': 'want'},
     ('без лестниц', 'доступно для коляски и пожилых — проверю по открытым данным')),
    (r'инвалид|маломобил|ходунк|(?:мам|пап|бабушк|дедушк|муж|жен|отц|мат)\w*\s+(?:на|в)\s+(?:инвалидн\w*\s+)?коляск', {}, {'accessible': 'must'},
     ('на коляске', 'доступная среда — обязательно; где её нет в данных, скажу «не подтверждено»')),
    (r'сразу в номер|сразу заселит|сразу (?:хочу )?(?:в )?душ|поспать в номере|заселиться (?:сразу|утром)', {'extras': ['early_checkin']}, {},
     ('сразу в номер', 'ранний заезд — платный, цену покажу в поездке')),
    (r'интернет|wi-?fi|вайфай|вай-фай', {}, {'wifi': 'want'}, None),
    (r'поезд|ж/д|жд\b|сапсан|ласточк|электричк', {}, {}, ('поездом', 'поезда пока не моделирую — считаю перелёт и честно помечаю как оценку')),
    (r'выспат|тих|тишин|спокой|без шума|уедин', {}, {'quiet': 'want'}, ('тишина', 'тихий район и отели без ночной анимации')),
    (r'командиров|конференц|выставк|форум|переговор|по работе|офис', {'purpose': 'business'}, {'office': 'want'},
     ('командировка', 'рядом с площадкой, завтрак, без ночных рейсов')),
    (r'музе|театр|экскурс|достопримеч', {}, {'culture': 'want'}, None),
    (r'бассейн', {}, {'pool': 'want'}, None),
    (r'вид\w* на море', {}, {'sea_view': 'want'}, None),
    (r'недорог|дешев|бюджетн|эконом|подешевле', {'cheap': True}, {}, ('недорого', 'сначала цена, потом всё остальное')),
]
HOLIDAYS = [  # (word, (month, day) start, (month, day) end, years after start for the end, why)
    ('майск', (5, 1), (5, 5), 0, 'майские праздники — взял 1–5 мая'),
    ('8 марта', (3, 6), (3, 9), 0, 'на 8 Марта — взял 6–9 марта'),
    ('23 феврал', (2, 21), (2, 24), 0, 'на 23 Февраля — взял 21–24 февраля'),
    ('новогодн', (12, 30), (1, 8), 1, 'новогодние праздники — взял 30 декабря – 8 января'),
    ('новый год', (12, 29), (1, 2), 1, 'на Новый год — взял 29 декабря – 2 января'),
]
ASSUME_TWO = 'Состав не назван — считаю двух взрослых.'
MAX_ADULTS, MAX_CHILDREN = 8, 6  # FlowSpec limits for one booking


class Reading:
    """One pass over the request: where → when → who → hidden requirements. What to show from it is Shown."""

    def __init__(self, text, llm_fields=None, memory=None):
        self.text, self.t, self.ref, self.memory = text, text.casefold().replace('ё', 'е').strip(), today(), memory
        self.llm = llm_fields or {}
        self.f = self._rules_then_llm()
        self.spec = {'text': text[:500]}
        self.origin = self._origin()
        self.said, self.assumed, self.hidden, self.pr, self.remembered = {}, {}, [], {}, []

    def _rules_then_llm(self):
        try:
            f = parse_local(self.text)
        except ValueError:
            f = {}
        words = re.search(ADULT_WORDS, self.t)
        if words and 'adults' not in f:
            f['adults'] = GROUP_WORDS[words[1]]
        for key in ('check_in', 'check_out', 'adults', 'children_ages', 'budget'):
            if key not in f and self.llm.get(key) not in (None, [], ''):
                f[key] = self.llm[key]
        return f

    def _origin(self):
        """The departure city as named: Moscow (the only modelled origin) or another city, said honestly."""
        m = re.search(ORIGIN, self.text)
        if not m:
            return None
        word = m[1]
        if re.match(MOSCOW, word.casefold()):
            return 'Москва'
        known = data.find_destination(word)
        if known:
            return data.DEST[known]['name']
        return word[:-1] + 'ь' if word.endswith('и') else word[:-1] if word[-1] in 'ая' else word[:-1] + 'а' if word.endswith('ы') else word

    def has(self, pattern):
        return re.search(pattern, self.t) is not None

    def hide(self, rule):
        if rule:
            self.hidden.append({'from': rule[0], 'to': rule[1]})

    # ---------- where ----------
    def where(self):
        self.named = data.find_all_destinations(self.text)
        self.did = self.named[0] if len(self.named) == 1 else None
        if len(self.named) > 1:
            self.spec['only'] = self.named[:5]
        if not self.named and self.llm.get('destination'):
            self.did = data.find_destination(self.llm['destination'])
        self._country_or_unknown()
        if self.did:
            self.spec['destination'] = self.did
            self.said['where'] = data.DEST[self.did]['name']
        self._kind_and_warmth()

    def _country_or_unknown(self):
        """No place from the catalogue: maybe a country («в Турцию»), maybe a place we have no data for («на Бали»)."""
        self.countries = [] if self.named else data.find_countries(self.text)
        if self.countries:
            self.spec['countries'] = self.countries
        self.unknown = None if (self.named or self.did or self.countries) else data.find_unknown_place(self.text) or self._moscow_as_place()
        alternative = re.search(r'(?:или|либо)\s+(?:в|на)?\s*([^\s,.!?]+)', self.t)  # «Сочи или Бали», «…, Казань или на Кипр»
        self.unknown_beside = data.find_unknown_place(alternative[1]) if self.named and alternative else None

    def _moscow_as_place(self):
        """Moscow named as where to stay (not «из Москвы»): the catalogue has no Moscow hotels, so say it."""
        to_moscow = [m for m in re.finditer(MOSCOW, self.t) if not re.search(r'из\s+$', self.t[:m.start()])]
        return {'name': 'в Москву', 'kind': 'city'} if to_moscow else None

    def _kind_and_warmth(self):
        kinds = [('sea', r'мор[еюя]|пляж|купат|океан|\bbeach\b|\bsea\b'), ('nature', r'гор[ыаху]|природ|лес|озер'), ('city', r'город|музе|театр|экскурс')]
        about_trip = re.sub(r'вид\w*\s+на\s+мор\w*', '', self.t)  # «вид на море» is about the room, not a beach trip
        self.hint = next((k for k, rx in kinds if re.search(rx, about_trip)), None)
        if self.hint:
            self.spec['kind'] = self.hint
        if self.has(r'тепл|жар|солнц|загорать|купат|\bwarm\b'):
            self.spec['warm'] = True
            self.hide(('тёплое', 'днём от +24° по климатической норме месяца'))
        elif self.hint == 'sea' and not self.did:
            self.spec['warm'] = True
            self.hide(('на море', 'тёплое море, где можно купаться: днём от +24°'))

    # ---------- when ----------
    def when(self):
        nights = _nights(self.t)
        self.month = self._month_named()
        sources = (self._explicit, self._holiday, self._month, self._season, self._weekend, self._default)
        ci, co, why = next(found for found in (source(nights) for source in sources) if found)
        if why:
            self.assumed['when'] = (fmt_range(ci, co), why)
        else:
            self.said['when'] = fmt_range(ci, co)
        self.spec['check_in'], self.spec['check_out'] = self._sane(ci, co)

    def _month_named(self):
        ru = next((v for k, v in MONTHS.items() if self.has(r'(?<![а-я])' + k)), None)
        return ru or next((v for k, v in EN_MONTHS.items() if k in self.t), None)

    def _explicit(self, nights):
        """Dates said outright; reversed ones are swapped and a zero-night stay gets one night — both said out loud."""
        if not (self.f.get('check_in') and self.f.get('check_out')):
            return None
        ci, co = date.fromisoformat(str(self.f['check_in'])), date.fromisoformat(str(self.f['check_out']))
        if co > ci:
            return ci, co, None
        if co < ci:
            return co, ci, f'Даты названы в обратном порядке — взял {fmt_range(co, ci)}. Поменяй, если нужно.'
        return ci, ci + timedelta(days=1), 'Заезд и выезд в один день — взял одну ночь. Поменяй, если нужно.'

    def _holiday(self, nights):
        hit = next((h for h in HOLIDAYS if h[0] in self.t), None)
        if not hit or (self.month and hit[0] != 'новогодн'):
            return None
        _, (m1, d1), (m2, d2), roll, why = hit
        year = self.ref.year + ((m1, d1) < (self.ref.month, self.ref.day) and m1 < 12)
        ci = date(year, m1, d1)
        co = ci + timedelta(days=nights) if nights else date(year + roll, m2, d2)
        return ci, co, why.capitalize() + '. Поменяй, если нужно.'

    def _month(self, nights):
        if not self.month:
            return None
        ci, co = _month_dates(self.month, self.t, self.ref)
        if ci.month != self.month:  # the month is under way and its third Saturday has passed
            return ci, co, f'Названный месяц почти закончился — взял ближайшие {nights or 7} ночей через две недели. Поменяй, если нужно.'
        return ci, co, f'Месяц назван, точных дат нет — взял {nights or 7} ночей с третьей субботы. Поменяй, если нужно.'

    def _season(self, nights):
        season = next((v for k, v in SEASONS.items() if k in self.t), None)
        if not season:
            return None
        ci, co = _month_dates(season[0], self.t, self.ref)
        return ci, co, f'Сказал «{season[1]}», {nights or 7} ночей с третьей субботы. Поменяй, если нужно.'

    def _weekend(self, nights):
        if not self.has(r'выходн|weekend'):
            return None
        return *_next_weekend(self.ref), 'Ближайшие выходные: с пятницы по воскресенье.'

    def _default(self, nights):
        ci = self.ref + timedelta(days=14)
        return ci, ci + timedelta(days=nights or 7), 'Даты не названы — через две недели на неделю. Поменяй, если нужно.'

    def _sane(self, ci, co):
        """Past dates move to the next year, more than 30 nights are cut — both said out loud."""
        old = ci.year
        while ci < self.ref:
            ci, co = ci.replace(year=ci.year + 1), co.replace(year=co.year + 1)
        if ci.year != old and self.said.pop('when', None):
            self.assumed['when'] = (fmt_range(ci, co), f'Эти даты в {old} году уже прошли — взял {ci.year} год. Поменяй, если нужно.')
        if (co - ci).days > 30:
            co = ci + timedelta(days=30)
            self.said.pop('when', None)
            self.assumed['when'] = (fmt_range(ci, co), 'Больше 30 ночей не бронируем — сократил до 30. Поменяй, если нужно.')
        self.ci, self.co = ci, co
        return ci, co

    # ---------- who ----------
    def who(self):
        kids = self.has(KIDS)
        group = self._group()
        relatives = len(re.findall(r'(?:с|со)\s+(?:' + RELATIVES + r')|\s(?:и|,)\s+(?:' + RELATIVES + r')', self.t))
        self.party_said = self._party_named(kids, group, relatives)
        self.adults_said = bool(self.f.get('adults') or group or relatives or self.has(r'один|одна|командиров|вдво|семь[ей]|компани'))
        ages = self._ages()
        adults = self._adults(group, relatives, kids, ages)
        if not self.party_said and self.memory:
            adults, ages = self._remembered_party()
        if kids and not ages:
            ages = [6]
            self.assumed['age'] = ('ребёнок 6 лет', 'Возраст не назван — взял 6 лет: от него зависят номер и детский клуб. Поменяй.')
        adults, ages = self._fits_one_booking(adults, ages)
        self.spec['adults'], self.spec['children_ages'] = adults, ages
        if ages:
            self.pr['kids'] = 'want'
            self.hide(('с ребёнком', 'детская инфраструктура и без ночных переездов'))
        self._party_chip(fmt_party(FlowSpec(adults=adults, children_ages=ages, check_in=self.ci, check_out=self.co)))

    def _fits_one_booking(self, adults, ages):
        """One booking takes up to 8 adults and 6 children; a bigger group is cut and told so, never an error."""
        self.capped = adults > MAX_ADULTS or len(ages) > MAX_CHILDREN
        return min(adults, MAX_ADULTS), ages[:MAX_CHILDREN]

    def _ages(self):
        """Ages said in the request: «ребёнок 5 лет», «подросток 13 лет», a baby is 0."""
        listed = re.search(KIDS_LIST, self.t)
        said = (list(self.f.get('children_ages') or []) or (re.findall(r'\d{1,2}', listed[1]) if listed else [])
                or [int(a) for a in re.findall(TEEN_AGE, self.t)])
        said = [int(a) for a in said]
        return said or ([0] if self.has(r'младен|грудн|малыш до года') else [])

    def _party_named(self, kids, group, relatives):
        """Did the request say anything about who travels (then memory and the «two adults» default stay out)?"""
        said = self.f.get('adults') or self.f.get('children_ages') or kids or group or relatives
        return bool(said or self.has(r'один|одна|семь[ей]|компани|командиров'))

    def _remembered_party(self):
        """Last trip's party; children are older by the years since then."""
        grown = max(0, self.ref.year - self.memory.get('saved_year', self.ref.year))
        self.remembered.append('who')
        return self.memory['adults'], [min(17, a + grown) for a in self.memory['children_ages']]

    def _group(self):
        m = re.search(r'(?:нас|едем|поедем)\s+(двое|трое|четверо|пятеро|шестеро|\d{1,2})|(вдвоем|втроем|вчетвером|впятером)|for (two|three|four)|(\d{1,2}) adults?', self.t)
        if not m:
            return None
        word = next(g for g in m.groups() if g)
        return GROUP_WORDS.get(word) or int(word)

    def _from_group(self, group, kids, ages):
        """«нас двое и дети 2 и 9» — the number is the adults; «нас трое с ребёнком» — the child is among them."""
        if self.has(ADULTS_AND_KIDS):
            return group
        return max(1, group - len(ages) - (1 if kids and not ages else 0))

    def _adults(self, group, relatives, kids, ages):
        if self.f.get('adults'):
            return self.f['adults']
        if group:
            return self._from_group(group, kids, ages)
        if relatives:
            return 1 + relatives
        return 1 if self.has(r'командиров|один|одна') and not kids else 2

    def _party_chip(self, party):
        if self.capped:
            self.assumed['who'] = (party, f'Вас больше {MAX_ADULTS} взрослых или {MAX_CHILDREN} детей — в один заказ беру {party}. '
                                          'Для большой группы оформим несколько заказов. Поменяй, если нужно.')
        elif self.party_said and not self.adults_said:
            self.assumed['who'] = (party, 'Ребёнка назвал, взрослых — нет: считаю двух взрослых. Поправь, если иначе.')
        elif self.party_said:
            self.said['who'] = party
        else:
            why = 'Помню по прошлой поездке. Поправь, если едете в другом составе.' if self.remembered else ASSUME_TWO
            self.assumed['who'] = (party, why)

    # ---------- hidden requirements, wishes, budget ----------
    def wishes(self):
        self._hidden_rules()
        if self.hint == 'sea' or self.spec.get('warm') and self.hint != 'city':
            self.pr.setdefault('beach', 'want')
        self._meals()
        self._flight_limit()
        self._budget()
        self._liked_before()
        self.spec['priorities'] = self.pr
        self.spec['remembered'] = [w for w in self.remembered if w != 'who']

    def _hidden_rules(self):
        for pattern, fields, priorities, chip in HIDDEN_RULES:
            if self.has(pattern):
                self.spec.update(fields)
                self.pr.update(priorities)
                self.hide(chip)
        if self.spec.get('purpose') == 'business' and self.has(r'экспо|expo'):
            self.spec['target_point'] = 'expo'

    def _meals(self):
        if self.has(r'вс[её] включено|all inclusive'):
            self.pr['all_inclusive'] = 'want'
        elif self.has(r'завтрак') or self.spec.get('purpose') == 'business':
            self.pr['breakfast'] = 'want'

    def _liked_before(self):
        """Portable likes from the last trip count as «want» unless this request already says otherwise."""
        for w in (self.memory or {}).get('liked', []):
            if w in WISHES and w not in self.pr:
                self.pr[w] = 'want'
                self.remembered.append(w)

    def _flight_limit(self):
        if self.has(r'без долг\w* перел[её]т|недолго лететь|не больше \d+ час|без пересад') or self.f.get('max_travel_hours'):
            self.spec['max_flight_minutes'] = int((self.f.get('max_travel_hours') or 5) * 60)
            self.hide(('без долгих перелётов', f'перелёт не дольше {self.spec["max_flight_minutes"] // 60} ч'))

    def _budget(self):
        if self.f.get('nightly_budget'):
            self.spec['nightly_budget'] = self.f['nightly_budget']
            self.said['budget'] = f'до {money(self.f["nightly_budget"])} за ночь'
        elif not self.f.get('budget') and find_budget(self.t):
            self.f['budget'] = find_budget(self.t)
            self._budget()
        elif self.f.get('budget', 0) > 10_000_000:
            self.assumed['budget'] = ('без ограничения', 'Бюджет больше 10 млн ₽ — считаю, что ограничения нет')
        elif self.f.get('budget'):
            self.spec['budget'] = self.f['budget']
            self.said['budget'] = f'до {money(self.f["budget"])} на всё'


class Shown:
    """What screen 2 shows from a reading: the questions still open and one chip per decision."""

    def __init__(self, reading):
        self.r = reading

    def questions(self):
        """Only when there is no place and no hint at all; then also ask what else is missing."""
        if self._any_place_hint():
            return []
        asked = ['where']
        if 'when' in self.r.assumed and not self.r.month and 'выходн' not in self.r.t:
            asked.append('when')
        return asked + ([] if self.r.party_said else ['who'])

    def _any_place_hint(self):
        return bool(self.r.did or self.r.hint or self.r.spec.get('warm') or self.r.unknown or self.r.named or self.r.countries)

    def chips(self, flow):
        chips = [self._where_chip(), self._said_or_assumed('when', 'Когда', 'dates'), self._said_or_assumed('who', 'Кто', 'party')]
        if 'age' in self.r.assumed:
            chips.append(_chip('age', 'Возраст', *self.r.assumed['age'], 'assumed', 'party'))
        chips.append(self._budget_chip(flow))
        chips.append(self._origin_chip())
        chips += [_chip('memory', 'Помню', 'любишь: ' + WISHES[w].lower(), 'Из прошлой поездки — учитываю как «желательно»', 'memory', 'priorities')
                  for w in self.r.remembered if w != 'who']
        if 'who' in self.r.remembered:
            chips[2]['source'] = 'memory'
        chips += [_chip('hidden', h['from'], h['to'], 'Скрытое требование: додумал из твоих слов', 'assumed', 'priorities') for h in self.r.hidden]
        return chips

    def _origin_chip(self):
        city = self.r.origin
        if city == 'Москва':
            return _chip('origin', 'Откуда', 'Москва', 'Назвал в запросе', 'said', 'origin')
        if city:
            return _chip('origin', 'Откуда', f'{city} → считаю из Москвы', f'Рейсы из города «{city}» в демо-данных не моделирую — считаю дорогу из Москвы, '
                         'цена перелёта будет оценкой. Поменяй, если нужно.', 'assumed', 'origin')
        return _chip('origin', 'Откуда', 'Москва', 'Город отправления не назван — считаю из Москвы', 'assumed', 'origin')

    def _where_chip(self):
        if self.r.did:
            return _chip('where', 'Куда', self.r.said['where'], 'Назвал в запросе' + self._unknown_note(), 'said', 'destination')
        if len(self.r.named) > 1:
            return _chip('where', 'Куда', 'сравню: ' + ', '.join(data.DEST[x]['name'] for x in self.r.named[:5]), 'Назвал несколько мест — покажу их рядом' + self._unknown_note(), 'said', 'destination')
        if self.r.countries:
            return _chip('where', 'Куда', ', '.join(self.r.countries) + ' — предложу места', 'Назвал страну — выберу направления внутри неё', 'said', 'destination')
        return _chip('where', 'Куда', 'Предложу 3 варианта', 'Город не назван — подберу направления под условия', 'assumed', 'destination')

    def _unknown_note(self):
        u = self.r.unknown_beside
        return f'. Поездку {u["name"]} не сравниваю: этого места нет в демо-данных' if u else ''

    def _said_or_assumed(self, key, title, edit):
        if key in self.r.said:
            return _chip(key, title, self.r.said[key], 'Назвал в запросе', 'said', edit)
        return _chip(key, title, *self.r.assumed[key], 'assumed', edit)

    def _budget_chip(self, flow):
        if 'budget' in self.r.said or 'budget' in self.r.assumed:
            return self._said_or_assumed('budget', 'Бюджет', 'budget')
        if flow.cheap:
            return _chip('budget', 'Бюджет', 'подешевле', 'Сказал «недорого» — сначала покажу то, что дешевле', 'said', 'budget')
        return _chip('budget', 'Бюджет', 'не задан', 'Бюджет не спрашиваю — покажу варианты дешевле и дороже', 'assumed', 'budget')


def _chip(key, title, value, reason, source, edit):
    return {'key': key, 'title': title, 'value': value, 'source': source, 'reason': reason, 'edit': edit}


def _offtopic(text, tr):
    tr.step('Разбор запроса', detail='не про поездку')
    return {'status': 'offtopic', 'quote': text, 'message': 'Давай о поездках. Скажи, куда и как хочешь поехать — или начни с примера.', 'examples': EXAMPLES, 'trace': tr.dump()}


def _similar(flow, unknown):
    from backend.flow.screens import destinations
    cards = destinations(flow.model_copy(update={'kind': unknown['kind'], 'warm': flow.warm or unknown['kind'] == 'sea'}))['cards']
    return {'status': 'unknown_place', 'message': f'Поездку {unknown["name"]} подобрать не могу: этого места нет в демо-данных. Похожие по погоде и дороге:',
            'similar': [{'id': c['id'], 'name': c['name'], 'character': c['character']} for c in cards]}


def _question(key):
    q = QUESTIONS[key]
    return {'key': key, **q, 'options': [{'id': i, 'label': label} for i, label in q['options']], 'default': 'auto'}


def understand(text, llm_fields=None, memory=None):
    tr = Trace()
    t = text.casefold().replace('ё', 'е').strip()
    if re.search(OFFTOPIC, t) or not re.search(TRIP_WORDS, t):
        return _offtopic(text, tr)
    r = Reading(text, llm_fields, memory)
    r.where()
    r.when()
    r.who()
    r.wishes()
    flow = FlowSpec.model_validate(r.spec)
    parser = 'llm+rules' if llm_fields else 'rules'
    tr.step('Разбор запроса', detail=parser)
    shown = Shown(r)
    questions = shown.questions()
    chips = shown.chips(flow)
    result = {'status': 'questions' if questions else 'ready', 'quote': text, 'spec': flow.model_dump(mode='json'), 'chips': chips, 'hidden': r.hidden,
              'questions': [_question(q) for q in questions], 'next': 'places' if r.did else 'destinations', 'parser': parser,
              'priorities': [{'key': k, 'title': WISHES[k], 'level': v} for k, v in r.pr.items()]}
    if r.unknown:
        result.update(_similar(flow, r.unknown))
    tr.step('Допущения', len([c for c in chips if c['source'] == 'assumed']))
    result['trace'] = tr.dump(llm_calls=1 if llm_fields else 0)
    return result


def _next_weekend(ref):
    ci = ref + timedelta(days=(4 - ref.weekday()) % 7 or 7)
    return ci, ci + timedelta(days=2)


def _in_a_month(ref):
    ci = ref + timedelta(days=30)
    return ci, ci + timedelta(days=7)


WHEN_ANSWERS = {'weekend': _next_weekend, 'next_month': _in_a_month, 'december': lambda ref: _month_dates(12, '', ref)}
WHO_ANSWERS = {'solo': (1, []), 'couple': (2, []), 'family': (2, [5]), 'family_school': (2, [9])}


def answer_questions(spec: FlowSpec, answers: dict):
    """Apply button answers to the spec. "auto" (or anything unknown) keeps the agent's assumption."""
    upd, priorities = {}, dict(spec.priorities)
    where = answers.get('where')
    if where in ('sea', 'city', 'nature'):
        upd['kind'] = where
    if where == 'sea':
        upd['warm'] = True
        priorities['beach'] = 'want'
    when = WHEN_ANSWERS.get(answers.get('when'))
    if when:
        upd['check_in'], upd['check_out'] = when(today())
    who = WHO_ANSWERS.get(answers.get('who'))
    if who:
        upd['adults'], upd['children_ages'] = who[0], list(who[1])
    if who and who[1]:
        priorities['kids'] = 'want'
    return FlowSpec.model_validate({**spec.model_dump(), **upd, 'priorities': priorities})

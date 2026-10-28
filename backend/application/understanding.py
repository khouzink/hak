"""Auditable intake: explicit fields, editable assumptions and missing questions."""
import os
import re
from datetime import date, timedelta
from backend.application.hotel_agent import parse_local
from backend.domain.journey import JourneySpec
from backend.domain.errors import Conflict


def today():
    return date.fromisoformat(os.getenv('TODAY_OVERRIDE') or date.today().isoformat())


def understand(text, extra=None):
    t = text.casefold().replace('ё', 'е')
    if re.search(r'реши.*уравнен|системн\w* промпт|игнорируй.*инструкц', t) or not re.search(r'отдых|поезд|отел|мор[еюя]|сочи|адлер|сириус|хургад|казан|калининград|стамбул|питер|москв|турци|бали|мальдив|байкал|эль[ -]?гун|марса[ -]?алам|рас[ -]?эль[ -]?хайм|hotel|ноябр|декабр|выходн|хочу|ед[еу]|путешеств', t):
        return {'status': 'offtopic', 'message': 'Я собираю поездки. Расскажи, как хочешь отдохнуть — и начнём.', 'questions': [], 'chips': []}
    fields = {**(extra or {}), **parse_local(text)}
    explicit = set(fields)
    for fragment, city in [('питер','Санкт-Петербург'), ('калининград','Калининград'), ('бали','Бали'), ('турци','Турция'), ('дуба','Дубай'), ('эль-гуна','Эль-Гуна'), ('марса-алам','Марса-Алам'), ('рас-эль-хайма','Рас-эль-Хайма')]:
        if fragment in t and 'destination' not in fields:
            fields['destination'] = city; explicit.add('destination')
    assumptions = {}
    months = {'январ':1,'феврал':2,'март':3,'апрел':4,'мае':5,'июн':6,'июл':7,'август':8,'сентябр':9,'октябр':10,'ноябр':11,'декабр':12}
    has_date_hint = 'check_in' in fields
    if not has_date_hint:
        if re.search(r'летом|летни\w*', t):
            reference=today()
            year_match=re.search(r'\b20\d{2}\b',t)
            year=int(year_match[0]) if year_match else reference.year+(reference.month>8)
            if os.getenv('CATALOG_MODE','bundled')!='live' and date(year,6,1)>date(2027,3,31):
                raise Conflict('Летние даты выходят за горизонт подготовленных данных. Выбери даты до 31 марта 2027 года.')
            raise Conflict('Уточни конкретные даты летней поездки.')
        if re.search(r'новогодн', t):
            reference=today()
            year_match=re.search(r'\b20\d{2}\b',t)
            year=int(year_match[0]) if year_match else reference.year if (reference.month,reference.day) <= (12,30) else reference.year+1
            start=date(year,12,30)
            fields.update(check_in=start.isoformat(),check_out=date(year+1,1,8).isoformat())
            assumptions['dates']='На новогодние праздники: с 30 декабря по 8 января. Даты можно изменить.'
            has_date_hint=True
        month = next((v for k,v in months.items() if k in t), None)
        if not has_date_hint and month:
            year_match = re.search(r'\b20\d{2}\b', t)
            year = int(year_match[0]) if year_match else today().year + (month < today().month)
            start = date(year, month, 1)
            start += timedelta(days=(5-start.weekday()) % 7)
            duration=re.search(r'на\s+(\d{1,2})\s+(?:ноч|дн)',t)
            nights=int(duration[1]) if duration else 7
            fields.update(check_in=start.isoformat(), check_out=(start+timedelta(days=nights)).isoformat())
            assumptions['dates'] = f'Выбрали первую субботу месяца и {nights} ночей; даты можно изменить.'
            has_date_hint = True
        elif not has_date_hint and 'выходн' in t:
            start = today() + timedelta(days=(4-today().weekday()) % 7 or 7)
            fields.update(check_in=start.isoformat(), check_out=(start+timedelta(days=2)).isoformat())
            assumptions['dates'] = 'Ближайшие выходные: с пятницы по воскресенье.'
            has_date_hint = True
    questions = []
    if 'destination' not in fields:
        fields['destination'] = ''
        assumptions['destination'] = 'Направление не названо. Выбери подходящее место из предложенных вариантов.'
        if not re.search(r'мор[еюя]|пляж|гор[ыах]|природ', t): questions.append('destination')
    if not has_date_hint:
        start = today()+timedelta(days=7)
        fields.update(check_in=start.isoformat(), check_out=(start+timedelta(days=7)).isoformat())
        assumptions['dates'] = 'Через неделю на 7 ночей. Можно выбрать свои даты.'
        questions.append('dates')
    has_party = bool({'adults','children_ages'} & explicit) or bool(re.search(r'ребен|семь|деть|командиров',t))
    if 'adults' not in fields:
        fields['adults'] = 1 if 'командиров' in t else 2
        assumptions['adults'] = 'Состав взрослых не указан; проверь это допущение.'
    if not has_party: questions.append('guests')
    if re.search(r'ребен|деть',t) and 'children_ages' not in fields:
        fields['children_age_unknown'] = True
        if 'dates' not in questions and ('destination' in explicit or not re.search(r'мор[еюя]|пляж',t)): questions.append('children_ages')
    fields.setdefault('children_ages', [])
    fields.setdefault('origin', 'Москва')
    if 'origin' not in explicit: assumptions['origin'] = 'Город отправления не указан; взяли Москву.'
    if 'budget' not in fields:
        fields['budget'] = 0
        fields['budget_unlimited'] = True
        assumptions['budget'] = 'Бюджет не задан. Показываем стоимость без ограничения сверху.'
    fields['wishes'] = text
    if fields.get('check_in') and fields.get('check_out') and fields['check_out']<fields['check_in']:
        fields['check_in'],fields['check_out']=fields['check_out'],fields['check_in']
        assumptions['dates']='Даты были в обратном порядке: поменяли местами. Проверь перед подбором.'
    spec = JourneySpec.model_validate(fields).model_dump(mode='json')
    if date.fromisoformat(spec['check_in']) < today():
        raise Conflict('Эти даты уже прошли. Выбери будущую поездку.')
    labels = {'destination': ('Куда', spec['destination']), 'origin': ('Откуда',spec['origin']), 'dates': ('Когда',spec['check_in']+' → '+spec['check_out']), 'adults': ('Гости',str(spec['adults'])+' взрослых'+(' · дети: '+', '.join(map(str,spec['children_ages'])) if spec['children_ages'] else '')), 'budget': ('Бюджет',str(spec['budget'])+' ₽' if spec['budget'] else 'Не задан')}
    chips = [{'key':key,'title':title,'value':value,'source':'assumption' if key in assumptions else 'explicit','reason':assumptions.get(key,'Указано в запросе.')} for key,(title,value) in labels.items()]
    if 'destination' in assumptions:
        next(chip for chip in chips if chip['key']=='destination')['value']='Предложу направления'
    if any(k in fields for k in ('transport','no_night','early_checkin','max_travel_hours','outbound_slot','inbound_slot')):
        chips.append({'key':'transport','title':'Дорога и заезд','value':'Поезд' if spec['transport']=='train' else 'Самолёт','source':'explicit','reason':'Условия дороги из запроса. Расписание демонстрационное, время и бюджет проверяются кодом.'})
    warnings = []
    if re.search(r'тепл\w* мор|купат',t): warnings.append('Температура моря на даты поездки не подтверждена. Климатические данные не являются прогнозом.')
    if re.search(r'перелет|рейс|поезд\b|трансфер|час\w* в пути',t): warnings.append('Расписание и трансферы моделируются для демонстрации. Состыковки проверяет код; это не реальные билеты.')
    from backend.infrastructure.hotel_provider import provider
    if spec['destination'] and not provider.list_hotels(spec['destination']): warnings.append('Для этого направления пока не удалось найти отели. Можно выбрать другое место.')
    return {'status':'ready','spec':spec,'chips':chips,'questions':questions,'warnings':warnings,'parser':'local_rules'}

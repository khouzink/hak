"""Application orchestration using a replaceable catalogue, without UI dependencies."""
import re
import os
from datetime import date,timedelta
from backend.domain.journey import JourneySpec
from backend.domain.errors import Conflict
from backend.domain.hotel_planner import rank_hotels
from backend.infrastructure.hotel_provider import provider,NOTICE


def recommend(spec:JourneySpec,selected_id=None):
    if spec.children_age_unknown:
        raise Conflict('Укажи возраст ребёнка перед расчётом поездки: он влияет на условия и стоимость.')
    inventory=provider.list_hotels(spec.destination)
    if 'hotel' in spec.locked and selected_id:inventory=[h for h in inventory if h['id']==selected_id]
    result=rank_hotels(spec,inventory,provider.version)
    if selected_id and not any(h['id']==selected_id for h in result['offers']+result['alternatives']):
        candidate=rank_hotels(spec,[h for h in inventory if h['id']==selected_id],provider.version)['offers']
        result['alternatives'].extend(candidate)
    result['notice']=NOTICE
    result['warnings']=['Тишина конкретного номера и неперечисленные услуги не подтверждены. При особых требованиях смотри источники и неизвестные условия.']
    result['reason']=('Для этого направления пока не удалось найти отели. Попробуй выбрать другое место.' if not inventory else 'Нет вариантов, выполняющих все условия. Ни одно ограничение не было ослаблено автоматически.' if not result['offers'] else None)
    return result


def attach_recommendations(journey):
    result=recommend(JourneySpec.model_validate(journey['spec']),(journey.get('selected_hotel') or {}).get('id'))
    journey['recommendation']=result
    journey['hotels']=[{**h,'source_url':h.get('source_url',h['website']),'distance_km':None,'address':h['area'],'source_name':'Публичные сведения; модельный тариф','availability':'synthetic','rate':h['quote']['hotel_total']} for h in result['offers']+result['alternatives']]
    previous=journey.get('selected_hotel')
    journey['selected_hotel']=next((h for h in journey['hotels'] if previous and h['id']==previous['id']),None)
    journey['source_error']=result['reason']
    from backend.infrastructure.regional_catalog import find
    region=find(journey['spec']['destination'])
    journey['place']=({'name':region['name'],'country':region['country'],'timezone':region['timezone']} if region else {'name':journey['spec']['destination'],'country':'Россия','timezone':'Europe/Moscow'}) if result['scanned'] else None
    journey['trace']={'executor':'deterministic_code','llm_calls':0,'hotels_scanned':result['scanned'],'flights_scanned':result['flights_scanned'],'trains_scanned':result['trains_scanned'],'offers':len(result['offers']),'alternatives':len(result['alternatives']),'rejected':result['rejected'],'rates':'synthetic','source_mode':'bundled_public_snapshot'}
    return journey


def parse_local(text:str,current:dict|None=None):
    """Explicit non-LLM fallback. Extract only supported facts; retain original wishes."""
    t=text.casefold().replace('ё','е');fields={}
    if re.search(r'\bkazan\b',t):fields['destination']='Казань'
    english_budget=re.search(r'\bunder\s+(\d[\d ]*)\s*(?:rub|rubles|roubles)\b',t)
    if english_budget:fields.update(budget=int(english_budget[1].replace(' ','')),budget_unlimited=False)
    english_adults=re.search(r'\b(\d+)\s+adults?\b',t)
    if english_adults:fields['adults']=int(english_adults[1])
    english_dates=re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})(?:\s+(20\d{2}))?',t)
    if english_dates:
        month=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].index(english_dates[1])+1
        reference=date.fromisoformat(os.getenv('TODAY_OVERRIDE') or date.today().isoformat())
        year=int(english_dates[4]) if english_dates[4] else reference.year+(month<reference.month)
        fields.update(check_in=date(year,month,int(english_dates[2])).isoformat(),check_out=date(year,month,int(english_dates[3])).isoformat())
    for fragment,city in [('сочи','Сочи'),('сириус','Сириус'),('адлер','Адлер'),('казан','Казань'),('екатеринбург','Екатеринбург'),('хургад','Хургада'),('стамбул','Стамбул'),('антал','Анталья'),('москв','Москва'),('санкт-петербург','Санкт-Петербург'),('петербург','Санкт-Петербург'),('питер','Санкт-Петербург'),('калининград','Калининград'),('шарм','Шарм-эль-Шейх'),('дуба','Дубай'),('мальдив','Мальдивы'),('байкал','Байкал')]:
        if fragment in t:
            if re.search(r'из\s+\w*'+fragment,t):fields['origin']=city
            else:fields['destination']=city
    money=re.search(r'(?:до|бюджет|за|максимум)\s*(\d[\d ]*(?:[.,]\d+)?)\s*(тыс\.?|т\.р\.|к\b|руб|₽)',t)
    if money:
        fields['budget']=round(float(money[1].replace(' ','').replace(',','.'))*(1000 if money[2].startswith(('тыс','т.','к')) else 1))
        fields['budget_unlimited']=False
    adults=re.search(r'(\d+)\s*взросл',t)
    if adults:fields['adults']=int(adults[1])
    elif re.search(r'вдвоем|двое взрослых',t):fields['adults']=2
    elif re.search(r'еду один|еду одна|один взросл',t):fields['adults']=1
    children=re.findall(r'(?:ребен\w*|сын\w*|доч\w*)\s*(\d{1,2})\s*(?:лет|год)',t)
    two_children=re.search(r'детьми\s+(\d{1,2})\s+и\s+(\d{1,2})\s+лет',t)
    if two_children:children=list(two_children.groups())
    if children:fields['children_ages']=[int(a) for a in children]
    if 'без детей' in t:fields['children_ages']=[]
    iso=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',t)
    if len(iso)>=2:fields.update(check_in=iso[0],check_out=iso[1])
    months={'январ':1,'феврал':2,'март':3,'апрел':4,'мая':5,'июн':6,'июл':7,'август':8,'сентябр':9,'октябр':10,'ноябр':11,'декабр':12}
    interval=re.search(r'(?:с\s*)?(\d{1,2})\s*(?:по|[-–—])\s*(\d{1,2})\s*([а-я]+)(?:\s+(20\d{2}))?',t)
    if interval:
        month=next((v for k,v in months.items() if interval[3].startswith(k)),None)
        if month:
            reference = date.fromisoformat(os.getenv('TODAY_OVERRIDE') or date.today().isoformat())
            year=int(interval[4]) if interval[4] else reference.year+(month<reference.month)
            fields.update(check_in=date(year,month,int(interval[1])).isoformat(),check_out=date(year,month,int(interval[2])).isoformat())
    if not interval and len(iso)<2:
        single=re.search(r'(?:с\s+)?(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|мая|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)(?:\s+(20\d{2}))?',t)
        if single:
            month=next(v for k,v in months.items() if single[2].startswith(k))
            reference=date.fromisoformat(os.getenv('TODAY_OVERRIDE') or date.today().isoformat())
            year=int(single[3]) if single[3] else reference.year+(month<reference.month)
            start=date(year,month,int(single[1]))
            nights=re.search(r'на\s+(\d{1,2})\s+ноч',t)
            fields.update(check_in=start.isoformat(),check_out=(start+timedelta(days=int(nights[1]) if nights else 7)).isoformat())
    if current and ('на два дня позже' in t or 'на 2 дня позже' in t):
        for key in ('check_in','check_out'):fields[key]=(date.fromisoformat(current[key])+timedelta(days=2)).isoformat()
    if any(w in t for w in ['тихо','спокой','тишин']):fields['mood']='Спокойствие'
    if any(w in t for w in ['романт','вдвоем','медовый месяц']):fields.setdefault('mood','Романтика')
    if re.search(r'на поезде|поездом|ночного поезда|\bпоезд\b',t):fields['transport']='train'
    elif re.search(r'самолет|перелет|летим|рейс',t):fields['transport']='air'
    if re.search(r'без ночн|не ночью',t):fields.update(no_night=True,outbound_slot='day',inbound_slot='day')
    if 'можно ночью' in t:fields['no_night']=False
    if re.search(r'ранний заезд|после ночного поезда',t):fields['early_checkin']=True
    hours=re.search(r'(?:до|максимум|не больше)\s*(\d+(?:[.,]\d+)?)\s*час',t)
    if hours:fields['max_travel_hours']=float(hours[1].replace(',','.'))
    elif re.search(r'без долг\w* перелет',t):fields['max_travel_hours']=5.0
    late=re.search(r'(?:поздний выезд|выезд до)\s*(?:до\s*)?(\d{1,2})',t)
    if late and 12<=int(late[1])<=23:fields['late_checkout']=int(late[1])
    for phrase,slot in [('утрен','morning'),('утром','morning'),('дневн','day'),('вечерн','evening'),('ночной рейс','night')]:
        if phrase in t:fields['inbound_slot' if 'обратн' in t else 'outbound_slot']=slot
    if current:
        shift=re.search(r'(?:сдвинь|перенеси).*?(\d+)\s*дн',t)
        if shift:
            delta=int(shift[1])*(-1 if 'раньше' in t else 1)
            for key in ('check_in','check_out'):fields[key]=(date.fromisoformat(current[key])+timedelta(days=delta)).isoformat()
    if fields.get('budget') and re.search(r'за ночь|в сутки',t):fields['nightly_budget']=fields.pop('budget');fields.pop('budget_unlimited',None)
    stars=re.search(r'([1-5])\s*(?:звезд|звёзд|\*)',t)
    if stars:fields['min_stars']=int(stars[1])
    if 'пятизвезд' in t:fields['min_stars']=5
    if 'четырехзвезд' in t:fields['min_stars']=4
    if re.search(r'дешевле.*(?:рейс|перелет)|(?:рейс|перелет).*дешевле',t):fields['outbound_slot']='evening'
    return fields


def local_turn(text:str,journey:dict,allow_model_prices=True):
    hotel=journey.get('selected_hotel')
    if re.search(r'сэконом|подешевле',text,re.I) and not re.search(r'не\s+(?:нужно\s+|надо\s+)?(?:сэконом|эконом)',text,re.I):
        unchanged={'spec_patch':{},'add_items':[],'source':'rule_replan'}
        if not allow_model_prices:
            return {**unchanged,'answer':'Не могу сравнить цены: источник реальных тарифов не подключён.'}
        if not hotel or not hotel.get('quote'):
            return {**unchanged,'answer':'Сначала выбери вариант поездки, чтобы сравнить стоимость.'}
        spec=JourneySpec.model_validate(journey['spec'])
        if 'hotel' in spec.locked:
            return {**unchanged,'answer':'Отель закреплён. Сними закрепление, если хочешь сравнить другие варианты.'}
        if re.search(r'утренн|утром',text,re.I) and spec.outbound_slot!='morning':
            return {**unchanged,'answer':'Сейчас выбран не утренний рейс. Сначала выбери утренний рейс, который нужно сохранить.'}
        result=recommend(spec)
        candidates=result['offers']+result['alternatives']
        cheaper=[o for o in candidates if o['quote']['total']<hotel['quote']['total']]
        if not cheaper:
            return {**unchanged,'answer':'С сохранением текущего рейса более дешёвого подходящего варианта не найдено.'}
        target=min(cheaper,key=lambda o:(o['quote']['total'],o['id']))
        return {**unchanged,'target_hotel_id':target['id'],'answer':'Нашёл более дешёвый модельный вариант с тем же рейсом. Изменения применятся только после подтверждения.'}
    question='?' in text or bool(re.search(r'^(а там|есть ли|можно ли|какие|что с|расскажи)',text,re.I))
    is_date_shift='на два дня позже' in text.casefold() or 'на 2 дня позже' in text.casefold()
    if hotel and question and not is_date_shift:
        if re.search(r'тихо|тишин|отзыв|шум',text,re.I):
            return {'answer':'Проверенных отзывов и замеров шума для этого отеля нет. Не могу подтвердить тишину конкретного номера. Уточни расположение номера у отеля; ссылки на источники есть в карточке.','spec_patch':{},'add_items':[],'source':'verified_catalog'}
        facts='\n'.join(f"{f['label']}: {f['value']}\nИсточник: {f.get('source','')}" for f in hotel.get('facts',[]))
        return {'answer':facts+'\nЭто все подтверждённые сведения в снимке. Неперечисленные услуги и условия неизвестны.','spec_patch':{},'add_items':[],'source':'verified_catalog'}
    patch=parse_local(text,journey['spec'])
    if any(w in text.casefold() for w in ['бассейн','собак','кошк','детский клуб','безбарьер']):patch['wishes']=(journey['spec']['wishes']+'\n'+text).strip()
    if patch:return {'answer':'Предлагаю обновить условия и пересчитать подбор. Изменения применятся только после подтверждения. Цены и наличие в этой версии моделируются.','spec_patch':patch,'add_items':[],**({'source':'rule_replan'} if re.search(r'собак|кошк|питом',text,re.I) else {})}
    hotel=journey.get('selected_hotel')
    if hotel and any(w in text.casefold() for w in ['отел','бассейн','дет','питом','собак','завтрак','питан']):
        facts=hotel.get('facts',[])
        answer='\n'.join(f"{f['label']}: {f['value']}\nИсточник: {f.get('source','')}" for f in facts)
        return {'answer':answer+'\nДругих подтверждённых сведений в локальной базе нет. Демо-тариф не гарантирует реальные условия.','spec_patch':{},'add_items':[]}
    if any(w in text.casefold() for w in ['дешев','бюджет','цена','стоим']):
        if not allow_model_prices:
            return {'answer':'Не могу сравнить цены: источник реальных тарифов не подключён.','spec_patch':{},'add_items':[]}
        result=recommend(JourneySpec.model_validate(journey['spec']))
        if result['offers']:
            cheapest=min(result['offers']+result['alternatives'],key=lambda o:o['quote']['total'])
            return {'answer':f"Самый доступный подходящий вариант: {cheapest['name']}. Полный модельный бюджет — {cheapest['quote']['total']} ₽, из них отель — {cheapest['quote']['hotel_total']} ₽. Выбрать его можно в разделе «Отели». Цены и наличие демонстрационные.",'spec_patch':{},'add_items':[]}
    return {'answer':'Сейчас работает локальный помощник с ограниченным разбором языка. Могу пересчитать даты, бюджет, состав гостей, проверить бассейн и условия с собакой. Например: «Бюджет до 80 тысяч» или «Сдвинь на два дня позже». Для произвольных вопросов предусмотрено подключение LLM. Брони сам не создаю.','spec_patch':{},'add_items':[]}

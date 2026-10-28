import json,re
from pathlib import Path
from backend.infrastructure.regional_catalog import regions
from backend.infrastructure.hotel_provider import provider
from backend.domain.hotel_planner import rank_hotels

def catalogue():
    return [{'id':'sochi','name':'Сочи','country':'Россия','timezone':'Europe/Moscow','count':4,'retrieved_at':'2026-10-26'},*[{'id':r['id'],'name':r['name'],'country':r['country'],'timezone':r['timezone'],'count':len(r['hotels']),'retrieved_at':r['retrieved_at']} for r in regions()]]

def inspire(spec):
    path=Path(__file__).resolve().parents[1]/'datasets/region_climate.json'
    climate=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'regions':{}}
    warm=bool(re.search(r'тепл|жар|купат',spec.wishes.casefold().replace('ё','е')));rows=[]
    for region in catalogue():
        changed=spec.model_copy(update={'destination':region['name']})
        weather=next((m for m in climate['regions'].get(region['id'],[]) if m['month']==spec.check_in.month),None)
        if warm and (not weather or weather['day_c'] is None or weather['day_c']<24):continue
        offers=rank_hotels(changed,provider.list_hotels(region['name']),provider.version)['offers']
        near=False
        if not offers and changed.max_travel_hours is not None:
            relaxed=changed.model_copy(update={'max_travel_hours':None})
            offers=rank_hotels(relaxed,provider.list_hotels(region['name']),provider.version)['offers']
            near=bool(offers)
        if not offers:continue
        cheapest=min(offers,key=lambda h:h['quote']['total'])
        duration=cheapest['package']['outbound']['duration_minutes']
        if near and duration<=changed.max_travel_hours*60:continue
        rows.append({**region,'total':cheapest['quote']['total'],'nights':cheapest['quote']['nights'],'weather':weather,'climate_period':climate.get('period'),'climate_source':climate.get('source'),'duration_minutes':duration,'near_match':near,'near_reason':f'Дорога по модели {duration//60} ч {duration%60} мин — дольше ограничения {changed.max_travel_hours:g} ч.' if near else None,'mode':'synthetic_transport_and_price','hotel':cheapest['name']})
    # Curated warm-sea places are considered before generic city destinations;
    # hard constraints above still apply to every candidate.
    featured={'el_gouna':0,'marsa_alam':1,'ras_al_khaimah':2} if warm else {}
    rows.sort(key=lambda r:(r['near_match'], featured.get(r['id'],99),r['total'],r['duration_minutes'],r['name']))
    chosen=[];country_count={};near_count=0
    for row in rows:
        if country_count.get(row['country'],0)>=2 or (row['near_match'] and near_count>=1):continue
        chosen.append(row);country_count[row['country']]=country_count.get(row['country'],0)+1
        near_count+=int(row['near_match'])
        if len(chosen)==3:break
    rows=chosen
    return {'options':rows,'notice':'Цены и время в пути модельные. Температура и осадки — историческое среднее за 2016–2025, не прогноз; температуру моря не подтверждают.','reason':None if rows else 'Нет направлений, где подтверждены все обязательные условия. Можно явно изменить требования.'}

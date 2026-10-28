"""Open hotel facts with explicit unknowns. Scenario tariffs are not OSM facts."""
import json
from functools import lru_cache
from pathlib import Path
from backend.infrastructure.live_sources import safe_url
PATH=Path(__file__).resolve().parents[1]/'datasets/regions.json'

@lru_cache(maxsize=4)
def _read(stamp):
    return json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {'regions':[]}

def regions():return _read(PATH.stat().st_mtime_ns if PATH.exists() else 0)['regions']

def find(destination):
    aliases={'питер':'санкт-петербург','saint petersburg':'санкт-петербург','kazan':'казань','istanbul':'стамбул','hurghada':'хургада','dubai':'дубай','шарм':'шарм-эль-шейх','el gouna':'эль-гуна','marsa alam':'марса-алам','ras al khaimah':'рас-эль-хайма'}
    normalized=destination.strip().casefold()
    normalized=aliases.get(normalized,normalized)
    return next((r for r in regions() if r['name'].casefold()==normalized or r['id']==normalized),None)

def hotels(destination):
    region=find(destination)
    if not region:return []
    result=[]
    for row in region['hotels']:
        tags=row['tags'];url=row['source_url']
        def flag(key):return True if tags.get(key)=='yes' else False if tags.get(key)=='no' else None
        facts=[{'label':'Название и расположение','value':row['name'],'source':url,'checked_at':region['retrieved_at'],'kind':'public_fact'}]
        district=row.get('nominatim_district') or {}
        if district.get('name') and district.get('source_url'):
            facts.append({'label':'Район по OpenStreetMap','value':district['name'],'source':district['source_url'],'checked_at':region['retrieved_at'],'kind':'public_fact'})
        labels={'swimming_pool':'Бассейн','pets':'Питомцы','wheelchair':'Доступность','internet_access':'Интернет','stars':'Звёзды'}
        for key,label in labels.items():
            if key in tags:facts.append({'label':label,'value':tags[key],'source':url,'checked_at':region['retrieved_at'],'kind':'public_fact'})
        result.append({'id':row['id'],'name':row['name'],'district':district.get('name'),'area':', '.join(filter(None,[region['name'],district.get('name'),tags.get('addr:street'),tags.get('addr:housenumber')])),'stars':tags.get('stars'),'base_night':5000,'family':None,'pool':flag('swimming_pool'),'pets':flag('pets'),'accessible':flag('wheelchair'),'meal':'Неизвестно','moods':[],'website':safe_url(tags.get('website') or tags.get('contact:website')) or url,'facts':facts,'tradeoff':'OSM подтверждает только перечисленные сведения. Цена 5 000 ₽ за базовую ночь — единая модель расчёта, не тариф отеля. Удобства и условия нужно уточнить.','source_url':url,'latitude':row['latitude'],'longitude':row['longitude'],'region_id':region['id'],'timezone':region['timezone'],'geo':{'latitude':row['latitude'],'longitude':row['longitude'],'elevation_m':None,'limitation':'Отсутствие тега не означает отсутствие услуги. Рельеф здесь не проверен.','source_url':url,'elevation_source':'https://open-meteo.com/en/docs/elevation-api','retrieved_at':region['retrieved_at'],'attribution':'© OpenStreetMap contributors, ODbL'}})
    return result

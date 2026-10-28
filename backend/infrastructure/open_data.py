"""Read-only bundled OSM + terrain evidence. No network in the request path."""
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def snapshot():
    path = Path(__file__).resolve().parents[1] / 'datasets' / 'sochi_open.json'
    if not path.exists(): return {'hotels':[], 'attribution':'Open data snapshot unavailable'}
    return json.loads(path.read_text(encoding='utf-8'))

# Reviewed object identities; no fuzzy match that could attach another hotel's facts.
LINKS = {'sochi-park':'way/277803906','mercure-sochi':'way/201474331','azimut-vinogradnaya':'way/51764141'}

def enrich(hotel):
    data = snapshot()
    row = next((r for r in data['hotels'] if r['id']==LINKS.get(hotel['id'])), None)
    if row:
        hotel['geo'] = {key:row.get(key) for key in ('latitude','longitude','elevation_m','source_url')}
        hotel['geo'].update(retrieved_at=data['retrieved_at'], attribution=data['attribution'], elevation_source='https://open-meteo.com/en/docs/elevation-api', limitation='Высота рельефа в ячейке 90 м. Это не уклон маршрута и не проверка доступности для коляски.')
    return hotel

def summary():
    data=snapshot()
    return {k:v for k,v in data.items() if k!='hotels'} | {'osm_objects':len(data['hotels']), 'enriched_hotels':sum(any(r['id']==id for r in data['hotels']) for id in LINKS.values())}

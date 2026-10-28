"""Verified OSM points of interest and ORS walking-time matrix; no fabricated estimates."""
import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'datasets' / 'sochi_poi_matrix.json'

@lru_cache(maxsize=8)
def _load_snapshot(mtime_ns):
    if not PATH.exists():
        return {'status':'not_generated','places':[],'routes':[],'source':'OpenStreetMap / openrouteservice'}
    return json.loads(PATH.read_text(encoding='utf-8'))

def snapshot():
    return _load_snapshot(PATH.stat().st_mtime_ns if PATH.exists() else None)

def hotel_routes(hotel_id, category=None):
    data=snapshot()
    routes=[r for r in data.get('routes',[]) if r['hotel_id']==hotel_id and (category is None or r['category']==category)]
    return sorted(routes,key=lambda r:r['duration_s'])

def walking_evidence(hotel_id,category,max_minutes=15):
    routes=hotel_routes(hotel_id,category)
    if not routes:return None
    nearest=routes[0]
    return {'within_limit':nearest['duration_s']<=max_minutes*60,'nearest':nearest,'verified':snapshot().get('status')=='verified' and nearest.get('verified',False),'source':snapshot().get('source'),'calculated_at':snapshot().get('calculated_at')}

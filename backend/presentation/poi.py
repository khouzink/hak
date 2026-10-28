from fastapi import APIRouter, Query
from backend.infrastructure.poi_matrix import snapshot, hotel_routes

router=APIRouter(prefix='/api/v1/poi',tags=['Verified walking distances'])

@router.get('/status')
def status():
    data=snapshot()
    return {'status':data.get('status','not_generated'),'calculated_at':data.get('calculated_at'),'hotels':len(data.get('hotels',[])),'places':len(data.get('places',[])),'routes':len(data.get('routes',[])),'source':data.get('source'),'notice':'No walking time is asserted unless routing provider returned a value.'}

@router.get('/hotels/{hotel_id}/nearby')
def nearby(hotel_id:str,category:str|None=None,limit:int=Query(10,ge=1,le=100)):
    if category not in (None,'museum','theatre','culture'):return {'detail':'Unknown category','routes':[]}
    return {'hotel_id':hotel_id,'routes':hotel_routes(hotel_id,category)[:limit],'verified':snapshot().get('status')=='verified','source':snapshot().get('source')}

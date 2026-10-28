from datetime import datetime,timezone,date
from uuid import uuid4
from backend.domain.journey import JourneySpec
from backend.domain.errors import Conflict
from backend.application.hotel_agent import recommend


def checkout(store,owner,journey,version,quote_id,accepted,travelers=None):
    existing=store.existing_order(owner,journey['id'],quote_id)
    if existing:return store.get_journey(owner,journey['id'])
    if not accepted:raise Conflict('Подтверди, что это тестовый заказ без списания денег')
    if journey['version']!=version:raise Conflict('Поездка изменилась. Обнови итоговую стоимость.')
    if journey.get('order',{}).get('status')=='confirmed':raise Conflict('В этой поездке уже есть заказ')
    spec=JourneySpec.model_validate(journey['spec'])
    if spec.check_in<date.today():raise Conflict('Нельзя оформить заказ на прошедшие даты')
    selected=journey.get('selected_hotel')
    if not selected:raise Conflict('Сначала выбери отель')
    result=recommend(spec,selected['id'])
    offer=next((o for o in result['offers']+result['alternatives'] if o['id']==selected['id']),None)
    if not offer or offer['quote']['id']!=quote_id:raise Conflict('Предложение изменилось или больше не соответствует условиям. Повтори подбор.')
    quote=offer['quote']
    travelers=travelers or []
    if len(travelers)!=spec.adults+len(spec.children_ages):raise Conflict('Укажи имя каждого путешественника; состав должен совпадать с поездкой')
    expected=[('adult',None)]*spec.adults+[('child',age) for age in spec.children_ages]
    clean=[]
    for person,(kind,age) in zip(travelers,expected):
        name=person.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise Conflict('Укажи имя путешественника, от 1 до 80 символов')
        if person.get('kind')!=kind or person.get('age')!=age:raise Conflict('Состав и возраст путешественников не совпадают с поездкой')
        clean.append({'name':name.strip(),'kind':kind,'age':age})
    if any(item.get('amount') is None for item in journey['items']):raise Conflict('В плане есть позиции без стоимости. Укажи сумму или 0 для бесплатного события перед подтверждением полного бюджета.')
    additional=sum(item.get('amount') or 0 for item in journey['items'])
    if not spec.budget_unlimited and quote['total']+additional>spec.budget:raise Conflict('С дополнительными расходами план превышает бюджет. Измени расходы или бюджет перед оформлением.')
    order={'id':'O-'+uuid4().hex[:12].upper(),'status':'confirmed','mode':'simulation','hotel_id':offer['id'],'hotel_name':offer['name'],'quote_id':quote_id,'check_in':spec.check_in.isoformat(),'check_out':spec.check_out.isoformat(),'rooms':quote['rooms'],'amount':quote['hotel_total'],'trip_total':quote['total']+additional,'currency':'RUB','created_at':datetime.now(timezone.utc).isoformat(),'notice':'Тестовый заказ. Деньги не списывались, реальная бронь у отеля не создавалась.','quote_snapshot':quote,'spec_snapshot':spec.model_dump(mode='json')}
    order.update(id='DEMO-'+uuid4().hex[:6].upper(),travelers=clean,package_snapshot=offer['package'],check_in=quote.get('hotel_check_in',order['check_in']),check_out=quote.get('hotel_check_out',order['check_out']))
    journey.update(order=order,version=version+1)
    store.confirm_order(owner,journey,order,version)
    return store.get_journey(owner,journey['id'])

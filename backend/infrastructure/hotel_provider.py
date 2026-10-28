"""Replaceable catalogue port. Bundled facts are separated from scenario tariffs."""
from typing import Protocol
from copy import deepcopy
from backend.infrastructure.open_data import enrich

CATALOG_VERSION='sochi-2026-10-26-v2'
NOTICE='Демо-тарифы и наличие для хакатона. Это не предложение реального бронирования.'

class HotelProvider(Protocol):
    version:str
    def list_hotels(self,destination:str)->list[dict]: ...


def fact(label,value,url):
    return {'label':label,'value':value,'source':url,'checked_at':'2026-10-25','kind':'public_fact'}


HOTELS=[
 {'id':'sochi-park','name':'Сочи Парк Отель','area':'Сириус','stars':None,'base_night':6500,'family':True,'pool':True,'pets':None,'accessible':None,'meal':'Завтрак','moods':['Драйв','Приключение'],
  'website':'https://sochiparkhotel.ru/','facts':[fact('Для детей','Игровые пространства и детские клубы','https://sochiparkhotel.ru/infrastructure/for-children/'),fact('Бассейны','Часть открытых бассейнов подогревается','https://sochiparkhotel.ru/vse-vklyucheno/')],
  'tradeoff':'Тишина конкретного номера не подтверждена; уточни расположение номера у отеля.'},
 {'id':'mercure-sochi','name':'Mercure Сочи Центр','area':'Центральный Сочи','stars':'4','base_night':8500,'family':None,'pool':False,'pets':True,'accessible':None,'meal':'Завтрак','moods':['Романтика','Перезагрузка'],
  'website':'https://accor.ru/sochi/mercure-sochi-center/','facts':[fact('Бассейн','Собственного бассейна нет; условия посещения соседнего Pullman зависят от категории номера','https://accor.ru/sochi/mercure-sochi-center/'),fact('Питомцы','Допускаются собаки до 20 кг, услуга платная','https://accor.ru/sochi/mercure-sochi-center/')],
  'tradeoff':'Бассейн соседнего отеля не считается собственным. Ограничение по собаке — до 20 кг.'},
 {'id':'azimut-vinogradnaya','name':'AZIMUT Парк Отель Виноградная Сочи','area':'Сочи, ул. Виноградная, 101/1','stars':None,'base_night':7200,'family':None,'pool':True,'pets':None,'accessible':None,'meal':'Завтрак','moods':['Спокойствие','Перезагрузка'],
  'website':'https://sochi-art.azimuthotels.com/','facts':[fact('Спа','Крытый и открытый подогреваемые бассейны; условия доступа уточняются отдельно','https://sochi-art.azimuthotels.com/services/spa')],
  'tradeoff':'Включение спа в реальный тариф не подтверждено; уточни условия у отеля.'},
 {'id':'mantera-congress','name':'Mantera Resort & Congress','area':'Имеретинская бухта','stars':None,'base_night':11000,'family':True,'pool':True,'pets':None,'accessible':None,'meal':'Завтрак','moods':['Спокойствие','Романтика'],
  'website':'https://manteracongress.ru/','facts':[fact('Бассейны','Открытый подогреваемый и крытый бассейны работают круглый год','https://manteracongress.ru/imeretinskiy-otel-s-basseynom'),fact('Сезонность','Детский бассейн и мини-аквапарк: сезон 05.06–30.09.2026','https://manteracongress.ru/imeretinskiy-otel-s-basseynom')],
  'tradeoff':'Детский бассейн и мини-аквапарк сезонные; в ноябре их не обещаем.'},
]


class BundledHotelProvider:
    version=CATALOG_VERSION
    def list_hotels(self,destination):
        # Deliberately finite coverage, never silently change the user's city.
        if destination.strip().casefold() not in {'сочи','большой сочи','адлер','сириус','sochi'}:
            from backend.infrastructure.regional_catalog import hotels
            return hotels(destination)
        return [enrich(h) for h in deepcopy(HOTELS)]


provider:HotelProvider=BundledHotelProvider()

"""Consistent error codes without changing the established `detail` field."""
import json
import logging
import sqlite3
try:
    import psycopg
except ImportError:
    psycopg = None

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.domain.errors import Conflict, JourneyNotFound

log=logging.getLogger('uno.errors')
STATUS_CODES={400:'invalid_request',401:'unauthorized',403:'forbidden',404:'not_found',
              409:'conflict',413:'request_too_large',422:'validation_error',
              429:'rate_limited',502:'provider_invalid_response',503:'service_unavailable',504:'provider_timeout'}


def error_response(detail,code,status,headers=None):
    return JSONResponse({'detail':detail,'code':code},status_code=status,headers=headers)


def install_error_handlers(app):
    @app.exception_handler(Conflict)
    async def conflict(_request:Request,error:Conflict):
        return error_response(str(error),error.code,409)

    @app.exception_handler(JourneyNotFound)
    async def not_found(_request:Request,_error:JourneyNotFound):
        return error_response('Поездка не найдена в этой сессии.','journey_not_found',404)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request:Request,error:sqlite3.Error):
        log.warning('Storage failure: %s',type(error).__name__)
        return error_response('Хранилище временно недоступно. Повтори попытку позже.','storage_unavailable',503,{'Retry-After':'1'})

    if psycopg:
        app.add_exception_handler(psycopg.Error, storage_error)

    @app.exception_handler(HTTPException)
    async def http_error(_request:Request,error:HTTPException):
        return error_response(error.detail,STATUS_CODES.get(error.status_code,'http_error'),error.status_code,error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request:Request,error:RequestValidationError):
        response=await request_validation_exception_handler(request,error)
        payload=json.loads(response.body)
        payload['code']='validation_error'
        return JSONResponse(payload,status_code=response.status_code)

    @app.exception_handler(RecursionError)
    async def nested(_request:Request,_error:RecursionError):
        return error_response('Слишком сложная структура запроса.','invalid_request',400)

    @app.exception_handler(ValueError)
    async def invalid(_request:Request,_error:ValueError):
        return error_response('Проверь даты, возраст и параметры поездки.','invalid_parameters',409)

    @app.exception_handler(KeyError)
    async def unexpected_key(_request:Request,error:KeyError):
        log.error('Unexpected key missing: %s',type(error).__name__)
        return error_response('Не удалось обработать запрос. Попробуй позже.','internal_error',500)

    @app.exception_handler(Exception)
    async def unexpected(_request:Request,error:Exception):
        log.error('Unexpected failure: %s',type(error).__name__)
        return error_response('Не удалось обработать запрос. Попробуй позже.','internal_error',500)

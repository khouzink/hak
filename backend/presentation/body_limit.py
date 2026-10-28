"""Bound HTTP request bodies before JSON parsing, including streamed requests."""
from fastapi.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes=1048576):
        self.app=app
        self.max_bytes=max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        chunks=[]
        total=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':
                return
            chunk=message.get('body',b'')
            total+=len(chunk)
            if total>self.max_bytes:
                response=JSONResponse({'detail':'Запрос слишком большой. Максимальный размер — 1 МБ.','code':'request_too_large'},status_code=413)
                return await response(scope,receive,send)
            chunks.append(chunk)
            if not message.get('more_body',False):break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':b''.join(chunks),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)

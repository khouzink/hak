"""Read-only MCP Streamable HTTP JSON-RPC endpoint; tool discovery and calls.
No privileged mutations; production deployment should add auth before exposing publicly.
"""
import json
import os
import hmac
import time
from collections import deque
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from backend.flow.mcp_tools import FLOW_TOOLS, call as call_flow_tool
from backend.infrastructure.free_tools import TOOLS, execute_tool
from backend.infrastructure.product_store import ProductStore

router=APIRouter()
store=ProductStore()
_calls=deque()

@router.get('/mcp')
async def no_stream():
    return Response(status_code=405,headers={'Allow':'POST'})

@router.post('/mcp')
async def mcp(request:Request):
    origin=request.headers.get('origin')
    allowed=set(os.getenv('MCP_ALLOWED_ORIGINS','').split(','))|{str(request.base_url).rstrip('/')}
    if origin and origin not in allowed:
        return JSONResponse({'error':'Origin not allowed'},status_code=403)
    key=os.getenv('MCP_API_KEY','')
    if key and not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+key):
        return JSONResponse({'error':'Authentication required'},status_code=401)
    if os.getenv('MCP_REQUIRE_AUTH')=='1' and not key:
        return JSONResponse({'error':'MCP authentication not configured'},status_code=503)
    now=time.monotonic()
    while _calls and _calls[0]<now-60:_calls.popleft()
    if len(_calls)>=int(os.getenv('MCP_REQUESTS_PER_MINUTE','60')):
        return JSONResponse({'error':'Rate limit exceeded'},status_code=429,headers={'Retry-After':'60'})
    _calls.append(now)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>32768:return JSONResponse({'error':'Request too large'},status_code=413)
    try:
        body=json.loads(raw)
        if not isinstance(body,dict):raise ValueError('Invalid request')
        method=body.get('method'); request_id=body.get('id')
        if body.get('jsonrpc')!='2.0' or not isinstance(method,str):raise ValueError('Invalid JSON-RPC')
        if method.startswith('notifications/') and request_id is None:return Response(status_code=202)
        if request_id is None:raise ValueError('Missing id')
        if method=='initialize':
            result={'protocolVersion':'2025-03-26','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'uno-free-travel-tools','version':'1.0.0'}}
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':TOOLS+FLOW_TOOLS}
        elif method=='tools/call':
            params=body.get('params') or {}
            if not isinstance(params,dict):raise ValueError('Invalid params')
            try:
                name=params.get('name')
                if name in {t['name'] for t in FLOW_TOOLS}:data=call_flow_tool(name,params.get('arguments') or {})
                else:data=await execute_tool(name,params.get('arguments') or {},store)
                result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],'isError':False}
            except ValueError as exc:
                result={'content':[{'type':'text','text':str(exc)[:250]}],'isError':True}
            except Exception:
                result={'content':[{'type':'text','text':'Data provider unavailable; no invented result was substituted.'}],'isError':True}
        else:return {'jsonrpc':'2.0','id':request_id,'error':{'code':-32601,'message':'Method not found'}}
        return {'jsonrpc':'2.0','id':request_id,'result':result}
    except (ValueError,TypeError):
        return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}},status_code=400)

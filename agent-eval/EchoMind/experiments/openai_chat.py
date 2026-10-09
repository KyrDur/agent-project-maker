"""OpenAI-compatible Chat Completions transport for the existing text/tool contract.
Reference: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
"""
import json
import httpx
from anthropic.types import Message
from .providers import ProviderFailure, explicitly_unsupported_tools


def chat_messages(messages,system=None):
    output=[]
    if system:
        output.append({'role':'system','content':system})
    for message in messages:
        content=message['content']
        if isinstance(content,str):
            output.append({'role':message['role'],'content':content})
            continue
        blocks=[b.model_dump(mode='json') if hasattr(b,'model_dump') else b for b in content]
        text='\n'.join(b['text'] for b in blocks if b.get('type')=='text')
        if any(b.get('type') not in {'text','tool_use','tool_result'} for b in blocks):
            raise ProviderFailure('INVALID_RESPONSE')
        if message['role']=='assistant':
            calls=[{'id':b['id'],'type':'function','function':{'name':b['name'],
                    'arguments':json.dumps(b['input'],ensure_ascii=False,allow_nan=False)}} for b in blocks if b['type']=='tool_use']
            item={'role':'assistant','content':text or None}
            if calls:item['tool_calls']=calls
            output.append(item)
        else:
            if text:output.append({'role':'user','content':text})
            output.extend({'role':'tool','tool_call_id':b['tool_use_id'],'content':b['content']}
                          for b in blocks if b['type']=='tool_result')
    return output

class ChatCompletionClient:
    def __init__(self,config,key):
        self._config,self._key=config,key
        self._http=httpx.AsyncClient(timeout=config.timeout_seconds,trust_env=False,follow_redirects=False)
        self.messages=self

    async def create(self,**kwargs):
        body={'model':kwargs['model'],'temperature':kwargs['temperature'],
              self._config.completion_token_parameter:kwargs['max_tokens'],
              'messages':chat_messages(kwargs['messages'],kwargs.get('system')),'stream':False,'n':1,'store':False}
        if self._config.thinking_mode is not None:
            body['thinking'] = {'type': self._config.thinking_mode}
        if kwargs.get('tools'):
            body['tools']=[{'type':'function','function':{'name':t['name'],'description':t['description'],
                           'parameters':t['input_schema']}} for t in kwargs['tools']]
        if kwargs.get('tool_choice'):
            choice=kwargs['tool_choice']
            body['tool_choice']={'type':'function','function':{'name':choice['name']}}
        response=await self._http.post(self._config.base_url.rstrip('/')+'/chat/completions',
                                      headers={'Authorization':'Bearer '+self._key},json=body)
        if response.status_code>=400:
            if response.status_code in {400,422}:
                try:unsupported=explicitly_unsupported_tools(response.json())
                except ValueError:unsupported=False
                if unsupported:raise ProviderFailure('TOOL_CALL_UNSUPPORTED')
            raise ProviderFailure({401:'AUTH_FAILED',403:'AUTH_FAILED',404:'MODEL_NOT_FOUND',429:'RATE_LIMITED'}.get(response.status_code,'PROVIDER_ERROR'))
        if response.status_code!=200:
            raise ProviderFailure('PROVIDER_ERROR')
        data=response.json()
        if self._key in json.dumps(data,ensure_ascii=False,allow_nan=False):
            raise ProviderFailure('INVALID_RESPONSE')
        if (not isinstance(data,dict) or data.get('object')!='chat.completion'
                or not isinstance(data.get('id'),str) or not data['id']
                or not isinstance(data.get('model'),str) or not data['model']
                or not isinstance(data.get('choices'),list) or len(data['choices'])!=1):
            raise ProviderFailure('INVALID_RESPONSE')
        choice=data['choices'][0]
        message=choice.get('message',{})
        if (message.get('role')!='assistant' or choice.get('finish_reason') not in {'stop','length','tool_calls'}
                or message.get('refusal')):
            raise ProviderFailure('INVALID_RESPONSE')
        content=[]
        if isinstance(message.get('content'),str) and message['content'].strip():
            content.append({'type':'text','text':message['content']})
        elif message.get('content') is not None and not isinstance(message['content'],str):
            raise ProviderFailure('INVALID_RESPONSE')
        calls=message.get('tool_calls') or []
        if not isinstance(calls,list) or len(calls)>32:
            raise ProviderFailure('INVALID_RESPONSE')
        if (choice['finish_reason']=='tool_calls') != bool(calls):
            raise ProviderFailure('INVALID_RESPONSE')
        for call in calls:
            if call.get('type')!='function':raise ProviderFailure('INVALID_RESPONSE')
            args=json.loads(call['function']['arguments'])
            if not isinstance(args,dict):raise ProviderFailure('INVALID_RESPONSE')
            content.append({'type':'tool_use','id':call['id'],'name':call['function']['name'],'input':args})
        # Message is the internal contract only; no Anthropic request is made.
        return Message.model_validate({'id':data['id'],'type':'message','role':'assistant','model':data['model'],
                    'content':content,'stop_reason':'tool_use' if calls else 'end_turn','stop_sequence':None,
                    'usage':{'input_tokens':0,'output_tokens':0}})

    async def close(self):
        await self._http.aclose()

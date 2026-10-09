"""Anonymous browser identities select private stores, skills and memory vaults.

The cookie is a random bearer credential, never an artifact or a browser storage
pointer. Only its SHA256 directory name is persisted. Historical shared stores
are not migrated or exposed. One API worker owns the memory-only Provider keys.
"""
import asyncio
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import threading
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.requests import Request
from core.skill_loader import SkillManager
from .service import ExperimentService
from .store import JsonStore
from .retrieval_service import RetrievalService

request_service = ContextVar('anonymous_experiment_service', default=None)
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
PUBLIC_PROVIDER_HOSTS = frozenset({
    'api.deepseek.com', 'api.openai.com', 'api.anthropic.com',
    'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com',
    'dashscope-us.aliyuncs.com', 'api.moonshot.cn', 'api.moonshot.ai',
    'api.siliconflow.cn', 'api.siliconflow.com', 'open.bigmodel.cn',
    'api.minimax.chat', 'api.minimaxi.com', 'ark.cn-beijing.volces.com',
})

def public_provider_endpoint(config):
    url = urlsplit(config.base_url)
    if (url.scheme != 'https' or url.hostname not in PUBLIC_PROVIDER_HOSTS
            or url.port not in (None, 443) or url.username or url.password):
        raise ValueError('PUBLIC_PROVIDER_ENDPOINT_NOT_ALLOWED')

class WorkspaceRegistry:
    def __init__(self, root, skill_template, origin, secure=True, max_loaded=64):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.template = Path(skill_template)
        self.origin = origin.rstrip('/')
        if not self.origin.startswith('https://' if secure else 'http'):
            raise ValueError('Anonymous workspace requires an explicit public origin')
        self.secure = secure
        self.cookie = '__Host-echomind_workspace' if secure else 'echomind_workspace'
        self.services = {}
        self.lock = threading.RLock()
        self.max_loaded = max_loaded
        self.expensive = asyncio.Semaphore(2)

    @staticmethod
    def identity(token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return None
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    def known(self, token):
        identity = self.identity(token)
        return identity if identity and (self.root / identity / 'workspace.json').is_file() else None

    def create(self):
        with self.lock:
            if len(self.services) >= self.max_loaded:
                raise RuntimeError('WORKSPACE_CAPACITY_REACHED')
            token = secrets.token_urlsafe(32)
            identity = self.identity(token)
            directory = self.root / identity
            directory.mkdir(mode=0o700)
            shutil.copytree(self.template, directory / 'skills')
            # No raw cookie or model credential is written to disk.
            (directory / 'workspace.json').write_text(json.dumps({'version': 1}))
            return token, identity

    def get(self, identity):
        with self.lock:
            if identity not in self.services:
                if len(self.services) >= self.max_loaded:
                    raise RuntimeError('WORKSPACE_CAPACITY_REACHED')
                directory = self.root / identity
                manager = SkillManager(str(directory / 'skills'))
                manager.load_strict()
                service = ExperimentService(JsonStore(directory / 'artifacts'), manager)
                service.providers.endpoint_validator = public_provider_endpoint
                service.retrieval = RetrievalService(service)
                self.services[identity] = service
            return self.services[identity]

    def close(self):
        for service in self.services.values():
            service.providers._keys.clear()
            service.store.forbidden_values = ()
        self.services.clear()


class WorkspaceMiddleware:
    """Pure ASGI: request ContextVar also follows FastAPI's threadpool handlers."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        if path == '/healthz':
            return await JSONResponse({'status': 'ok'})(scope, receive, send)
        registry = getattr(scope['app'].state, 'workspaces', None)
        if registry is None:
            if path == '/experiments/workspace' and scope['method'] == 'GET':
                return await JSONResponse({'isolated': False})(scope, receive, send)
            return await self.app(scope, receive, send)
        # The public process does not expose API schemas or non-workspace routes.
        if not path.startswith('/experiments/'):
            return await JSONResponse({'detail': 'Not found'}, status_code=404)(scope, receive, send)
        request = Request(scope)
        origin = request.headers.get('origin')
        if ((origin is not None and origin != registry.origin)
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            return await JSONResponse({'detail': 'WORKSPACE_ORIGIN_REJECTED'}, status_code=403)(scope, receive, send)
        token = request.cookies.get(registry.cookie)
        identity = registry.known(token)
        try:
            if path == '/experiments/workspace' and scope['method'] == 'GET':
                created = identity is None
                if created:
                    token, identity = registry.create()
                registry.get(identity)
                response = JSONResponse({'isolated': True, 'created': created,
                                         'workspace_ref': identity, 'cookie_max_age_days': 90})
                response.set_cookie(registry.cookie, token, max_age=90*24*3600,
                                    httponly=True, secure=registry.secure, samesite='lax', path='/')
                response.headers['Cache-Control'] = 'no-store'
                return await response(scope, receive, send)
            if identity is None:
                return await JSONResponse({'detail': 'WORKSPACE_UNAVAILABLE'}, status_code=401)(scope, receive, send)
            service = registry.get(identity)
        except RuntimeError:
            return await JSONResponse({'detail': 'WORKSPACE_CAPACITY_REACHED'}, status_code=503)(scope, receive, send)
        context = request_service.set(service)
        async def private_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [(k,v) for k,v in message.get('headers', [])
                                      if k.lower() != b'cache-control'] + [(b'cache-control', b'no-store')]
            await send(message)
        try:
            expensive = scope['method'] == 'POST' and (
                path.endswith('/runs') or path.endswith('/retrieval-runs')
                or path.endswith('/index') or path.endswith('/test')
                or path.endswith('/test-tools') or path.endswith('/retrieval-rewrite-preview')
                or path.endswith('/chat-turns') or path.endswith('/retrieval-repeats'))
            if expensive:
                if registry.expensive.locked():
                    return await JSONResponse({'detail': 'WORKSPACE_BUSY'}, status_code=429)(scope, receive, send)
                async with registry.expensive:
                    await self.app(scope, receive, private_send)
            else:
                await self.app(scope, receive, private_send)
        finally:
            request_service.reset(context)

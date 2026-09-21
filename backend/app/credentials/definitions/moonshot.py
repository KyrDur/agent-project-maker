"""Moonshot / Kimi API key (OpenAI-compatible chat API)."""

from __future__ import annotations

from app.credentials.authenticate import GenericAuth
from app.credentials.domain import CredentialDefinition, TestRequestSpec
from app.credentials.field import FieldDef, FieldKind

definition = CredentialDefinition(
    key="moonshot",
    display_name="Kimi / Moonshot",
    icon_id="moonshot",
    documentation_url="https://platform.moonshot.cn/docs",
    category="llm",
    properties=[
        FieldDef(
            name="api_key",
            display_name="API Key",
            kind=FieldKind.PASSWORD,
            required=True,
            type_options={"password": True},
        ),
    ],
    authenticate=GenericAuth(
        properties={
            "headers": {
                "Authorization": "=Bearer {{ $credentials.api_key }}",
            }
        }
    ),
    test=TestRequestSpec(
        request={
            "method": "GET",
            "url": "https://api.moonshot.cn/v1/models",
        },
        rules=[{"type": "responseCode", "value": [200]}],
    ),
)

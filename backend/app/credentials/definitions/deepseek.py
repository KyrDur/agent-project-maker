"""DeepSeek API key (OpenAI-compatible chat API)."""

from __future__ import annotations

from app.credentials.authenticate import GenericAuth
from app.credentials.domain import CredentialDefinition, TestRequestSpec
from app.credentials.field import FieldDef, FieldKind

definition = CredentialDefinition(
    key="deepseek",
    display_name="DeepSeek",
    icon_id="deepseek",
    documentation_url="https://api-docs.deepseek.com/",
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
            "url": "https://api.deepseek.com/v1/models",
        },
        rules=[{"type": "responseCode", "value": [200]}],
    ),
)

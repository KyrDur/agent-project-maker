"""Zhipu GLM API key (OpenAI-compatible chat API)."""

from __future__ import annotations

from app.credentials.authenticate import GenericAuth
from app.credentials.domain import CredentialDefinition, TestRequestSpec
from app.credentials.field import FieldDef, FieldKind

definition = CredentialDefinition(
    key="zhipu_glm",
    display_name="Zhipu GLM",
    icon_id="zhipu_glm",
    documentation_url="https://open.bigmodel.cn/dev/api",
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
            "url": "https://open.bigmodel.cn/api/paas/v4/models",
        },
        rules=[{"type": "responseCode", "value": [200]}],
    ),
)

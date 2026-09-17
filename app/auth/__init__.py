"""Phase 6 API-key authentication/authorization.

app.auth.models: the auth.api_keys ORM model.
app.auth.api_keys: key generation, hashing, and persistence (issue,
    revoke, rotate, list) — never a plaintext key stored, ever.
app.auth.dependencies: FastAPI dependencies resolving X-API-Key into a
    role/student identity for route authorization.
app.auth.manage_api_keys: the administrative provisioning CLI — the
    only way a key is ever created; there is no public endpoint for it.
"""

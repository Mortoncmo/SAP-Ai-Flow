# Security Policy

## Reporting

Do not put credentials, customer data, access tokens, or exploit details in a public issue. Report suspected vulnerabilities through the repository owner's private security channel and include the affected version, reproduction conditions, and impact.

## Automated Checks

CI runs:

- `pip-audit` against API runtime dependencies.
- `npm audit --omit=dev --audit-level=high` against Web runtime dependencies.
- `scripts/security_scan.py --include-build` against production sources and the generated Web bundle.
- Backend redaction tests covering request logs, validation errors, upstream exceptions, ChangeLog content, and external Provider payloads.

## Temporary Advisory Exception

### PYSEC-2026-311 / CVE-2026-45829

- Recorded: 2026-08-09
- Review by: 2026-09-09 or immediately when ChromaDB publishes a fixed release
- Affected dependency: ChromaDB 1.0.0 through 1.5.9
- Upstream status at review: 1.5.9 is the latest release and no fixed version is listed
- Advisory scope: unauthenticated code injection through the Chroma HTTP endpoint `/api/v2/tenants/{tenant}/databases/{db}/collections` when an attacker supplies a model repository with `trust_remote_code=true`

The application does not run a Chroma server, expose a Chroma port, mount Chroma's FastAPI routes, or accept model repository configuration. It uses `PersistentClient` or `EphemeralClient` in the API process and exposes only the application's controlled knowledge search endpoints. `tests/test_logging.py::test_chroma_http_api_is_not_exposed` is the regression gate for this deployment assumption.

CI ignores only `PYSEC-2026-311` while these controls remain true. The exception must be removed if a Chroma HTTP server is added, arbitrary embedding functions or model repositories become configurable, or a fixed ChromaDB release becomes available.

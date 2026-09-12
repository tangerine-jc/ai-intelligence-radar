# Security Policy

## Reporting

Report suspected vulnerabilities privately to the repository maintainer. Do not
open a public issue containing credentials, personal data, or exploit details.

## Credential Handling

- Keep `.env` and `config/users.json` local.
- Never commit API keys, tokens, webhook URLs, or user identifiers.
- Rotate any credential that may have appeared in a public repository or log.
- Use environment variables or a dedicated secret manager in production.

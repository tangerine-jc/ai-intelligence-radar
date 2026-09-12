# Configuration

## Environment Variables

Create a local `.env` from `.env.example`.

### LLM

| Variable | Required | Description |
| --- | --- | --- |
| `BLUE_CONVERSE_API_KEY` | Yes | API key used for model requests |
| `BLUE_CONVERSE_BASE_URL` | Yes | API base URL without a trailing slash |
| `BLUE_CONVERSE_APP_ID` | Depends on provider | Provider application identifier |
| `BLUE_CONVERSE_CHAT_ID` | No | Provider conversation identifier |

The legacy `BLUE_CONVERSE_API_TOKEN` variable is accepted as an alias for the API key.

### Feishu

| Variable | Required | Description |
| --- | --- | --- |
| `FEISHU_APP_ID` | Yes | Feishu application ID |
| `FEISHU_APP_SECRET` | Yes | Feishu application secret |
| `FEISHU_TOKEN` | No | Pre-issued tenant token |
| `FEISHU_JAPAN_CHAT_ID` | Optional | Japan group |
| `FEISHU_GAMING_CHAT_ID` | Optional | Gaming group |
| `FEISHU_NA_CHAT_ID` | Optional | North America group |
| `FEISHU_GLOBAL_AI_BUSINESS_CHAT_ID` | Optional | Global AI business group |
| `FEISHU_EXECUTIVE_CHAT_ID` | Optional | Executive group |
| `FEISHU_INNOVATION_CHAT_ID` | Optional | Innovation group |

### Audio

| Variable | Required | Description |
| --- | --- | --- |
| `MINIMAX_GROUP_ID` | Optional | Text-to-speech group ID |
| `MINIMAX_API_KEY` | Optional | Text-to-speech API key |
| `FFMPEG_PATH` | Optional | Override the `ffmpeg` executable path |
| `FFPROBE_PATH` | Optional | Override the `ffprobe` executable path |

Audio features are disabled automatically when Minimax credentials are absent.

## User Profiles

Real user information must not be committed. Copy the anonymous template:

```bash
cp config/users.example.json config/users.json
```

Each profile supports:

```json
{
  "name": "User One",
  "email": "user1@example.com",
  "keywords": ["AI", "automation"],
  "interests": "AI applications and automation"
}
```

Set `USER_PROFILES_FILE` to use a different local path.

## Secret Handling

- Keep `.env` and `config/users.json` local.
- Use deployment environment variables in production.
- Rotate credentials that have ever been committed or shared.
- Do not put Chat IDs, webhook URLs, or user identifiers in source files.

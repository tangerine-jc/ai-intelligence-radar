# Architecture

## Processing Flow

1. `NewsURLCrawler` discovers article URLs and stores them in SQLite.
2. `NewsContentExtractor` fetches article content, generates summaries, and stores normalized records.
3. `NewsDeduplicator` and `URLDeduplicator` prevent repeated processing and delivery.
4. `OptimizedNewsProcessor` and the application service perform LLM-based scoring and filtering.
5. `FeishuPodcastNewsBot` generates group content, optionally creates audio, and delivers messages.
6. `FeishuUserService` resolves users and sends direct messages when enabled.

## Module Layout

```text
src/application.py                    Main workflow orchestration
src/config.py                         Environment and source configuration
src/crawlers/url_crawler.py            URL discovery
src/crawlers/content_extractor.py      Article extraction and summaries
src/crawlers/backup_crawler.py         Fallback content generation
src/processing/news_deduplicator.py    Cross-run news deduplication
src/processing/url_deduplicator.py     URL-level deduplication
src/processing/optimized_news_processor.py  LLM filtering helpers
src/integrations/feishu_bot.py         Feishu group delivery and audio workflow
src/integrations/feishu_user_service.py  Feishu user lookup and direct messages
src/integrations/audio/minimax_tts.py  Optional text-to-speech client
```

## Runtime Data

Runtime state is deliberately excluded from source control:

```text
data/news_urls.db
data/news_content.db
data/news_deduplication.db
data/processed_data/processed_urls.json
audio_files/
logs/
```

The application creates these directories on demand.

## Extension Points

- Add sources in `Config.TARGET_SITES`.
- Add group definitions in `FeishuConfig.GROUP_CONFIGS`.
- Add prompt variants under `prompts/` while keeping fallback templates.
- Replace the LLM provider by updating `src/config.py` and the HTTP adapters.

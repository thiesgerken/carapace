---
name: web
description: >-
  Search the web and fetch page content. Use web_search to find information
  across the web via Brave Search. Use web_fetch to retrieve and extract
  readable content from a specific URL. Activate when the user asks to look
  something up online, find recent information, or read a webpage.
---

# Web Skill

Two tools for accessing web content: **web_search** (search engine queries) and **web_fetch** (fetch and extract a single URL).

Both tools are lightweight HTTP-based — they do **not** execute JavaScript. For JS-heavy pages, SPAs, or sites requiring login, these tools will not work.

## When to use which

| Goal                                                        | Tool                                               |
| ----------------------------------------------------------- | -------------------------------------------------- |
| Find pages, articles, or answers about a topic              | `web_search`                                       |
| Get recent news or developments                             | `web_search` with `--freshness`                    |
| Read/extract content from a known URL                       | `web_fetch`                                        |
| Get the text of a specific article, docs page, or blog post | `web_fetch`                                        |
| Fact-check a claim or find sources                          | `web_search`, then `web_fetch` on relevant results |

**Typical workflow**: search first to find relevant URLs, then fetch specific pages for full content.

## web_search

Search the web using a configurable backend (default: Brave Search API).

### Usage

```bash
# Basic search
uv run --directory /workspace/skills/web web_search 'pancake recipes'

# Limit results
uv run --directory /workspace/skills/web web_search -n 3 'python async tutorial'

# Filter by country and language
uv run --directory /workspace/skills/web web_search --country DE --language de 'Wetter Bremen'

# Recent results only
uv run --directory /workspace/skills/web web_search --freshness week 'AI news'
```

### Parameters

| Parameter                      | Description                                    |
| ------------------------------ | ---------------------------------------------- |
| `query` (positional, required) | Search query                                   |
| `-n`, `--count`                | Number of results to return (default: 5)       |
| `-b`, `--backend`              | Search backend to use (default: `brave`)       |
| `--country`                    | 2-letter ISO country code (e.g. `US`, `DE`)    |
| `--language`                   | ISO 639-1 language code (e.g. `en`, `de`)      |
| `--freshness`                  | Time filter: `day`, `week`, `month`, or `year` |

### Output

JSON object to stdout:

```json
{
  "query": "pancake recipes",
  "backend": "brave",
  "resultCount": 5,
  "results": [
    {
      "title": "Best Pancake Recipe",
      "url": "https://example.com/pancakes",
      "snippet": "Light and fluffy pancakes...",
      "age": "3 days ago"
    }
  ]
}
```

### Available backends

| Backend           | API key env var | Notes                                             |
| ----------------- | --------------- | ------------------------------------------------- |
| `brave` (default) | `BRAVE_API_KEY` | Brave Search API. Free tier: 1,000 queries/month. |

To add a new backend (e.g. SearXNG, Tavily), implement the `SearchBackend` protocol in `backends.py` and register it in `_BACKENDS`.

## web_fetch

Fetch a URL via HTTP GET and extract readable content. Converts HTML to markdown (default) or plain text using trafilatura.

### Usage

```bash
# Fetch and extract as markdown
uv run --directory /workspace/skills/web web_fetch 'https://example.com/article'

# Extract as plain text
uv run --directory /workspace/skills/web web_fetch -m text 'https://example.com/article'

# Limit output length
uv run --directory /workspace/skills/web web_fetch -c 5000 'https://example.com/long-article'
```

### Parameters

| Parameter                    | Description                                     |
| ---------------------------- | ----------------------------------------------- |
| `url` (positional, required) | URL to fetch (http or https only)               |
| `-m`, `--mode`               | Extraction mode: `markdown` (default) or `text` |
| `-c`, `--max-chars`          | Truncate output to this many characters         |
| `--user-agent`               | Override the User-Agent header                  |

### Output

JSON object to stdout:

```json
{
  "url": "https://example.com/article",
  "finalUrl": "https://example.com/article",
  "status": 200,
  "title": "Article Title",
  "contentType": "text/html",
  "extractMode": "markdown",
  "content": "# Article Title\n\nExtracted content in markdown...",
  "contentLength": 4523,
  "truncated": false
}
```

### Content handling

| Content-Type       | Behavior                                                  |
| ------------------ | --------------------------------------------------------- |
| `text/html`        | Main content extracted via trafilatura → markdown or text |
| `application/json` | Pretty-printed JSON                                       |
| `text/markdown`    | Returned as-is                                            |
| Other              | Raw body text                                             |

### Limits

- Timeout: 30 seconds
- Max redirects: 5
- Only `http://` and `https://` URLs are accepted
- Does **not** execute JavaScript — use for static pages, articles, docs
- Some sites may block the request or return CAPTCHAs

---
name: wikipedia
description: >-
  Suche und Lese-Funktion für Wikipedia-Artikel (Deutsch als Standard). Nutze diesen Skill, um nach Artikeln zu suchen oder deren Inhalt abzurufen. Unterstützt Deutsch und Englisch via --lang Flag.
metadata:
  carapace:
    network:
      domains:
        - de.wikipedia.org
        - en.wikipedia.org
    commands:
      - name: wiki-search
        command: uv run --directory /workspace/skills/wikipedia wiki-search
      - name: wiki-fetch
        command: uv run --directory /workspace/skills/wikipedia wiki-fetch
---

# Wikipedia Search & Fetch

Zwei Kommandos für Wikipedia-Zugriff über die offizielle API: **wiki-search** (Artikelsuche) und **wiki-fetch** (Artikelinhalt abrufen).

## Exposed Commands

- `wiki-search`: Sucht Wikipedia-Artikel über die offizielle API.
- `wiki-fetch`: Lädt den Klartext eines Wikipedia-Artikels.

## When to use

- Um nach einem Wikipedia-Artikel zu suchen (ohne direkten Link)
- Um den Textinhalt eines Artikels zu lesen
- Wenn du strukturierte Informationen aus der Wikipedia benötigst
- Für schnelle Faktenchecks oder Hintergrundinformationen

**Nicht verwenden für:**

- Sehr tiefgehende Analysen (Wikipedia ist ein Nachschlagewerk, keine Primärquelle)
- Hochspezialisierte technische Details (ggf. Fachliteratur bevorzugen)

## wiki-search

Suche nach Wikipedia-Artikeln:

```bash
# Suche auf Deutsch (Standard)
wiki-search 'Künstliche Intelligenz'

# Suche auf Englisch
wiki-search 'machine learning' --lang en

# Max 5 Treffer
wiki-search 'Quantencomputer' -n 5
```

| Parameter                          | Beschreibung                          |
| ---------------------------------- | ------------------------------------- |
| `query` (positional, erforderlich) | Suchbegriff                           |
| `--lang`                           | Sprachcode: `de` (Standard) oder `en` |
| `-n`, `--limit`                    | Max. Trefferzahl (Standard: 10)       |

Ausgabe: JSON mit Trefferliste:

```json
{
  "query": "Künstliche Intelligenz",
  "lang": "de",
  "resultCount": 10,
  "results": [
    {
      "title": "Künstliche Intelligenz",
      "snippet": "Zusammenfassung...",
      "pageid": 12345,
      "url": "https://de.wikipedia.org/wiki/K%C3%BCnstliche_Intelligenz"
    }
  ]
}
```

## wiki-fetch

Lade den Volltext eines Wikipedia-Artikels als Klartext:

```bash
# Deutschen Artikel lesen
wiki-fetch 'Künstliche Intelligenz'

# Englischen Artikel lesen
wiki-fetch 'Artificial intelligence' --lang en

# Inhalt auf 5000 Zeichen kürzen
wiki-fetch 'Philosophie' -c 5000
```

| Parameter                         | Beschreibung                               |
| --------------------------------- | ------------------------------------------ |
| `page` (positional, erforderlich) | Seitenname (Leerzeichen oder Unterstriche) |
| `--lang`                          | Sprachcode: `de` (Standard) oder `en`      |
| `-c`, `--max-chars`               | Inhalt auf diese Zeichenzahl kürzen        |

Ausgabe: JSON mit Artikelinhalt:

```json
{
  "pageid": 12345,
  "title": "Künstliche Intelligenz",
  "url": "https://de.wikipedia.org/wiki/K%C3%BCnstliche_Intelligenz",
  "lang": "de",
  "content": "Artikeltext als Klartext...",
  "contentLength": 45230,
  "truncated": false
}
```

## Edge cases

- **Seite nicht gefunden:** wiki-fetch gibt Fehlermeldung mit Vorschlägen für ähnliche Seiten
- **Mehrdeutige Seiten:** Erst wiki-search nutzen, dann wiki-fetch mit dem exakten Titel
- **Sprache:** Nur `de` und `en` sind in der Netzwerk-Konfiguration erlaubt

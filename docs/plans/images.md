# Plan: Image Support

> Status: planned. The primary goal is user image input via the web UI. The architecture is designed so agent-produced images (tool outputs, generated content) can be added later without structural changes.

## Problem

The current system is text-only end to end. User messages are plain strings, the WebSocket protocol carries no binary data, and the agent receives a single `str` as `user_input`. Vision-capable LLMs can analyze images, but there is no way to get images into the conversation.

## How pydantic-ai handles images

Pydantic AI (≥1.59) natively supports multimodal input. `agent.run()` accepts either a plain string or a `Sequence[UserContent]`, where `UserContent` can be `str`, `TextPart`, `BinaryContent`, `ImageUrl`, etc.

```python
from pydantic_ai.messages import BinaryContent

result = await agent.run(
    [
        "What's in this image?",
        BinaryContent(data=image_bytes, media_type="image/png"),
    ],
    deps=deps,
)
```

This means the backend integration is straightforward: construct a list instead of a string when images are present, and pass it through. No changes to the agent definition or tool signatures are required.

## Design

### Transport: REST upload + WebSocket reference

Images are uploaded via a REST endpoint and stored on disk per session. The WebSocket message then references images by ID rather than embedding base64.

```
Frontend                    Backend
   │                           │
   │  POST /api/sessions/{id}/images
   │  (multipart form)         │
   │ ─────────────────────────►│  → save to data/sessions/{id}/images/{uuid}.ext
   │  { images: [{id, url}] }  │
   │ ◄─────────────────────────│
   │                           │
   │  WS: { type: "message",  │
   │        content: "analyze  │
   │          this photo",     │
   │        images: ["uuid.png"] }
   │ ─────────────────────────►│  → load bytes, build [TextPart, BinaryContent, ...]
   │                           │  → agent.run(multimodal_prompt, ...)
```

Why REST instead of base64 in WebSocket:

- Avoids bloating WS frames (images can be several MB)
- Allows upload progress and retry without blocking the chat connection
- Reusable by other channels (Matrix, CLI) in the future
- Image serving endpoint enables display in history without re-uploading

### Storage: session-scoped files on disk

```
data/sessions/{session_id}/images/
  a1b2c3d4.png
  e5f6a7b8.jpeg
```

- UUID filenames prevent collisions and path traversal
- Session deletion already removes the entire session directory — images are cleaned up automatically
- No database needed; the filesystem is the index

The storage layer is a shared helper in `SessionManager`, used by both the user upload endpoint and agent tools that produce images. This avoids duplicating storage logic when agent image output is added later.

### Event format: image IDs alongside content

```yaml
---
role: user
content: "analyze this photo"
images:
  - a1b2c3d4.png
---
role: assistant
content: "The image shows a network topology diagram with..."
```

The `images` key is only present when images exist (backward compatible). The history endpoint returns raw events, so image IDs automatically flow to the frontend, which constructs full URLs from session ID + image ID.

## Implementation phases

### Phase 1 — Backend: image storage & REST endpoints

**`src/carapace/session/manager.py`** — shared image helpers:

- `save_image(session_id, data, media_type) → image_id` — validate media type (JPEG/PNG/GIF/WebP), generate UUID filename, write to `data/sessions/{id}/images/`
- `load_image(session_id, image_id) → (bytes, media_type)` — read back with media type detection from extension
- `image_path(session_id, image_id) → Path` — resolve path for serving

**`src/carapace/server.py`** — two new routes:

| Method | Path                                   | Purpose                                                                                       |
| ------ | -------------------------------------- | --------------------------------------------------------------------------------------------- |
| `POST` | `/api/sessions/{id}/images`            | Multipart upload; validates file type + size (20 MB cap); returns `{ images: [{ id, url }] }` |
| `GET`  | `/api/sessions/{id}/images/{image_id}` | Serve stored image with correct `Content-Type`; bearer auth                                   |

Session cleanup: no changes needed — existing `DELETE /api/sessions/{id}` removes the session directory.

### Phase 2 — Backend: WebSocket protocol extension

**`src/carapace/ws_models.py`**:

- Add `images: list[str] = []` to `UserMessage` (list of image IDs from upload)
- `parse_client_message()` already discriminates on the `type` field — no changes needed

### Phase 3 — Backend: agent integration

**`src/carapace/session/engine.py`**:

- `submit_message()` and `_run_turn()` accept and forward image IDs
- Before calling `run_agent_turn()`, load image bytes from disk via `load_image()`
- Record `images` in the user message event dict (only when non-empty)

**`src/carapace/agent/loop.py`**:

- `run_agent_turn()` accepts optional `images: list[tuple[bytes, str]]` (data + media_type)
- If images present: construct `[text, BinaryContent(...), BinaryContent(...), ...]`
- If no images: pass plain string (unchanged behavior)
- Pass to `agent.run(user_input=...)`

### Phase 4 — Frontend: upload & input UI

**`frontend/src/lib/api.ts`**:

- `uploadImages(sessionId, files): Promise<ImageRef[]>` — `FormData` upload with bearer auth
- `imageUrl(sessionId, imageId): string` — construct serving URL

**`frontend/src/lib/types.ts`**:

- Add `images?: string[]` to `UserMessage` client message type

**`frontend/src/components/chat-input.tsx`**:

- Attach button (paperclip/image icon) next to submit — opens file picker (`image/jpeg,image/png,image/gif,image/webp`)
- Drag-and-drop on the input area — accept dropped image files
- Paste support — detect `clipboardData.files` on `onPaste`
- Image preview strip below textarea — removable thumbnails of attached images
- Submit flow: if images attached, upload via REST first → collect IDs → send WS message with `{ type: "message", content, images }`; disable send during upload

**`frontend/src/components/chat-view.tsx`**:

- `handleSend()` orchestrates upload + WS send

### Phase 5 — Frontend: display

**`frontend/src/components/message.tsx`**:

- User messages with `images`: render `<img>` tags using `imageUrl()` helper
- Assistant messages with `images`: same rendering

**`frontend/src/components/markdown-content.tsx`**:

- Enable `<img>` rendering in `react-markdown` components config
- Required for tool results that reference images via markdown `![desc](url)`

**`frontend/src/components/chat-view.tsx`**:

- History loading: parse `images` field from events, pass to message components

## Architecture considerations for agent image output

The design above already accounts for agent-produced images. Here is how it extends without structural changes:

### Tool-produced images

Tools keep returning `str`. A tool that generates an image (screenshot, chart, render):

1. Calls the shared `save_image()` helper via `Deps` to store the image
2. Returns a markdown reference in its text result: `![chart](/api/sessions/{sid}/images/{id})`
3. `ToolResultInfo` stays unchanged — the existing `MarkdownContent` renderer displays the image

This requires:

- **`src/carapace/models.py`**: expose `save_image` access through `Deps` (add `SessionManager` ref or a bound closure)
- **`frontend/src/components/markdown-content.tsx`**: `<img>` rendering (already required for Phase 5)

No new protocol messages, no tool return type changes.

### Structured images in assistant responses

For cases where the LLM response itself should carry image references (not embedded in markdown), the `Done` WebSocket message gets an `images: list[str] = []` field. This enables the frontend to render agent images as first-class content (gallery layout, thumbnails) rather than relying on markdown parsing.

The assistant event in `events.yaml` mirrors this:

```yaml
---
role: assistant
content: "Here's the generated diagram:"
images:
  - f9e8d7c6.png
```

### Security sentinel

Images should be forwarded to the sentinel's shadow conversation as well. Image content could contain prompt injection text (steganographic or visible). The sentinel already receives the full user message — extending it with `BinaryContent` uses the same pydantic-ai mechanism. This is not a structural change, just passing images through.

## Files changed

### Backend

| File                              | Changes                                                          |
| --------------------------------- | ---------------------------------------------------------------- |
| `src/carapace/session/manager.py` | `save_image()`, `load_image()`, `image_path()` helpers           |
| `src/carapace/server.py`          | `POST` + `GET` image endpoints                                   |
| `src/carapace/ws_models.py`       | `UserMessage.images`, `Done.images`                              |
| `src/carapace/session/engine.py`  | `submit_message()`, `_run_turn()` accept images; event recording |
| `src/carapace/agent/loop.py`      | `run_agent_turn()` multimodal prompt construction                |
| `src/carapace/models.py`          | `Deps` — expose image storage for future tools                   |

### Frontend

| File                                           | Changes                                                    |
| ---------------------------------------------- | ---------------------------------------------------------- |
| `frontend/src/lib/api.ts`                      | `uploadImages()`, `imageUrl()`                             |
| `frontend/src/lib/types.ts`                    | `UserMessage.images`, `Done.images`                        |
| `frontend/src/components/chat-input.tsx`       | Attach button, drag-drop, paste, preview, upload-then-send |
| `frontend/src/components/chat-view.tsx`        | `handleSend()` with upload, history image handling         |
| `frontend/src/components/message.tsx`          | Render images in user + assistant bubbles                  |
| `frontend/src/components/markdown-content.tsx` | Enable `<img>` rendering                                   |

## Testing

1. **Unit**: `save_image()` / `load_image()` — valid/invalid media type, path traversal rejection
2. **Unit**: Image upload endpoint — valid file, wrong type, oversized, missing session
3. **Unit**: `run_agent_turn()` with images — verify `BinaryContent` construction
4. **Integration**: Upload → WS message → agent receives multimodal prompt
5. **Manual**: Attach image via button / drag / paste → send with text → image appears in chat
6. **Manual**: Reload page → images appear in history
7. **Manual**: Delete session → images removed from disk
8. **Lint**: `uvx ruff check src/`

## Open questions

- **Max images per message**: 5 seems reasonable for v1. Most LLMs have token limits on image inputs anyway. Make configurable?
- **Image resize on upload**: Should the server downsample large images to reduce LLM token cost, or pass through as-is and let the model handle it?
- **Matrix channel**: Can reuse `run_agent_turn()` multimodal support later. Matrix has native image message support (`m.image`). Defer to the channels plan.

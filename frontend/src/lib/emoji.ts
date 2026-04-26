import emojiRegex from "emoji-regex";

import { bundledEmojiCodepoints, emojiSet } from "./emoji.generated";

export { emojiSet };

type TextSegment = {
  kind: "text";
  value: string;
};

type EmojiSegment = {
  kind: "emoji";
  value: string;
  src: string;
};

export type EmojiTextSegment = TextSegment | EmojiSegment;

const bundledEmojiSet = new Set<string>(bundledEmojiCodepoints);

export function resolveBundledEmojiAsset(value: string): string | null {
  for (const candidate of getCodepointCandidates(value)) {
    if (bundledEmojiSet.has(candidate)) {
      return `/emoji/${candidate}.svg`;
    }
  }

  return null;
}

export function splitEmojiText(value: string): EmojiTextSegment[] {
  if (!value) {
    return [{ kind: "text", value }];
  }

  const segments: EmojiTextSegment[] = [];
  const pattern = emojiRegex();
  let lastIndex = 0;

  for (const match of value.matchAll(pattern)) {
    const emoji = match[0];
    const start = match.index ?? 0;
    const asset = resolveBundledEmojiAsset(emoji);

    if (start > lastIndex) {
      pushTextSegment(segments, value.slice(lastIndex, start));
    }

    if (asset) {
      segments.push({ kind: "emoji", value: emoji, src: asset });
    } else {
      pushTextSegment(segments, emoji);
    }

    lastIndex = start + emoji.length;
  }

  if (lastIndex === 0) {
    return [{ kind: "text", value }];
  }

  if (lastIndex < value.length) {
    pushTextSegment(segments, value.slice(lastIndex));
  }

  return segments;
}

function getCodepointCandidates(value: string): string[] {
  const exact = Array.from(
    value,
    (char) => char.codePointAt(0)?.toString(16) ?? "",
  )
    .filter(Boolean)
    .join("-")
    .toLowerCase();
  const withoutVariationSelectors = exact.replace(/-fe0f/g, "");

  return exact === withoutVariationSelectors
    ? [exact]
    : [exact, withoutVariationSelectors];
}

function pushTextSegment(segments: EmojiTextSegment[], value: string): void {
  if (!value) {
    return;
  }

  const previous = segments.at(-1);
  if (previous?.kind === "text") {
    previous.value += value;
    return;
  }

  segments.push({ kind: "text", value });
}

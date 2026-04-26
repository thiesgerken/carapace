"use client";

import Image from "next/image";

import { splitEmojiText } from "@/lib/emoji";
import { cn } from "@/lib/utils";

interface EmojiTextProps {
  text: string;
  className?: string;
  emojiClassName?: string;
}

export function EmojiText({
  text,
  className,
  emojiClassName,
}: EmojiTextProps) {
  const segments = splitEmojiText(text);

  return (
    <span className={className}>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <span key={`text-${index}`}>{segment.value}</span>;
        }

        return (
          <Image
            key={`emoji-${index}-${segment.src}`}
            className={cn("emoji-inline", emojiClassName)}
            src={segment.src}
            alt={segment.value}
            width={16}
            height={16}
            decoding="async"
            draggable={false}
            unoptimized
          />
        );
      })}
    </span>
  );
}

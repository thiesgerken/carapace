import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

export type TortoisePose = "pulse" | "munch" | "glass" | "think" | "walk" | "sleep";

// The logo's colours (public/icon.svg). The shell plates take theirs from globals.css, where the poses animate them.
const SHELL = "#236b86";
const SKIN = "#53b8c8";

// The pulse lights plate *i* a quarter cycle after plate *i - 1*.
const plateIndex = (i: number) => ({ "--plate": i }) as CSSProperties;

/**
 * The carapace tortoise as the chat's waiting mark, doing *pose*. Every pose shares one viewBox, so
 * switching poses never shifts the line; the motion lives in the `.tortoise-*` rules in globals.css.
 */
export function Tortoise({ pose, className }: { pose: TortoisePose; className?: string }) {
  return (
    <svg viewBox="6 -6 184 118" aria-hidden="true" data-pose={pose} className={cn("tortoise", `tortoise-${pose}`, className)}>
      {pose === "walk" && (
        <line className="ground stroke-border" x1="10" y1="106" x2="160" y2="106" strokeWidth="3" strokeDasharray="14 10" strokeLinecap="round" />
      )}
      {/* Legs pair up diagonally (leg-a, leg-b) so the walk is a trot. */}
      <path className="leg leg-a" fill={SHELL} d="M49 80 59 85 55 99H43L42 95Z" />
      <path className="leg leg-b" fill={SHELL} d="M100 81 111 84 119 98H106L99 93Z" />
      <g className="body">
        <path fill={SKIN} d="M31 77 13 85Q11 87 16 87L29 85Z" />
        {/* Drawn before the shell, so a retracted head disappears under it. */}
        <g className="head">
          <path fill={SKIN} d="M115 70Q126 69 132 58L134 53Q138 47 145 48Q157 49 158 59Q159 69 148 71L139 72Q131 86 116 89Z" />
          <circle fill="#163f50" cx="148" cy="56" r="2.2" />
        </g>
        <path fill={SHELL} d="M24 77C27 48 45 26 74 25C101 24 122 43 129 75L128 84Q107 94 75 94Q44 94 23 85Z" />
        {/* Clockwise from the left, the order the pulse lights them in. */}
        <path className="plate" style={plateIndex(0)} d="M50 39 62 57 54 76 32 76Q36 53 50 39Z" />
        <path className="plate" style={plateIndex(1)} d="M57 36Q75 26 93 34L101 44 91 56 69 55 55 43Z" />
        <path className="plate" style={plateIndex(2)} d="M103 40Q116 52 121 75L111 77 98 59 107 47Z" />
        <path className="plate" style={plateIndex(3)} d="M68 61 91 62 105 77 101 83 62 83 59 78Z" />
        <path fill={SKIN} d="M29 82 53 82 57 88Q42 87 29 82ZM61 88 104 88 107 84 121 81Q101 91 76 91Z" />
      </g>
      <path className="leg leg-b" fill={SKIN} d="M35 80 52 84 45 94 44 100Q44 104 40 104H28Q24 104 26 100L30 89Z" />
      <path className="leg leg-a" fill={SKIN} d="M102 80 119 80 121 92 128 100Q131 104 126 104H114Q111 104 109 100Z" />
      {pose === "munch" && (
        <g className="leaf">
          <path fill="#6bbf59" d="M161 74Q170 56 186 62Q178 82 161 74Z" />
          <path d="M162 73 182 63" stroke="#3f8a33" strokeWidth="1.4" fill="none" />
        </g>
      )}
      {pose === "think" && (
        <g className="fill-muted stroke-muted-foreground" strokeWidth="1">
          <circle cx="152" cy="38" r="2.5" />
          <circle cx="159" cy="28" r="4" />
          <g className="puff">
            <ellipse cx="170" cy="9" rx="17" ry="11" />
            <circle className="dot fill-muted-foreground stroke-none" cx="162" cy="9" r="2.4" />
            <circle className="dot fill-muted-foreground stroke-none" cx="170" cy="9" r="2.4" />
            <circle className="dot fill-muted-foreground stroke-none" cx="178" cy="9" r="2.4" />
          </g>
        </g>
      )}
      {pose === "glass" && (
        <g className="glass">
          <line x1="157" y1="74" x2="166" y2="62" stroke="#7a5230" strokeWidth="4" strokeLinecap="round" />
          <circle className="lens stroke-muted-foreground" cx="173" cy="52" r="11" strokeWidth="2.5" />
        </g>
      )}
      {pose === "sleep" && (
        <g className="fill-muted-foreground font-mono font-semibold" fontSize="18">
          <text className="z" x="126" y="44">z</text>
          <text className="z" x="138" y="32">z</text>
          <text className="z" x="150" y="20">Z</text>
        </g>
      )}
    </svg>
  );
}

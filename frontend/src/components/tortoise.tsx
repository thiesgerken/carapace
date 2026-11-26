import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

export type TortoisePose =
  | "pulse"
  | "munch"
  | "glass"
  | "book"
  | "hourglass"
  | "think"
  | "walk"
  | "turbo"
  | "snail"
  | "scribble"
  | "wrench"
  | "peek"
  | "sleep";

// The logo's colours (public/icon.svg). The shell plates take theirs from globals.css, where the poses animate them.
const SHELL = "#236b86";
const SKIN = "#53b8c8";
const EYE = "#163f50";
const WOOD = "#7a5230";
const PAPER = "#fbf8f0";
const PAPER_EDGE = "#9a8f7a";
const GRAPHITE = "#3b4a5a";
const SAND = "#e2b860";
const STEEL = "#8a96a3";

// Poses that trot: they share the leg, bob and ground motion in globals.css.
const WALKING = new Set<TortoisePose>(["walk", "turbo", "snail"]);

// The pulse lights plate *i* a quarter cycle after plate *i - 1*.
const plateIndex = (i: number) => ({ "--plate": i }) as CSSProperties;

const SQUIGGLE = "q1-2.5 2 0t2 0 2 0 2 0";

// What a pose holds or shows besides the tortoise itself, drawn on top of it.
const PROPS: Partial<Record<TortoisePose, ReactNode>> = {
  munch: (
    <g className="leaf">
      <path fill="#6bbf59" d="M161 74Q170 56 186 62Q178 82 161 74Z" />
      <path d="M162 73 182 63" stroke="#3f8a33" strokeWidth="1.4" fill="none" />
    </g>
  ),
  glass: (
    <g className="glass">
      <line x1="157" y1="74" x2="166" y2="62" stroke={WOOD} strokeWidth="4" strokeLinecap="round" />
      <circle className="lens stroke-muted-foreground" cx="173" cy="52" r="11" strokeWidth="2.5" />
    </g>
  ),
  book: (
    <g stroke={PAPER_EDGE} strokeWidth="1">
      <path fill="#8c3b3b" stroke="none" d="M172 66 156 63 156 90 172 92 188 90 188 63Z" />
      <path fill={PAPER} d="M172 64Q165 60 158 62L158 87Q165 85 172 89Z" />
      <path fill={PAPER} d="M172 64Q179 60 186 62L186 87Q179 85 172 89Z" />
      <path stroke="#b5ab96" strokeWidth="1.4" strokeLinecap="round" d="M161 68H169M161 73H169M161 78H167M175 68H183M175 73H183M175 78H181" />
      {/* The page that turns, over its resting copy. */}
      <path className="turning-page" fill="#fff" d="M172 64Q179 60 186 62L186 87Q179 85 172 89Z" />
    </g>
  ),
  hourglass: (
    <g className="hourglass">
      <rect fill={WOOD} x="165" y="54" width="22" height="4" rx="1.5" />
      <rect fill={WOOD} x="165" y="96" width="22" height="4" rx="1.5" />
      <path stroke={WOOD} strokeWidth="2" d="M167 58V96M185 58V96" />
      <path className="bulb stroke-muted-foreground" strokeWidth="1.5" d="M169 58 183 58Q183 70 177 77Q183 84 183 96L169 96Q169 84 175 77Q169 70 169 58Z" />
      <path className="sand-top" fill={SAND} d="M170.5 61 181.5 61Q180 71 176 76Q172 71 170.5 61Z" />
      <path className="sand-bottom" fill={SAND} d="M170 95 182 95Q180 86 176 84Q172 86 170 95Z" />
      <line className="stream" x1="176" y1="76" x2="176" y2="94" stroke={SAND} strokeWidth="1.4" />
    </g>
  ),
  think: (
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
  ),
  turbo: (
    <>
      <g className="flame">
        <path fill="#f08a24" d="M19 84Q8 73 -2 84Q8 95 19 84Z" />
        <path fill="#ffd34d" d="M17 84Q10 79 5 84Q10 89 17 84Z" />
      </g>
      <path className="speed-lines stroke-muted-foreground" strokeWidth="2.5" strokeLinecap="round" d="M8 46H20M6 58H16M10 70H18" />
    </>
  ),
  snail: (
    <g className="snail">
      <path fill="#d9c6a0" d="M6 106Q8 101 16 101L32 101Q36 101 37 96Q38 93 40 96L40 106Z" />
      <path d="M37.5 96 35.5 89M39.5 96 42 90" stroke="#d9c6a0" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="35.5" cy="89" r="1.4" fill={EYE} />
      <circle cx="42" cy="90" r="1.4" fill={EYE} />
      <circle cx="22" cy="93" r="9" fill="#c98b4a" />
      <path d="M22 93m-1 0a1.5 1.5 0 1 1 3 0a3.5 3.5 0 1 1-7 0a5.5 5.5 0 1 1 11 0" stroke={WOOD} strokeWidth="1.4" fill="none" />
    </g>
  ),
  scribble: (
    <>
      <rect fill={PAPER} stroke={PAPER_EDGE} strokeWidth="1.5" x="164" y="54" width="22" height="34" rx="2" />
      <g stroke={GRAPHITE} strokeWidth="1.6" strokeLinecap="round" fill="none">
        {/* pathLength 1 lets the CSS draw each line with a dash offset from 1 to 0. */}
        <path className="ink" pathLength={1} d={`M168 62${SQUIGGLE}`} />
        <path className="ink" pathLength={1} d={`M168 70${SQUIGGLE}`} />
        <path className="ink" pathLength={1} d={`M168 78${SQUIGGLE}`} />
      </g>
      <g className="pencil" strokeLinecap="round">
        <line x1="152" y1="69" x2="166" y2="63.6" stroke="#e9b949" strokeWidth="4" />
        <line x1="166" y1="63.6" x2="169.5" y2="62.2" stroke={GRAPHITE} strokeWidth="2.4" />
      </g>
    </>
  ),
  wrench: (
    <>
      <g className="wrench" stroke={STEEL} strokeLinecap="round" fill="none">
        <line x1="151" y1="70" x2="173" y2="58.5" strokeWidth="5" />
        <path d="M181.9 54.1A5 5 0 1 1 177.9 50.1" strokeWidth="4.5" />
      </g>
      <path className="clank stroke-muted-foreground" strokeWidth="2" strokeLinecap="round" d="M184 42 187 37M185 50 190 49M179 38 180 33" />
    </>
  ),
  sleep: (
    <g className="fill-muted-foreground font-mono font-semibold" fontSize="18">
      <text className="z" x="126" y="44">z</text>
      <text className="z" x="138" y="32">z</text>
      <text className="z" x="150" y="20">Z</text>
    </g>
  ),
};

/**
 * The carapace tortoise as the chat's waiting mark, doing *pose*. Every pose shares one viewBox, so
 * switching poses never shifts the line; the motion lives in the `.tortoise-*` rules in globals.css.
 */
export function Tortoise({ pose, className }: { pose: TortoisePose; className?: string }) {
  const walking = WALKING.has(pose);
  return (
    <svg
      viewBox="6 -6 184 118"
      aria-hidden="true"
      data-pose={pose}
      className={cn("tortoise", `tortoise-${pose}`, walking && "tortoise-walking", className)}
    >
      {walking && (
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
          <circle fill={EYE} cx="148" cy="56" r="2.2" />
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
      {PROPS[pose]}
    </svg>
  );
}

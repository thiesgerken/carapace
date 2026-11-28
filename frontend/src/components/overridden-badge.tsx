/** Marks a skill that skills/flake.nix adjusts with an override, in the sources list and on its card. */
export function OverriddenBadge({ label, hint }: { label: string; hint: string }) {
  return (
    <span className="rounded bg-info/10 px-1.5 text-[11px] font-normal text-info" title={hint}>
      {label}
    </span>
  );
}

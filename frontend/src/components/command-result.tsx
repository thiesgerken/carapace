"use client";

interface CommandResultViewProps {
  command: string;
  data: unknown;
}

export function CommandResultView({ command, data }: CommandResultViewProps) {
  if (command === "help" && isHelpData(data)) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-4 font-medium">Command</th>
              <th className="pb-1 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {data.commands.map((c) => (
              <tr key={c.command} className="border-b border-border/50">
                <td className="py-1 pr-4 font-mono text-xs">{c.command}</td>
                <td className="py-1 text-muted-foreground">{c.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (command === "rules" && Array.isArray(data)) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">ID</th>
              <th className="pb-1 pr-3 font-medium">Trigger</th>
              <th className="pb-1 pr-3 font-medium">Mode</th>
              <th className="pb-1 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {(
              data as Array<{
                id: string;
                trigger: string;
                mode: string;
                status: string;
              }>
            ).map((r) => (
              <tr key={r.id} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{r.id}</td>
                <td className="py-1 pr-3 text-xs">{r.trigger}</td>
                <td className="py-1 pr-3 text-xs">{r.mode}</td>
                <td className="py-1 text-xs">
                  <span
                    className={
                      r.status === "disabled"
                        ? "text-destructive"
                        : r.status === "always-on"
                          ? "text-green-600 dark:text-green-400"
                          : r.status === "activated"
                            ? "text-warning"
                            : "text-muted-foreground"
                    }
                  >
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (command === "verbose" && isVerboseData(data)) {
    return <p className="my-1 text-sm text-muted-foreground">{data.message}</p>;
  }

  if ((command === "disable" || command === "enable") && isMessageData(data)) {
    if (data.error)
      return <p className="my-1 text-sm text-destructive">{data.error}</p>;
    return <p className="my-1 text-sm text-muted-foreground">{data.message}</p>;
  }

  return (
    <pre className="my-2 rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function isHelpData(
  d: unknown,
): d is { commands: { command: string; description: string }[] } {
  return (
    !!d &&
    typeof d === "object" &&
    "commands" in d &&
    Array.isArray((d as { commands: unknown }).commands)
  );
}

function isVerboseData(d: unknown): d is { verbose: boolean; message: string } {
  return !!d && typeof d === "object" && "message" in d;
}

function isMessageData(d: unknown): d is { message?: string; error?: string } {
  return !!d && typeof d === "object";
}

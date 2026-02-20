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

  if (command === "usage" && isUsageData(data)) {
    return <UsageView data={data} />;
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

interface UsageBucket {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  input_audio_tokens: number;
  output_audio_tokens: number;
  cache_audio_read_tokens: number;
  requests: number;
}

interface UsagePayload {
  models: Record<string, UsageBucket>;
  categories: Record<string, UsageBucket>;
  total_input: number;
  total_output: number;
}

function isUsageData(d: unknown): d is UsagePayload {
  return !!d && typeof d === "object" && "models" in d && "categories" in d;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function UsageView({ data }: { data: UsagePayload }) {
  const allBuckets = [
    ...Object.values(data.models),
    ...Object.values(data.categories),
  ];
  const hasCache = allBuckets.some(
    (b) => b.cache_read_tokens || b.cache_write_tokens,
  );

  const isEmpty =
    Object.keys(data.models).length === 0 &&
    Object.keys(data.categories).length === 0;
  if (isEmpty) {
    return (
      <p className="my-1 text-sm text-muted-foreground">
        No token usage recorded yet.
      </p>
    );
  }

  function renderTable(title: string, rows: Record<string, UsageBucket>) {
    return (
      <div className="my-2 text-sm">
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {title}
        </p>
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">Source</th>
              <th className="pb-1 pr-3 font-medium text-right">Input</th>
              <th className="pb-1 pr-3 font-medium text-right">Output</th>
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">Cache Read</th>
              )}
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">
                  Cache Write
                </th>
              )}
              <th className="pb-1 font-medium text-right">Requests</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(rows).map(([name, u]) => (
              <tr key={name} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{name}</td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.input_tokens)}
                </td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.output_tokens)}
                </td>
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_read_tokens)}
                  </td>
                )}
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_write_tokens)}
                  </td>
                )}
                <td className="py-1 text-xs text-right">{u.requests}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const total = data.total_input + data.total_output;
  return (
    <div>
      {Object.keys(data.models).length > 0 &&
        renderTable("By Model", data.models)}
      {Object.keys(data.categories).length > 0 &&
        renderTable("By Category", data.categories)}
      <p className="mt-1 text-xs text-muted-foreground">
        Total: {fmt(total)} tokens ({fmt(data.total_input)} in +{" "}
        {fmt(data.total_output)} out)
      </p>
    </div>
  );
}

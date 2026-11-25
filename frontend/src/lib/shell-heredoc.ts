import { languageFromFilePath } from "./sandbox-read";

/** A run of a shell command's lines and the language to highlight them as. */
export interface CommandFragment {
  language: string;
  code: string;
}

interface Heredoc {
  delimiter: string;
  /** `<<-`: the terminator line may be indented with tabs. */
  stripsTabs: boolean;
  /** Null when the body is not a script we know how to highlight. */
  language: string | null;
}

const SHELL = "shell";

const INTERPRETER_LANGUAGES = new Map([
  ["python", "python"],
  ["python3", "python"],
  ["node", "javascript"],
  ["bash", "bash"],
  ["sh", "bash"],
]);

// `<<` or `<<-` with a quoted, backslash-escaped or bare delimiter. Not a `<<<` here-string, and a bare
// delimiter starts with a letter so arithmetic like `$((1<<2))` doesn't open a heredoc.
const HEREDOC_OPERATOR = /(?<!<)<<(-?)[ \t]*(?:'([^'\n]+)'|"([^"\n]+)"|\\?([A-Za-z_]\w*))/g;
const COMMAND_SEPARATOR = /&&|\|\||[;|()]/;
// `tee` also writes to stdout, which is often silenced: `tee f >/dev/null <<EOF`.
const FILE_TARGET = /^(?:cat\s*>\s*([^\s>]+)|tee(?:\s+-a)?\s+([^\s>]+)(?:\s*>\s*\/dev\/null)?)$/;

/**
 * *command* split into shell fragments and the bodies of its heredocs whose language is known from the
 * interpreter (`python3 - <<'PY'`) or the target file (`cat > x.json <<EOF`, `tee x.json <<EOF`). Every
 * other part, including heredocs of unknown language, stays in the shell fragments. The fragments'
 * code joined with newlines is *command* again. A heredoc still being written (no terminator yet) runs
 * to the end, so a streaming command highlights as soon as its opening line is complete.
 */
export function splitHeredocs(command: string): CommandFragment[] {
  const lines = command.split("\n");
  const fragments: { language: string; lines: string[] }[] = [];
  const append = (language: string, added: string[]) => {
    if (added.length === 0) return;
    const last = fragments.at(-1);
    if (last?.language === language) last.lines.push(...added);
    else fragments.push({ language, lines: [...added] });
  };

  let next = 0;
  while (next < lines.length) {
    const line = lines[next++];
    append(SHELL, [line]);
    // A heredoc's body starts on the line after its operator, so the last line (no newline yet) opens none.
    if (next === lines.length) break;
    for (const heredoc of heredocsOpenedBy(line)) {
      const terminator = terminatorIndex(lines, next, heredoc);
      append(heredoc.language ?? SHELL, lines.slice(next, terminator));
      append(SHELL, lines.slice(terminator, terminator + 1));
      next = terminator + 1;
    }
  }
  return fragments.map(({ language, lines }) => ({ language, code: lines.join("\n") }));
}

function heredocsOpenedBy(line: string): Heredoc[] {
  return line.split(COMMAND_SEPARATOR).flatMap((simpleCommand) =>
    [...simpleCommand.matchAll(HEREDOC_OPERATOR)].map((match) => ({
      delimiter: match[2] ?? match[3] ?? match[4],
      stripsTabs: match[1] === "-",
      language: heredocLanguage(simpleCommand, match.index),
    })),
  );
}

/** The heredoc's language from the interpreter reading it, or else the file `cat`/`tee` writes it to. */
function heredocLanguage(simpleCommand: string, operatorIndex: number): string | null {
  const [program, ...args] = simpleCommand.slice(0, operatorIndex).trim().split(/\s+/);
  const interpreterLanguage = INTERPRETER_LANGUAGES.get(program);
  if (interpreterLanguage && ["", "-"].includes(args.join(" "))) return interpreterLanguage;

  const match = FILE_TARGET.exec(simpleCommand.replace(HEREDOC_OPERATOR, "").trim());
  const target = match?.[1] ?? match?.[2];
  const fileLanguage = target ? languageFromFilePath(target.replace(/^(['"])(.*)\1$/, "$2")) : "text";
  return fileLanguage === "text" ? null : fileLanguage;
}

/** The index of the heredoc's terminator line from *start* on, or the end of *lines* while it is still open. */
function terminatorIndex(lines: string[], start: number, { delimiter, stripsTabs }: Heredoc): number {
  for (let index = start; index < lines.length; index++) {
    const line = stripsTabs ? lines[index].replace(/^\t+/, "") : lines[index];
    if (line === delimiter) return index;
  }
  return lines.length;
}

/** *fragments* split so that *tail* holds their last *count* lines, cutting the fragment that crosses the boundary. */
export function splitLastLines(fragments: CommandFragment[], count: number): { head: CommandFragment[]; tail: CommandFragment[] } {
  let remaining = count;
  for (let index = fragments.length - 1; index >= 0; index--) {
    const { language, code } = fragments[index];
    const lines = code.split("\n");
    if (lines.length < remaining) {
      remaining -= lines.length;
      continue;
    }
    const cut = lines.length - remaining;
    return {
      head: [...fragments.slice(0, index), ...(cut > 0 ? [{ language, code: lines.slice(0, cut).join("\n") }] : [])],
      tail: [{ language, code: lines.slice(cut).join("\n") }, ...fragments.slice(index + 1)],
    };
  }
  return { head: [], tail: fragments };
}

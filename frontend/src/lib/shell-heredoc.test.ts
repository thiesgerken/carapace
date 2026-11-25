import assert from "node:assert/strict";
import test from "node:test";

import { splitHeredocs, splitLastLines, type CommandFragment } from "./shell-heredoc";

const shell = (code: string): CommandFragment => ({ language: "shell", code });

/** The fragments of *command*, checked to join back into it. */
function fragmentsOf(command: string): CommandFragment[] {
  const fragments = splitHeredocs(command);
  assert.equal(fragments.map((fragment) => fragment.code).join("\n"), command, "the fragments join back into the command");
  return fragments;
}

test("a heredoc read by a known interpreter is highlighted as its language", () => {
  assert.deepEqual(fragmentsOf("python3 - <<'PY'\nimport json\nprint(json.dumps({}))\nPY\necho done"), [
    shell("python3 - <<'PY'"),
    { language: "python", code: "import json\nprint(json.dumps({}))" },
    shell("PY\necho done"),
  ]);
  assert.deepEqual(fragmentsOf('node <<"JS"\nconsole.log(1)\nJS'), [shell('node <<"JS"'), { language: "javascript", code: "console.log(1)" }, shell("JS")]);
  assert.deepEqual(fragmentsOf("sh <<EOF\necho hi\nEOF"), [shell("sh <<EOF"), { language: "bash", code: "echo hi" }, shell("EOF")]);
  assert.deepEqual(fragmentsOf("out=$(python <<\\PY\nprint(1)\nPY\n)"), [shell("out=$(python <<\\PY"), { language: "python", code: "print(1)" }, shell("PY\n)")]);
});

test("a heredoc written to a file is highlighted by the file's extension", () => {
  assert.deepEqual(fragmentsOf("cat > x.json <<'EOF'\n{\"a\": 1}\nEOF\ncat x.json"), [
    shell("cat > x.json <<'EOF'"),
    { language: "json", code: '{"a": 1}' },
    shell("EOF\ncat x.json"),
  ]);
  assert.deepEqual(fragmentsOf('cat <<EOF >"/workspace/run.py"\nprint(1)\nEOF'), [shell('cat <<EOF >"/workspace/run.py"'), { language: "python", code: "print(1)" }, shell("EOF")]);
  assert.deepEqual(fragmentsOf("tee config.yaml <<EOF\na: 1\nEOF"), [shell("tee config.yaml <<EOF"), { language: "yaml", code: "a: 1" }, shell("EOF")]);
  assert.deepEqual(fragmentsOf("tee -a notes.md <<EOF\n# Notes\nEOF"), [shell("tee -a notes.md <<EOF"), { language: "markdown", code: "# Notes" }, shell("EOF")]);
  assert.deepEqual(fragmentsOf("tee app.py >/dev/null <<EOF\nx = 1\nEOF"), [shell("tee app.py >/dev/null <<EOF"), { language: "python", code: "x = 1" }, shell("EOF")]);
  assert.deepEqual(fragmentsOf("tee -a app.py <<'EOF' > /dev/null\nx = 1\nEOF"), [shell("tee -a app.py <<'EOF' > /dev/null"), { language: "python", code: "x = 1" }, shell("EOF")]);
});

test("several heredocs, on separate lines or one, each get their own language", () => {
  assert.deepEqual(fragmentsOf("cat > a.py <<'A'\nx = 1\nA\nnode <<'B'\nconsole.log(1)\nB"), [
    shell("cat > a.py <<'A'"),
    { language: "python", code: "x = 1" },
    shell("A\nnode <<'B'"),
    { language: "javascript", code: "console.log(1)" },
    shell("B"),
  ]);
  assert.deepEqual(fragmentsOf("cat <<A > a.json && python3 - <<B\n{}\nA\nprint()\nB"), [
    shell("cat <<A > a.json && python3 - <<B"),
    { language: "json", code: "{}" },
    shell("A"),
    { language: "python", code: "print()" },
    shell("B"),
  ]);
});

test("<<- ends at a tab-indented terminator, << only at an unindented one", () => {
  assert.deepEqual(fragmentsOf("\tcat > s.sh <<-EOF\n\techo hi\n\tEOF\necho after"), [
    shell("\tcat > s.sh <<-EOF"),
    { language: "bash", code: "\techo hi" },
    shell("\tEOF\necho after"),
  ]);
  assert.deepEqual(fragmentsOf("bash <<EOF\necho hi\n\tEOF\nEOF"), [shell("bash <<EOF"), { language: "bash", code: "echo hi\n\tEOF" }, shell("EOF")]);
});

test("unknown interpreters, targets and unparsable commands stay one shell block", () => {
  for (const command of [
    "ruby <<'RB'\nputs 1\nRB",
    "uv run python - <<'PY'\nprint(1)\nPY",
    "python3 -u - <<'PY'\nprint(1)\nPY",
    "cat <<EOF | python3\nprint(1)\nEOF",
    "cat >> log.py <<EOF\nprint(1)\nEOF",
    "cat > a.py >/dev/null <<EOF\nprint(1)\nEOF",
    "tee a.py > copy.py <<EOF\nprint(1)\nEOF",
    "cat > notes.txt <<EOF\nhello\nEOF",
    "python3 <<< 'print(1)'",
    "echo $((1<<2))\nls",
    "ls -la /workspace",
    "",
  ]) {
    assert.deepEqual(fragmentsOf(command), [shell(command)], command);
  }
});

test("an unknown heredoc's body is skipped, so a script inside it opens nothing", () => {
  assert.deepEqual(fragmentsOf("cat > a.sh <<'EOF'\npython3 - <<PY\nEOF\nruby <<X\npython3 - <<PY\nX"), [
    shell("cat > a.sh <<'EOF'"),
    { language: "bash", code: "python3 - <<PY" },
    shell("EOF\nruby <<X\npython3 - <<PY\nX"),
  ]);
});

test("a heredoc still being written highlights once its opening line is complete", () => {
  assert.deepEqual(fragmentsOf("python3 - <<'PY'"), [shell("python3 - <<'PY'")]);
  assert.deepEqual(fragmentsOf("python3 - <<'PY'\nimport js"), [shell("python3 - <<'PY'"), { language: "python", code: "import js" }]);
  assert.deepEqual(fragmentsOf("cat > a.json <<A && python3 - <<B\n{}\nA\npri"), [
    shell("cat > a.json <<A && python3 - <<B"),
    { language: "json", code: "{}" },
    shell("A"),
    { language: "python", code: "pri" },
  ]);
});

test("the last lines split off on line boundaries, cutting the fragment that crosses the boundary", () => {
  const python = (code: string): CommandFragment => ({ language: "python", code });
  const fragments = [shell("python3 - <<'PY'"), python("a = 1\nb = 2\nc = 3"), shell("PY\necho done")];

  assert.deepEqual(splitLastLines(fragments, 3), { head: [shell("python3 - <<'PY'"), python("a = 1\nb = 2")], tail: [python("c = 3"), shell("PY\necho done")] });
  assert.deepEqual(splitLastLines(fragments, 5), { head: [shell("python3 - <<'PY'")], tail: [python("a = 1\nb = 2\nc = 3"), shell("PY\necho done")] }, "a fragment that fits whole is not cut");
  assert.deepEqual(splitLastLines(fragments, 1), { head: [shell("python3 - <<'PY'"), python("a = 1\nb = 2\nc = 3"), shell("PY")], tail: [shell("echo done")] });
  assert.deepEqual(splitLastLines(fragments, 6), { head: [], tail: fragments });
  assert.deepEqual(splitLastLines(fragments, 200), { head: [], tail: fragments });
});

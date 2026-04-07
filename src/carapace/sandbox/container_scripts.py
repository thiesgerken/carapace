"""Python source snippets run inside the sandbox via ``python3 -c``.

Base64-encoded CLI args avoid shell-escaping issues. Scripts use only double
quotes so ``shlex.quote`` (single-quote wrapping) works without escaping.
"""

from __future__ import annotations

# Placeholder replaced by :func:`build_file_read_script` with the real separator line.
FILE_READ_BODY_SEPARATOR_TOKEN = "__READ_BODY_SEP__"

SANDBOX_STR_REPLACE_SCRIPT = """\
import base64, os, sys
p, o_b64, n_b64, replace_all_flag = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
old = base64.b64decode(o_b64).decode()
new = base64.b64decode(n_b64).decode()
replace_all = replace_all_flag == "1"
if not old:
    print("Error: old_string must not be empty.")
    sys.exit(1)
if not os.path.exists(p):
    print(f"Error: file not found: {p}")
    sys.exit(1)
try:
    text = open(p).read()
except PermissionError:
    print(f"Error: permission denied: {p}")
    sys.exit(1)
positions = []
start = 0
while True:
    idx = text.find(old, start)
    if idx < 0:
        break
    positions.append(idx)
    start = idx + len(old)
count = len(positions)
if count == 0:
    print(f"Error: old_string not found in {p}.")
    sys.exit(1)
line_numbers = [text.count("\\n", 0, i) + 1 for i in positions]
lines_str = ",".join(str(n) for n in line_numbers)
if not replace_all and count > 1:
    print(
        f"Error: old_string appears {count} times in {p} at lines {lines_str}; "
        "set replace_all=true to replace all."
    )
    sys.exit(1)
updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
try:
    open(p, "w").write(updated)
except PermissionError:
    print(f"Error: permission denied (read-only): {p}")
    sys.exit(1)
if replace_all:
    print(f"Replaced {count} occurrences in {p} at lines {lines_str}.")
else:
    print(f"Replaced 1 occurrence in {p} at line {line_numbers[0]}.")
"""

# argv: path, offset (0-based line), limit (max lines), max_body_chars.
SANDBOX_FILE_READ_SCRIPT_TEMPLATE = """\
import os, subprocess, sys
p, off_s, lim_s, cap_s = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
offset, limit, max_chars = int(off_s), int(lim_s), int(cap_s)
probe_len = 65536
if not os.path.lexists(p):
    print(f"Error: path not found: {p}")
    sys.exit(1)
if not os.access(p, os.R_OK):
    print(f"Error: permission denied: {p}")
    sys.exit(1)
if os.path.isdir(p):
    print("::DIR::")
    for name in sorted(os.listdir(p)):
        print(name)
    sys.exit(0)
if not os.path.isfile(p):
    print(f"Error: not a regular file or directory: {p}")
    sys.exit(1)
try:
    with open(p, "rb") as bf:
        chunk = bf.read(probe_len)
except OSError as e:
    print(f"Error: cannot read {p}: {e}")
    sys.exit(1)
if bytes([0]) in chunk:
    try:
        st = os.stat(p)
        size = st.st_size
    except OSError as e:
        print(f"Error: stat {p}: {e}")
        sys.exit(1)
    try:
        desc = subprocess.check_output(["file", "-b", p], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        desc = "(file command unavailable)"
    print(f"Binary file; content not shown.\\nSize: {size} bytes\\nFile description: {desc}")
    sys.exit(0)
try:
    wc = subprocess.run(["wc", "-l", p], capture_output=True, text=True, check=True)
    total_lines = int(wc.stdout.split()[0])
except (subprocess.CalledProcessError, ValueError, IndexError) as e:
    print(f"Error: wc -l failed for {p}: {e}")
    sys.exit(1)
body_parts = []
used = 0
first_idx = None
last_idx = None
hit_cap = False
partial_last = False
try:
    with open(p, encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            if idx < offset:
                continue
            if idx >= offset + limit:
                break
            remaining = max_chars - used
            if remaining <= 0:
                hit_cap = True
                break
            line_len = len(line)
            if used + line_len <= max_chars:
                body_parts.append(line)
                used += line_len
                first_idx = idx if first_idx is None else first_idx
                last_idx = idx
                continue
            prefix_len = min(line_len, remaining)
            suffix = ""
            while prefix_len >= 0:
                suffix = f" [truncated: line has {line_len} characters, {prefix_len} shown]"
                if prefix_len + len(suffix) <= remaining:
                    break
                prefix_len -= 1
            if prefix_len < 0:
                piece = " [truncated]"[: max(0, remaining)]
            else:
                piece = line[:prefix_len] + suffix
            body_parts.append(piece)
            used += len(piece)
            first_idx = idx if first_idx is None else first_idx
            last_idx = idx
            hit_cap = True
            partial_last = True
            break
except OSError as e:
    print(f"Error: cannot read {p}: {e}")
    sys.exit(1)
hdr = []
hdr.append(f"Total lines: {total_lines}")
if first_idx is None:
    if total_lines == 0:
        hdr.append("No lines in this window (file is empty).")
    elif offset >= total_lines:
        hdr.append(
            f"No lines in this window. File has {total_lines} line(s); "
            f"after skipping {offset} line(s), the window starts past the end of the file."
        )
    else:
        hdr.append(
            f"No lines in this window. File has {total_lines} line(s) "
            f"(skipped {offset}, showing up to {limit} lines per request)."
        )
else:
    hdr.append(f"Reading lines {first_idx + 1} through {last_idx + 1}.")
if hit_cap:
    hdr.append(f"Output is truncated at {max_chars} characters.")
if partial_last:
    hdr.append("The last line is incomplete.")
print("\\n".join(hdr))
print("__READ_BODY_SEP__")
sys.stdout.write("".join(body_parts))
"""


def build_file_read_script(body_separator: str) -> str:
    """Return the read script with ``body_separator`` as the header/body divider line."""
    return SANDBOX_FILE_READ_SCRIPT_TEMPLATE.replace(FILE_READ_BODY_SEPARATOR_TOKEN, body_separator)

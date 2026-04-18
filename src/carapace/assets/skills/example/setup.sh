#!/bin/sh
set -eu

mkdir -p .example-skill
cat > .example-skill/imap-demo.json <<'EOF'
{
	"host": "imap.gmail.com",
	"port": 1993
}
EOF

echo "prepared example IMAP tunnel config"

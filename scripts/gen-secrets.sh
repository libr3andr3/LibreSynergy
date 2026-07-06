#!/usr/bin/env bash
# gen-secrets.sh — materialize secrets/*.env from the *.env.example templates,
# auto-filling every "openssl rand -hex N" placeholder. Never overwrites an
# existing secret file. Values you must supply by hand (Stripe, BTCPay) are left
# as placeholders and reported. chmod 600 on everything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/libresynergy.env" ] && { set -a; . "$ROOT/libresynergy.env"; set +a; }
SECRETS="${LS_SECRETS_DIR:-$ROOT/secrets}"
say(){ printf '  • %s\n' "$*"; }

shopt -s nullglob
for ex in "$ROOT"/secrets/*.example; do
  base="$(basename "$ex" .example)"          # auth-secrets.env  /  spaces.json
  target="$SECRETS/$base"
  if [ -e "$target" ]; then say "keep existing $base"; continue; fi
  mkdir -p "$SECRETS"

  if [[ "$base" == *.json ]]; then
    cp "$ex" "$target"; chmod 600 "$target"; say "copied $base (edit by hand)"; continue
  fi

  pgpass=""
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^([A-Za-z0-9_]+)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
      if [[ "$val" =~ rand_hex_([0-9]+) ]]; then
        val="$(openssl rand -hex "${BASH_REMATCH[1]}")"
        [ "$key" = "POSTGRES_PASSWORD" ] && pgpass="$val"
      elif [[ "$val" == *SAME_VALUE_AS_POSTGRES_PASSWORD* ]]; then
        val="${pgpass:-$(openssl rand -hex 50)}"
      fi
      printf '%s=%s\n' "$key" "$val"
    else
      printf '%s\n' "$line"
    fi
  done < "$ex" > "$target"
  chmod 600 "$target"

  if grep -qE 'REPLACE_WITH|CHANGE_ME|^[A-Za-z0-9_]+=<' "$target"; then
    say "generated $base  ⚠ still has manual values (Stripe/BTCPay/etc.) — edit before enabling that profile"
  else
    say "generated $base (all secrets auto-filled)"
  fi
done
echo "Secrets in $SECRETS (chmod 600). Never commit them — they are gitignored."

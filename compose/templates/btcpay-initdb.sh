#!/bin/sh
# Runs once on first postgres init: NBXplorer needs its own database alongside
# btcpayserver (the image only creates $POSTGRES_DB). Without this, BTCPay
# fails at startup with: database "nbxplorer" does not exist.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'CREATE DATABASE nbxplorer OWNER btcpay;'

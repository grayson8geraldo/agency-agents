#!/usr/bin/env bash
#
# ICT Paper Trading Bot — quick launcher
#
# Usage:
#   ./run.sh                  # Run once (analyze current market)
#   ./run.sh --continuous     # Monitor every 5 minutes
#   ./run.sh --status         # Show account balance & history
#   ./run.sh --reset          # Reset account to €200
#
set -euo pipefail
cd "$(dirname "$0")/../.."

# API key from config.json (auto-loaded by the bot)
# Or override via environment:
#   export TWELVE_DATA_KEY="your-key"
#   export OANDA_API_TOKEN="your-oanda-token"

case "${1:-}" in
    --continuous|-c)
        echo "Starting continuous paper trading (Ctrl+C to stop)..."
        PYTHONPATH=. python -m trading.bot.paper_trading --symbol EUR/USD --interval 5
        ;;
    --status|-s)
        PYTHONPATH=. python -m trading.bot.paper_trading --status
        ;;
    --reset|-r)
        PYTHONPATH=. python -m trading.bot.paper_trading --reset
        ;;
    --help|-h)
        echo "ICT Paper Trading Bot — €200 virtual account on real forex data"
        echo ""
        echo "Usage:"
        echo "  ./run.sh                  Run pipeline once"
        echo "  ./run.sh --continuous     Monitor every 5 min (Ctrl+C to stop)"
        echo "  ./run.sh --status         Show account balance & trade history"
        echo "  ./run.sh --reset          Reset account to €200"
        echo ""
        echo "Config: trading/bot/config.json"
        echo "Account state: paper_account.json"
        ;;
    *)
        PYTHONPATH=. python -m trading.bot.paper_trading --symbol EUR/USD --once
        ;;
esac

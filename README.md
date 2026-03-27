# Krypto-Bot 2 – EMA/RSI + Gestaffelter Take-Profit

Automatisierter Krypto-Trading-Bot für Alpaca Markets (Paper Trading).

## Strategie

- **Einstieg:** Golden Cross EMA 9/21 + RSI < 65
- **Ausstieg:** Death Cross EMA 9/21 oder Take-Profit / Stop-Loss
- **Take-Profit 1:** +4% → 50% der Position sichern, Stop-Loss auf Break-Even
- **Take-Profit 2:** +10% → restliche 50% sichern
- **Stop-Loss:** -1.5% automatisch
- **Zeitrahmen:** Tages-Kerzen
- **Scan-Frequenz:** Alle 30 Minuten, 24/7

## Portfolio (3-Tier)

| Tier | Coins | Allokation |
|---|---|---|
| Tier 1 – Blue Chips | BTC, ETH | je 15% |
| Tier 2 – Altcoins | SOL, AVAX, LINK, XRP | je 10% |
| Tier 3 – High-Vol | DOGE, ADA, DOT, LTC | je 5% |
| Cash-Reserve | – | 10% |

## Backtesting-Ergebnisse (12 Monate)

- Gesamtrendite: **+16.7%**
- Beste Performer: BTC (+41%), AVAX (+32%), ETH (+29%)
- Ø Win-Rate: 49%
- Ø Max. Drawdown: 9.6%

## Einrichtung

1. Repository forken
2. Secrets hinterlegen: `ALPACA_API_KEY` und `ALPACA_API_SECRET`
3. GitHub Actions aktivieren → Bot läuft automatisch alle 30 Minuten

## Logs einsehen

GitHub → Actions → "Krypto-Bot 2" → letzter Run

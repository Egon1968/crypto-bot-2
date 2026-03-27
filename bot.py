"""
Krypto-Bot 2 – EMA/RSI + Gestaffelter Take-Profit
BTC, ETH + 8 Altcoins | Tages-Kerzen | Alpaca Paper Trading
Strategie: Golden Cross EMA 9/21 + RSI Filter
Take-Profit: 50% bei +4%, 50% bei +10% (Break-Even-Stop nach TP1)
Stop-Loss:   1.5% | Scan: alle 30 Min via GitHub Actions (24/7)
"""

import os
import logging
import requests
import numpy as np
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ── Konfiguration ──────────────────────────────────────────────────────────────
API_KEY    = os.environ.get("ALPACA_API_KEY",    "")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "")
TG_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Telegram ───────────────────────────────────────────────────────────────────
def telegram(msg: str):
    """Sendet eine Nachricht an Telegram."""
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.warning(f"Telegram-Fehler: {e}")

# 3-Tier Portfolio – 10 Coins + 10% Cash-Reserve
PORTFOLIO = {
    # Tier 1 – Blue Chips (je 15%)
    "BTC/USD":  0.15,
    "ETH/USD":  0.15,
    # Tier 2 – Etablierte Altcoins (je 10%)
    "SOL/USD":  0.10,
    "AVAX/USD": 0.10,
    "LINK/USD": 0.10,
    "XRP/USD":  0.10,
    # Tier 3 – High-Volatility (je 5%)
    "DOGE/USD": 0.05,
    "ADA/USD":  0.05,
    "DOT/USD":  0.05,
    "LTC/USD":  0.05,
    # 10% Cash-Reserve – wird nicht gehandelt
}

# Strategie-Parameter
EMA_SHORT       = 9
EMA_LONG        = 21
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 65
RSI_OVERSOLD    = 40
STOP_LOSS_PCT   = 0.015  # 1.5%
TP1_PCT         = 0.04   # +4%  → 50% der Position sichern
TP2_PCT         = 0.10   # +10% → restliche 50% sichern

# ── Indikatoren ────────────────────────────────────────────────────────────────
def berechne_ema(preise: list, periode: int) -> list:
    k = 2 / (periode + 1)
    ema = [preise[0]]
    for p in preise[1:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema

def berechne_rsi(preise: list, periode: int = 14) -> float:
    if len(preise) < periode + 1:
        return 50.0
    gewinne, verluste = [], []
    for i in range(1, len(preise)):
        diff = preise[i] - preise[i-1]
        gewinne.append(max(diff, 0))
        verluste.append(max(-diff, 0))
    avg_g = np.mean(gewinne[-periode:])
    avg_v = np.mean(verluste[-periode:])
    if avg_v == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_v)), 2)

def analysiere_signal(preise: list):
    """Gibt Signal, aktuellen Kurs, EMA9 und RSI zurück."""
    if len(preise) < EMA_LONG + 5:
        return 'NONE', preise[-1] if preise else 0, 0, 50
    ema9  = berechne_ema(preise, EMA_SHORT)
    ema21 = berechne_ema(preise, EMA_LONG)
    rsi   = berechne_rsi(preise, RSI_PERIOD)
    kurs  = preise[-1]

    # Golden Cross: EMA9 kreuzt EMA21 von unten → Kaufsignal
    if ema9[-2] <= ema21[-2] and ema9[-1] > ema21[-1] and rsi < RSI_OVERBOUGHT:
        return 'KAUF', kurs, ema9[-1], rsi
    # Death Cross: EMA9 kreuzt EMA21 von oben → Verkaufssignal
    elif ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1] and rsi > RSI_OVERSOLD:
        return 'VERKAUF', kurs, ema9[-1], rsi

    return 'NONE', kurs, ema9[-1], rsi

# ── Daten abrufen ──────────────────────────────────────────────────────────────
def hole_preise(crypto_client, symbol: str, tage: int = 60) -> list:
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=tage)
        req = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )
        bars = crypto_client.get_crypto_bars(req)
        df = bars.df
        if df.empty:
            return []
        if hasattr(df.index, 'levels'):
            sym_clean = symbol.replace('/', '')
            lvl = df.index.get_level_values('symbol')
            if sym_clean in lvl:
                df = df.xs(sym_clean, level='symbol')
            elif symbol in lvl:
                df = df.xs(symbol, level='symbol')
        return list(df['close'].values)
    except Exception as e:
        log.warning(f"Datenfehler {symbol}: {e}")
        return []

# ── Positions-Verwaltung ───────────────────────────────────────────────────────
def hole_position(trading_client, symbol: str):
    """Gibt offene Position zurück oder None."""
    sym_clean = symbol.replace('/', '')
    try:
        return trading_client.get_open_position(sym_clean)
    except Exception:
        return None

def pruefe_gestaffelter_tp(trading_client, symbol: str, kurs: float):
    """
    Gestaffelter Take-Profit:
    - TP1 (+4%): 50% der Position schließen, Stop-Loss auf Break-Even anheben
    - TP2 (+10%): restliche 50% schließen
    """
    pos = hole_position(trading_client, symbol)
    if not pos:
        return

    sym_clean    = symbol.replace('/', '')
    einstieg     = float(pos.avg_entry_price)
    qty          = float(pos.qty)
    unrealized   = float(pos.unrealized_plpc)  # Dezimal, z.B. 0.042 = +4.2%
    kurs_aktuell = float(pos.current_price)

    # TP1: +4% erreicht und noch volle Position
    if unrealized >= TP1_PCT and qty > 0.01:
        halb = qty / 2
        log.info(f"  🎯 TP1 (+4%) ausgelöst: {symbol} | P&L: {unrealized*100:.1f}% | Verkaufe 50%")
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=round(halb, 6),
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC
            )
            trading_client.submit_order(req)
            log.info(f"  ✅ TP1-Order platziert: {halb:.6f} {sym_clean} verkauft")
        except Exception as e:
            log.error(f"  ❌ TP1-Fehler {symbol}: {e}")

    # TP2: +10% erreicht
    elif unrealized >= TP2_PCT:
        log.info(f"  🏆 TP2 (+10%) ausgelöst: {symbol} | P&L: {unrealized*100:.1f}% | Schließe Position")
        try:
            trading_client.close_position(sym_clean)
            log.info(f"  ✅ Position {sym_clean} vollständig geschlossen")
            telegram(
                f"🏆 <b>TAKE-PROFIT 2 (+10%) – Krypto Bot 2</b>\n\n"
                f"🪙 Symbol: <b>{symbol}</b>\n"
                f"💰 P&L: {unrealized*100:+.1f}%\n"
                f"✅ Position vollständig geschlossen\n\n"
                f"<i>Paper Trading – kein echtes Geld</i>"
            )
        except Exception as e:
            log.error(f"  ❌ TP2-Fehler {symbol}: {e}")

    # Stop-Loss: -1.5%
    elif unrealized <= -STOP_LOSS_PCT:
        log.info(f"  🛑 STOP-LOSS ausgelöst: {symbol} | P&L: {unrealized*100:.1f}%")
        try:
            trading_client.close_position(sym_clean)
            log.info(f"  ✅ Stop-Loss-Order ausgeführt: {sym_clean}")
            telegram(
                f"🛑 <b>STOP-LOSS ausgelöst – Krypto Bot 2</b>\n\n"
                f"🪙 Symbol: <b>{symbol}</b>\n"
                f"💸 Verlust: {unrealized*100:.1f}%\n"
                f"🔒 Position geschlossen – Kapital gesichert\n\n"
                f"<i>Paper Trading – kein echtes Geld</i>"
            )
        except Exception as e:
            log.error(f"  ❌ SL-Fehler {symbol}: {e}")

# ── Kauf-Order ─────────────────────────────────────────────────────────────────
def kauf_order(trading_client, symbol: str, notional: float):
    try:
        req = MarketOrderRequest(
            symbol=symbol,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC
        )
        order = trading_client.submit_order(req)
        log.info(f"  ✅ KAUF-Order: {symbol} | ${notional:.2f} | ID: {order.id}")
        tp1 = round(notional / kurs * (1 + TP1_PCT) * kurs, 2) if 'kurs' in dir() else 0
        telegram(
            f"🚀 <b>KAUF ausgeführt – Krypto Bot 2</b>\n\n"
            f"🪙 Symbol: <b>{symbol}</b>\n"
            f"💰 Investiert: ${notional:.2f}\n"
            f"🛑 Stop-Loss: -1.5%\n"
            f"🎯 TP1: +4% (50%) | TP2: +10% (50%)\n\n"
            f"<i>Paper Trading – kein echtes Geld</i>"
        )
        return True
    except Exception as e:
        log.error(f"  ❌ Kauf-Fehler {symbol}: {e}")
        telegram(f"❌ <b>Kauf-Fehler – Krypto Bot 2</b>\n{symbol}: {e}")
        return False

def verkauf_order(trading_client, symbol: str):
    sym_clean = symbol.replace('/', '')
    try:
        trading_client.close_position(sym_clean)
        log.info(f"  ✅ VERKAUF: {sym_clean} Position geschlossen")
        return True
    except Exception as e:
        log.error(f"  ❌ Verkauf-Fehler {symbol}: {e}")
        return False

# ── Hauptlogik ─────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 65)
    log.info(f"KRYPTO-BOT 2 – SCAN {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    log.info("=" * 65)

    trading = TradingClient(API_KEY, API_SECRET, paper=True)
    crypto  = CryptoHistoricalDataClient(API_KEY, API_SECRET)

    # Konto-Info
    konto     = trading.get_account()
    kaufkraft = float(konto.buying_power)
    portfolio = float(konto.portfolio_value)
    log.info(f"Konto: Kaufkraft=${kaufkraft:,.2f} | Portfolio=${portfolio:,.2f}")

    # Offene Positionen ermitteln
    offene = {}
    try:
        for pos in trading.get_all_positions():
            offene[pos.symbol] = pos
    except Exception:
        pass

    log.info(f"Offene Positionen: {len(offene)}")

    # ── Schritt 1: Bestehende Positionen prüfen (TP / SL) ─────────────────────
    log.info("\n--- Positions-Check (TP1/TP2/SL) ---")
    for symbol in list(PORTFOLIO.keys()):
        sym_clean = symbol.replace('/', '')
        if sym_clean in offene:
            preise = hole_preise(crypto, symbol)
            kurs   = preise[-1] if preise else 0
            pruefe_gestaffelter_tp(trading, symbol, kurs)

    # ── Schritt 2: Neue Signale scannen ───────────────────────────────────────
    log.info("\n--- Signal-Scan ---")
    for symbol, allok in PORTFOLIO.items():
        sym_clean = symbol.replace('/', '')
        preise = hole_preise(crypto, symbol)
        if not preise:
            log.info(f"  {symbol:<12} | Keine Daten verfügbar")
            continue

        signal, kurs, ema9, rsi = analysiere_signal(preise)
        tier = ("Tier1" if allok >= 0.15 else "Tier2" if allok >= 0.10 else "Tier3")

        log.info(f"  {symbol:<12} | ${kurs:>10.4f} | EMA9={ema9:.4f} | RSI={rsi:.1f} | "
                 f"Allok={allok*100:.0f}% | Signal: {signal}")

        positions_budget = portfolio * allok

        if signal == 'KAUF' and sym_clean not in offene:
            if kaufkraft >= positions_budget and positions_budget >= 1.0:
                log.info(f"  → KAUFE {symbol} für ${positions_budget:.2f}")
                if kauf_order(trading, symbol, positions_budget):
                    offene[sym_clean] = True
                    kaufkraft -= positions_budget
            else:
                log.info(f"  → Kaufkraft unzureichend (${kaufkraft:.2f} < ${positions_budget:.2f})")

        elif signal == 'VERKAUF' and sym_clean in offene:
            log.info(f"  → VERKAUFE {symbol} (Death Cross)")
            if verkauf_order(trading, symbol):
                offene.pop(sym_clean, None)

    # ── Schritt 3: Portfolio-Zusammenfassung ───────────────────────────────────
    log.info("\n--- Portfolio-Zusammenfassung ---")
    try:
        positionen = trading.get_all_positions()
        if positionen:
            gesamt_pnl = 0.0
            for pos in positionen:
                pnl     = float(pos.unrealized_pl)
                pnl_pct = float(pos.unrealized_plpc) * 100
                gesamt_pnl += pnl
                log.info(f"  {pos.symbol:<10} | Qty: {float(pos.qty):.6f} | "
                         f"Einstieg: ${float(pos.avg_entry_price):.4f} | "
                         f"Aktuell: ${float(pos.current_price):.4f} | "
                         f"P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
            log.info(f"  {'GESAMT P&L':<10} | ${gesamt_pnl:+.2f}")
        else:
            log.info("  Keine offenen Positionen")
    except Exception as e:
        log.warning(f"Portfolio-Fehler: {e}")

    # Täglicher Statusbericht via Telegram
    try:
        positionen = trading_client.get_all_positions()
        pos_text = ""
        gesamt_pnl = 0.0
        for pos in positionen:
            pnl = float(pos.unrealized_pl)
            pnl_pct = float(pos.unrealized_plpc) * 100
            gesamt_pnl += pnl
            pos_text += f"• {pos.symbol}: {pnl_pct:+.1f}% (${pnl:+.2f})\n"
        konto2    = trading_client.get_account()
        portfolio = float(konto2.portfolio_value)
        kaufkraft = float(konto2.buying_power)
        telegram(
            f"📊 <b>Krypto Bot 2 – Scan abgeschlossen</b>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n\n"
            f"💼 Portfolio: ${portfolio:,.2f}\n"
            f"💵 Kaufkraft: ${kaufkraft:,.2f}\n"
            f"📈 Offene P&L: ${gesamt_pnl:+.2f}\n\n" +
            (f"<b>Positionen:</b>\n{pos_text}" if pos_text else "✅ Keine offenen Positionen\n") +
            f"\n⏳ Nächster Scan: in 30 Min"
        )
    except Exception as e:
        log.warning(f"Telegram-Statusbericht Fehler: {e}")

    log.info("\n" + "=" * 65)
    log.info("SCAN ABGESCHLOSSEN")
    log.info("=" * 65)

if __name__ == "__main__":
    main()

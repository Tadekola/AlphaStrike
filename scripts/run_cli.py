import argparse
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from cal_pro.data_providers.tradier import TradierProvider
from cal_pro.data_providers.mock import MockProvider
from cal_pro.engine.pipeline import Pipeline
from cal_pro.strategies.calendar import CalendarStrategy
from cal_pro.strategies.vertical import VerticalStrategy
from cal_pro.strategies.iron_condor import IronCondorStrategy
from cal_pro.strategies.iron_fly import IronButterflyStrategy
from cal_pro.strategies.short_strangle import ShortStrangleStrategy
from cal_pro.strategies.diagonal import DiagonalStrategy
from cal_pro.strategies.ratio import RatioStrategy
from cal_pro.strategies.jade_lizard import JadeLizardStrategy
from cal_pro.strategies.butterfly import ButterflyStrategy

STRATEGIES = {
    "calendar": CalendarStrategy,
    "vertical": VerticalStrategy,
    "iron_condor": IronCondorStrategy,
    "iron_fly": IronButterflyStrategy,
    "strangle": ShortStrangleStrategy,
    "diagonal": DiagonalStrategy,
    "ratio": RatioStrategy,
    "jade_lizard": JadeLizardStrategy,
    "butterfly": ButterflyStrategy
}

def main():
    parser = argparse.ArgumentParser(description="AlphaStrike CLI")
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. SPY)")
    parser.add_argument("--provider", default="mock", choices=["mock", "tradier"], help="Data provider")
    parser.add_argument("--strategy", default="all", choices=["all"] + list(STRATEGIES.keys()), help="Strategy to run")
    parser.add_argument("--min-pop", type=float, default=0.40, help="Minimum POP filter")
    
    args = parser.parse_args()
    
    ticker = args.ticker.upper()
    print(f"Starting AlphaStrike scan for {ticker}...")
    
    # Setup Provider
    if args.provider == "tradier":
        provider = TradierProvider(ticker)
    else:
        provider = MockProvider(ticker)
        
    # Setup Strategies
    selected_strategies = []
    if args.strategy == "all":
        for s_cls in STRATEGIES.values():
            selected_strategies.append(s_cls())
    else:
        selected_strategies.append(STRATEGIES[args.strategy]())
        
    # Run Pipeline
    pipeline = Pipeline(provider, selected_strategies)
    try:
        candidates, market = pipeline.run(ticker)
    except Exception as e:
        print(f"Error running pipeline: {e}")
        return

    # Filter and Display
    print(f"\nMarket Context: Spot=${market.spot:.2f}, Regime={market.regime}, GEX=${market.gex:,.0f}")
    print(f"Found {len(candidates)} raw candidates. Filtering for POP >= {args.min_pop:.0%}...\n")
    
    filtered = [c for c in candidates if c.pop >= args.min_pop]
    filtered.sort(key=lambda x: x.confidence_score, reverse=True)
    
    if not filtered:
        print("No trades found matching criteria.")
    else:
        print(f"{'STRATEGY':<20} {'DESCRIPTION':<35} {'CONF':<6} {'PROFIT':<10} {'POP':<6}")
        print("-" * 85)
        for c in filtered:
            print(f"{c.strategy_name:<20} {c.description:<35} {c.confidence_score:<6} ${c.max_profit:<9.2f} {c.pop:.0%}")

if __name__ == "__main__":
    main()

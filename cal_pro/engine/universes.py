from typing import Dict, List

UNIVERSES: Dict[str, List[str]] = {
    "Indices": ["SPY", "QQQ", "IWM", "DIA"],
    "Mega Cap Tech": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "NFLX"],
    "Semiconductors": ["SMH", "NVDA", "AMD", "INTC", "QCOM", "MU", "TSM", "AVGO"],
    "Energy": ["XLE", "XOM", "CVX", "COP", "SLB", "EOG"],
    "Financials": ["XLF", "JPM", "BAC", "WFC", "C", "GS", "MS"],
    "High Liquid": ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMD", "AMZN"],
}

def get_universe(name: str) -> List[str]:
    return UNIVERSES.get(name, [])

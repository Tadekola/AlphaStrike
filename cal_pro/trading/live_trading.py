"""
Live Trading Module for AlphaStrike

CRITICAL: This module executes REAL trades with REAL money.
All safety controls must be respected.

Safety features:
1. Explicit confirmation required for every order
2. Position size limits enforced
3. Preflight checks before order submission
4. Paper mode default - must explicitly enable live
5. All orders logged for audit trail
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

from cal_pro.data_providers.public_provider import (
    PublicProvider, PublicAPIError, TRADING_BASE
)
from cal_pro.engine.base_strategy import CandidateTrade


class TradingMode(Enum):
    """Trading mode - defaults to PAPER for safety."""
    PAPER = "paper"
    LIVE = "live"


class OrderType(Enum):
    """Order types supported."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"
    BUY_TO_OPEN = "BUY_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"


@dataclass
class OrderLeg:
    """Single leg of an order."""
    symbol: str
    side: str
    quantity: int
    asset_type: str = "OPTION"  # OPTION or EQUITY


@dataclass
class PreflightResult:
    """Result of preflight check."""
    approved: bool
    buying_power_required: float
    buying_power_available: float
    margin_requirement: float
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    estimated_commission: float = 0.0
    estimated_rebate: float = 0.0


@dataclass
class OrderResult:
    """Result of order placement."""
    success: bool
    order_id: Optional[str] = None
    status: str = ""
    message: str = ""
    filled_price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradingLimits:
    """Position and risk limits."""
    max_position_size: int = 10  # Max contracts per position
    max_daily_trades: int = 20  # Max trades per day
    max_single_loss: float = 500.0  # Max loss per trade in dollars
    max_daily_loss: float = 2000.0  # Max daily loss in dollars
    require_limit_orders: bool = True  # Force limit orders (no market orders)


class LiveTradingEngine:
    """
    Live trading engine with comprehensive safety controls.
    
    DEFAULTS TO PAPER MODE. Must explicitly enable live trading.
    """
    
    def __init__(
        self,
        provider: PublicProvider,
        mode: TradingMode = TradingMode.PAPER,
        limits: Optional[TradingLimits] = None
    ):
        self.provider = provider
        self.mode = mode
        self.limits = limits or TradingLimits()
        self._daily_trades = 0
        self._daily_pnl = 0.0
        self._trade_log: List[Dict] = []
        
        # Safety check: require explicit environment variable for live mode
        if mode == TradingMode.LIVE:
            if os.getenv("ALPHASTRIKE_LIVE_TRADING") != "ENABLED":
                raise ValueError(
                    "Live trading requires ALPHASTRIKE_LIVE_TRADING=ENABLED environment variable. "
                    "This is a safety measure to prevent accidental live trades."
                )
    
    def _log_action(self, action: str, details: Dict):
        """Log all trading actions for audit trail."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": self.mode.value,
            "action": action,
            **details
        }
        self._trade_log.append(entry)
        
        # Also print to console for visibility
        mode_label = "🔴 LIVE" if self.mode == TradingMode.LIVE else "📝 PAPER"
        print(f"[{mode_label}] {action}: {details}")
    
    def _headers(self) -> Dict[str, str]:
        """Get authenticated headers."""
        return self.provider._headers()
    
    def preflight_single_leg(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> PreflightResult:
        """
        Preflight check for single-leg order.
        
        Validates buying power, margin, and returns estimated costs.
        """
        self._log_action("PREFLIGHT_SINGLE", {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type.value
        })
        
        # Check local limits first
        errors = []
        warnings = []
        
        if quantity > self.limits.max_position_size:
            errors.append(f"Quantity {quantity} exceeds max position size {self.limits.max_position_size}")
        
        if self._daily_trades >= self.limits.max_daily_trades:
            errors.append(f"Daily trade limit ({self.limits.max_daily_trades}) reached")
        
        if self.limits.require_limit_orders and order_type == OrderType.MARKET:
            errors.append("Market orders disabled. Use limit orders for better execution.")
        
        if errors:
            return PreflightResult(
                approved=False,
                buying_power_required=0,
                buying_power_available=0,
                margin_requirement=0,
                errors=errors
            )
        
        # Call Public.com preflight API
        try:
            data = self.provider._request(
                "POST",
                f"{TRADING_BASE}/options/preflight/single-leg",
                json={
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "orderType": order_type.value,
                    "limitPrice": limit_price
                }
            )
            
            return PreflightResult(
                approved=data.get("approved", False),
                buying_power_required=float(data.get("buyingPowerRequired", 0)),
                buying_power_available=float(data.get("buyingPowerAvailable", 0)),
                margin_requirement=float(data.get("marginRequirement", 0)),
                warnings=data.get("warnings", []),
                errors=data.get("errors", []),
                estimated_commission=float(data.get("estimatedCommission", 0)),
                estimated_rebate=float(data.get("estimatedRebate", 0))
            )
        except PublicAPIError as e:
            return PreflightResult(
                approved=False,
                buying_power_required=0,
                buying_power_available=0,
                margin_requirement=0,
                errors=[str(e)]
            )
    
    def preflight_multi_leg(
        self,
        legs: List[OrderLeg],
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> PreflightResult:
        """
        Preflight check for multi-leg order (spreads, condors, etc.).
        """
        self._log_action("PREFLIGHT_MULTI", {
            "legs": [{"symbol": l.symbol, "side": l.side, "qty": l.quantity} for l in legs],
            "order_type": order_type.value
        })
        
        # Check local limits
        errors = []
        max_qty = max(l.quantity for l in legs)
        
        if max_qty > self.limits.max_position_size:
            errors.append(f"Max leg quantity {max_qty} exceeds position limit {self.limits.max_position_size}")
        
        if self._daily_trades >= self.limits.max_daily_trades:
            errors.append(f"Daily trade limit ({self.limits.max_daily_trades}) reached")
        
        if errors:
            return PreflightResult(
                approved=False,
                buying_power_required=0,
                buying_power_available=0,
                margin_requirement=0,
                errors=errors
            )
        
        # Call Public.com preflight API
        try:
            data = self.provider._request(
                "POST",
                f"{TRADING_BASE}/options/preflight/multi-leg",
                json={
                    "legs": [
                        {
                            "symbol": l.symbol,
                            "side": l.side,
                            "quantity": l.quantity,
                            "assetType": l.asset_type
                        }
                        for l in legs
                    ],
                    "orderType": order_type.value,
                    "limitPrice": limit_price
                }
            )
            
            return PreflightResult(
                approved=data.get("approved", False),
                buying_power_required=float(data.get("buyingPowerRequired", 0)),
                buying_power_available=float(data.get("buyingPowerAvailable", 0)),
                margin_requirement=float(data.get("marginRequirement", 0)),
                warnings=data.get("warnings", []),
                errors=data.get("errors", []),
                estimated_commission=float(data.get("estimatedCommission", 0)),
                estimated_rebate=float(data.get("estimatedRebate", 0))
            )
        except PublicAPIError as e:
            return PreflightResult(
                approved=False,
                buying_power_required=0,
                buying_power_available=0,
                margin_requirement=0,
                errors=[str(e)]
            )
    
    def preflight_trade(self, trade: CandidateTrade, quantity: int = 1) -> PreflightResult:
        """
        Preflight check for a CandidateTrade from the analysis pipeline.
        
        Converts strategy legs to order legs and runs preflight.
        """
        # Check max loss against limits
        if trade.max_loss and trade.max_loss != float('inf'):
            total_risk = trade.max_loss * quantity
            if total_risk > self.limits.max_single_loss:
                return PreflightResult(
                    approved=False,
                    buying_power_required=0,
                    buying_power_available=0,
                    margin_requirement=0,
                    errors=[
                        f"Trade max loss ${total_risk:.0f} exceeds limit ${self.limits.max_single_loss:.0f}"
                    ]
                )
        
        # Convert trade legs to order legs
        order_legs = []
        for leg in trade.legs:
            # Construct option symbol (OCC format)
            # Format: SYMBOL + YYMMDD + C/P + Strike (8 digits with 3 decimals)
            exp_str = leg.expiry.strftime("%y%m%d")
            right_char = "C" if leg.right.lower() == "call" else "P"
            strike_str = f"{int(leg.strike * 1000):08d}"
            option_symbol = f"{leg.ticker}{exp_str}{right_char}{strike_str}"
            
            # Determine side based on direction
            if leg.direction.lower() == "buy":
                side = "BUY_TO_OPEN"
            else:
                side = "SELL_TO_OPEN"
            
            order_legs.append(OrderLeg(
                symbol=option_symbol,
                side=side,
                quantity=quantity
            ))
        
        # Calculate limit price from trade debit/credit
        limit_price = abs(trade.debit) / 100 if trade.debit else None
        
        return self.preflight_multi_leg(
            legs=order_legs,
            order_type=OrderType.LIMIT,
            limit_price=limit_price
        )
    
    def place_order(
        self,
        trade: CandidateTrade,
        quantity: int = 1,
        limit_price: Optional[float] = None,
        confirmed: bool = False
    ) -> OrderResult:
        """
        Place a live order for a CandidateTrade.
        
        REQUIRES explicit confirmation (confirmed=True).
        
        Args:
            trade: The analyzed trade to execute
            quantity: Number of contracts
            limit_price: Limit price (required for safety)
            confirmed: Must be True to actually place order
            
        Returns:
            OrderResult with success status and details
        """
        # SAFETY: Require explicit confirmation
        if not confirmed:
            return OrderResult(
                success=False,
                message="Order not confirmed. Set confirmed=True to execute."
            )
        
        # SAFETY: Paper mode check
        if self.mode == TradingMode.PAPER:
            self._log_action("PAPER_ORDER", {
                "trade": trade.description,
                "quantity": quantity,
                "limit_price": limit_price
            })
            self._daily_trades += 1
            return OrderResult(
                success=True,
                order_id=f"PAPER-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                status="FILLED",
                message="Paper trade executed (no real order placed)"
            )
        
        # LIVE MODE - Run preflight first
        preflight = self.preflight_trade(trade, quantity)
        
        if not preflight.approved:
            return OrderResult(
                success=False,
                message=f"Preflight failed: {'; '.join(preflight.errors)}"
            )
        
        # Require limit price for live orders
        if limit_price is None:
            # Use conservative pricing from trade
            limit_price = abs(trade.debit) / 100
        
        # Convert legs to order format
        order_legs = []
        for leg in trade.legs:
            exp_str = leg.expiry.strftime("%y%m%d")
            right_char = "C" if leg.right.lower() == "call" else "P"
            strike_str = f"{int(leg.strike * 1000):08d}"
            option_symbol = f"{leg.ticker}{exp_str}{right_char}{strike_str}"
            
            side = "BUY_TO_OPEN" if leg.direction.lower() == "buy" else "SELL_TO_OPEN"
            
            order_legs.append({
                "symbol": option_symbol,
                "side": side,
                "quantity": quantity,
                "assetType": "OPTION"
            })
        
        # Place the order
        self._log_action("PLACE_ORDER", {
            "trade": trade.description,
            "legs": order_legs,
            "limit_price": limit_price
        })
        
        try:
            data = self.provider._request(
                "POST",
                f"{TRADING_BASE}/options/orders/multi-leg",
                json={
                    "legs": order_legs,
                    "orderType": "LIMIT",
                    "limitPrice": limit_price,
                    "timeInForce": "DAY"
                }
            )
            
            self._daily_trades += 1
            
            return OrderResult(
                success=True,
                order_id=data.get("orderId"),
                status=data.get("status", "PENDING"),
                message="Order placed successfully"
            )
            
        except PublicAPIError as e:
            return OrderResult(
                success=False,
                message=f"Order failed: {str(e)}"
            )
    
    def get_order_status(self, order_id: str) -> Dict:
        """Get status of an existing order."""
        try:
            return self.provider._request(
                "GET",
                f"{TRADING_BASE}/orders/{order_id}"
            )
        except PublicAPIError as e:
            return {"error": str(e)}
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        self._log_action("CANCEL_ORDER", {"order_id": order_id})
        
        if self.mode == TradingMode.PAPER:
            return True
        
        try:
            self.provider._request(
                "DELETE",
                f"{TRADING_BASE}/orders/{order_id}"
            )
            return True
        except PublicAPIError:
            return False
    
    def get_trade_log(self) -> List[Dict]:
        """Get audit log of all trading actions."""
        return self._trade_log.copy()


def create_trading_engine(
    ticker: str,
    live: bool = False,
    limits: Optional[TradingLimits] = None
) -> LiveTradingEngine:
    """
    Factory function to create a trading engine.
    
    Args:
        ticker: Underlying symbol
        live: If True, enable live trading (requires env var)
        limits: Optional custom trading limits
        
    Returns:
        Configured LiveTradingEngine
    """
    provider = PublicProvider(ticker)
    mode = TradingMode.LIVE if live else TradingMode.PAPER
    return LiveTradingEngine(provider, mode, limits)

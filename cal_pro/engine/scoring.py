from .base_strategy import CandidateTrade, POP_LABEL_UNVERIFIED
from .market import MarketState

# Confidence labels
CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_INSUFFICIENT_DATA = "LOW CONFIDENCE: INSUFFICIENT DATA"


class Scorer:
    """Score trades based on available, verified data only.
    
    Scoring Philosophy:
    - Only uses real, computed inputs
    - When POP is None/UNVERIFIED, falls back to conservative baseline
    - Provides explicit explanation of what the score is based on
    """
    
    def score(self, trade: CandidateTrade, market: MarketState) -> None:
        # Build explanation of scoring inputs
        score_inputs = []
        
        # Check if POP is available and verified
        pop_available = trade.pop is not None and trade.pop_label != POP_LABEL_UNVERIFIED
        
        if pop_available:
            q_score = self._calculate_q_score_with_pop(trade, market)
            score_inputs.append(f"POP={trade.pop:.0%} ({trade.pop_label})")
        else:
            # Conservative baseline when POP is unavailable
            q_score = 35.0  # Below neutral - conservative
            score_inputs.append("POP=UNVERIFIED (conservative baseline)")
        
        # No L-Score - removed fake stub
        # Previously L-score was always 50.0 which was meaningless
        
        # Final confidence is just Q-score since L-score is not implemented
        final = q_score
        
        trade.q_score = round(q_score, 1)
        trade.l_score = 0.0  # Explicitly zero - not implemented
        trade.confidence_score = round(final, 1)
        
        # Determine confidence label
        if not pop_available:
            trade.confidence_label = CONFIDENCE_INSUFFICIENT_DATA
        elif final >= 80:
            trade.confidence_label = CONFIDENCE_HIGH
        elif final >= 50:
            trade.confidence_label = CONFIDENCE_MEDIUM
        else:
            trade.confidence_label = CONFIDENCE_LOW
        
        # Store scoring explanation in metrics
        trade.metrics['score_basis'] = "; ".join(score_inputs)

    def _calculate_q_score_with_pop(self, trade: CandidateTrade, market: MarketState) -> float:
        """Calculate Q-score when verified POP is available."""
        score = 50.0
        
        # Boost for high POP
        if trade.pop > 0.5:
            score += (trade.pop - 0.5) * 100.0
            
        # Penalty for low POP
        if trade.pop < 0.4:
            score -= (0.4 - trade.pop) * 100.0
            
        return max(0.0, min(100.0, score))

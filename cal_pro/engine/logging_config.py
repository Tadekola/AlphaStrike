"""
Structured logging configuration for AlphaStrike.

Provides consistent logging across all modules with appropriate levels
and formatting for production use.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(
    level: str = "INFO",
    log_file: str = None,
    include_timestamp: bool = True
) -> logging.Logger:
    """Configure structured logging for AlphaStrike.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        include_timestamp: Whether to include timestamps in log format
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("alphastrike")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Format string
    if include_timestamp:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    else:
        fmt = "%(levelname)-8s | %(name)s:%(funcName)s | %(message)s"
    
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger for a specific module.
    
    Args:
        name: Module name (e.g., 'pipeline', 'tradability')
        
    Returns:
        Logger instance
    """
    return logging.getLogger(f"alphastrike.{name}")


# Default logger instance
logger = get_logger("core")


class AuditLogger:
    """Specialized logger for audit-relevant events.
    
    Logs events that are important for compliance and debugging:
    - Trade proposals
    - Rejections with reasons
    - Data quality issues
    - User actions
    """
    
    def __init__(self):
        self.logger = get_logger("audit")
    
    def log_trade_proposed(self, ticker: str, strategy: str, confidence: float, tradable: bool):
        """Log a trade proposal event."""
        status = "TRADABLE" if tradable else "REJECTED"
        self.logger.info(
            f"TRADE_PROPOSED | {ticker} | {strategy} | confidence={confidence:.1f} | status={status}"
        )
    
    def log_trade_rejected(self, ticker: str, strategy: str, reasons: list):
        """Log a trade rejection with reasons."""
        reason_str = "; ".join(reasons) if reasons else "Unknown"
        self.logger.warning(
            f"TRADE_REJECTED | {ticker} | {strategy} | reasons=[{reason_str}]"
        )
    
    def log_data_quality_issue(self, ticker: str, issue: str):
        """Log a data quality issue."""
        self.logger.warning(
            f"DATA_QUALITY | {ticker} | issue={issue}"
        )
    
    def log_greeks_missing(self, ticker: str, strategy: str):
        """Log missing Greeks data."""
        self.logger.warning(
            f"GREEKS_MISSING | {ticker} | {strategy} | Stress test results may be unreliable"
        )
    
    def log_regime_detection(self, ticker: str, trend: str, vol: str, adx: float, hv_ratio: float):
        """Log regime detection result."""
        self.logger.info(
            f"REGIME_DETECTED | {ticker} | trend={trend} | vol={vol} | adx={adx:.1f} | hv_ratio={hv_ratio:.2f}"
        )
    
    def log_journal_action(self, action: str, entry_id: str, details: str = ""):
        """Log journal actions."""
        self.logger.info(
            f"JOURNAL_{action.upper()} | id={entry_id} | {details}"
        )


# Global audit logger instance
audit_logger = AuditLogger()

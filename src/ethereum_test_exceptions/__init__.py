"""
Exceptions for invalid execution.
"""

from .engine_api import EngineAPIError
from .evmone_exceptions import EvmoneExceptionMapper
from .exception_mapper import ExceptionMapper
from .exceptions import (
    BlockException,
    BlockExceptionInstanceOrList,
    EOFException,
    EOFExceptionInstanceOrList,
    ExceptionInstanceOrList,
    TransactionException,
    TransactionExceptionInstanceOrList,
)

__all__ = [
    "BlockException",
    "BlockExceptionInstanceOrList",
    "EOFException",
    "EOFExceptionInstanceOrList",
    "EngineAPIError",
    "ExceptionMapper",
    "EvmoneExceptionMapper",
    "ExceptionInstanceOrList",
    "TransactionException",
    "TransactionExceptionInstanceOrList",
]

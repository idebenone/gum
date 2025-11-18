"""
Observer module for GUM - General User Models.

This module provides observer classes for different types of user interactions.
"""

from .observer import Observer
# from .screen import Screen
from .text import TextObserver

__all__ = ["Observer", "TextObserver"] 
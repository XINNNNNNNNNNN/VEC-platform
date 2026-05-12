"""Calculation engine base class."""

from abc import ABC, abstractmethod
from typing import Any

from vec_platform.models import UserInput, DailyProfile, BillBreakdown, ShadowPrices


class CalculationEngine(ABC):
    """Abstract base class for calculation engines."""
    
    @abstractmethod
    def generate_profile(self, user_input: UserInput) -> DailyProfile:
        """Generate daily load profile based on user input.
        
        Args:
            user_input: UserInput model with building info
            
        Returns:
            DailyProfile model with 96-slot load curves
        """
        pass
    
    @abstractmethod
    def calculate_bill(
        self,
        profile: DailyProfile,
        scenario: str,
        area_m2: float | None = None,
    ) -> BillBreakdown:
        """Calculate bill breakdown for a given scenario.

        Args:
            profile: DailyProfile with load data
            scenario: "no_vec" | "vec_no_adjust" | "vec_adjusted"
            area_m2: Floor area for grid fee tier (Phase N F6). None
                falls back to the lowest tier — callers should pass
                ``user_input.area_m2`` whenever they have the
                user_input row.

        Returns:
            BillBreakdown model with cost breakdown
        """
        pass
    
    @abstractmethod
    def get_shadow_prices(self, session_id: str) -> ShadowPrices:
        """Get VEC internal shadow prices.

        Args:
            session_id: Session UUID

        Returns:
            ShadowPrices model with 96-slot price curves
        """
        pass
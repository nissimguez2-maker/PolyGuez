"""
CogDx Connector
Cognitive Diagnostics for Prediction Market Agents

Optional reasoning verification before trade execution.
Detects logical fallacies, calibration issues, and cognitive biases.

API: https://api.cerebratech.ai
"""

import os
import requests
from typing import Dict, Any, Optional, List

class CogDxClient:
    """
    Client for Cerebratech's Cognitive Diagnostics API.
    
    Verifies agent reasoning quality before high-stakes decisions.
    Detects logical fallacies, calibration issues, and cognitive biases.
    """
    
    BASE_URL = "https://api.cerebratech.ai"
    
    def __init__(self, coupon: Optional[str] = None, wallet: Optional[str] = None):
        """
        Initialize CogDx client.
        
        Args:
            coupon: Optional coupon code for credits
            wallet: Ethereum wallet address for credit-based payments
        """
        self.coupon = coupon or os.getenv("COGDX_COUPON")
        self.wallet = wallet or os.getenv("COGDX_WALLET")
    
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.coupon:
            headers["X-COUPON"] = self.coupon
        if self.wallet:
            headers["X-WALLET"] = self.wallet
        return headers
    
    def analyze_reasoning(self, reasoning_trace: str) -> Dict[str, Any]:
        """
        Analyze a reasoning trace for logical fallacies and validity issues.
        
        Args:
            reasoning_trace: The agent's reasoning text to analyze
            
        Returns:
            dict with:
                - logical_validity: float 0-1
                - status: 'valid' | 'flawed'
                - flaws_detected: list of detected fallacies
                - recommendations: suggested improvements
        """
        try:
            response = requests.post(
                f"{self.BASE_URL}/reasoning_trace_analysis",
                headers=self._headers(),
                json={"trace": reasoning_trace},
                timeout=30
            )
            
            if response.status_code == 402:
                return {
                    "error": "payment_required",
                    "message": "Add COGDX_COUPON or COGDX_WALLET to env",
                    "logical_validity": None
                }
            
            # Handle other HTTP errors (500, 403, 429, etc.)
            if not response.ok:
                return {
                    "error": f"http_{response.status_code}",
                    "message": f"API returned status {response.status_code}",
                    "logical_validity": None
                }
            
            return response.json()
            
        except Exception as e:
            return {"error": str(e), "logical_validity": None}
    
    def calibration_audit(
        self,
        agent_id: str,
        predictions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Audit prediction calibration - do confidence levels match accuracy?
        
        Args:
            agent_id: Identifier for the agent
            predictions: List of {prompt, response, confidence} dicts
            
        Returns:
            dict with:
                - calibration_score: float 0-1 (1 = perfectly calibrated)
                - overconfidence_rate: float
                - underconfidence_rate: float
                - recommendations: list of strings
        """
        try:
            response = requests.post(
                f"{self.BASE_URL}/calibration_audit",
                headers=self._headers(),
                json={
                    "agent_id": agent_id,
                    "sample_outputs": predictions
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def bias_scan(
        self,
        agent_id: str,
        outputs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Scan for cognitive biases in agent outputs.
        
        Detects: anchoring, confirmation bias, availability heuristic,
        representativeness, sunk cost, and more.
        
        Args:
            agent_id: Identifier for the agent
            outputs: List of {prompt, response, confidence} dicts
            
        Returns:
            dict with:
                - biases_detected: list of bias findings
                - severity: 'low' | 'medium' | 'high'
                - recommendations: list of strings
        """
        try:
            response = requests.post(
                f"{self.BASE_URL}/bias_scan",
                headers=self._headers(),
                json={
                    "agent_id": agent_id,
                    "sample_outputs": outputs
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def verify_before_trade(
        self,
        reasoning: str,
        min_validity: float = 0.7
    ) -> Dict[str, Any]:
        """
        Pre-trade verification gate.
        
        Use this before executing trades to catch reasoning flaws.
        
        Args:
            reasoning: The reasoning trace that led to the trade decision
            min_validity: Minimum logical validity score to pass (default 0.7)
            
        Returns:
            dict with:
                - approved: bool
                - validity_score: float
                - issues: list of detected problems
                - recommendation: 'proceed' | 'review' | 'reject' | 'skip' (on error)
        """
        result = self.analyze_reasoning(reasoning)
        
        if result.get("error"):
            # On error, fail closed (don't approve unverified trades)
            return {
                "approved": False,
                "validity_score": None,
                "issues": [f"CogDx unavailable: {result.get('error')}"],
                "recommendation": "skip"
            }
        
        # Handle null values explicitly (dict.get returns None for null, not default)
        validity = result.get("logical_validity")
        if validity is None:
            validity = 0
        flaws = result.get("flaws_detected") or []
        
        approved = validity >= min_validity and len(flaws) == 0
        
        if validity >= min_validity and len(flaws) == 0:
            recommendation = "proceed"
        elif validity >= 0.5:
            recommendation = "review"
        else:
            recommendation = "reject"
        
        # Handle flaws as either dicts or strings
        issues = []
        for f in flaws:
            if isinstance(f, dict):
                issues.append(f.get("name", str(f)))
            else:
                issues.append(str(f))
        
        return {
            "approved": approved,
            "validity_score": validity,
            "issues": issues,
            "recommendation": recommendation
        }


def verify_trade_reasoning(
    reasoning: str, 
    coupon: str = None, 
    wallet: str = None
) -> bool:
    """
    Convenience function for quick trade verification.
    
    Usage:
        from agents.connectors.cogdx import verify_trade_reasoning
        
        if verify_trade_reasoning(my_reasoning):
            execute_trade()
        else:
            print("Reasoning flagged for review")
    
    Args:
        reasoning: The reasoning trace to verify
        coupon: Optional coupon code for credits
        wallet: Optional wallet address for credits
    
    Returns:
        True if reasoning passes verification, False otherwise.
        Note: Returns False if API is unavailable (fails closed).
    """
    client = CogDxClient(coupon=coupon, wallet=wallet)
    result = client.verify_before_trade(reasoning)
    return result.get("approved", False)

"""Multi-model ensemble forecasting for improved accuracy"""

from typing import List, Dict, Optional, Tuple
from langchain_openai import ChatOpenAI
import re


class EnsembleForecaster:
    """
    Combine forecasts from multiple LLM models to reduce bias and improve accuracy
    """

    def __init__(self):
        """Initialize multiple model instances"""
        self.models = {
            'gpt-3.5-turbo': ChatOpenAI(model='gpt-3.5-turbo-16k', temperature=0),
            'gpt-4': ChatOpenAI(model='gpt-4-1106-preview', temperature=0),
            # Add more models as needed
            # 'claude': ChatAnthropic(...),
            # 'gemini': ChatGoogleGenerativeAI(...),
        }

        # Model weights based on historical Brier scores
        # These should be updated based on calibration data
        self.model_weights = {
            'gpt-3.5-turbo': 0.40,
            'gpt-4': 0.60,
        }

    def extract_probability(self, llm_response: str) -> Optional[float]:
        """Extract probability from LLM response text"""
        try:
            # Look for patterns like "0.65", "65%", "probability of 0.65"
            patterns = [
                r'probability.*?(\d+\.?\d*)',
                r'likelihood.*?(\d+\.?\d*)',
                r'(\d+\.?\d*)\s*(?:probability|likelihood)',
                r'(\d+)%',
                r'(\d+\.\d+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, llm_response.lower())
                if match:
                    prob = float(match.group(1))
                    # Convert percentage to decimal if needed
                    if prob > 1.0:
                        prob = prob / 100.0
                    # Ensure valid probability range
                    if 0.0 <= prob <= 1.0:
                        return prob

            return None
        except:
            return None

    def get_ensemble_forecast(self,
                             prompt_messages: List,
                             min_agreement: float = 0.80) -> Optional[Dict]:
        """
        Get forecasts from multiple models and combine them

        Args:
            prompt_messages: List of LangChain messages for the forecast
            min_agreement: Minimum agreement threshold (default 80%)

        Returns:
            dict with ensemble forecast or None if models disagree too much
        """
        forecasts = {}
        probabilities = []

        # Get forecast from each model
        for model_name, model in self.models.items():
            try:
                result = model.invoke(prompt_messages)
                probability = self.extract_probability(result.content)

                if probability is not None:
                    forecasts[model_name] = {
                        'probability': probability,
                        'response': result.content
                    }
                    probabilities.append(probability)
                else:
                    print(f"Warning: Could not extract probability from {model_name}")

            except Exception as e:
                print(f"Error getting forecast from {model_name}: {e}")
                continue

        if len(probabilities) < 2:
            print("Warning: Not enough model forecasts for ensemble")
            return None

        # Calculate weighted average
        weighted_forecast = sum(
            forecasts[model]['probability'] * self.model_weights.get(model, 1.0)
            for model in forecasts.keys()
        ) / sum(self.model_weights.get(model, 1.0) for model in forecasts.keys())

        # Calculate agreement (using standard deviation)
        import statistics
        if len(probabilities) > 1:
            std_dev = statistics.stdev(probabilities)
            # Agreement is inverse of standard deviation
            # Low std dev = high agreement
            agreement = 1.0 - min(std_dev * 2, 1.0)  # Scale std_dev
        else:
            agreement = 1.0

        # Check if models agree enough
        if agreement < min_agreement:
            print(f"Warning: Low model agreement ({agreement:.1%}), consider skipping trade")
            # Return forecast but flag low confidence
            return {
                'ensemble_forecast': weighted_forecast,
                'individual_forecasts': forecasts,
                'agreement': agreement,
                'confidence': agreement,
                'should_trade': False,
                'reason': 'low_agreement'
            }

        return {
            'ensemble_forecast': weighted_forecast,
            'individual_forecasts': forecasts,
            'agreement': agreement,
            'confidence': agreement,
            'should_trade': True,
            'reason': 'consensus'
        }

    def get_fast_ensemble(self, prompt_messages: List) -> Tuple[float, float]:
        """
        Quick ensemble using only available models

        Returns:
            (forecast_probability, confidence_score)
        """
        result = self.get_ensemble_forecast(prompt_messages, min_agreement=0.70)

        if result is None:
            return (0.5, 0.0)  # Neutral forecast, zero confidence

        return (result['ensemble_forecast'], result['confidence'])

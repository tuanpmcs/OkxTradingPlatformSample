from __future__ import annotations

from ml_pipeline.serving.app import PredictionService


# Entry points for SageMaker model server integration can import PredictionService from here.
__all__ = ["PredictionService"]

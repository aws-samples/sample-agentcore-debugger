"""
Settings Service — runtime-configurable application settings stored in DynamoDB.

Currently manages the active Bedrock model used for code analysis/fixes, so an
admin can change the model from the Settings UI without code edits or redeploys.
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10})

SETTINGS_PK = "SETTINGS"
MODEL_SK = "MODEL_CONFIG"

# Path to the bundled model catalog (available models + defaults)
_AI_MODELS_JSON = Path(__file__).resolve().parent.parent.parent.parent / "src" / "config" / "ai_models.json"


class SettingsService:
    """Read/write runtime settings (model selection) in DynamoDB."""

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.table_name = os.getenv("DYNAMODB_TABLE_NAME", "")
        self.ddb = boto3.resource("dynamodb", region_name=region, config=RETRY_CONFIG)

    def _table(self):
        if not self.table_name:
            raise Exception("DYNAMODB_TABLE_NAME not configured")
        return self.ddb.Table(self.table_name)

    def _load_catalog(self) -> Dict[str, Any]:
        """Load the available models catalog from ai_models.json."""
        try:
            with open(_AI_MODELS_JSON, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load model catalog: {e}")
            return {"default_model": "", "available_models": []}

    def get_model_settings(self) -> Dict[str, Any]:
        """Return the currently selected model + the list of available models."""
        catalog = self._load_catalog()
        default_model = catalog.get("default_model", "")
        available: List[Dict[str, Any]] = catalog.get("available_models", [])

        selected = default_model
        try:
            resp = self._table().get_item(Key={"PK": SETTINGS_PK, "SK": MODEL_SK})
            item = resp.get("Item")
            if item and item.get("model_id"):
                selected = item["model_id"]
        except Exception as e:
            logger.warning(f"Could not read model setting from DynamoDB: {e}")

        return {
            "selected_model": selected,
            "default_model": default_model,
            "available_models": available,
            "source": "dynamodb" if selected != default_model else "default",
        }

    def set_model(self, model_id: str) -> Dict[str, Any]:
        """Set the active model. Validates against the available catalog."""
        catalog = self._load_catalog()
        valid_ids = {m["id"] for m in catalog.get("available_models", [])}
        if valid_ids and model_id not in valid_ids:
            return {
                "status": "failed",
                "error": f"Model '{model_id}' is not in the available models list.",
                "available_models": sorted(valid_ids),
            }
        try:
            self._table().put_item(Item={
                "PK": SETTINGS_PK,
                "SK": MODEL_SK,
                "model_id": model_id,
            })
            logger.info(f"Active model set to {model_id}")
            return {"status": "success", "selected_model": model_id}
        except Exception as e:
            logger.error(f"Failed to set model: {e}")
            return {"status": "failed", "error": str(e)}

"""
Configuration for AgentCore Debugger Assistant
"""
import os
import time

# Model Configuration
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Allow override via environment variable
MODEL_ID = os.getenv('BEDROCK_MODEL_ID', DEFAULT_MODEL_ID)

# AWS Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

# ── Runtime model selection (DynamoDB-backed, no code edits needed) ──────
# An admin can change the active model from the Settings UI; it's stored in
# DynamoDB and read here with a short cache so all analysis/fix code uses it.
_SETTINGS_PK = "SETTINGS"
_SETTINGS_SK = "MODEL_CONFIG"
_model_cache = {"model_id": None, "ts": 0.0, "ttl": 30}


def _get_selected_model_from_db():
    """Read the admin-selected model from DynamoDB. Returns None if unset/unavailable."""
    table_name = os.getenv("DYNAMODB_TABLE_NAME")
    if not table_name:
        return None
    now = time.time()
    if _model_cache["model_id"] and (now - _model_cache["ts"]) < _model_cache["ttl"]:
        return _model_cache["model_id"]
    try:
        import boto3
        from botocore.config import Config as _Cfg
        ddb = boto3.client("dynamodb", region_name=AWS_REGION,
                           config=_Cfg(retries={"mode": "adaptive", "max_attempts": 5}))
        resp = ddb.get_item(
            TableName=table_name,
            Key={"PK": {"S": _SETTINGS_PK}, "SK": {"S": _SETTINGS_SK}},
        )
        item = resp.get("Item")
        model_id = item["model_id"]["S"] if item and "model_id" in item else None
        _model_cache["model_id"] = model_id
        _model_cache["ts"] = now
        return model_id
    except Exception:
        return None

# Model settings
MODEL_CONFIG = {
    'model_id': MODEL_ID,
    'region': AWS_REGION,
    'max_tokens': 4096,
    'temperature': 0.0,  # Deterministic for code fixes
}

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

def get_model_id() -> str:
    """Get the active model ID.

    Priority: admin selection in DynamoDB > BEDROCK_MODEL_ID env > default.
    """
    selected = _get_selected_model_from_db()
    return selected or MODEL_ID

def get_aws_region() -> str:
    """Get the configured AWS region"""
    return AWS_REGION

def get_model_config() -> dict:
    """Get the full model configuration"""
    cfg = MODEL_CONFIG.copy()
    cfg['model_id'] = get_model_id()
    return cfg

def get_fallback_models() -> list:
    """Get list of fallback models to try when primary model fails"""
    import json
    import os
    
    # Load from config file
    config_path = os.path.join(os.path.dirname(__file__), 'ai_models.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            return config.get('fallback_models', [])
    except:
        # Hardcoded fallback if config file fails - Claude 4.x models only
        return [
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "us.anthropic.claude-opus-4-1-20250805-v1:0",
            "global.anthropic.claude-sonnet-4-20250514-v1:0"
        ]

# Cache for model health check to avoid too many requests
_health_check_cache = {
    'result': None,
    'timestamp': None,
    'cache_duration': 60  # Cache for 60 seconds
}

def check_model_health(force_check: bool = False) -> dict:
    """
    Check if the Bedrock model is available and responding.
    Tries fallback models if primary fails.
    
    Args:
        force_check: If True, bypass cache and force a new health check
    
    Returns:
        dict with keys:
            - status: 'healthy', 'unhealthy', or 'error'
            - message: Description of the status
            - response_time: Time taken for the health check (if successful)
            - error: Error details (if failed)
            - cached: True if result is from cache
            - model_id: The model that was checked (or succeeded with fallback)
    """
    import boto3
    import json
    import time
    from datetime import datetime, timedelta
    
    # Check cache first (unless force_check is True)
    if not force_check and _health_check_cache['result'] is not None:
        cache_age = (datetime.now() - _health_check_cache['timestamp']).total_seconds()
        if cache_age < _health_check_cache['cache_duration']:
            cached_result = _health_check_cache['result'].copy()
            cached_result['cached'] = True
            cached_result['cache_age'] = round(cache_age, 1)
            return cached_result
    
    # Get fallback models to try
    fallback_models = get_fallback_models()
    
    # Initialize Bedrock client with adaptive retry
    from botocore.config import Config
    _retry = Config(retries={"mode": "adaptive", "max_attempts": 10})
    bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION, config=_retry)
    
    # Prepare a minimal test request
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 10,
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": "Respond with OK"
            }
        ]
    }
    
    # Try each model until one succeeds
    last_error = None
    for attempt, model_id in enumerate(fallback_models, 1):
        try:
            # Measure response time
            start_time = time.time()
            
            # Invoke model
            response = bedrock.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body)
            )
            
            response_time = time.time() - start_time
            
            # Check HTTP status code first - this is the primary health indicator
            http_status = response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0)
            
            if http_status != 200:
                # Model failed, try next one
                last_error = Exception(f'Model returned HTTP {http_status}')
                if attempt < len(fallback_models):
                    time.sleep(1)
                    continue
                else:
                    break
            
            # HTTP 200 means the model is healthy - try to parse response for additional validation
            try:
                response_body = json.loads(response['body'].read())
                
                # Check if we got a valid response structure
                has_content = 'content' in response_body and len(response_body['content']) > 0
                has_stop_reason = 'stop_reason' in response_body
                
                if has_content or has_stop_reason:
                    message = 'Model is responding normally'
                    if attempt > 1:
                        message = f'Fallback model is responding normally (tried {attempt} models)'
                    
                    result = {
                        'status': 'healthy',
                        'message': message,
                        'response_time': round(response_time, 2),
                        'http_status': http_status,
                        'model_id': model_id,
                        'region': AWS_REGION,
                        'cached': False,
                        'fallback_used': attempt > 1,
                        'attempts': attempt
                    }
                    # Cache the result - this caches the WORKING model
                    _health_check_cache['result'] = result.copy()
                    _health_check_cache['timestamp'] = datetime.now()
                    _health_check_cache['cache_duration'] = 60  # Reset to normal duration
                    return result
                else:
                    # HTTP 200 but unexpected format - still consider healthy since model responded
                    message = 'Model responded (HTTP 200) but with unexpected format'
                    if attempt > 1:
                        message = f'Fallback model responded (tried {attempt} models)'
                    
                    result = {
                        'status': 'healthy',
                        'message': message,
                        'response_time': round(response_time, 2),
                        'http_status': http_status,
                        'model_id': model_id,
                        'region': AWS_REGION,
                        'warning': 'Response body format unexpected',
                        'cached': False,
                        'fallback_used': attempt > 1,
                        'attempts': attempt
                    }
                    # Cache the result
                    _health_check_cache['result'] = result.copy()
                    _health_check_cache['timestamp'] = datetime.now()
                    _health_check_cache['cache_duration'] = 60
                    return result
            except Exception as parse_error:
                # HTTP 200 but couldn't parse - still healthy since model responded
                message = 'Model responded (HTTP 200) but response parsing failed'
                if attempt > 1:
                    message = f'Fallback model responded (tried {attempt} models)'
                
                result = {
                    'status': 'healthy',
                    'message': message,
                    'response_time': round(response_time, 2),
                    'http_status': http_status,
                    'model_id': model_id,
                    'region': AWS_REGION,
                    'warning': f'Parse error: {str(parse_error)}',
                    'cached': False,
                    'fallback_used': attempt > 1,
                    'attempts': attempt
                }
                # Cache the result
                _health_check_cache['result'] = result.copy()
                _health_check_cache['timestamp'] = datetime.now()
                _health_check_cache['cache_duration'] = 60
                return result
            
        except Exception as e:
            # This model failed, try next one
            last_error = e
            error_msg = str(e)
            
            # Check if it's a retryable error
            is_retryable = any(keyword in error_msg for keyword in [
                'ServiceUnavailable', 'Too many connections', 'serviceUnavailableException',
                'ThrottlingException', 'TooManyRequestsException'
            ])
            
            if is_retryable and attempt < len(fallback_models):
                # Try next model
                time.sleep(1)  # Brief pause
                continue
            elif not is_retryable:
                # Non-retryable error, don't try other models
                break
    
    # All models failed - return error
    if last_error:
        error_msg = str(last_error)
    
    # Categorize the error
    if 'serviceUnavailableException' in error_msg or 'ServiceUnavailable' in error_msg:
        status_message = f'All {len(fallback_models)} models unavailable - Bedrock service issue'
        suggestion = 'Wait a few minutes and try again, or check AWS Service Health'
    elif 'AccessDeniedException' in error_msg or 'AccessDenied' in error_msg:
        status_message = 'Access denied - check IAM permissions'
        suggestion = 'Ensure your IAM role has bedrock:InvokeModel permission'
    elif 'ValidationException' in error_msg:
        status_message = 'Model validation failed'
        suggestion = 'Verify the model ID is correct and available in your region'
    elif 'ThrottlingException' in error_msg or 'Too many connections' in error_msg:
        status_message = f'All {len(fallback_models)} models throttled - rate limit exceeded'
        suggestion = 'Wait a few minutes before trying again'
    else:
        status_message = f'All {len(fallback_models)} models failed: {error_msg[:100]}'
        suggestion = 'Check AWS credentials and network connectivity'
    
    result = {
        'status': 'error',
        'message': status_message,
        'suggestion': suggestion,
        'error': error_msg,
        'model_id': fallback_models[0],  # Report primary model
        'region': AWS_REGION,
        'cached': False,
        'attempts': len(fallback_models)
    }
    
    # Cache error results for shorter duration (30 seconds) to avoid hammering the service
    _health_check_cache['result'] = result.copy()
    _health_check_cache['timestamp'] = datetime.now()
    _health_check_cache['cache_duration'] = 30  # Shorter cache for errors
    
    return result

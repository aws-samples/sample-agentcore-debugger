"""
AI-Powered Error Analysis using Claude for AgentCore Debugger Assistant
"""
import boto3
import json
import hashlib
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import re


def safe_get_case_insensitive(data: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Safely get value from dict with case-insensitive key matching"""
    if not isinstance(data, dict):
        return default
    
    # Try exact match first (fastest)
    if key in data:
        return data[key]
    
    # Try case-insensitive match
    key_lower = key.lower()
    for k, v in data.items():
        if str(k).lower() == key_lower:
            return v
    
    return default


def has_ai_analysis_indicators(analysis: Dict[str, Any]) -> bool:
    """Check if analysis has AI-powered indicators (case-insensitive)"""
    if not isinstance(analysis, dict):
        return False
    
    # Check for various AI analysis indicators
    ai_indicators = [
        'analysis_type', 'executive_summary', 'actionable_recommendations',
        'root_cause_analysis', 'recommendations', 'summary', 'root_causes'
    ]
    
    for indicator in ai_indicators:
        value = safe_get_case_insensitive(analysis, indicator)
        if value:
            # Check for specific AI analysis types
            if indicator == 'analysis_type':
                ai_types = ['ai_powered_analysis', 'text_fallback']
                if str(value).lower().replace('_', '').replace('-', '') in [t.replace('_', '') for t in ai_types]:
                    return True
            # Check for non-empty lists/strings
            elif isinstance(value, (list, str)) and value:
                return True
    
    return False


@dataclass
class ErrorCluster:
    """Represents a cluster of similar errors"""
    signature: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_error: Dict[str, Any]
    all_errors: List[Dict[str, Any]]


class AIErrorAnalyzer:
    """AI-powered error analyzer using Claude for intelligent insights"""
    
    def __init__(self, region: str = 'us-east-1', model_id: Optional[str] = None, config_path: Optional[str] = None, debug_logging: bool = False):
        """Initialize AI error analyzer
        
        Args:
            region: AWS region for Bedrock client
            model_id: Claude model ID to use (defaults to config default)
            config_path: Path to AI models configuration file
            debug_logging: Enable detailed debug logging of prompts and responses
        """
        self.region = region
        # Use adaptive retry for Bedrock to handle TPM/quota limits
        from botocore.config import Config
        retry_config = Config(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)
        self.bedrock_client = boto3.client('bedrock-runtime', region_name=region, config=retry_config)
        
        # Load model configuration
        self.config = self._load_model_config(config_path)
        
        # Use provided model ID or default from config
        from src.config.config import get_model_id as get_default_model_id
        default_model = get_default_model_id()
        self.model_id = model_id or self.config.get('default_model', default_model)
        
        # Similarity thresholds for deduplication
        self.similarity_threshold = 0.8
        self.max_errors_per_cluster = 10
        self.max_clusters_for_analysis = 20
        
        # Debug logging flag
        self.debug_logging = debug_logging
        
        print(f"AIErrorAnalyzer initialized with model: {self.model_id}")
        if debug_logging:
            print(f"Debug logging enabled - will show full context sent to Claude")
    
    def _format_datetime_for_ai(self, dt) -> str:
        """Format datetime for AI analysis context"""
        if not dt:
            return "Unknown"
        
        # Handle different datetime types
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except:
                return dt  # Return as-is if can't parse
        elif isinstance(dt, (int, float)):
            # Handle Unix timestamps (seconds or milliseconds)
            try:
                # If it's a large number, assume milliseconds
                if dt > 1e10:
                    dt = datetime.fromtimestamp(dt / 1000)
                else:
                    dt = datetime.fromtimestamp(dt)
            except (ValueError, OSError):
                return "Invalid timestamp"
        elif not isinstance(dt, datetime):
            # Try to convert other types to string first
            try:
                dt = datetime.fromisoformat(str(dt).replace('Z', '+00:00'))
            except:
                return str(dt)  # Return as-is if can't parse
        
        # Format for AI context - include both absolute and relative time
        now = datetime.now()
        diff = now - dt
        
        if diff.days > 0:
            relative = f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            relative = f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            relative = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            relative = "Just now"
        
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S UTC')} ({relative})"
    
    def _load_model_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load AI models configuration from JSON file
        
        Args:
            config_path: Optional path to config file
            
        Returns:
            Configuration dictionary
        """
        if config_path is None:
            # Default config path relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, '..', 'config', 'ai_models.json')
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            print(f"Loaded AI models config from: {config_path}")
            return config
        except FileNotFoundError:
            print(f"Config file not found: {config_path}, using fallback configuration")
            return self._get_fallback_config()
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in config file: {e}, using fallback configuration")
            return self._get_fallback_config()
    
    def _get_fallback_config(self) -> Dict[str, Any]:
        """Get fallback configuration if config file is not available
        
        Returns:
            Fallback configuration dictionary
        """
        # Use cross-region inference profile IDs (no account ID needed)
        return {
            "default_model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "available_models": [
                {
                    "id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "name": "Claude Sonnet 4.5",
                    "description": "Latest Claude Sonnet 4.5 model with advanced reasoning and capabilities",
                    "status": "recommended"
                },
                {
                    "id": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                    "name": "Claude 3.7 Sonnet",
                    "description": "Previous generation Claude model with enhanced capabilities",
                    "status": "available"
                }
            ]
        }
    
    def set_model_id(self, model_id: str):
        """Set the Claude model ID to use
        
        Args:
            model_id: New model ID to use
        """
        self.model_id = model_id
        print(f"AIErrorAnalyzer model updated to: {self.model_id}")
    
    def get_available_models(self) -> List[str]:
        """Get list of available Claude model IDs
        
        Returns:
            List of available model IDs
        """
        models = self.config.get('available_models', [])
        return [model['id'] for model in models]
    
    def get_model_details(self) -> List[Dict[str, Any]]:
        """Get detailed information about available models
        
        Returns:
            List of model detail dictionaries
        """
        return self.config.get('available_models', [])
    
    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model
        
        Args:
            model_id: Model ID to get info for
            
        Returns:
            Model information dictionary or None if not found
        """
        models = self.config.get('available_models', [])
        for model in models:
            if model['id'] == model_id:
                return model
        return None
    
    def get_recommended_models(self) -> List[str]:
        """Get list of recommended model IDs
        
        Returns:
            List of recommended model IDs
        """
        models = self.config.get('available_models', [])
        return [model['id'] for model in models if model.get('status') == 'recommended']
    
    def reload_config(self, config_path: Optional[str] = None):
        """Reload model configuration from file
        
        Args:
            config_path: Optional path to config file
        """
        self.config = self._load_model_config(config_path)
        print("AI models configuration reloaded")
    
    def set_debug_logging(self, enabled: bool):
        """Enable or disable debug logging
        
        Args:
            enabled: Whether to enable debug logging
        """
        self.debug_logging = enabled
        status = "enabled" if enabled else "disabled"
        print(f"Debug logging {status}")
    
    def is_debug_logging_enabled(self) -> bool:
        """Check if debug logging is enabled
        
        Returns:
            True if debug logging is enabled
        """
        return self.debug_logging
    
    def deduplicate_errors(self, errors: List[Dict[str, Any]]) -> Tuple[List[ErrorCluster], Dict[str, Any]]:
        """Deduplicate similar errors into clusters
        
        Args:
            errors: List of error log entries
            
        Returns:
            Tuple of (error clusters, suppression summary)
        """
        clusters = {}
        
        for error in errors:
            # Create error signature for similarity matching
            signature = self._create_error_signature(error)
            
            if signature in clusters:
                # Add to existing cluster
                cluster = clusters[signature]
                cluster.count += 1
                cluster.last_seen = max(cluster.last_seen, error['timestamp'])
                cluster.first_seen = min(cluster.first_seen, error['timestamp'])
                if len(cluster.all_errors) < self.max_errors_per_cluster:
                    cluster.all_errors.append(error)
                
                # Update sample_error to prefer errors with stackTrace
                current_has_stack = cluster.sample_error.get('stack_trace') or cluster.sample_error.get('traceback')
                new_has_stack = error.get('stack_trace') or error.get('traceback')
                if new_has_stack and not current_has_stack:
                    cluster.sample_error = error
            else:
                # Create new cluster
                clusters[signature] = ErrorCluster(
                    signature=signature,
                    count=1,
                    first_seen=error['timestamp'],
                    last_seen=error['timestamp'],
                    sample_error=error,
                    all_errors=[error]
                )
        
        # Sort clusters by count (most frequent first)
        sorted_clusters = sorted(clusters.values(), key=lambda x: x.count, reverse=True)
        
        # Calculate suppression summary
        total_original_errors = len(errors)
        total_unique_patterns = len(sorted_clusters)
        total_suppressed = total_original_errors - total_unique_patterns
        
        # Get top suppressed errors (clusters with count > 1)
        suppressed_clusters = [c for c in sorted_clusters if c.count > 1]
        top_suppressed = sorted(suppressed_clusters, key=lambda x: x.count - 1, reverse=True)[:5]
        
        suppression_summary = {
            "total_original_errors": total_original_errors,
            "total_unique_patterns": total_unique_patterns,
            "total_suppressed": total_suppressed,
            "suppression_rate": (total_suppressed / total_original_errors * 100) if total_original_errors > 0 else 0,
            "top_suppressed_errors": []
        }
        
        for cluster in top_suppressed:
            # Get the exact error message
            if cluster.sample_error.get('structured_data'):
                body = cluster.sample_error['structured_data'].get('body', '')
                exact_message = str(body) if body else cluster.sample_error.get('message', '')
            else:
                exact_message = cluster.sample_error.get('message', '')
            
            suppression_summary["top_suppressed_errors"].append({
                "message": exact_message,
                "original_count": cluster.count,
                "suppressed_count": cluster.count - 1,
                "error_type": cluster.sample_error.get('error_type', 'unknown'),
                "severity": cluster.sample_error.get('severity', 'unknown')
            })
        
        # Limit to top clusters for analysis
        limited_clusters = sorted_clusters[:self.max_clusters_for_analysis]
        
        return limited_clusters, suppression_summary
    
    def _create_error_signature(self, error: Dict[str, Any]) -> str:
        """Create a signature for error similarity matching
        
        Args:
            error: Error log entry
            
        Returns:
            Error signature string
        """
        # For structured logs, use exception message for precise matching (not body!)
        if error.get('structured_data'):
            structured = error['structured_data']
            
            # Priority: exception.message > errorMessage > body
            # The body often just says "Invocation failed" which groups different errors together
            exception_message = structured.get('attributes', {}).get('exception.message', '')
            error_message = structured.get('errorMessage', '')
            body = structured.get('body', '')
            
            # Use the most specific error message available
            primary_message = exception_message or error_message or body
            
            if primary_message:
                # Use actual error message as primary signature for structured logs
                signature_parts = [
                    'structured_log',
                    str(primary_message).strip()[:500],  # First 500 chars of actual error
                    error.get('error_type', structured.get('attributes', {}).get('exception.type', 'unknown')),
                    structured.get('severityText', ''),
                    # Add code location for more precision
                    structured.get('attributes', {}).get('code.function.name', ''),
                    structured.get('attributes', {}).get('code.file.path', '').split('/')[-1] if structured.get('attributes', {}).get('code.file.path') else ''
                ]
            else:
                # Fallback to message if nothing else available
                signature_parts = [
                    'structured_log_no_body',
                    error.get('message', '')[:200],
                    error.get('error_type', 'unknown')
                ]
        else:
            # For unstructured logs, use normalized message
            message = error.get('message', '')
            error_type = error.get('error_type', 'unknown')
            
            # Normalize the message for similarity matching
            normalized_message = self._normalize_error_message(message)
            
            signature_parts = [
                'unstructured_log',
                error_type,
                normalized_message[:200]
            ]
            
            # Add stack trace signature if available
            if error.get('stack_trace'):
                stack_signature = self._extract_stack_signature(error['stack_trace'])
                signature_parts.append(stack_signature)
        
        # Create hash of the signature
        signature_text = '|'.join(str(part) for part in signature_parts if part)
        return hashlib.sha256(signature_text.encode()).hexdigest()
    
    def _normalize_error_message(self, message: str) -> str:
        """Normalize error message for similarity matching
        
        Args:
            message: Raw error message
            
        Returns:
            Normalized error message
        """
        # Remove timestamps, IDs, and other variable parts
        normalized = message
        
        # Remove common variable patterns
        patterns_to_remove = [
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',  # ISO timestamps
            r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',   # Simple timestamps
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',  # UUIDs
            r'[a-f0-9]{32,}',  # Long hex strings
            r'\b\d+\.\d+\.\d+\.\d+\b',  # IP addresses
            r'\b\d{10,}\b',  # Large numbers (timestamps, etc.)
            r'session[_-]?id[:\s=]+[a-zA-Z0-9-]+',  # Session IDs
            r'trace[_-]?id[:\s=]+[a-f0-9-]+',  # Trace IDs
        ]
        
        for pattern in patterns_to_remove:
            normalized = re.sub(pattern, '[REDACTED]', normalized, flags=re.IGNORECASE)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _extract_stack_signature(self, stack_trace: str) -> str:
        """Extract signature from stack trace
        
        Args:
            stack_trace: Stack trace string
            
        Returns:
            Stack trace signature
        """
        # Extract function names and file paths from stack trace
        lines = stack_trace.split('\n')
        signature_parts = []
        
        for line in lines:
            # Look for function calls and file references
            if 'at ' in line or 'in ' in line:
                # Extract function name
                func_match = re.search(r'(\w+)\s*\(', line)
                if func_match:
                    signature_parts.append(func_match.group(1))
        
        return '->'.join(signature_parts[:5])  # Limit to top 5 functions
    
    async def analyze_errors_with_ai(self, error_clusters: List[ErrorCluster], 
                                   agent_name: str, time_range: str, 
                                   suppression_summary: Optional[Dict[str, Any]] = None) -> str:
        """Analyze error clusters using Claude AI
        
        Args:
            error_clusters: List of deduplicated error clusters
            agent_name: Name of the agent being analyzed
            time_range: Time range of the analysis
            
        Returns:
            AI-generated analysis report
        """
        if not error_clusters:
            return "No errors found for analysis."
        
        # Prepare error data for Claude
        error_summary = self._prepare_error_summary(error_clusters, agent_name, time_range)
        
        # Create prompt for Claude
        prompt = self._create_analysis_prompt(error_summary, agent_name, time_range, suppression_summary)
        
        try:
            print(f"Calling Claude model: {self.model_id}")
            print(f"Analyzing {len(error_clusters)} error clusters for agent: {agent_name}")
            
            # Log the context being sent to Claude
            print(f"\nCONTEXT SENT TO ANTHROPIC MODEL:")
            print(f"=" * 80)
            print(f"Agent: {agent_name}")
            print(f"Time Range: {time_range}")
            print(f"Error Clusters: {len(error_clusters)}")
            
            # Log error summary details
            print(f"\n📈 ERROR SUMMARY:")
            print(f"- Total Errors: {error_summary.get('total_errors', 0)}")
            print(f"- Unique Error Types: {error_summary.get('unique_error_types', 0)}")
            print(f"- Time Span: {error_summary.get('time_span', 'Unknown')}")
            
            # Log suppression summary if available
            if suppression_summary:
                print(f"\n🔇 SUPPRESSION SUMMARY:")
                print(f"- Original Errors: {suppression_summary.get('total_original_errors', 0)}")
                print(f"- Unique Patterns: {suppression_summary.get('total_unique_patterns', 0)}")
                print(f"- Suppressed: {suppression_summary.get('total_suppressed', 0)}")
                print(f"- Suppression Rate: {suppression_summary.get('suppression_rate', 0):.1f}%")
            
            # Log first few error clusters for context
            print(f"\nERROR CLUSTERS (First 3):")
            for i, cluster in enumerate(error_clusters[:3], 1):
                sample = cluster.sample_error
                print(f"  {i}. Count: {cluster.count}, Type: {sample.get('error_type', 'Unknown')}")
                print(f"     Message: {sample.get('message', 'No message')[:100]}...")
                if sample.get('structured_data'):
                    attrs = sample['structured_data'].get('attributes', {})
                    if attrs.get('code.function.name'):
                        print(f"     Function: {attrs['code.function.name']}")
            
            # Log the actual prompt being sent
            if self.debug_logging:
                print(f"\nFULL PROMPT SENT TO CLAUDE:")
                print(f"-" * 80)
                print(prompt)
                print(f"-" * 80)
            else:
                print(f"\nPROMPT PREVIEW (First 500 chars):")
                print(f"-" * 50)
                print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
                print(f"-" * 50)
            
            print(f"Total Prompt Length: {len(prompt)} characters")
            
            # Log request parameters
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            print(f"\nREQUEST PARAMETERS:")
            print(f"- Model ID: {self.model_id}")
            print(f"- Max Tokens: {request_body['max_tokens']}")
            print(f"- Temperature: {request_body['temperature']}")
            print(f"- Anthropic Version: {request_body['anthropic_version']}")
            print(f"=" * 80)
            
            # Call Claude via Bedrock with fallback support
            from src.config.config import get_fallback_models
            fallback_models = get_fallback_models()
            models_to_try = [self.model_id] + fallback_models
            
            response = None
            last_error = None
            
            for attempt, current_model_id in enumerate(models_to_try, 1):
                try:
                    if attempt > 1:
                        print(f"\nFALLBACK ATTEMPT {attempt}/{len(models_to_try)}")
                        print(f"   Location: ai_error_analyzer.py, line ~569 (_analyze_with_ai method)")
                        print(f"   Retrying with model: {current_model_id}")
                    else:
                        print(f"\nPRIMARY MODEL ATTEMPT")
                        print(f"   Location: ai_error_analyzer.py, line ~569 (_analyze_with_ai method)")
                        print(f"   Using model: {current_model_id}")
                    
                    response = self.bedrock_client.invoke_model(
                        modelId=current_model_id,
                        body=json.dumps({
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 4000,
                            "temperature": 0.1,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ]
                        })
                    )
                    
                    if attempt > 1:
                        print(f"SUCCESS WITH FALLBACK MODEL: {current_model_id}")
                        print(f"   Location: ai_error_analyzer.py, line ~569")
                    else:
                        print(f"SUCCESS WITH PRIMARY MODEL: {current_model_id}")
                    
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    error_msg = str(e)
                    last_error = e
                    
                    # Log the error details
                    print(f"\nBEDROCK ERROR OCCURRED")
                    print(f"   Location: ai_error_analyzer.py, line ~569 (_analyze_with_ai method)")
                    print(f"   Model: {current_model_id}")
                    print(f"   Attempt: {attempt}/{len(models_to_try)}")
                    print(f"   Error Type: {type(e).__name__}")
                    print(f"   Error Message: {error_msg[:200]}...")
                    
                    # Check if it's a rate limit / connection error
                    is_rate_limit = any(keyword in error_msg for keyword in [
                        'ServiceUnavailableException',
                        'Too many connections',
                        'ThrottlingException',
                        'rate limit',
                        'TooManyRequestsException'
                    ])
                    
                    if is_rate_limit:
                        print(f"RATE LIMIT DETECTED")
                        print(f"   Location: ai_error_analyzer.py, line ~569")
                        print(f"   Failed model: {current_model_id}")
                        
                        if attempt < len(models_to_try):
                            print(f"   Will retry with next fallback model in 2 seconds...")
                            import time
                            time.sleep(2)  # Brief delay before retry
                            continue
                        else:
                            print(f"   NO MORE FALLBACK MODELS AVAILABLE")
                            raise
                    else:
                        print(f"   NON-RATE-LIMIT ERROR - Not retrying")
                        print(f"   Location: ai_error_analyzer.py, line ~569")
                        raise
            
            if response is None:
                # All models failed
                print(f"\nALL MODELS FAILED")
                print(f"   Location: ai_error_analyzer.py, line ~569")
                print(f"   Tried {len(models_to_try)} models")
                print(f"   Last error: {last_error}")
                raise Exception(f"All models failed. Last error: {last_error}")
            
            # Parse response
            response_body = json.loads(response['body'].read())
            raw_analysis = response_body['content'][0]['text']
            
            # Log response details
            print(f"\nRESPONSE FROM ANTHROPIC MODEL:")
            print(f"=" * 80)
            print(f"Analysis completed successfully")
            print(f"Response Length: {len(raw_analysis)} characters")
            
            if self.debug_logging:
                print(f"FULL RESPONSE FROM CLAUDE:")
                print(f"-" * 80)
                print(raw_analysis)
                print(f"-" * 80)
            else:
                print(f"Response Preview (First 300 chars):")
                print(f"-" * 50)
                print(raw_analysis[:300] + "..." if len(raw_analysis) > 300 else raw_analysis)
                print(f"-" * 50)
            
            # Log token usage if available in response
            if 'usage' in response_body:
                usage = response_body['usage']
                print(f"Token Usage:")
                print(f"- Input Tokens: {usage.get('input_tokens', 'N/A')}")
                print(f"- Output Tokens: {usage.get('output_tokens', 'N/A')}")
                print(f"- Total Tokens: {usage.get('total_tokens', 'N/A')}")
            
            print(f"=" * 80)
            
            # Return the raw analysis text as-is (like before)
            print(f"AI analysis completed successfully")
            return raw_analysis
            
        except Exception as e:
            error_msg = str(e)
            print(f"Claude analysis failed: {error_msg}")
            
            # Re-raise the exception so the dashboard can handle it properly
            raise e
    
    def _prepare_error_summary(self, error_clusters: List[ErrorCluster], 
                             agent_name: str, time_range: str) -> Dict[str, Any]:
        """Prepare error data summary for AI analysis
        
        Args:
            error_clusters: List of error clusters
            agent_name: Agent name
            time_range: Time range
            
        Returns:
            Error summary dictionary
        """
        summary = {
            "agent_name": agent_name,
            "time_range": time_range,
            "total_errors": sum(cluster.count for cluster in error_clusters),
            "unique_error_types": len(error_clusters),
            "error_clusters": []
        }
        
        for cluster in error_clusters:
            sample_error = cluster.sample_error
            
            # For structured logs, prioritize body text over message
            if sample_error.get('structured_data'):
                structured = sample_error['structured_data']
                primary_message = structured.get('body', sample_error.get('message', ''))
                
                cluster_data = {
                    "count": cluster.count,
                    "first_seen": self._format_datetime_for_ai(cluster.first_seen),
                    "last_seen": self._format_datetime_for_ai(cluster.last_seen),
                    "error_type": sample_error.get('error_type', 'unknown'),
                    "severity": sample_error.get('severity', 'unknown'),
                    "category": sample_error.get('category', 'unknown'),
                    "primary_message": str(primary_message),  # Exact body text for structured logs
                    "raw_message": sample_error.get('message', '')[:200],  # Keep raw message for context
                    "level": sample_error.get('level', 'unknown'),
                    "service_name": sample_error.get('service_name', ''),
                    "trace_id": sample_error.get('trace_id', ''),
                    "log_type": "structured"
                }
                
                # Add detailed structured data
                attributes = structured.get('attributes', {})
                
                # Extract file path and make it prominent
                code_file_path = attributes.get('code.file.path', '')
                code_function = attributes.get('code.function.name', '')
                code_line = attributes.get('code.line.number', '')
                
                # Extract just the filename from full path for easier identification
                code_filename = code_file_path.split('/')[-1] if code_file_path else ''
                
                # Check if this is agent code (not library code)
                # Check for common app directories or agent-specific files
                app_dirs = ['/app/', '/code/', '/src/', '/opt/app/', '/usr/src/app/', '/lambda/', '/var/task/']
                is_agent_code = any(app_dir in code_file_path for app_dir in app_dirs) or code_file_path.startswith('agent')
                
                cluster_data["structured_details"] = {
                    "severity_text": structured.get('severityText', ''),
                    "body": str(structured.get('body', '')),
                    "scope_name": structured.get('scope', {}).get('name', ''),
                    "code_location": {
                        "file": code_file_path,
                        "filename": code_filename,
                        "function": code_function,
                        "line": code_line,
                        "is_agent_code": is_agent_code,
                        "location_summary": f"{code_filename}:{code_line} in {code_function}" if code_filename and code_function else ""
                    },
                    "exception_details": {
                        "exception_type": attributes.get('exception.type', ''),
                        "exception_message": attributes.get('exception.message', ''),
                        "exception_stacktrace": attributes.get('exception.stacktrace', '')
                    },
                    "resource_info": {
                        "service_name": structured.get('resource', {}).get('attributes', {}).get('service.name', ''),
                        "cloud_resource_id": structured.get('resource', {}).get('attributes', {}).get('cloud.resource_id', ''),
                        "deployment_env": structured.get('resource', {}).get('attributes', {}).get('deployment.environment.name', '')
                    }
                }
            else:
                # For unstructured logs, use the original approach
                cluster_data = {
                    "count": cluster.count,
                    "first_seen": self._format_datetime_for_ai(cluster.first_seen),
                    "last_seen": self._format_datetime_for_ai(cluster.last_seen),
                    "error_type": sample_error.get('error_type', 'unknown'),
                    "severity": sample_error.get('severity', 'unknown'),
                    "category": sample_error.get('category', 'unknown'),
                    "primary_message": sample_error.get('message', '')[:500],
                    "level": sample_error.get('level', 'unknown'),
                    "service_name": sample_error.get('service_name', ''),
                    "trace_id": sample_error.get('trace_id', ''),
                    "log_type": "unstructured"
                }
                
                # Add stack trace if available (truncated)
                if sample_error.get('stack_trace'):
                    cluster_data["stack_trace"] = sample_error['stack_trace'][:1000]
            
            summary["error_clusters"].append(cluster_data)
        
        return summary
    
    def _create_analysis_prompt(self, error_summary: Dict[str, Any], 
                              agent_name: str, time_range: str,
                              suppression_summary: Optional[Dict[str, Any]] = None) -> str:
        """Create analysis prompt for Claude with structured JSON response
        
        Args:
            error_summary: Prepared error summary
            agent_name: Agent name
            time_range: Time range
            suppression_summary: Optional deduplication summary
            
        Returns:
            Analysis prompt string requesting structured JSON response
        """
        # Add suppression info to prompt if available
        suppression_info = ""
        if suppression_summary:
            suppression_info = f"""
DEDUPLICATION SUMMARY:
- Original error count: {suppression_summary['total_original_errors']}
- Unique error patterns: {suppression_summary['total_unique_patterns']}
- Suppressed duplicates: {suppression_summary['total_suppressed']} ({suppression_summary['suppression_rate']:.1f}% reduction)

TOP SUPPRESSED ERRORS (Most Frequent Duplicates):
{json.dumps(suppression_summary['top_suppressed_errors'], indent=2)}
"""

        prompt = f"""You are an expert AI system administrator and developer analyzing errors from an Amazon Bedrock AgentCore agent named "{agent_name}" over the time period: {time_range}.

I have {error_summary['total_errors']} total errors clustered into {error_summary['unique_error_types']} unique error patterns based on EXACT error message matching (not similarity). Each cluster represents identical error messages that occurred multiple times.
{suppression_info}
ERROR CLUSTERS (Exact Matches):
{json.dumps(error_summary['error_clusters'], indent=2)}

IMPORTANT CONTEXT:
- These are OpenTelemetry structured logs from Amazon Bedrock AgentCore
- "primary_message" contains the exact error text from the log body
- "structured_details" contains code location and resource information
- Clusters are based on EXACT message matching, so each represents a specific recurring issue

Please provide a comprehensive analysis including:

1. **EXECUTIVE SUMMARY**: Brief overview of the error situation and overall health assessment

2. **CRITICAL ISSUES**: Most urgent problems that need immediate attention (if any)

3. **ERROR PATTERN ANALYSIS**: 
   - What are the main error patterns based on exact error messages?
   - Are there any cascading failures or related errors?
   - Frequency and timing analysis of recurring issues

4. **ROOT CAUSE ANALYSIS**:
   - What are the likely root causes for each specific error message?
   - Are there infrastructure, code, or configuration issues?
   - Look at code locations (file, function, line) for clues

5. **IMPACT ASSESSMENT**:
   - How severe are these specific errors for the agent's functionality?
   - Are there any user-facing impacts?
   - Which errors are warnings vs actual failures?

6. **ACTIONABLE RECOMMENDATIONS**:
   - Immediate actions to take (priority order)
   - Code fixes for specific file/function locations with actual code examples
   - Configuration changes needed
   - Long-term improvements and prevention strategies

7. **TECHNICAL INSIGHTS**:
   - Analysis of code locations and function names
   - OpenTelemetry instrumentation issues
   - Resource or performance related problems
   - Integration or dependency problems

Focus on the EXACT error messages and their specific meanings. Be specific about which files and functions need attention. Provide detailed code examples and actionable fixes that developers can implement immediately. Use technical language appropriate for DevOps and development teams."""
        
        return prompt
    
    def _generate_basic_analysis(self, error_clusters: List[ErrorCluster]) -> str:
        """Generate basic analysis as fallback
        
        Args:
            error_clusters: List of error clusters
            
        Returns:
            Basic analysis string
        """
        if not error_clusters:
            return "No errors found for analysis."
        
        total_errors = sum(cluster.count for cluster in error_clusters)
        
        analysis = f"""BASIC ERROR ANALYSIS
===================

Total Errors: {total_errors}
Unique Error Types: {len(error_clusters)}

TOP ERROR PATTERNS:
"""
        
        for i, cluster in enumerate(error_clusters[:5], 1):
            analysis += f"""
{i}. Error Type: {cluster.sample_error.get('error_type', 'unknown')}
   Count: {cluster.count}
   Severity: {cluster.sample_error.get('severity', 'unknown')}
   First Seen: {self._format_datetime_for_ai(cluster.first_seen)}
   Last Seen: {self._format_datetime_for_ai(cluster.last_seen)}
   Sample Message: {cluster.sample_error.get('message', '')[:200]}...
"""
        
        return analysis
    
    def _extract_recommendations_from_text(self, text: str) -> List[str]:
        """Extract recommendations from text analysis as fallback
        
        Args:
            text: Raw text analysis
            
        Returns:
            List of extracted recommendations
        """
        recommendations = []
        
        # Look for common recommendation patterns
        lines = text.split('\n')
        in_recommendations_section = False
        
        for line in lines:
            line = line.strip()
            
            # Check if we're entering a recommendations section
            if any(keyword in line.lower() for keyword in ['recommendation', 'action', 'fix', 'solution']):
                in_recommendations_section = True
                continue
            
            # Extract numbered or bulleted recommendations
            if in_recommendations_section and line:
                if (line.startswith(('1.', '2.', '3.', '4.', '5.', '-', '*', '•')) or
                    'add' in line.lower() or 'fix' in line.lower() or 'update' in line.lower()):
                    # Clean up the recommendation
                    clean_rec = line.lstrip('1234567890.-*• ').strip()
                    if len(clean_rec) > 10:  # Only add substantial recommendations
                        recommendations.append(clean_rec)
            
            # Stop if we hit another major section
            if line.isupper() and len(line) > 5:
                in_recommendations_section = False
        
        # If no recommendations found, create generic ones
        if not recommendations:
            recommendations = [
                "Review error logs for specific issues",
                "Check agent configuration and dependencies",
                "Monitor agent performance and resource usage"
            ]
        
        return recommendations[:10]  # Limit to 10 recommendations
    
    def get_error_statistics(self, error_clusters: List[ErrorCluster]) -> Dict[str, Any]:
        """Get statistical summary of error clusters
        
        Args:
            error_clusters: List of error clusters
            
        Returns:
            Statistics dictionary
        """
        if not error_clusters:
            return {}
        
        total_errors = sum(cluster.count for cluster in error_clusters)
        
        # Group by severity
        severity_counts = defaultdict(int)
        error_type_counts = defaultdict(int)
        
        for cluster in error_clusters:
            severity = cluster.sample_error.get('severity', 'unknown')
            error_type = cluster.sample_error.get('error_type', 'unknown')
            
            severity_counts[severity] += cluster.count
            error_type_counts[error_type] += cluster.count
        
        # Calculate time span
        all_timestamps = []
        for cluster in error_clusters:
            all_timestamps.extend([cluster.first_seen, cluster.last_seen])
        
        time_span = max(all_timestamps) - min(all_timestamps) if all_timestamps else None
        
        return {
            "total_errors": total_errors,
            "unique_patterns": len(error_clusters),
            "severity_distribution": dict(severity_counts),
            "error_type_distribution": dict(error_type_counts),
            "time_span": time_span,
            "most_frequent_error": error_clusters[0].sample_error.get('error_type', 'unknown') if error_clusters else None,
            "error_rate": total_errors / time_span.total_seconds() * 3600 if time_span and time_span.total_seconds() > 0 else 0
        }
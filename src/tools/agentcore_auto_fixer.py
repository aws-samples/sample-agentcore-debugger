"""
AgentCore Auto-Fixer Tool - Automated debugging and testing
"""
import os
import subprocess
import tempfile
import shutil
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from contextlib import contextmanager
import boto3

# Add parent directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from agents.strands_orchestrator import StrandsOrchestrator
from analyzers.ai_error_analyzer import AIErrorAnalyzer
from utils.agentcore_network_patcher import patch_agent_workspace_config


@contextmanager
def change_directory(path):
    """Context manager for safely changing directories"""
    original_dir = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(original_dir)


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


def is_success_status(status: Any) -> bool:
    """Check if status indicates success (case-insensitive)"""
    if not status:
        return False
    
    success_values = ['success', 'successful', 'completed', 'ok', 'active', 'ready', 'prepared']
    return str(status).lower().strip() in success_values


def is_python_file(filename: str) -> bool:
    """Check if filename is a Python file (case-insensitive)"""
    if not filename:
        return False
    
    python_extensions = ['.py', '.pyx', '.py3', '.pyw']
    return any(filename.lower().endswith(ext) for ext in python_extensions)


def contains_rate_limit_keywords(text: str) -> bool:
    """Check if text contains rate limiting related keywords (case-insensitive)"""
    if not text:
        return False
    
    rate_limit_keywords = [
        'rate limit', 'rate-limit', 'ratelimit', 'rate limiting', 'rate-limiting',
        'throttl', 'throttling', 'throttled', 'too many requests', '429',
        'quota exceeded', 'api limit', 'request limit'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in rate_limit_keywords)



class AgentCoreAutoFixer:
    """Automated AgentCore debugging and fixing tool"""
    
    def __init__(self, work_dir: Optional[str] = None, agent_id: Optional[str] = None, time_range: Optional[str] = None, force_new: bool = True):
        """Initialize the auto-fixer
        
        Args:
            work_dir: Working directory for temporary files (defaults to temp dir)
            agent_id: Agent ID for shared workspace (if provided, creates agent-specific workspace)
            time_range: Time range identifier (e.g., "20251101-20251105") to isolate workspaces by time period
            force_new: If True, always create a fresh workspace with timestamp (default: True)
        """
        if work_dir:
            self.work_dir = Path(work_dir)
        else:
            # Create a permanent directory under the AGENTCORE-DEBUGGER root folder
            # Use resolve() to get absolute path regardless of where Python is running from
            project_root = Path(__file__).resolve().parent.parent.parent  # This is the AGENTCORE-DEBUGGER root
            
            if agent_id:
                # Clean agent_id for directory name
                clean_agent_id = agent_id.replace('-DEFAULT', '').replace('_', '-').lower()
                
                # Always include timestamp to ensure fresh workspace for each fix
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                if time_range:
                    # Clean time_range for directory name (remove special chars)
                    clean_time_range = time_range.replace(':', '').replace(' ', '_').replace('-', '')
                    workspace_name = f"agent_{clean_agent_id}_{clean_time_range}_{timestamp}"
                else:
                    workspace_name = f"agent_{clean_agent_id}_{timestamp}"
                
                self.work_dir = project_root / "agentcore_fixes" / workspace_name
                self.is_shared_workspace = False  # Each fix gets its own workspace now
            else:
                # Legacy: unique directory per execution
                self.work_dir = project_root / "agentcore_fixes" / f"fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.is_shared_workspace = False
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # Track extracted code path for reuse in Fix All operations
        # This allows subsequent fixes to build on previous fixes in the same workspace
        self._extracted_code_path: Optional[Path] = None
        self._code_analysis: Optional[Dict[str, Any]] = None
        
        # Log the working directory for easy access
        if agent_id:
            print(f"🗂️  Shared workspace for agent: {agent_id}")
        print(f"🗂️  Working directory: {self.work_dir}")
        print(f"You can find extracted code and reports at: {self.work_dir.absolute()}")
        
        # Also log to agent_execution.log if possible
        try:
            import logging
            agent_logger = logging.getLogger('AgentDashboard')
            agent_logger.info(f"AUTO_FIXER: 🗂️ Working directory: {self.work_dir}")
            agent_logger.info(f"AUTO_FIXER: You can find extracted code and reports at: {self.work_dir.absolute()}")
        except:
            pass  # If logging fails, just continue
        
        # Initialize AWS clients with adaptive retry
        from src.core.retry_config import ADAPTIVE_RETRY
        self.ecr_client = boto3.client('ecr', config=ADAPTIVE_RETRY)
        self.bedrock_client = boto3.client('bedrock-agentcore-control', config=ADAPTIVE_RETRY)
        
        # ECR extractor (no Docker needed)
        from src.tools.ecr_extractor import ECRExtractor
        self.ecr_extractor = ECRExtractor()
        
        # Initialize workflow cache (shared across instances for same agent)
        # Cache key format: workflow_{type}_{agent_id}_{error_hash}
        # This cache persists across pattern processing but is cleared when:
        # - Agent changes (different agent_id)
        # - Time period changes (handled by dashboard)
        # - User manually clears cache
        if not hasattr(AgentCoreAutoFixer, '_workflow_cache'):
            AgentCoreAutoFixer._workflow_cache = {}
        self._workflow_cache = AgentCoreAutoFixer._workflow_cache
        
        # Results tracking
        self.results = {
            'start_time': datetime.now(),
            'steps': [],
            'errors': [],
            'fixes_applied': [],
            'test_results': {},
            'final_status': 'pending'
        }
    

    
    def auto_fix_agent(self, agent_runtime_id: str, ai_analysis: Dict[str, Any], initial_choice: str = None) -> Dict[str, Any]:
        """Automated fix workflow using intelligent multi-agent system
        
        Args:
            agent_runtime_id: AgentCore Runtime ID
            ai_analysis: AI analysis results with recommendations
            initial_choice: Pre-selected user choice for mixed patterns ('library', 'code', 'both', 'skip')
            
        Returns:
            Dictionary with results from multi-agent system
        """
        try:
            self._log_step("Starting intelligent multi-agent AgentCore fix workflow")
            
            # Skip model health check during execution (already checked at app startup)
            # This saves 2-3 seconds per execution
            # Model health is checked once when the Streamlit app starts
            
            # Step 1: Classify error type to determine if ECR download is needed
            self._log_step("� INPPUT AI ANALYSIS RECEIVED:")
            analysis_preview = str(ai_analysis)[:200] + "..." if len(str(ai_analysis)) > 200 else str(ai_analysis)
            self._log_step(f"   Analysis preview: {analysis_preview}")
            
            error_classification = self._classify_error_type(ai_analysis)
            
            # Step 2: Route based on error type with detailed logging
            self._log_step("="*80)
            self._log_step("WORKFLOW ROUTING BASED ON CLASSIFICATION")
            self._log_step("="*80)
            
            if error_classification['type'] == 'package_only':
                # Package-only issues: Run Library Agent, then let user choose
                self._log_step("PACKAGE-ONLY WORKFLOW SELECTED:")
                self._log_step("   Library Agent: WILL RUN AUTOMATICALLY (fast analysis)")
                self._log_step("   ❓ Code Agent: USER CAN CHOOSE after seeing recommendations")
                self._log_step("   Focus: Package/dependency/library issues with optional code fix")
                return self._handle_package_workflow_with_choice(agent_runtime_id, ai_analysis, error_classification)
            
            elif error_classification['type'] == 'code_fix_required':
                # Code issues: Need ECR download and Code Agent
                self._log_step("CODE-FIX WORKFLOW SELECTED:")
                self._log_step("   Library Agent: WILL BE SKIPPED")
                self._log_step("   Code Agent: WILL BE USED")
                self._log_step("   ECR Download: REQUIRED")
                self._log_step("   Focus: Code modifications and fixes")
                return self._handle_code_fix_issue(agent_runtime_id, ai_analysis, error_classification)
            
            else:
                # Mixed: Run Library Agent first, then let user choose (or use pre-selected choice)
                self._log_step("MIXED ISSUE DETECTED - HYBRID WORKFLOW:")
                if initial_choice:
                    self._log_step(f"   User choice PRE-SELECTED: {initial_choice}")
                    self._log_step("   Will use cached analysis if available")
                else:
                    self._log_step("   Library Agent: WILL RUN AUTOMATICALLY (fast analysis)")
                    self._log_step("   ❓ Code Agent: USER WILL CHOOSE after seeing library analysis")
                self._log_step("   Focus: Informed decision-making")
                return self._handle_mixed_workflow_with_choice(agent_runtime_id, ai_analysis, error_classification, initial_choice)
            
        except Exception as e:
            self._log_error(f"Multi-agent workflow failed: {e}")
            self.results['final_status'] = 'failed'
            self.results['end_time'] = datetime.now()
            
            return {
                'status': 'failed',
                'error': str(e),
                'results': self.results
            }
    
    def _classify_error_type(self, ai_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Use AI model to intelligently classify error type with enhanced logging"""
        
        self._log_step("="*80)
        self._log_step("ERROR CLASSIFICATION PHASE STARTED")
        self._log_step("="*80)
        
        # Check for cached classification first (from UI)
        cached_classification = ai_analysis.get('cached_classification')
        if cached_classification:
            self._log_step("USING CACHED AI CLASSIFICATION FROM UI:")
            self._log_step(f"   Type: {cached_classification.get('type')}")
            self._log_step(f"   Confidence: {cached_classification.get('confidence')}")
            self._log_step(f"   💭 Reasoning: {cached_classification.get('reasoning')}")
            self._log_step("   Skipping duplicate AI call (already classified in UI)")
            self._log_step("="*80)
            return cached_classification
        
        try:
            # Extract full error information
            self._log_step("EXTRACTING ERROR INFORMATION:")
            
            if isinstance(ai_analysis, dict):
                error_details = ai_analysis.get('error_details', {})
                error_message = error_details.get('message', '')
                error_traceback = error_details.get('traceback', '')
                error_level = error_details.get('level', '')
                summary = ai_analysis.get('summary', '')
                recommendations = ai_analysis.get('recommendations', [])
                
                self._log_step(f"   Error Message: {error_message[:100]}{'...' if len(error_message) > 100 else ''}")
                self._log_step(f"   🎚️ Error Level: {error_level}")
                self._log_step(f"   Summary: {summary[:100]}{'...' if len(summary) > 100 else ''}")
                self._log_step(f"   Recommendations: {len(recommendations)} items")
                self._log_step(f"   Has Traceback: {'Yes' if error_traceback else 'No'}")
            else:
                error_message = str(ai_analysis)
                error_traceback = ''
                error_level = ''
                summary = ''
                recommendations = []
                
                self._log_step(f"   Simple Error Message: {error_message[:100]}{'...' if len(error_message) > 100 else ''}")
                self._log_step("   No structured error details available")
            
            # Create comprehensive prompt for AI classification
            classification_prompt = f"""You are an expert system administrator analyzing AgentCore errors to determine the optimal fix approach.

**Error Information:**
- Error Message: {error_message}
- Error Level: {error_level}
- Summary: {summary}
- Recommendations: {recommendations}
- Traceback: {error_traceback}

**Your Task:**
Classify this error into one of three categories to determine the fix approach:

1. **package_only** - Package/library/dependency issues that can be resolved ONLY with package management:
   - Missing modules or import errors (e.g., "ModuleNotFoundError: No module named 'requests'")
   - Package version conflicts
   - Dependency issues
   - Library configuration problems
   - Security vulnerabilities in packages
   - Installation/upgrade issues
   - Instrumentation/tracing library conflicts
   - These do NOT require downloading agent code from ECR

2. **code_fix_required** - Code issues that can ONLY be fixed by modifying the agent source code:
   - Syntax errors in agent code (e.g., "SyntaxError: invalid syntax")
   - Logic errors in agent implementation (e.g., wrong algorithm, incorrect conditions)
   - Wrong function arguments where the API signature hasn't changed (e.g., "TypeError: function() takes 2 positional arguments but 3 were given")
   - Configuration errors in agent code
   - These REQUIRE downloading agent code from ECR to fix
   - Package upgrade would NOT solve these issues
   - **IMPORTANT**: If error is "AttributeError: module 'X' has no attribute 'Y'", this is likely MIXED (old package version), NOT code_fix_required

3. **mixed** - Issues that could be solved by EITHER upgrading packages OR fixing code:
   - API deprecation errors (e.g., "AttributeError: 'DataFrame' object has no attribute 'append'")
     → Can upgrade pandas OR change code to use pd.concat()
   - Missing API in old package version (e.g., "AttributeError: module 'torch' has no attribute 'linalg'")
     → Can upgrade torch OR use old API (torch.norm instead of torch.linalg.norm)
   - Missing submodule in old version (e.g., "AttributeError: module 'torch' has no attribute 'linalg'")
     → torch.linalg was added in torch 1.13, can upgrade OR use torch.norm()
   - Method signature changes (e.g., function expects different parameters in new version)
     → Can upgrade package OR adjust code to match old signature
   - Deprecated functions with alternatives (e.g., "np.int is deprecated")
     → Can upgrade numpy OR change code to use int()
   
   **Key indicators for mixed** (ALWAYS classify as mixed if you see these patterns):
   - "AttributeError: module 'X' has no attribute 'Y'" → Old package version missing API
   - "AttributeError: 'ClassName' object has no attribute 'method'" → Deprecated/removed method
   - "has no attribute" + library name (torch, numpy, pandas, etc.) → Version mismatch
   - Error mentions API that was added in newer version → Can upgrade OR use old API
   - Error mentions deprecated API → Can upgrade OR change code
   
   **Examples that MUST be classified as mixed:**
   - "AttributeError: module 'torch' has no attribute 'linalg'" → MIXED (upgrade torch OR use torch.norm)
   - "AttributeError: module 'numpy' has no attribute 'int'" → MIXED (upgrade numpy OR use int())
   - "AttributeError: 'DataFrame' object has no attribute 'append'" → MIXED (upgrade pandas OR use concat)

**Classification Decision Tree:**
Follow this decision tree for accurate classification:

1. Is it an import/module error (ModuleNotFoundError, ImportError)?
   → YES: **package_only**
   → NO: Continue to step 2

2. Is it a syntax/indentation error in code?
   → YES: **code_fix_required**
   → NO: Continue to step 3

3. Is it "AttributeError: module/object 'X' has no attribute 'Y'" with a library name?
   → YES: **mixed** (version mismatch - can upgrade package OR change code)
   → NO: Continue to step 4

4. Is it a deprecated API with an alternative mentioned?
   → YES: **mixed** (can upgrade package OR change code to use alternative)
   → NO: Continue to step 5

5. Is it an instrumentation/tracing/telemetry configuration issue?
   → YES: **package_only**
   → NO: Continue to step 6

6. Is it a logic error, rate limit, timeout, or algorithm issue?
   → YES: **code_fix_required**
   → NO: Default to **mixed** (when uncertain, give user both options)

**Response Format:**
Respond with ONLY a JSON object in this exact format:
{{
    "type": "package_only",
    "confidence": 0.9,
    "reasoning": "Brief explanation of why this classification was chosen"
}}

**Classification Examples:**

**package_only examples:**
- "ModuleNotFoundError: No module named 'requests'" → {{"type": "package_only", "confidence": 0.95, "reasoning": "Missing package dependency"}}
- "ImportError: cannot import name 'deprecated' from 'typing_extensions'" → {{"type": "package_only", "confidence": 0.95, "reasoning": "Package version conflict"}}
- "Attempting to instrument while already instrumented" → {{"type": "package_only", "confidence": 0.9, "reasoning": "Instrumentation library conflict"}}

**code_fix_required examples:**
- "SyntaxError: invalid syntax in agent.py line 42" → {{"type": "code_fix_required", "confidence": 0.95, "reasoning": "Syntax error in agent code"}}
- "NameError: name 'undefined_var' is not defined" → {{"type": "code_fix_required", "confidence": 0.9, "reasoning": "Undefined variable in code"}}
- "Rate limit exceeded in API call" → {{"type": "code_fix_required", "confidence": 0.85, "reasoning": "Needs retry logic in code"}}
- "TypeError: function() takes 2 positional arguments but 3 were given" → {{"type": "code_fix_required", "confidence": 0.9, "reasoning": "Wrong number of arguments in function call"}}

**mixed examples:**
- "AttributeError: module 'torch' has no attribute 'linalg'" → {{"type": "mixed", "confidence": 0.95, "reasoning": "torch.linalg added in v1.13 - can upgrade torch OR use torch.norm()"}}
- "AttributeError: module 'numpy' has no attribute 'int'" → {{"type": "mixed", "confidence": 0.95, "reasoning": "numpy.int deprecated - can upgrade numpy OR use int()"}}
- "AttributeError: 'DataFrame' object has no attribute 'append'" → {{"type": "mixed", "confidence": 0.95, "reasoning": "pandas.append deprecated - can upgrade pandas OR use pd.concat()"}}
- "DeprecationWarning: np.float is deprecated, use float instead" → {{"type": "mixed", "confidence": 0.9, "reasoning": "Deprecated API - can upgrade numpy OR change code"}}

Analyze the error and provide your classification:"""

            self._log_step("AI CLASSIFICATION ANALYSIS:")
            self._log_step(f"   Classification prompt length: {len(classification_prompt)} characters")
            self._log_step("   Classification options: package_only, code_fix_required, mixed")
            self._log_step("   🧠 Using Claude Sonnet 4.5 for intelligent classification")
            
            # Use Bedrock to get AI classification with Claude Sonnet 4.5
            import boto3
            import json
            import time
            from botocore.exceptions import EventStreamError, ClientError
            
            self._log_step("🔗 CONNECTING TO AWS BEDROCK:")
            from src.core.retry_config import ADAPTIVE_RETRY
            bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1', config=ADAPTIVE_RETRY)
            self._log_step("   Bedrock client initialized")
            
            # Call Claude via Bedrock for classification with fallback model support
            from src.config.config import get_fallback_models, get_model_id
            fallback_models = get_fallback_models()
            # Use configured model ID (from env var) as primary, then fallbacks
            primary_model = get_model_id()
            models_to_try = [primary_model] + fallback_models
            
            response = None
            retry_delay = 2
            
            for attempt, model_id in enumerate(models_to_try, 1):
                try:
                    model_name = model_id.split('/')[-1] if '/' in model_id else model_id
                    if attempt == 1:
                        self._log_step(f"INVOKING CLAUDE FOR CLASSIFICATION (Attempt {attempt}/{len(models_to_try)}):")
                    else:
                        self._log_step(f"FALLBACK MODEL ATTEMPT {attempt}/{len(models_to_try)}:")
                    self._log_step(f"   Model: {model_name}")
                    self._log_step("   Temperature: 0.1 (deterministic)")
                    self._log_step("   Max Tokens: 500")
                    
                    response = bedrock_client.invoke_model(
                        modelId=model_id,
                        body=json.dumps({
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 500,
                            "temperature": 0.1,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": classification_prompt
                                }
                            ]
                        })
                    )
                    
                    if attempt > 1:
                        self._log_step(f"   Classification successful with fallback model #{attempt}")
                    else:
                        self._log_step(f"   Classification successful")
                    break  # Success, exit retry loop
                    
                except (EventStreamError, ClientError) as e:
                    error_msg = str(e)
                    self._log_error(f"   Bedrock error on attempt {attempt}/{len(models_to_try)}: {error_msg}")
                    
                    # Check if it's a retryable error
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'serviceunavailableexception', 'throttlingexception', 'too many connections',
                        'service unavailable', 'throttling', 'rate limit'
                    ])
                    
                    if 'AccessDeniedException' in error_msg:
                        self._log_error(f"   Access denied - check IAM permissions")
                        raise  # Don't retry on permission errors
                    
                    if is_retryable and attempt < len(models_to_try):
                        self._log_step(f"   Switching to fallback model...")
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 1.5, 10)  # Exponential backoff, capped at 10s
                    elif attempt >= len(models_to_try):
                        self._log_error(f"   All {len(models_to_try)} models exhausted")
                        raise
                    else:
                        raise  # Non-retryable error
            
            if response is None:
                raise Exception("Failed to get classification response after retries")
            
            # Parse response
            response_body = json.loads(response['body'].read())
            classification_response = response_body['content'][0]['text']
            
            self._log_step("AI CLASSIFICATION RESPONSE RECEIVED:")
            self._log_step(f"   Response length: {len(classification_response)} characters")
            self._log_step(f"   Raw response: {classification_response[:200]}{'...' if len(classification_response) > 200 else ''}")
            
            # Parse JSON response
            try:
                # Extract JSON from response if it's wrapped in text
                response_text = classification_response.strip()
                if '```json' in response_text:
                    # Extract JSON from code block
                    start = response_text.find('```json') + 7
                    end = response_text.find('```', start)
                    json_text = response_text[start:end].strip()
                elif '{' in response_text and '}' in response_text:
                    # Extract JSON from text
                    start = response_text.find('{')
                    end = response_text.rfind('}') + 1
                    json_text = response_text[start:end]
                else:
                    json_text = response_text
                
                classification_result = json.loads(json_text)
                
                # Validate required fields
                if 'type' not in classification_result:
                    raise ValueError("Missing 'type' field in classification")
                
                if classification_result['type'] not in ['package_only', 'code_fix_required', 'mixed']:
                    raise ValueError(f"Invalid type: {classification_result['type']}")
                
                # Set defaults for missing fields
                classification_result.setdefault('confidence', 0.8)
                classification_result.setdefault('reasoning', 'AI classification')
                
                self._log_step("="*60)
                self._log_step("AI CLASSIFICATION COMPLETED:")
                self._log_step(f"   Classification Type: {classification_result['type']}")
                self._log_step(f"   Confidence Level: {classification_result['confidence']}")
                self._log_step(f"   💭 AI Reasoning: {classification_result['reasoning']}")
                self._log_step("="*60)
                
                # VALIDATION LAYER: Double-check AI classification with rule-based validation
                self._log_step("VALIDATING AI CLASSIFICATION WITH RULE-BASED CHECKS:")
                validated_result = self._validate_classification(classification_result, error_message, error_traceback, summary)
                
                if validated_result['type'] != classification_result['type']:
                    self._log_step(f"   CLASSIFICATION OVERRIDE:")
                    self._log_step(f"      AI suggested: {classification_result['type']}")
                    self._log_step(f"      Rule-based override: {validated_result['type']}")
                    self._log_step(f"      Reason: {validated_result['override_reason']}")
                    classification_result = validated_result
                else:
                    self._log_step(f"   AI classification validated by rule-based checks")
                
                # Log routing decision
                if classification_result['type'] == 'package_only':
                    self._log_step("ROUTING DECISION: Library Agent ONLY (no ECR download needed)")
                elif classification_result['type'] == 'code_fix_required':
                    self._log_step("ROUTING DECISION: Code Agent ONLY (ECR download required)")
                else:
                    self._log_step("ROUTING DECISION: Full multi-agent workflow (ECR + both agents)")
                
                return classification_result
                
            except (json.JSONDecodeError, ValueError, KeyError) as parse_error:
                self._log_step("AI CLASSIFICATION PARSING FAILED:")
                self._log_step(f"   Parse Error: {parse_error}")
                self._log_step(f"   Raw Response: {classification_response}")
                
                # Fallback to simple text analysis
                self._log_step("FALLING BACK TO SIMPLE TEXT ANALYSIS:")
                response_lower = classification_response.lower()
                
                if 'package_only' in response_lower:
                    self._log_step("   Found 'package_only' in response text")
                    return {
                        'type': 'package_only',
                        'confidence': 0.7,
                        'reasoning': 'AI suggested package_only (parsed from text)'
                    }
                elif 'code_fix_required' in response_lower:
                    return {
                        'type': 'code_fix_required', 
                        'confidence': 0.7,
                        'reasoning': 'AI suggested code_fix_required (parsed from text)'
                    }
                else:
                    return {
                        'type': 'mixed',
                        'confidence': 0.5,
                        'reasoning': 'AI classification failed, defaulting to mixed'
                    }
                    
        except Exception as e:
            self._log_step(f"AI classification failed: {e}")
            
            # Ultimate fallback - robust rule-based classification
            self._log_step("USING RULE-BASED FALLBACK CLASSIFICATION:")
            
            if isinstance(ai_analysis, dict):
                error_details = ai_analysis.get('error_details', {})
                error_message = error_details.get('message', '').lower()
                error_traceback = error_details.get('traceback', '').lower()
                summary = ai_analysis.get('summary', '').lower()
                combined = f"{error_message} {summary} {error_traceback}"
            else:
                combined = str(ai_analysis).lower()
            
            # PRIORITY 1: Check for MIXED patterns first (most specific)
            # These are errors that could be solved by EITHER package upgrade OR code fix
            mixed_patterns = [
                ('attributeerror', 'has no attribute', 'module'),  # module 'X' has no attribute 'Y'
                ('attributeerror', 'has no attribute', 'object'),  # 'Class' object has no attribute 'method'
                ('deprecated', 'use', 'instead'),  # Deprecated API with alternative
                ('removed in version', 'use', 'instead'),  # API removed in newer version
                ('torch.linalg', 'attributeerror'),  # Specific torch.linalg case
                ('numpy.int', 'deprecated'),  # Specific numpy deprecation
                ('dataframe', 'append', 'attributeerror'),  # Specific pandas deprecation
            ]
            
            for pattern in mixed_patterns:
                if all(keyword in combined for keyword in pattern):
                    self._log_step(f"   Matched MIXED pattern: {pattern}")
                    return {
                        'type': 'mixed',
                        'confidence': 0.85,
                        'reasoning': f'Fallback: Matched mixed pattern - {pattern[0]}'
                    }
            
            # PRIORITY 2: Check for PACKAGE_ONLY patterns
            # These are errors that can ONLY be solved by package management
            package_only_patterns = [
                ('modulenotfounderror', 'no module named'),  # Missing module
                ('importerror', 'cannot import name'),  # Import error
                ('no module named',),  # Generic missing module
                ('instrument', 'already instrumented'),  # Instrumentation conflict
                ('tracing', 'span'),  # Tracing library issue
                ('telemetry', 'exporter'),  # Telemetry configuration
                ('version conflict', 'requires'),  # Version conflict
                ('dependency', 'not satisfied'),  # Dependency issue
            ]
            
            for pattern in package_only_patterns:
                if all(keyword in combined for keyword in pattern):
                    self._log_step(f"   Matched PACKAGE_ONLY pattern: {pattern}")
                    return {
                        'type': 'package_only',
                        'confidence': 0.85,
                        'reasoning': f'Fallback: Matched package_only pattern - {pattern[0]}'
                    }
            
            # PRIORITY 3: Check for CODE_FIX_REQUIRED patterns
            # These are errors that can ONLY be solved by modifying code
            code_fix_patterns = [
                ('syntaxerror', 'invalid syntax'),  # Syntax error
                ('indentationerror',),  # Indentation error
                ('nameerror', 'is not defined'),  # Undefined variable
                ('typeerror', 'takes', 'positional arguments'),  # Wrong number of arguments
                ('valueerror', 'invalid literal'),  # Invalid value
                ('keyerror',),  # Missing dictionary key
                ('indexerror',),  # List index out of range
                ('zerodivisionerror',),  # Division by zero
                ('rate limit', 'exceeded'),  # Rate limiting (needs retry logic)
                ('timeout', 'exceeded'),  # Timeout (needs retry logic)
                ('logic error',),  # Logic error
                ('assertion', 'failed'),  # Assertion failure
            ]
            
            for pattern in code_fix_patterns:
                if all(keyword in combined for keyword in pattern):
                    self._log_step(f"   Matched CODE_FIX_REQUIRED pattern: {pattern}")
                    return {
                        'type': 'code_fix_required',
                        'confidence': 0.85,
                        'reasoning': f'Fallback: Matched code_fix_required pattern - {pattern[0]}'
                    }
            
            # PRIORITY 4: Default to MIXED for safety
            # If we can't determine the type, mixed gives users both options
            self._log_step("   No clear pattern matched - defaulting to MIXED for safety")
            return {
                'type': 'mixed',
                'confidence': 0.5,
                'reasoning': 'Fallback: No clear pattern detected, defaulting to mixed for user choice'
            }
            

    
    def _extract_text_from_agent_result(self, agent_result) -> str:
        """Extract text content from Strands AgentResult object
        
        Args:
            agent_result: AgentResult object from Strands SDK
            
        Returns:
            Extracted text content as string
        """
        if not agent_result:
            return ""
        
        # If it's already a string, return it
        if isinstance(agent_result, str):
            return agent_result
        
        # Try to extract from AgentResult object
        if hasattr(agent_result, 'message') and hasattr(agent_result.message, 'content'):
            content = agent_result.message.content
            
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Extract text from content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif hasattr(block, 'text'):
                        text_parts.append(block.text)
                return '\n'.join(text_parts)
        
        # Fallback to string representation
        return str(agent_result) if agent_result else ""
    
    def _generate_code_fix_preview(self, ai_analysis: Dict[str, Any], code_analysis: Dict[str, Any], extracted_files: Dict[str, str]) -> Dict[str, Any]:
        """Generate a preview of what Code Agent would fix (without applying changes)
        
        This shows users what code changes would be made so they can make an informed decision.
        
        Args:
            ai_analysis: AI error analysis
            code_analysis: Code structure analysis
            extracted_files: Extracted code files
            
        Returns:
            Dictionary with code fix preview information
        """
        self._log_step("   Analyzing error traces to identify affected files...")
        
        try:
            # Extract files from error traces (returns dict of file_path: content)
            files_to_fix_dict = self._extract_files_from_error_traces(ai_analysis, code_analysis)
            
            if not files_to_fix_dict:
                self._log_step("   No files identified from error traces, trying simple extraction...")
                # Fallback: extract files from traceback without LLM filtering
                files_to_fix_dict = self._simple_extract_files_from_traceback(ai_analysis, extracted_files)
            
            if not files_to_fix_dict:
                return {
                    'status': 'no_files_identified',
                    'message': 'No specific files identified from error traces',
                    'files': []
                }
            
            # Get error details
            error_details = ai_analysis.get('error_details', {})
            error_message = error_details.get('message', '')
            error_traceback = error_details.get('traceback', '')
            
            # Generate preview for each file
            file_previews = []
            for file_path, file_content in files_to_fix_dict.items():
                # Get just the filename for display
                filename = Path(file_path).name
                
                # Extract line numbers from traceback
                import re
                line_pattern = rf'File ".*{re.escape(filename)}".*line (\d+)'
                line_matches = re.findall(line_pattern, error_traceback)
                affected_lines = [int(line) for line in line_matches] if line_matches else []
                
                # Create preview
                preview = {
                    'file': filename,
                    'affected_lines': affected_lines,
                    'error_context': error_message,
                    'file_size': len(file_content),
                    'suggested_fix': self._suggest_fix_for_file(filename, error_message, affected_lines)
                }
                
                file_previews.append(preview)
                self._log_step(f"      Will fix: {filename}")
            
            return {
                'status': 'preview_generated',
                'files': file_previews,
                'total_files': len(file_previews),
                'message': f'Code Agent would modify {len(file_previews)} file(s)'
            }
            
        except Exception as e:
            self._log_error(f"Failed to generate code fix preview: {e}")
            return {
                'status': 'preview_failed',
                'error': str(e),
                'files': []
            }
    
    def _simple_extract_files_from_traceback(self, ai_analysis: Dict[str, Any], extracted_files: Dict[str, str]) -> Dict[str, str]:
        """Simple extraction of files from traceback without LLM filtering
        
        Extracts ONLY the file where the actual error occurs (last file in traceback),
        not all files in the call stack.
        
        Args:
            ai_analysis: AI error analysis with traceback
            extracted_files: Dictionary of extracted files
            
        Returns:
            Dictionary of file paths to contents that need fixing
        """
        files_to_fix = {}
        
        # Get traceback
        error_details = ai_analysis.get('error_details', {})
        traceback_text = error_details.get('traceback', '')
        
        if not traceback_text:
            return files_to_fix
        
        # Parse traceback to find file paths
        import re
        file_pattern = r'File "([^"]+)", line (\d+)'
        matches = re.findall(file_pattern, traceback_text)
        
        self._log_step(f"   Found {len(matches)} file references in traceback")
        
        # Get the LAST file reference (where the actual error occurs)
        # Skip library files (site-packages, usr/local/lib, etc.)
        target_file = None
        for file_ref, line_num in reversed(matches):
            # Skip Python library files
            if 'site-packages' in file_ref or '/usr/' in file_ref or '/lib/python' in file_ref:
                continue
            
            filename = Path(file_ref).name
            if filename == '__init__.py' or filename.startswith('_'):
                continue
            
            target_file = filename
            self._log_step(f"      Target file (where error occurs): {filename} at line {line_num}")
            break
        
        if not target_file:
            self._log_step(f"      Could not identify target file, falling back to all files")
            # Fallback: include all non-library files
            for file_ref, _ in matches:
                filename = Path(file_ref).name
                if filename == '__init__.py' or filename.startswith('_'):
                    continue
                if 'site-packages' in file_ref or '/usr/' in file_ref:
                    continue
                    
                for file_path, content in extracted_files.items():
                    if filename in file_path:
                        files_to_fix[file_path] = content
                        self._log_step(f"      Found: {filename} ({len(content)} chars)")
                        break
        else:
            # Find the target file in extracted files
            for file_path, content in extracted_files.items():
                if target_file in file_path:
                    files_to_fix[file_path] = content
                    self._log_step(f"      Will fix ONLY: {target_file} ({len(content)} chars)")
                    break
        
        return files_to_fix
    
    def _suggest_fix_for_file(self, file_path: str, error_message: str, affected_lines: List[int]) -> str:
        """Generate a human-readable suggestion for what would be fixed
        
        Args:
            file_path: Path to the file
            error_message: Error message
            affected_lines: Line numbers with errors
            
        Returns:
            Human-readable fix suggestion
        """
        error_lower = error_message.lower()
        
        # Pattern-based suggestions
        if 'np.int' in error_lower or 'numpy.int' in error_lower:
            return "Replace np.int with int() or np.int64"
        elif 'np.float' in error_lower or 'numpy.float' in error_lower:
            return "Replace np.float with float() or np.float64"
        elif 'dataframe' in error_lower and 'append' in error_lower:
            return "Replace df.append() with pd.concat()"
        elif 'torch.linalg' in error_lower:
            return "Replace torch.linalg.norm() with torch.norm()"
        elif 'attributeerror' in error_lower and 'has no attribute' in error_lower:
            return "Update deprecated API usage to current version"
        elif 'syntaxerror' in error_lower:
            return "Fix syntax error in code"
        elif 'nameerror' in error_lower:
            return "Fix undefined variable reference"
        else:
            line_info = f" at line(s) {', '.join(map(str, affected_lines))}" if affected_lines else ""
            return f"Fix error{line_info}"
    
    def _extract_requirements_only(self, image_id: str) -> Dict[str, str]:
        """Extract ONLY requirements.txt from ECR image (fast, minimal extraction).
        
        Uses boto3 ECR API — no Docker needed. Falls back to Docker if available.
        
        Args:
            image_id: ECR image URI (e.g. registry/repo:tag)
            
        Returns:
            Dictionary with requirements.txt content
        """
        self._log_step(f"Extracting requirements.txt only (fast mode)...")
        
        try:
            # Parse repository and tag from image_id
            repo_part = image_id.split("/")[-1] if "/" in image_id else image_id
            if ":" in repo_part:
                repository = repo_part.rsplit(":", 1)[0]
                tag = repo_part.rsplit(":", 1)[1]
            else:
                repository = repo_part
                tag = "latest"
            
            # If image_id contains registry prefix, extract just repo name
            if "/" in image_id:
                parts = image_id.split("/", 1)
                repository = parts[1].split(":")[0] if ":" in parts[1] else parts[1]
            
            self._log_step(f"   Using boto3 ECR extractor for {repository}:{tag}")
            result = self.ecr_extractor.extract_requirements_only(repository, tag)
            
            if result:
                self._log_step(f"   Found {len(result)} requirements file(s)")
                return result
            else:
                self._log_step("   No requirements.txt found - using empty requirements")
                return {'requirements.txt': ""}
                
        except Exception as e:
            self._log_error(f"Failed to extract requirements.txt: {e}")
            return {'requirements.txt': ""}
    
    def _validate_classification(self, ai_result: Dict[str, Any], error_message: str, error_traceback: str, summary: str) -> Dict[str, Any]:
        """Validate AI classification with minimal rule-based checks
        
        Philosophy: Trust the AI model's classification. Only override for 100% certain cases.
        The AI is trained on vast amounts of code and understands context better than simple rules.
        """
        combined = f"{error_message} {error_traceback} {summary}".lower()
        
        # MINIMAL OVERRIDE RULES - Only for absolutely certain cases
        
        # Rule 1: Missing module/package = PACKAGE_ONLY (100% certain)
        # These errors can ONLY be fixed by installing/upgrading packages
        if any(pattern in combined for pattern in ['modulenotfounderror', 'no module named']):
            if ai_result['type'] != 'package_only':
                return {
                    'type': 'package_only',
                    'confidence': 1.0,
                    'reasoning': 'Override: Missing module - must install package',
                    'override_reason': f"AI classified as {ai_result['type']}, but missing modules are always package_only"
                }
        
        # Rule 2: Syntax errors = CODE_FIX_REQUIRED (100% certain)
        # These errors can ONLY be fixed by changing code syntax
        if any(pattern in combined for pattern in ['syntaxerror', 'indentationerror', 'invalid syntax']):
            if ai_result['type'] != 'code_fix_required':
                return {
                    'type': 'code_fix_required',
                    'confidence': 1.0,
                    'reasoning': 'Override: Syntax error - must fix code',
                    'override_reason': f"AI classified as {ai_result['type']}, but syntax errors always require code fixes"
                }
        
        # That's it! Trust the AI for everything else.
        # The AI can handle:
        # - AttributeErrors (could be version mismatch OR code logic error)
        # - RuntimeErrors (could be invalid parameters OR missing features)
        # - ValueErrors (could be API changes OR code logic)
        # - Deprecated APIs (could upgrade OR change code)
        # - Import errors like "cannot import name" (could be version OR code)
        
        # No override needed - AI classification is valid
        return ai_result
    
    def _handle_code_fix_issue(self, agent_runtime_id: str, ai_analysis: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        """Handle code fix issues - pull from Git repo or ECR
        
        For Fix All operations, this method reuses previously extracted code
        so that subsequent fixes build on previous fixes in the same workspace.
        """
        
        # Initialize runtime_details - will be populated if we fetch from ECR
        runtime_details = {'agent_runtime_id': agent_runtime_id}
        
        # Check if we already have extracted code from a previous fix in this session
        # This enables Fix All to build fixes incrementally on the same codebase
        if self._extracted_code_path and self._extracted_code_path.exists() and self._code_analysis:
            self._log_step("♻️ REUSING EXISTING EXTRACTED CODE (Fix All shared workspace)")
            self._log_step(f"   Path: {self._extracted_code_path}")
            code_analysis = self._code_analysis
            extracted_path = self._extracted_code_path
            # Use cached runtime_details if available
            if hasattr(self, '_cached_runtime_details') and self._cached_runtime_details:
                runtime_details = self._cached_runtime_details
        else:
            # Check if source Git repo is configured
            git_source_repo = os.getenv('GIT_SOURCE_REPO', '').strip()
            git_source_branch = os.getenv('GIT_SOURCE_BRANCH', 'main').strip()
            
            if git_source_repo:
                self._log_step(f"Source Git repo configured: {git_source_repo}")
                self._log_step(f"🌿 Branch: {git_source_branch}")
                self._log_step("Processing code fix from Git repository")
                
                # Clone from Git
                code_analysis = self._clone_from_git_repo(git_source_repo, git_source_branch, agent_runtime_id)
                extracted_path = Path(code_analysis['extracted_path'])
            else:
                self._log_step("No source Git repo configured - pulling from ECR")
                self._log_step("Processing code fix issue with ECR download")
                
                # Get runtime details and ECR image
                runtime_details = self._get_runtime_details(agent_runtime_id)
                if not runtime_details:
                    raise Exception("Could not retrieve runtime details")
                
                # Cache runtime_details for reuse
                self._cached_runtime_details = runtime_details
                
                # Pull ECR image
                image_info = self._fetch_agent_code(runtime_details)
                
                # Extract and analyze code
                code_analysis = self._extract_and_analyze_code(image_info['image_id'])
                extracted_path = Path(code_analysis['extracted_path'])
            
            # Cache for reuse in subsequent Fix All operations
            self._extracted_code_path = extracted_path
            self._code_analysis = code_analysis
            self._log_step(f"💾 Cached extracted code for Fix All reuse: {extracted_path}")
        
        # STEP 2: Parse error traces to identify files that need fixing
        self._log_step("Step 2: Identifying files from error traces...")
        files_to_fix = self._extract_files_from_error_traces(ai_analysis, code_analysis)
        
        # CRITICAL FIX FOR FIX ALL: Read from app/ directory if files were already fixed
        # This ensures subsequent fixes build on previous fixes instead of overwriting them
        app_dir = extracted_path / "app"
        if app_dir.exists():
            self._log_step("   Checking for previously fixed files in app/ directory...")
            updated_files_to_fix = {}
            for file_path, original_content in files_to_fix.items():
                filename = Path(file_path).name
                app_file_path = app_dir / filename
                
                if app_file_path.exists():
                    try:
                        # Read the potentially already-fixed content from app/
                        current_content = app_file_path.read_text(encoding='utf-8')
                        if current_content != original_content:
                            self._log_step(f"      ♻️ Using already-fixed version of {filename} from app/")
                        updated_files_to_fix[file_path] = current_content
                    except Exception as e:
                        self._log_step(f"      Could not read {filename} from app/: {e}")
                        updated_files_to_fix[file_path] = original_content
                else:
                    updated_files_to_fix[file_path] = original_content
            
            files_to_fix = updated_files_to_fix
        
        # IMPORTANT: Merge with files_to_fix from ai_analysis (for "both" workflow)
        # This allows us to add requirements.txt when user chooses "both"
        if isinstance(ai_analysis, dict) and 'files_to_fix' in ai_analysis:
            additional_files = ai_analysis.get('files_to_fix', [])
            if additional_files:
                self._log_step(f"   Found {len(additional_files)} additional files from workflow:")
                for file in additional_files:
                    # Check if file is already in files_to_fix (by checking all keys)
                    already_included = any(file in key for key in files_to_fix.keys())
                    
                    if not already_included:
                        # Try to find and load the file from extracted code
                        file_content = ""
                        file_path = None
                        
                        # Search for the file in extracted_path
                        for potential_path in extracted_path.rglob(file):
                            if potential_path.is_file():
                                try:
                                    file_content = potential_path.read_text(encoding='utf-8')
                                    file_path = str(potential_path)
                                    self._log_step(f"      + {file} (loaded from {potential_path.name})")
                                    break
                                except Exception as e:
                                    self._log_step(f"      Could not read {file}: {e}")
                        
                        if file_path:
                            files_to_fix[file_path] = file_content
                        else:
                            # File not found, add with empty content and log warning
                            self._log_step(f"      {file} not found in codebase, adding with empty content")
                            files_to_fix[file] = ""
        
        # FALLBACK: If no files identified from traces, include all Python files
        if not files_to_fix:
            self._log_step("   No files identified from error traces - using fallback strategy")
            self._log_step("   📂 Including all Python files from codebase for analysis")
            
            # Get all Python files from code_analysis
            python_files = code_analysis.get('python_files', [])
            if python_files:
                for py_file in python_files:
                    try:
                        file_path = Path(py_file)
                        if file_path.exists() and file_path.is_file():
                            content = file_path.read_text(encoding='utf-8')
                            # Use relative path from extracted_code directory
                            rel_path = str(file_path.relative_to(extracted_path.parent))
                            files_to_fix[rel_path] = content
                            self._log_step(f"      + {file_path.name}")
                    except Exception as e:
                        self._log_step(f"      Could not read {py_file}: {e}")
            
            if not files_to_fix:
                self._log_error("No Python files found in codebase")
                return {'status': 'failed', 'error': 'No files to fix - no Python files found'}
        
        self._log_step(f"   Found {len(files_to_fix)} files to fix:")
        for file_path in files_to_fix:
            self._log_step(f"      - {file_path}")
        
        # STEP 3: Fix files using LLM (pass only specific files + error context)
        self._log_step("Step 3: Fixing files with LLM...")
        fix_results = self._fix_files_with_llm(files_to_fix, ai_analysis, code_analysis)
        
        # Check if Code Agent failed
        if fix_results.get('error'):
            error_msg = fix_results['error']
            error_type = fix_results.get('error_type', 'unknown')
            
            self._log_error(f"Code Agent execution failed: {error_msg}")
            
            if error_type == 'bedrock_unavailable':
                return {
                    'status': 'failed',
                    'error': 'Bedrock service unavailable',
                    'error_details': error_msg,
                    'message': 'Amazon Bedrock service is temporarily unavailable. Please wait a few minutes and try again.',
                    'suggestion': 'Check AWS Service Health Dashboard at https://health.aws.amazon.com/health/status',
                    'fixed_files': {},
                    'working_directory': str(extracted_path)
                }
            else:
                return {
                    'status': 'failed',
                    'error': 'Code Agent execution failed',
                    'error_details': error_msg,
                    'fixed_files': {},
                    'working_directory': str(extracted_path)
                }
        
        # STEP 4: Check for syntax errors in FIXED files (not original extracted files)
        self._log_step("Step 4: Checking for syntax errors in fixed files...")
        
        # Only check syntax if we actually fixed files
        if fix_results.get('fixed_files'):
            # Check the files that were actually fixed (they were written back to original locations)
            fixed_file_paths = []
            for filename in fix_results['fixed_files'].keys():
                for orig_path in files_to_fix.keys():
                    if Path(orig_path).name == filename:
                        fixed_file_paths.append(Path(orig_path))
                        break
            
            # Check syntax of only the fixed files
            syntax_errors = []
            for file_path in fixed_file_paths:
                try:
                    import ast
                    # Resolve path to absolute if it's relative
                    if not file_path.is_absolute():
                        file_path = self.work_dir / file_path
                    
                    content = file_path.read_text(encoding='utf-8')
                    ast.parse(content)
                    self._log_step(f"   Syntax OK: {file_path.name}")
                except SyntaxError as e:
                    syntax_errors.append({
                        'file': str(file_path),
                        'line': e.lineno,
                        'message': str(e)
                    })
                    self._log_step(f"   Syntax error in {file_path.name}: line {e.lineno}")
            
            if syntax_errors:
                self._log_step(f"   Found {len(syntax_errors)} syntax errors after Code Agent fixes")
                self._log_step("   This may indicate the Code Agent's fix was incomplete")
                fix_results['syntax_errors_remaining'] = syntax_errors
        else:
            self._log_step("   No files were fixed, skipping syntax check")
        
        # STEP 4.5: Generate comprehensive summary of Code Agent's work
        code_agent_summary = None
        if fix_results.get('fixed_files') and fix_results.get('agent_response'):
            self._log_step("Generating comprehensive Code Agent summary...")
            try:
                # Quick health check before summary generation
                from src.config.config import check_model_health
                health_check = check_model_health()
                
                if health_check['status'] == 'healthy':
                    code_agent_summary = self._generate_code_agent_summary_simple(
                        fix_results.get('agent_response', ''),
                        fix_results.get('fixed_files', {}),
                        ai_analysis
                    )
                    self._log_step(f"   Summary generated ({len(code_agent_summary)} characters)")
                else:
                    self._log_error(f"   Skipping summary generation - model unavailable: {health_check['message']}")
                    code_agent_summary = f"""## CODE FIXES APPLIED:

**Files Modified:** {', '.join(fix_results.get('fixed_files', {}).keys())}

**Status:** Code Agent completed successfully

**Note:** Automatic summary generation was skipped because the model became unavailable.

See the detailed Code Agent output below for full information about the fixes applied."""
            except Exception as e:
                self._log_error(f"   Summary generation failed: {e}")
                import traceback
                self._log_error(f"   Traceback: {traceback.format_exc()}")
        
        # STEP 5: ALWAYS save changes locally (defer git push for batch processing)
        # This applies to ALL classifications - user decides when to push
        self._log_step("Step 5: Saving changes locally (git push deferred)...")
        
        # Write fixed files to app/ directory for git tracking
        app_dir = extracted_path / "app"
        actual_git_diff = ""  # Capture git diff immediately after fix
        if app_dir.exists():
            fixed_files = fix_results.get('fixed_files', {})
            if fixed_files:
                self._log_step(f"   Writing {len(fixed_files)} fixed files to app/ directory...")
                for filename, content in fixed_files.items():
                    # Write to app/ directory (where git is initialized)
                    file_path = app_dir / filename
                    try:
                        file_path.write_text(content, encoding='utf-8')
                        self._log_step(f"      {filename} ({len(content)} chars)")
                    except Exception as e:
                        self._log_error(f"      Failed to write {filename}: {e}")
                self._log_step(f"   All fixed files written to {app_dir}")
                
                # Capture git diff immediately after writing fixed files
                self._log_step("   Capturing git diff of changes...")
                try:
                    original_dir = os.getcwd()
                    os.chdir(app_dir)
                    
                    # Stage all changes to capture the diff
                    subprocess.run(['git', 'add', '.'], capture_output=True, check=True)
                    
                    # Get the staged diff (includes new files with full content)
                    diff_result = subprocess.run(
                        ['git', 'diff', '--cached', '--no-color'],
                        capture_output=True, text=True, timeout=30
                    )
                    if diff_result.returncode == 0 and diff_result.stdout.strip():
                        actual_git_diff = diff_result.stdout.strip()
                        # Log summary of changes
                        diff_lines = actual_git_diff.split('\n')
                        added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
                        removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
                        self._log_step(f"   Git diff captured: {added} lines added, {removed} lines removed")
                    else:
                        # No cached diff - try to get diff against HEAD for modified files
                        self._log_step("    No staged diff, checking for modifications...")
                        head_diff = subprocess.run(
                            ['git', 'diff', 'HEAD', '--no-color'],
                            capture_output=True, text=True, timeout=30
                        )
                        if head_diff.returncode == 0 and head_diff.stdout.strip():
                            actual_git_diff = head_diff.stdout.strip()
                            diff_lines = actual_git_diff.split('\n')
                            added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
                            removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
                            self._log_step(f"   Git diff captured: {added} lines added, {removed} lines removed")
                        else:
                            # Get stat summary as fallback
                            status_result = subprocess.run(
                                ['git', 'diff', '--cached', '--stat'],
                                capture_output=True, text=True, timeout=30
                            )
                            if status_result.stdout.strip():
                                actual_git_diff = f"Files changed:\n{status_result.stdout.strip()}"
                                self._log_step(f"   Git stat captured")
                    
                    os.chdir(original_dir)
                except Exception as diff_error:
                    self._log_step(f"   Could not capture git diff: {diff_error}")
                    try:
                        os.chdir(original_dir)
                    except:
                        pass
            else:
                self._log_step("    No fixed files to write")
        else:
            self._log_step(f"    app/ directory not found at {app_dir}")
        
        self._log_step("   💾 Changes saved to workspace")
        self._log_step("    Use 'Push All Changes' button to push when ready")
        
        # STEP 5.5: Patch AgentCore network configuration for local testing (optional, silent)
        # This is only needed for Streamlit local testing, not for the React dashboard
        try:
            patched = patch_agent_workspace_config(
                agent_id=agent_runtime_id,
                workspace_dir=self.work_dir.parent,
                network_mode="HOST"
            )
            # Only log if successful, otherwise stay silent
            if patched:
                self._log_step("   Network configuration patched for local testing")
        except Exception:
            pass  # Silent - not critical for fix workflow
        
        git_result = {
            'status': 'deferred',
            'message': 'Changes saved locally, push deferred',
            'workspace': str(extracted_path)
        }
        
        orchestrator_result = {
            'status': 'success',
            'files_fixed': list(files_to_fix.keys()),
            'fix_results': fix_results,
            'git_info': git_result,
            'working_directory': str(extracted_path)
        }
        
        self.results['final_status'] = 'success'
        self.results['end_time'] = datetime.now()
        self.results['orchestrator_result'] = orchestrator_result
        self.results['classification'] = classification
        
        # Build original_files dict with just filenames as keys (matching fixed_files format)
        original_files = {}
        for file_path, content in files_to_fix.items():
            filename = Path(file_path).name
            original_files[filename] = content
        
        return {
            'status': 'success',
            'fixed_files': fix_results.get('fixed_files', {}),
            'original_files': original_files,  # Original file contents for diff comparison
            'package_recommendations': [],  # Focus on code fixes
            'code_fixes': orchestrator_result.get('code_fixes', []),
            'code_agent_summary': code_agent_summary,  # Add comprehensive summary
            'error_classification': classification,
            'runtime_details': runtime_details,
            'working_directory': orchestrator_result.get('working_directory', str(self.work_dir.absolute())),
            'git_info': orchestrator_result.get('git_info', {}),
            'results': self.results,
            'is_shared_workspace': True,  # Always true - all changes are deferred
            'agent_id': agent_runtime_id  # For tracking fixes per agent
        }
    
    def _handle_package_workflow_with_choice(self, agent_runtime_id: str, ai_analysis: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        """Handle package_only issues: Run Library Agent first, then let user choose Code Agent
        
        Same flow as mixed workflow - gives user control over whether to run Code Agent
        """
        
        self._log_step("="*80)
        self._log_step("PACKAGE WORKFLOW - STEP 1: LIBRARY ANALYSIS")
        self._log_step("="*80)
        
        # This is identical to mixed workflow - run Library Agent and present choices
        return self._run_library_analysis_and_present_choices(
            agent_runtime_id, 
            ai_analysis, 
            classification,
            workflow_type='package_only'
        )
    
    def _handle_mixed_workflow_with_choice(self, agent_runtime_id: str, ai_analysis: Dict[str, Any], classification: Dict[str, Any], initial_choice: str = None) -> Dict[str, Any]:
        """Handle mixed issues: Show analysis FIRST, then user chooses
        
        NEW WORKFLOW (Better UX):
        1. Generate Library Agent analysis (package recommendations)
        2. Generate Code Agent preview (code fix preview)
        3. Show BOTH options to user in UI
        4. User reviews and selects: Library Only, Code Only, Both, or Skip
        5. Execute based on user's informed choice
        
        Args:
            agent_runtime_id: Agent runtime ID
            ai_analysis: AI error analysis
            classification: Error classification
            initial_choice: Optional - Pre-selected choice for "Fix All" mode ('library', 'code', 'both', 'skip')
        """
        
        self._log_step("="*80)
        self._log_step("MIXED WORKFLOW - ANALYSIS FIRST, THEN CHOICE")
        self._log_step("="*80)
        
        # Check if we have cached analysis to skip regeneration
        import hashlib
        error_message = ai_analysis.get('error_message', '')
        error_details = ai_analysis.get('error_details', {})
        traceback = error_details.get('traceback', '')
        error_signature = f"{error_message}|{traceback[:200]}"
        error_hash = hashlib.sha256(error_signature.encode()).hexdigest()[:12]
        workflow_cache_key = f"workflow_mixed_{agent_runtime_id}_{error_hash}"
        
        if hasattr(self, '_workflow_cache') and workflow_cache_key in self._workflow_cache:
            self._log_step("   Found cached workflow result!")
            self._log_step("   Returning cached analysis for display")
            cached_result = self._workflow_cache[workflow_cache_key]
            
            # If initial_choice provided (Fix All mode), store it but still return analysis first
            if initial_choice and initial_choice != 'skip':
                cached_result['user_choice'] = initial_choice
                self._log_step(f"   📌 Pre-selected choice stored: {initial_choice}")
                self._log_step("   � UIx will display analysis, then execute choice")
            
            return cached_result
        
        # Generate analysis (Library Agent + Code Agent preview)
        self._log_step("Generating comprehensive analysis...")
        analysis_result = self._run_library_analysis_and_present_choices(
            agent_runtime_id,
            ai_analysis,
            classification,
            workflow_type='mixed'
        )
        
        # ALWAYS return analysis first for user to review
        # Status is already 'awaiting_user_choice' from _run_library_analysis_and_present_choices
        
        # If initial_choice provided (Fix All mode), store it but still show analysis first
        if initial_choice and initial_choice != 'skip':
            analysis_result['user_choice'] = initial_choice
            self._log_step("="*80)
            self._log_step(f"ANALYSIS COMPLETE - PRE-SELECTED CHOICE: {initial_choice}")
            self._log_step("="*80)
            self._log_step("   Returning analysis to UI for display")
            self._log_step("   🎨 User will see both Library and Code options")
            self._log_step(f"   � Pre-selehcted choice '{initial_choice}' will execute after display")
        else:
            self._log_step("="*80)
            self._log_step("ANALYSIS COMPLETE - AWAITING USER CHOICE")
            self._log_step("="*80)
            self._log_step("   Returning analysis to UI for display")
            self._log_step("   🎨 User will see both options and choose")
        
        return analysis_result
    
    def _run_library_analysis_and_present_choices(self, agent_runtime_id: str, ai_analysis: Dict[str, Any], classification: Dict[str, Any], workflow_type: str) -> Dict[str, Any]:
        """Shared method: Run Library Agent and present user choices
        
        Used by both package_only and mixed workflows
        
        Args:
            agent_runtime_id: Agent runtime ID
            ai_analysis: AI error analysis
            classification: Error classification
            workflow_type: 'package_only' or 'mixed'
        """
        
        workflow_label = "PACKAGE" if workflow_type == 'package_only' else "MIXED"
        
        # Check for cached workflow result first (content-based caching)
        # Cache key includes agent_id and error content hash
        # NOTE: Cache is NOT time-dependent - same error = same cache regardless of time period
        import hashlib
        error_message = ai_analysis.get('error_message', '')
        error_details = ai_analysis.get('error_details', {})
        traceback = error_details.get('traceback', '')
        
        # Create content-based cache key that includes agent_id
        # This ensures cache is agent-specific and error-specific
        # CACHE_VERSION: Increment this to invalidate all old caches after bug fixes
        CACHE_VERSION = "v2"  # Incremented to fix library_agent_output issue
        error_signature = f"{error_message}|{traceback[:200]}"
        error_hash = hashlib.sha256(error_signature.encode()).hexdigest()[:12]
        workflow_cache_key = f"workflow_{workflow_type}_{agent_runtime_id}_{error_hash}_{CACHE_VERSION}"
        
        # Check if we have cached workflow result
        # Cache is stored in session state (cleared when agent or time period changes)
        if hasattr(self, '_workflow_cache') and workflow_cache_key in self._workflow_cache:
            self._log_step("="*80)
            self._log_step(f"USING CACHED {workflow_label} WORKFLOW RESULT")
            self._log_step("="*80)
            self._log_step(f"   🔑 Cache key: {workflow_cache_key}")
            self._log_step(f"   Agent: {agent_runtime_id}")
            self._log_step("   Skipping ECR download, code extraction, and agent execution")
            self._log_step("   Library analysis: CACHED")
            if workflow_type == 'mixed':
                self._log_step("   Code preview: CACHED")
            self._log_step("   For mixed classification: Jumping directly to execute user choice")
            self._log_step("="*80)
            
            cached_result = self._workflow_cache[workflow_cache_key]
            self._log_step(f"\nCached analysis from previous run:")
            self._log_step(f"   Package recommendations: {len(cached_result.get('package_recommendations', []))} items")
            if workflow_type == 'mixed' and cached_result.get('code_fix_preview'):
                preview = cached_result['code_fix_preview']
                self._log_step(f"   Code fixes: {len(preview.get('files', []))} files")
            
            return cached_result
        
        # Initialize workflow cache if not exists
        if not hasattr(self, '_workflow_cache'):
            self._workflow_cache = {}
        
        self._log_step(f"{workflow_label} WORKFLOW - LIBRARY ANALYSIS")
        self._log_step(f"   🔑 Cache key: {workflow_cache_key}")
        self._log_step(f"   Agent: {agent_runtime_id}")
        
        # Step 1: Always run Library Agent (fast and informative)
        self._log_step(f"Running Library Agent for {workflow_label.lower()} analysis...")
        
        try:
            # Get runtime details to analyze requirements
            runtime_details = self._get_runtime_details(agent_runtime_id)
            if not runtime_details:
                raise Exception("Could not retrieve runtime details")
            
            # For mixed workflow, we need to show BOTH package and code fix options
            if workflow_type == 'mixed':
                self._log_step("="*80)
                self._log_step("MIXED WORKFLOW - GENERATING BOTH OPTIONS")
                self._log_step("="*80)
                self._log_step("   Step 1: Library Agent analysis (package recommendations)")
                self._log_step("   Step 2: Code Agent preview (code fix suggestions)")
                self._log_step("   ❓ Step 3: User chooses preferred approach")
                self._log_step("")
                
                # Check if we already have extracted code from a previous fix (Fix All shared workspace)
                reusing_cached = self._extracted_code_path and self._extracted_code_path.exists() and self._code_analysis
                if reusing_cached:
                    self._log_step("♻️ REUSING EXISTING EXTRACTED CODE (Fix All shared workspace)")
                    self._log_step(f"   Path: {self._extracted_code_path}")
                    code_analysis = self._code_analysis
                    extracted_files = self._extract_files_as_dict(code_analysis)
                    image_info = None  # Not needed when reusing
                else:
                    # Pull ECR image and extract full codebase for comprehensive analysis
                    self._log_step("Pulling ECR image for comprehensive analysis...")
                    image_info = self._fetch_agent_code(runtime_details)
                    
                    self._log_step("📂 Extracting codebase for analysis...")
                    code_analysis = self._extract_and_analyze_code(image_info['image_id'])
                    extracted_files = self._extract_files_as_dict(code_analysis)
                    
                    # Cache for reuse in subsequent Fix All operations
                    self._extracted_code_path = Path(code_analysis['extracted_path'])
                    self._code_analysis = code_analysis
                    self._log_step(f"💾 Cached extracted code for Fix All reuse: {self._extracted_code_path}")
                
                # Run Library Agent
                self._log_step("\nRunning Library Agent analysis...")
                from agents.strands_orchestrator import StrandsOrchestrator
                orchestrator = StrandsOrchestrator(work_dir=str(self.work_dir))
                
                library_analysis = {
                    **ai_analysis,
                    'classification': {'type': 'package_only', 'confidence': classification.get('confidence', 0.9)},
                    'processing_mode': 'library_only'
                }
                
                try:
                    library_result = orchestrator.orchestrate_fixes(library_analysis, extracted_files)
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check for Bedrock connection/throttling errors
                    if 'ServiceUnavailableException' in error_msg or 'Too many connections' in error_msg:
                        self._log_step("Bedrock API Error: Too many concurrent connections")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock API rate limit exceeded',
                            'message': '🔴 **Bedrock API Rate Limit Exceeded**\n\n'
                                      'The AI model service has too many active connections. This usually happens when:\n'
                                      '- Multiple patterns are being processed simultaneously\n'
                                      '- Previous requests are still running\n\n'
                                      '**What to do:**\n'
                                      '1. Wait 30-60 seconds for existing connections to close\n'
                                      '2. Try processing one pattern at a time\n'
                                      '3. If the issue persists, check your Amazon Bedrock quotas\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_rate_limit',
                            'retry_after': 60
                        }
                    elif 'ThrottlingException' in error_msg or 'rate limit' in error_msg.lower():
                        self._log_step("Bedrock API Error: Request throttled")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock API throttling',
                            'message': '🔴 **Bedrock API Throttling**\n\n'
                                      'Your requests are being throttled by Amazon Bedrock. This means you\'ve exceeded the allowed request rate.\n\n'
                                      '**What to do:**\n'
                                      '1. Wait a few minutes before trying again\n'
                                      '2. Process patterns one at a time instead of in parallel\n'
                                      '3. Consider requesting a quota increase from AWS if this happens frequently\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_throttling',
                            'retry_after': 120
                        }
                    elif 'ValidationException' in error_msg or 'ModelNotReadyException' in error_msg:
                        self._log_step("Bedrock API Error: Model validation error")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock model validation error',
                            'message': '🔴 **Bedrock Model Error**\n\n'
                                      'There was an issue with the AI model configuration or availability.\n\n'
                                      '**What to do:**\n'
                                      '1. Check that your model ID is correct in the configuration\n'
                                      '2. Verify the model is available in your AWS region\n'
                                      '3. Ensure you have access to the model in your AWS account\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_model_error'
                        }
                    else:
                        # Generic error handling
                        self._log_step(f"Library Agent execution failed: {error_msg}")
                        raise
                
                # Extract package recommendations and text output
                self._log_step(f"DEBUG: library_result type: {type(library_result)}")
                
                if isinstance(library_result, dict):
                    # Get both fields
                    library_agent_output_field = library_result.get('library_agent_output', '')
                    package_recs = library_result.get('package_recommendations', '')
                    
                    self._log_step(f"DEBUG: library_agent_output field type: {type(library_agent_output_field)}")
                    self._log_step(f"DEBUG: package_recommendations field type: {type(package_recs)}")
                    
                    # Try to extract text from package_recommendations if it's an AgentResult
                    if package_recs and not isinstance(package_recs, (str, list)):
                        self._log_step(f"DEBUG: Extracting text from AgentResult in package_recommendations...")
                        library_agent_output = self._extract_text_from_agent_result(package_recs)
                        package_recommendations = []
                        self._log_step(f"   Extracted {len(library_agent_output)} characters from AgentResult")
                    elif isinstance(package_recs, str) and len(package_recs) > 0:
                        library_agent_output = package_recs
                        package_recommendations = []
                        self._log_step(f"   Using string package_recommendations: {len(library_agent_output)} characters")
                    elif isinstance(package_recs, list):
                        library_agent_output = library_agent_output_field or ''
                        package_recommendations = package_recs
                        self._log_step(f"   Using list package_recommendations: {len(package_recommendations)} items")
                    else:
                        # Try library_agent_output field
                        library_agent_output = library_agent_output_field or ''
                        package_recommendations = []
                        self._log_step(f"   Using library_agent_output field: {len(library_agent_output)} characters")
                else:
                    library_agent_output = ''
                    package_recommendations = []
                    self._log_step(f"   Unexpected library_result type: {type(library_result)}")
                
                # Generate code fix preview (lightweight - just shows what will be changed)
                # This is NOT full code agent execution, just a preview for user decision
                self._log_step("\nGenerating Code Agent preview (lightweight)...")
                code_fix_preview = self._generate_code_fix_preview(ai_analysis, code_analysis, extracted_files)
                
                # Store for later use when user chooses Code Agent
                # Only cache runtime_details and image_info if we fetched them (not reusing cached code)
                if not reusing_cached:
                    self._cached_runtime_details = runtime_details
                    self._cached_image_info = image_info
                self._cached_code_analysis = code_analysis
                self._cached_extracted_files = extracted_files
                
            else:
                # For package_only workflow, minimal extraction
                self._log_step("="*80)
                self._log_step("PACKAGE-ONLY WORKFLOW - MINIMAL EXTRACTION")
                self._log_step("="*80)
                self._log_step("   Goal: Extract ONLY requirements.txt (fast)")
                self._log_step("   ⏭️  Code analysis: SKIPPED")
                self._log_step("")
                
                # Check if files already extracted in shared workspace
                extract_path = self.work_dir / "extracted_code"
                requirements_path = extract_path / "app" / "requirements.txt"
                
                if requirements_path.exists():
                    self._log_step("SHARED WORKSPACE: Using already extracted requirements.txt")
                    self._log_step(f"   📂 Found at: {requirements_path}")
                    extracted_files = {'requirements.txt': requirements_path.read_text()}
                else:
                    # Pull ECR image ONLY to get requirements.txt (minimal extraction)
                    self._log_step("Pulling ECR image for requirements.txt extraction...")
                    image_info = self._fetch_agent_code(runtime_details)
                    
                    # Extract ONLY requirements.txt for library analysis (fast)
                    extracted_files = self._extract_requirements_only(image_info['image_id'])
                
                # Run Library Agent with minimal files
                from agents.strands_orchestrator import StrandsOrchestrator
                orchestrator = StrandsOrchestrator(work_dir=str(self.work_dir))
                
                library_analysis = {
                    **ai_analysis,
                    'classification': {'type': 'package_only', 'confidence': classification.get('confidence', 0.9)},
                    'processing_mode': 'library_only'
                }
                
                try:
                    library_result = orchestrator.orchestrate_fixes(library_analysis, extracted_files)
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check for Bedrock connection/throttling errors
                    if 'ServiceUnavailableException' in error_msg or 'Too many connections' in error_msg:
                        self._log_step("Bedrock API Error: Too many concurrent connections")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock API rate limit exceeded',
                            'message': '🔴 **Bedrock API Rate Limit Exceeded**\n\n'
                                      'The AI model service has too many active connections. This usually happens when:\n'
                                      '- Multiple patterns are being processed simultaneously\n'
                                      '- Previous requests are still running\n\n'
                                      '**What to do:**\n'
                                      '1. Wait 30-60 seconds for existing connections to close\n'
                                      '2. Try processing one pattern at a time\n'
                                      '3. If the issue persists, check your Amazon Bedrock quotas\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_rate_limit',
                            'retry_after': 60
                        }
                    elif 'ThrottlingException' in error_msg or 'rate limit' in error_msg.lower():
                        self._log_step("Bedrock API Error: Request throttled")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock API throttling',
                            'message': '🔴 **Bedrock API Throttling**\n\n'
                                      'Your requests are being throttled by Amazon Bedrock. This means you\'ve exceeded the allowed request rate.\n\n'
                                      '**What to do:**\n'
                                      '1. Wait a few minutes before trying again\n'
                                      '2. Process patterns one at a time instead of in parallel\n'
                                      '3. Consider requesting a quota increase from AWS if this happens frequently\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_throttling',
                            'retry_after': 120
                        }
                    elif 'ValidationException' in error_msg or 'ModelNotReadyException' in error_msg:
                        self._log_step("Bedrock API Error: Model validation error")
                        return {
                            'status': 'failed',
                            'error': 'Bedrock model validation error',
                            'message': '🔴 **Bedrock Model Error**\n\n'
                                      'There was an issue with the AI model configuration or availability.\n\n'
                                      '**What to do:**\n'
                                      '1. Check that your model ID is correct in the configuration\n'
                                      '2. Verify the model is available in your AWS region\n'
                                      '3. Ensure you have access to the model in your AWS account\n\n'
                                      f'**Technical details:** {error_msg}',
                            'error_type': 'bedrock_model_error'
                        }
                    else:
                        # Generic error handling
                        self._log_step(f"Library Agent execution failed: {error_msg}")
                        raise
                
                # Extract package recommendations and text output
                if isinstance(library_result, dict):
                    # Get the library agent text output for display
                    library_agent_output = library_result.get('library_agent_output', '')
                    package_recs = library_result.get('package_recommendations', [])
                    
                    # If package_recs is a string (text output), use it for display
                    if isinstance(package_recs, str):
                        library_agent_output = package_recs
                        package_recommendations = []  # No structured list
                        self._log_step(f"   Extracted {len(library_agent_output)} characters of Library Agent text output")
                    elif isinstance(package_recs, list):
                        package_recommendations = package_recs
                        self._log_step(f"   Extracted {len(package_recommendations)} structured recommendations")
                    else:
                        package_recommendations = []
                        self._log_step(f"   Unexpected package_recommendations type: {type(package_recs)}")
                else:
                    library_agent_output = ''
                    package_recommendations = []
                    self._log_step(f"   Unexpected library_result type: {type(library_result)}")
                
                code_fix_preview = None  # No code preview for package_only
                
                # Store runtime details and image info for later use if user chooses Code Agent
                self._cached_runtime_details = runtime_details
                self._cached_image_info = image_info
            
            self._log_step("="*80)
            self._log_step("LIBRARY ANALYSIS COMPLETE")
            self._log_step("="*80)
            
            # Ensure package_recommendations is always a list
            if not isinstance(package_recommendations, list):
                self._log_step(f"   Warning: package_recommendations is {type(package_recommendations)}, converting to list")
                package_recommendations = []
            
            # Safely get count of recommendations
            rec_count = len(package_recommendations)
            self._log_step(f"Found {rec_count} package recommendation(s)")
            
            # Display package recommendations
            self._log_step("\n" + "="*80)
            self._log_step("ANALYSIS RESULTS")
            self._log_step("="*80)
            
            # Display Library Agent output (text or structured)
            self._log_step("\nOPTION A: PACKAGE UPGRADE APPROACH")
            self._log_step("-" * 80)
            
            if library_agent_output and len(library_agent_output) > 0:
                # Display the full Library Agent text output
                self._log_step(library_agent_output)
            elif package_recommendations and len(package_recommendations) > 0:
                # Display structured recommendations
                for i, rec in enumerate(package_recommendations, 1):
                    self._log_step(f"\n   {i}. {rec.get('type', 'recommendation').upper()}")
                    self._log_step(f"      Package: {rec.get('package', 'N/A')}")
                    self._log_step(f"      Current: {rec.get('from', 'N/A')}")
                    self._log_step(f"      Recommended: {rec.get('to', 'N/A')}")
                    self._log_step(f"      Reason: {rec.get('reason', 'N/A')}")
                    self._log_step(f"      Risk: {rec.get('risk', 'unknown')}")
            else:
                self._log_step("    No package upgrades recommended")
            
            # Display code fix preview (for mixed workflow)
            if code_fix_preview and code_fix_preview.get('status') == 'preview_generated':
                self._log_step("\nOPTION B: CODE FIX APPROACH")
                self._log_step("-" * 80)
                file_previews = code_fix_preview.get('files', [])
                
                if file_previews:
                    self._log_step(f"   Code Agent would modify {len(file_previews)} file(s):\n")
                    for i, preview in enumerate(file_previews, 1):
                        self._log_step(f"   {i}. File: {preview['file']}")
                        if preview['affected_lines']:
                            self._log_step(f"      Lines: {', '.join(map(str, preview['affected_lines']))}")
                        self._log_step(f"      Fix: {preview['suggested_fix']}")
                        self._log_step(f"      Size: {preview['file_size']} bytes")
                        self._log_step("")
                else:
                    self._log_step("    No specific code fixes identified")
            elif workflow_type == 'mixed':
                self._log_step("\nOPTION B: CODE FIX APPROACH")
                self._log_step("-" * 80)
                self._log_step("    Code fix preview not available")
            
            # Step 2: Present user with options
            self._log_step("\n" + "="*80)
            self._log_step("❓ USER DECISION REQUIRED")
            self._log_step("="*80)
            self._log_step(f"\nBased on the analysis above ({workflow_label} issue), what would you like to do?\n")
            self._log_step("OPTIONS:")
            self._log_step("  1️⃣  Upgrade packages only (manual)")
            self._log_step("      → Update requirements.txt based on recommendations above")
            self._log_step("      → No code changes")
            self._log_step("      → Risk: May have breaking changes in other code\n")
            
            self._log_step("  2️⃣  Fix code (backward compatible) - RECOMMENDED")
            self._log_step("      → Apply code fixes shown in Option B above")
            self._log_step("      → Run Code Agent to apply automated fixes")
            self._log_step("      → Creates GitLab MR for review")
            self._log_step("      → Works with current package versions\n")
            
            self._log_step("  3️⃣  Both (upgrade + code fix)")
            self._log_step("      → Apply both Option A and Option B")
            self._log_step("      → Updates requirements.txt + code files")
            self._log_step("      → Maximum compatibility\n")
            
            self._log_step("  4️⃣  Skip (manual fix)")
            self._log_step("      → I'll handle this manually")
            self._log_step("      → No automated changes\n")
            
            self._log_step("="*80)
            
            # Return results with user choice prompt
            # Convert library_result to dict if it's an AgentResult object
            if isinstance(library_result, dict):
                library_analysis_dict = library_result
            else:
                # Convert AgentResult to dict
                library_analysis_dict = {
                    'package_recommendations': package_recommendations,
                    'status': 'completed'
                }
            
            result = {
                'status': 'awaiting_user_choice',
                'workflow_type': workflow_type,
                'library_analysis': library_analysis_dict,
                'library_agent_output': library_agent_output,  # Add text output for UI display
                'package_recommendations': package_recommendations,
                'classification': classification,
                'runtime_details': runtime_details,
                'ai_analysis': ai_analysis,  # Store for later use
                'user_options': {
                    'option_1': 'upgrade_packages_only',
                    'option_2': 'fix_code_only',
                    'option_3': 'both',
                    'option_4': 'skip'
                },
                'message': f'Analysis complete for {workflow_label} issue. Please choose an option to proceed.',
                'next_step': 'Call continue_workflow_with_user_choice() with user choice',
                'is_shared_workspace': True,  # Enable push to GitLab tracking
                'agent_id': agent_runtime_id  # For tracking fixes per agent
            }
            
            # Add code fix preview for mixed workflow
            if workflow_type == 'mixed' and code_fix_preview:
                result['code_fix_preview'] = code_fix_preview
                result['note'] = 'Both package and code fix options analyzed. Choose your preferred approach.'
            else:
                result['note'] = 'Package analysis complete. Code fixes available if needed.'
            
            # Cache the workflow result for future use (content-based caching)
            self._workflow_cache[workflow_cache_key] = result
            self._log_step(f"\nWorkflow result cached with key: {workflow_cache_key}")
            self._log_step("   Future runs with same error will skip ECR/extraction/analysis")
            
            return result
            
        except Exception as e:
            self._log_error(f"Library analysis failed: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'message': 'Library analysis failed. You may need to proceed with manual fixes.'
            }
    
    def continue_mixed_workflow(self, previous_result: Dict[str, Any], user_choice: str) -> Dict[str, Any]:
        """Continue mixed workflow based on user choice
        
        Args:
            previous_result: Result from _handle_mixed_workflow_with_choice
            user_choice: One of: 'fix_code_only', 'both', 'upgrade_packages_only', 'skip'
        """
        
        self._log_step("="*80)
        self._log_step(f"USER CHOICE: {user_choice.upper().replace('_', ' ')}")
        self._log_step("="*80)
        
        if user_choice == 'skip':
            self._log_step("⏭️  User chose to skip automated fixes")
            return {
                'status': 'skipped',
                'message': 'User chose to handle fixes manually',
                'library_analysis': previous_result.get('library_analysis', {})
            }
        
        elif user_choice in ['upgrade_packages_only', 'library']:
            self._log_step(f"User chose '{user_choice}' - upgrade packages only")
            self._log_step("Extracting agent files and updating requirements.txt...")
            
            try:
                # Get runtime details
                runtime_details = previous_result.get('runtime_details', {})
                if not runtime_details:
                    self._log_error("Missing runtime_details in previous result")
                    return {
                        'status': 'failed',
                        'error': 'Missing runtime details from previous workflow step',
                        'user_choice': user_choice,
                        'message': 'Cannot continue workflow - missing runtime information'
                    }
                
                agent_runtime_id = runtime_details.get('agent_runtime_id')
                package_recommendations = previous_result.get('package_recommendations', [])
                ai_analysis = previous_result.get('ai_analysis', {})
                
                # Run the code fix workflow but ONLY update requirements.txt
                # We'll pass a flag to indicate we only want package updates
                self._log_step("   Running package upgrade workflow...")
                
                # Create a modified AI analysis that only targets requirements.txt
                modified_ai_analysis = ai_analysis.copy() if ai_analysis else {}
                modified_ai_analysis['package_upgrade_only'] = True
                modified_ai_analysis['package_recommendations'] = package_recommendations
                
                # CRITICAL: Only include requirements.txt in files_to_fix
                # This ensures Code Agent ONLY updates requirements.txt and doesn't touch Python code
                modified_ai_analysis['files_to_fix'] = ['requirements.txt']
                
                # Add instructions for Code Agent to only update requirements.txt
                modified_ai_analysis['instructions'] = """
                CRITICAL: ONLY update requirements.txt with the package recommendations.
                DO NOT modify any Python code files.
                DO NOT fix any code issues.
                ONLY update package versions in requirements.txt based on the recommendations provided.
                """
                
                # Run code fix workflow with package-only flag
                code_fix_result = self._handle_code_fix_issue(
                    agent_runtime_id, 
                    modified_ai_analysis, 
                    previous_result.get('classification', {})
                )
                
                # Add metadata
                code_fix_result['user_choice'] = user_choice
                code_fix_result['package_recommendations'] = package_recommendations
                code_fix_result['message'] = 'requirements.txt updated and pushed to GitLab'
                
                return code_fix_result
                
            except Exception as e:
                self._log_error(f"Package upgrade workflow failed: {e}")
                import traceback
                self._log_error(f"Traceback: {traceback.format_exc()}")
                
                return {
                    'status': 'failed',
                    'error': str(e),
                    'error_traceback': traceback.format_exc(),
                    'user_choice': user_choice,
                    'package_recommendations': previous_result.get('package_recommendations', []),
                    'message': f'Package upgrade failed: {str(e)}'
                }
        
        elif user_choice in ['fix_code_only', 'code', 'both']:
            self._log_step(f"User chose Code Agent - preparing to apply fixes...")
            
            # Validate required data from previous result
            runtime_details = previous_result.get('runtime_details', {})
            if not runtime_details:
                self._log_error("Missing runtime_details in previous result")
                return {
                    'status': 'failed',
                    'error': 'Missing runtime details from previous workflow step',
                    'user_choice': user_choice,
                    'message': 'Cannot continue workflow - missing runtime information'
                }
            
            classification = previous_result.get('classification', {})
            package_recommendations = previous_result.get('package_recommendations', [])
            ai_analysis = previous_result.get('ai_analysis', {})
            
            if not ai_analysis:
                self._log_error("Missing ai_analysis in previous result")
                return {
                    'status': 'failed',
                    'error': 'Missing AI analysis from previous workflow step',
                    'user_choice': user_choice,
                    'message': 'Cannot continue workflow - missing error analysis'
                }
            
            # Check if we already have cached code analysis (from mixed workflow preview)
            if hasattr(self, '_cached_code_analysis') and hasattr(self, '_cached_extracted_files'):
                self._log_step("   Using cached code analysis (already extracted for preview)")
                code_analysis = self._cached_code_analysis
                extracted_files = self._cached_extracted_files
            else:
                # Need to extract codebase (for package_only workflow that chose code fix)
                self._log_step("   � aExtracting codebase for Code Agent...")
                
                # Use cached image info if available (Fix All - reuse within session)
                if hasattr(self, '_cached_image_info') and self._cached_image_info:
                    self._log_step("   Using cached ECR image (Fix All reuse)")
                    image_info = self._cached_image_info
                else:
                    # First pattern in Fix All or Fix This - always pull fresh
                    self._log_step("   Pulling ECR image (fresh pull)...")
                    image_info = self._fetch_agent_code(runtime_details, force_pull=True)
                    # Cache for subsequent patterns in Fix All
                    self._cached_image_info = image_info
                
                # Extract full codebase
                self._log_step("   📂 Extracting full codebase...")
                code_analysis = self._extract_and_analyze_code(image_info['image_id'])
                extracted_files = self._extract_files_as_dict(code_analysis)
            
            # IMPORTANT: Build list of files to fix based on user choice
            files_to_fix = set()
            
            # 1. Files from error traceback (always include these)
            error_details = previous_result.get('library_analysis', {}).get('error_details', {})
            traceback = error_details.get('traceback', '')
            if traceback:
                # Extract file paths from traceback
                import re
                file_matches = re.findall(r'File "([^"]+)"', traceback)
                for file_path in file_matches:
                    # Get just the filename (e.g., agent.py from /app/agent.py)
                    filename = file_path.split('/')[-1]
                    if filename and filename.endswith('.py'):
                        files_to_fix.add(filename)
                        self._log_step(f"   Adding {filename} (from error traceback)")
            
            # 2. Files from package recommendations - based on user choice
            if user_choice == 'both':
                # User wants BOTH code fixes AND package updates
                self._log_step(f"\n   User chose 'both' - including ALL files:")
                
                for rec in package_recommendations:
                    # Add requirements.txt if package upgrade recommended
                    if rec.get('type') in ['package_upgrade', 'package_update', 'dependency_update']:
                        files_to_fix.add('requirements.txt')
                        self._log_step(f"   Adding requirements.txt (package upgrade needed)")
                    
                    # Add any other affected files mentioned
                    affected_files = rec.get('affected_files', [])
                    for file in affected_files:
                        files_to_fix.add(file)
                        self._log_step(f"   Adding {file} (from package recommendation)")
            
            elif user_choice in ['fix_code_only', 'code']:
                # User wants ONLY code fixes (backward compatible)
                # Don't add requirements.txt - just fix code to work with current packages
                self._log_step(f"\n   User chose '{user_choice}' - backward compatible fixes only")
                self._log_step(f"   ⏭️  Skipping requirements.txt (keeping current package versions)")
            
            self._log_step(f"\nFinal files to fix: {', '.join(sorted(files_to_fix))}")
            
            # Reuse the full code fix workflow from _handle_code_fix_issue
            # This ensures we use the same proven logic
            try:
                self._log_step("Running full code fix workflow...")
                agent_runtime_id = runtime_details.get('agent_runtime_id', 'unknown')
                
                # For "both" choice, we need to update the AI analysis to include requirements.txt
                if user_choice == 'both':
                    self._log_step("User chose 'both' - will update BOTH code AND requirements.txt")
                    
                    # Deep copy to avoid mutating the original
                    import copy
                    enhanced_ai_analysis = copy.deepcopy(ai_analysis)
                    
                    # CRITICAL: Add ALL files from files_to_fix set (including requirements.txt)
                    # This is the key - Code Agent checks for requirements.txt in this list
                    enhanced_ai_analysis['files_to_fix'] = list(files_to_fix)
                    
                    self._log_step(f"   Enhanced AI analysis with files_to_fix: {enhanced_ai_analysis['files_to_fix']}")
                    
                    # Add package recommendations to the AI analysis so Code Agent knows to update requirements.txt
                    enhanced_ai_analysis['package_recommendations'] = package_recommendations
                    enhanced_ai_analysis['update_requirements'] = True
                    enhanced_ai_analysis['user_choice'] = 'both'
                    
                    # Add a note to the error details to tell Code Agent to update requirements.txt
                    if 'error_details' not in enhanced_ai_analysis:
                        enhanced_ai_analysis['error_details'] = {}
                    elif not isinstance(enhanced_ai_analysis['error_details'], dict):
                        # Convert to dict if it's not already
                        enhanced_ai_analysis['error_details'] = {'original': str(enhanced_ai_analysis['error_details'])}
                    
                    # Format package recommendations for Code Agent
                    pkg_rec_text = "\n".join([
                        f"- {rec.get('package', 'unknown')}: {rec.get('from', 'current')} → {rec.get('to', 'latest')}"
                        for rec in package_recommendations
                    ]) if package_recommendations else "No specific recommendations"
                    
                    enhanced_ai_analysis['error_details']['additional_instructions'] = (
                        "IMPORTANT: User chose to update BOTH code AND packages.\n"
                        "Please also update requirements.txt with the recommended package versions.\n\n"
                        f"Package recommendations:\n{pkg_rec_text}"
                    )
                    
                    self._log_step(f"   Enhanced AI analysis with {len(package_recommendations)} package recommendations")
                    self._log_step(f"   Added requirements.txt to files_to_fix list")
                    
                    # For "both", we need to ensure requirements.txt gets to Code Agent
                    # Call _handle_code_fix_issue but it will extract files from traceback
                    # So we need to pass the files_to_fix through the orchestrator instead
                    code_fix_result = self._handle_code_fix_issue(agent_runtime_id, enhanced_ai_analysis, classification)
                else:
                    self._log_step(f"User chose '{user_choice}' - backward compatible code fixes only")
                    code_fix_result = self._handle_code_fix_issue(agent_runtime_id, ai_analysis, classification)
                
                # Validate the result
                if not code_fix_result or not isinstance(code_fix_result, dict):
                    raise ValueError(f"Invalid result from code fix workflow: {type(code_fix_result)}")
                
                # Check if the workflow actually succeeded
                if code_fix_result.get('status') == 'failed':
                    self._log_error(f"Code fix workflow returned failed status: {code_fix_result.get('error', 'Unknown error')}")
                    # Return the failed result as-is but add our metadata
                    code_fix_result['user_choice'] = user_choice
                    code_fix_result['package_recommendations'] = package_recommendations
                    return code_fix_result
                
                # Add user choice and package recommendations to result
                code_fix_result['user_choice'] = user_choice
                code_fix_result['package_recommendations'] = package_recommendations
                
                # CRITICAL: Preserve library_agent_output from initial analysis for UI display
                self._log_step(f"   DEBUG: previous_result keys: {list(previous_result.keys())}")
                self._log_step(f"   DEBUG: Has library_agent_output: {'library_agent_output' in previous_result}")
                if 'library_agent_output' in previous_result:
                    lib_output = previous_result['library_agent_output']
                    self._log_step(f"   DEBUG: library_agent_output type: {type(lib_output)}")
                    self._log_step(f"   DEBUG: library_agent_output length: {len(lib_output) if lib_output else 0}")
                    code_fix_result['library_agent_output'] = lib_output
                    self._log_step(f"   Preserved library_agent_output for UI display ({len(lib_output) if lib_output else 0} chars)")
                else:
                    self._log_error(f"   previous_result does NOT have library_agent_output!")
                    self._log_error(f"   Available keys: {list(previous_result.keys())}")
                
                # Also preserve workflow_type to indicate this is a mixed workflow
                code_fix_result['workflow_type'] = 'mixed'
                self._log_step(f"   Set workflow_type to 'mixed'")
                
                if user_choice == 'both':
                    # Check if requirements.txt was actually updated
                    fixed_files = code_fix_result.get('fixed_files', {})
                    if not fixed_files:
                        self._log_step("   No fixed files returned from code fix workflow")
                    
                    requirements_updated = False
                    if isinstance(fixed_files, dict):
                        requirements_updated = (
                            'requirements.txt' in fixed_files or 
                            any('requirements' in str(f).lower() for f in fixed_files.keys())
                        )
                    
                    if requirements_updated:
                        self._log_step("   requirements.txt was updated by Code Agent")
                        code_fix_result['message'] = 'Code fixes AND requirements.txt updated successfully'
                    else:
                        self._log_step("   requirements.txt was NOT updated by Code Agent")
                        code_fix_result['message'] = 'Code fixes applied successfully - Please manually update requirements.txt based on recommendations above'
                        code_fix_result['requirements_update_needed'] = True
                else:
                    self._log_step("   Code fixes applied (backward compatible)")
                
                return code_fix_result
                
            except Exception as e:
                self._log_error(f"Code fix workflow failed: {e}")
                import traceback
                self._log_error(f"Traceback: {traceback.format_exc()}")
                
                return {
                    'status': 'failed',
                    'error': str(e),
                    'error_traceback': traceback.format_exc(),
                    'user_choice': user_choice,
                    'package_recommendations': package_recommendations,
                    'message': f'Code fix failed: {str(e)}'
                }
        
        else:
            self._log_error(f"Invalid user choice: {user_choice}")
            self._log_error(f"Valid choices are: 'library', 'code', 'both', 'skip'")
            return {
                'status': 'error',
                'message': f'Invalid user choice: {user_choice}. Valid choices are: library, code, both, skip'
            }
    
    def _get_runtime_details(self, agent_runtime_id: str) -> Dict[str, Any]:
        """Get AgentCore Runtime details (supports container and code deployment)."""
        self._log_step(f"Retrieving runtime details for {agent_runtime_id}")
        
        # Remove -DEFAULT suffix if present (API expects runtime ID without endpoint suffix)
        if agent_runtime_id.endswith('-DEFAULT'):
            agent_runtime_id = agent_runtime_id[:-8]  # Remove '-DEFAULT'
            self._log_step(f"Adjusted runtime ID to: {agent_runtime_id}")
        
        try:
            response = self.bedrock_client.get_agent_runtime(agentRuntimeId=agent_runtime_id)
            
            artifact = response.get('agentRuntimeArtifact', {})
            container_config = artifact.get('containerConfiguration', {})
            code_config = artifact.get('codeConfiguration', {})
            ecr_uri = container_config.get('containerUri')

            details = {
                'agent_runtime_id': agent_runtime_id,
                'runtime_version': response.get('agentRuntimeVersion'),
                'runtime_name': response.get('agentRuntimeName'),
                'status': response.get('status'),
                'role_arn': response.get('roleArn'),
                'network_configuration': response.get('networkConfiguration'),
            }

            if ecr_uri:
                # Container-based deployment
                details['deployment_type'] = 'container'
                details['ecr_image_uri'] = ecr_uri
                self._log_step(f"Found ECR image: {ecr_uri}")
            elif code_config:
                # Direct code deployment (S3 zip)
                s3 = code_config.get('code', {}).get('s3', {})
                bucket = s3.get('bucket')
                prefix = s3.get('prefix')
                if not bucket or not prefix:
                    raise Exception("Code configuration missing S3 bucket/prefix")
                details['deployment_type'] = 'code'
                details['s3_bucket'] = bucket
                details['s3_prefix'] = prefix
                details['runtime'] = code_config.get('runtime', 'PYTHON_3_13')
                details['entry_point'] = code_config.get('entryPoint', ['agent.py'])
                self._log_step(f"Found S3 code package: s3://{bucket}/{prefix}")
            else:
                raise Exception("No container image or code configuration found in runtime")
            
            return details
            
        except Exception as e:
            self._log_error(f"Failed to get runtime details: {e}")
            raise
    
    def _clone_from_git_repo(self, repo_url: str, branch: str, agent_runtime_id: str) -> Dict[str, Any]:
        """Clone code from existing Git repository
        
        Args:
            repo_url: Git repository URL
            branch: Branch to clone
            agent_runtime_id: Agent runtime ID for naming
            
        Returns:
            Code analysis dict with extracted_path
        """
        import subprocess
        
        # Create extraction directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        extract_dir = self.work_dir / f"git_clone_{timestamp}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        self._log_step(f"📂 Cloning to: {extract_dir}")
        
        try:
            # Clone the repository
            self._log_step(f"Cloning repository...")
            result = subprocess.run(
                ['git', 'clone', '--branch', branch, '--single-branch', repo_url, str(extract_dir)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")
            
            self._log_step(f"Repository cloned successfully")
            
            # Find Python files
            python_files = []
            requirements_files = []
            
            # PRIORITY: Check if app/ directory exists with files (shared workspace mode)
            app_dir = extract_dir / "app"
            if app_dir.exists() and any(app_dir.glob("*.py")):
                # Shared workspace mode - only scan app/ directory to get current code
                self._log_step("Shared workspace detected - scanning app/ directory only")
                for root, dirs, files in os.walk(app_dir):
                    # Skip .git directory
                    if '.git' in root:
                        continue
                        
                    for file in files:
                        file_path = Path(root) / file
                        if file.endswith('.py'):
                            python_files.append(str(file_path))
                        elif file in ['requirements.txt', 'requirements-dev.txt', 'requirements-test.txt']:
                            requirements_files.append(str(file_path))
            else:
                # First time or non-shared workspace - scan entire directory
                for root, dirs, files in os.walk(extract_dir):
                    # Skip .git directory and helper directories
                    if '.git' in root or '/extracted' in root or '/fixed' in root or '/backups' in root:
                        continue
                        
                    for file in files:
                        file_path = Path(root) / file
                        if file.endswith('.py'):
                            python_files.append(str(file_path))
                        elif file in ['requirements.txt', 'requirements-dev.txt', 'requirements-test.txt']:
                            requirements_files.append(str(file_path))
            
            self._log_step(f"Found {len(python_files)} Python files")
            self._log_step(f"Found {len(requirements_files)} requirements files")
            
            # Log some file names
            for py_file in python_files[:5]:
                self._log_step(f"   {py_file}")
            
            return {
                'extracted_path': str(extract_dir),
                'python_files': python_files,
                'requirements_files': requirements_files,
                'source': 'git',
                'repo_url': repo_url,
                'branch': branch
            }
            
        except Exception as e:
            self._log_error(f"Failed to clone Git repository: {e}")
            raise
    
    def _fetch_agent_code(self, runtime_details: Dict[str, Any], force_pull: bool = True) -> Dict[str, Any]:
        """Fetch agent code from either ECR (container) or S3 (code deployment).

        Returns an image_info-style dict with 'image_id' and 'extract_path'.
        Both paths extract into self.work_dir/extracted_code/app so the rest of
        the workflow is agnostic to deployment type.
        """
        deployment_type = runtime_details.get('deployment_type', 'container')
        if deployment_type == 'code':
            return self._download_s3_code(
                runtime_details['s3_bucket'],
                runtime_details['s3_prefix'],
                force_pull=force_pull,
            )
        return self._pull_ecr_image(runtime_details['ecr_image_uri'], force_pull=force_pull)

    def _download_s3_code(self, bucket: str, prefix: str, force_pull: bool = True) -> Dict[str, Any]:
        """Download + unzip a direct-code-deployment package from S3.

        Extracts into self.work_dir/extracted_code/app to match the layout the
        rest of the workflow (and the ECR path) expects.
        """
        import zipfile
        import boto3

        self._log_step(f"Downloading code package from s3://{bucket}/{prefix}")
        extract_path = self.work_dir / "extracted_code"
        app_dir = extract_path / "app"

        if not force_pull and app_dir.exists() and any(app_dir.glob("*.py")):
            self._log_step("Using cached extraction (Fix All reuse)")
            return {'status': 'success', 'image_id': f"s3://{bucket}/{prefix}",
                    'repository': prefix, 'extract_path': str(extract_path), 'cached': True}

        app_dir.mkdir(parents=True, exist_ok=True)
        s3 = boto3.client("s3", region_name=getattr(self, "region", "us-east-1"))

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as tmp:
            s3.download_fileobj(bucket, prefix, tmp)
            tmp.flush()
            tmp.seek(0)
            with zipfile.ZipFile(tmp.name, "r") as zf:
                for member in zf.namelist():
                    # Only extract source/config files into app/, skip bundled deps dirs
                    base = member.split("/")[0]
                    if member.endswith("/"):
                        continue
                    # Place top-level source files directly under app/
                    if "/" not in member:
                        target = app_dir / member
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(member))

        py_count = len(list(app_dir.glob("*.py")))
        self._log_step(f"Extracted {py_count} source files to {app_dir}")
        return {'status': 'success', 'image_id': f"s3://{bucket}/{prefix}",
                'repository': prefix, 'extract_path': str(extract_path)}

    def _pull_ecr_image(self, ecr_uri: str, force_pull: bool = True) -> Dict[str, Any]:
        """Download agent code from ECR using boto3 API (no Docker needed).
        
        Args:
            ecr_uri: Full ECR image URI (e.g. ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/repo:tag)
            force_pull: If True, always pull fresh. If False, reuse cached extraction.
        """
        self._log_step(f"Pulling ECR image via boto3: {ecr_uri} (force_pull={force_pull})")
        
        try:
            # Parse ECR URI
            parts = ecr_uri.split('/')
            if len(parts) < 2:
                raise Exception(f"Invalid ECR URI format: {ecr_uri}")
            
            registry = parts[0]
            repository_with_tag = '/'.join(parts[1:])
            repository = repository_with_tag.split(':')[0]
            tag = repository_with_tag.split(':')[1] if ':' in repository_with_tag else 'latest'
            
            # Extract region from registry
            registry_parts = registry.split('.')
            region = registry_parts[3] if len(registry_parts) >= 4 else 'us-east-1'
            
            self._log_step(f"Repository: {repository}, Tag: {tag}, Region: {region}")
            
            # Check if already extracted (shared workspace reuse)
            extract_path = self.work_dir / "extracted_code"
            app_dir = extract_path / "app"
            if not force_pull and app_dir.exists() and any(app_dir.glob("*.py")):
                self._log_step("Using cached extraction (Fix All reuse)")
                return {
                    'status': 'success',
                    'image_id': ecr_uri,
                    'repository': repository_with_tag,
                    'cached': True,
                }
            
            # Use ECR extractor (boto3, no Docker)
            result = self.ecr_extractor.extract_code(
                repository=repository,
                tag=tag,
                extract_to=extract_path,
            )
            
            if result['status'] != 'success':
                raise Exception(result.get('error', 'ECR extraction failed'))
            
            self._log_step(f"Extracted {result['files_extracted']} files to {extract_path}")
            
            return {
                'status': 'success',
                'image_id': ecr_uri,
                'repository': repository_with_tag,
                'extract_path': str(extract_path),
            }
            
        except Exception as e:
            self._log_error(f"Failed to pull ECR image: {e}")
            
            # Parse repo name for error message
            try:
                repository = ecr_uri.split('/')[-1].split(':')[0]
                region = ecr_uri.split('.')[3]
            except Exception:
                repository = ecr_uri
                region = 'us-east-1'
            
            self._log_error(f"  - ECR URI: {ecr_uri}")
            self._log_error(f"  - Required IAM permissions:")
            self._log_error(f"    • ecr:GetAuthorizationToken")
            self._log_error(f"    • ecr:BatchGetImage")
            self._log_error(f"    • ecr:GetDownloadUrlForLayer")
            self._log_error(f"    • ecr:DescribeRepositories")
            self._log_error(f"    • ecr:DescribeImages")
            
            raise
    
    def _extract_and_analyze_code(self, image_id: str) -> Dict[str, Any]:
        """Extract code from ECR image and analyze structure (no Docker needed)."""
        self._log_step(f"Extracting code from image...")
        
        # Check if code already extracted (shared workspace mode)
        extract_path = self.work_dir / "extracted_code"
        app_dir = extract_path / "app"
        
        if app_dir.exists() and any(app_dir.glob("*.py")):
            self._log_step("SHARED WORKSPACE: Code already extracted, skipping ECR extraction")
            self._log_step(f"   📂 Using existing code in: {app_dir}")
            analysis = self._analyze_code_structure(extract_path)
            analysis['extracted_path'] = extract_path
            analysis['extracted_files'] = []
            return analysis
        
        try:
            # Parse repository and tag from image_id
            repo_part = image_id.split("/")[-1] if "/" in image_id else image_id
            repository = repo_part.split(":")[0]
            tag = repo_part.split(":")[1] if ":" in repo_part else "latest"
            
            # If image_id has registry prefix, extract repo name
            if "/" in image_id:
                parts = image_id.split("/", 1)
                repository = parts[1].split(":")[0]
            
            # Use ECR extractor
            result = self.ecr_extractor.extract_code(
                repository=repository,
                tag=tag,
                extract_to=extract_path,
            )
            
            if result['status'] != 'success':
                raise Exception(result.get('error', 'Extraction failed'))
            
            # Analyze code structure
            analysis = self._analyze_code_structure(extract_path)
            analysis['extracted_path'] = extract_path
            analysis['extracted_files'] = result.get('file_list', [])
            
            return analysis
            
        except Exception as e:
            self._log_error(f"Failed to extract code: {e}")
            raise
    
    def _analyze_code_structure(self, code_path: Path) -> Dict[str, Any]:
        """Analyze extracted code structure"""
        self._log_step("Analyzing code structure...")
        
        analysis = {
            'python_files': [],
            'requirements_files': [],
            'dockerfile_path': None,
            'main_entry_points': [],
            'dependencies': [],
            'total_files': 0
        }
        
        try:
            for root, dirs, files in os.walk(code_path):
                analysis['total_files'] += len(files)
                
                for file in files:
                    file_path = Path(root) / file
                    
                    # Skip empty files and weird artifacts
                    if file.startswith('=') or file.startswith('.'):
                        continue
                    
                    if file.endswith('.py'):
                        # Check file size before adding
                        file_size = file_path.stat().st_size if file_path.exists() else 0
                        if file_size > 0:
                            analysis['python_files'].append(str(file_path))
                            
                            # Check for main entry points
                            if file in ['main.py', 'app.py', 'handler.py', '__main__.py', 'agent.py']:
                                analysis['main_entry_points'].append(str(file_path))
                        else:
                            self._log_step(f"   Skipping empty Python file during analysis: {file}")
                    
                    elif file in ['requirements.txt', 'requirements_buggy.txt', 'Pipfile', 'pyproject.toml']:
                        # Check file size before adding
                        file_size = file_path.stat().st_size if file_path.exists() else 0
                        if file_size > 0:
                            analysis['requirements_files'].append(str(file_path))
                        else:
                            self._log_step(f"   Skipping empty requirements file during analysis: {file}")
                    
                    elif file.lower() == 'dockerfile':
                        analysis['dockerfile_path'] = str(file_path)
            
            self._log_step(f"Found {len(analysis['python_files'])} Python files")
            self._log_step(f"Found {len(analysis['requirements_files'])} requirements files")
            
            # Log file paths for debugging
            for py_file in analysis['python_files'][:3]:
                self._log_step(f"   {py_file}")
            
            return analysis
            
        except Exception as e:
            self._log_error(f"Code analysis failed: {e}")
            return analysis
    

    
    def _extract_files_from_error_traces(self, ai_analysis: Dict[str, Any], code_analysis: Dict[str, Any]) -> Dict[str, str]:
        """Extract files mentioned in error traces that need fixing
        
        Args:
            ai_analysis: AI error analysis with traceback
            code_analysis: Code analysis with file paths
            
        Returns:
            Dictionary of file paths to file contents
        """
        files_to_fix = {}
        extracted_path = Path(code_analysis['extracted_path'])
        
        # Get traceback from error details
        error_details = ai_analysis.get('error_details', {})
        traceback_text = error_details.get('traceback', '')
        
        if not traceback_text:
            self._log_error("No traceback found in error analysis")
            return files_to_fix
        
        # Parse traceback to find file paths
        import re
        # Match patterns like: File "/app/agent.py", line 94
        file_pattern = r'File "([^"]+)"'
        matches = re.findall(file_pattern, traceback_text)
        
        self._log_step(f"   Found {len(matches)} file references in traceback")
        
        for file_ref in matches:
            # Extract just the filename
            filename = Path(file_ref).name
            
            # PRIORITY 1: Check if app/ directory exists with files (shared workspace mode)
            app_dir = extracted_path / "app"
            if app_dir.exists() and any(app_dir.glob("*.py")):
                # Shared workspace mode - read from app/ to get previously fixed code
                app_file = app_dir / filename
                if app_file.exists():
                    try:
                        content = app_file.read_text(encoding='utf-8')
                        if content.strip():
                            # Store with just filename as key (Code Agent returns just filename)
                            # This ensures consistency between read and write operations
                            files_to_fix[filename] = content
                            self._log_step(f"      Found in app/: {filename} ({len(content)} chars) [preserves previous fixes]")
                            continue
                    except Exception as e:
                        self._log_error(f"      Could not read from app/{filename}: {e}")
            
            # PRIORITY 2: Fall back to searching entire directory tree
            for root, dirs, files in os.walk(extracted_path):
                if filename in files:
                    file_path = Path(root) / filename
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        if content.strip():
                            files_to_fix[str(file_path)] = content
                            self._log_step(f"      Found: {filename} ({len(content)} chars)")
                    except Exception as e:
                        self._log_error(f"      Could not read {filename}: {e}")
                    break
        
        # Filter files to only those that actually need fixing
        if files_to_fix:
            files_to_fix = self._filter_files_needing_fixes(files_to_fix, ai_analysis)
        
        return files_to_fix
    
    def _filter_files_needing_fixes(self, files_to_fix: Dict[str, str], ai_analysis: Dict[str, Any]) -> Dict[str, str]:
        """Ask LLM to determine which files actually need fixing
        
        Args:
            files_to_fix: Dictionary of file paths to contents
            ai_analysis: AI error analysis
            
        Returns:
            Filtered dictionary of only files that need fixing
        """
        self._log_step("   Asking LLM to determine which files need fixing...")
        
        # Initialize AI analyzer
        analyzer = AIErrorAnalyzer()
        
        # Create prompt for LLM to analyze which files need fixing
        files_list = "\n".join([f"- {Path(f).name}: {len(c)} chars" for f, c in files_to_fix.items()])
        
        prompt = f"""Analyze which files actually need fixing based on this error.

ERROR ANALYSIS:
{ai_analysis.get('summary', '')}

ERROR MESSAGE:
{ai_analysis.get('error_details', {}).get('message', '')}

TRACEBACK:
{ai_analysis.get('error_details', {}).get('traceback', '')}

FILES FOUND IN TRACEBACK:
{files_list}

For each file, determine if it needs fixing or is just mentioned in the stack trace.
For example, __init__.py files are often just package markers and don't need fixing.

Return ONLY a JSON object with this format:
{{
  "files_to_fix": ["filename1.py", "filename2.py"],
  "reasoning": "Brief explanation of why each file needs or doesn't need fixing"
}}

Be strict - only include files that actually contain the error or need code changes."""
        
        # Try with fallback models
        from src.config.config import get_fallback_models
        fallback_models = get_fallback_models()
        models_to_try = [analyzer.model_id] + fallback_models
        
        for attempt, model_id in enumerate(models_to_try, 1):
            try:
                if attempt > 1:
                    self._log_step(f"   Fallback attempt {attempt}/{len(models_to_try)} with model: {model_id}")
                
                response = analyzer.bedrock_client.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"temperature": 0.1, "maxTokens": 1000}
                )
            
                response_text = response['output']['message']['content'][0]['text']
                
                # Extract JSON from response
                import json
                import re
                
                # Try to find JSON in the response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    files_to_keep = result.get('files_to_fix', [])
                    reasoning = result.get('reasoning', '')
                    
                    self._log_step(f"   LLM Analysis: {reasoning}")
                    
                    # Filter the files
                    filtered_files = {}
                    for file_path, content in files_to_fix.items():
                        filename = Path(file_path).name
                        if filename in files_to_keep:
                            filtered_files[file_path] = content
                            self._log_step(f"      Will fix: {filename}")
                        else:
                            self._log_step(f"      ⏭️  Skipping: {filename} (not relevant to error)")
                    
                    return filtered_files
                else:
                    self._log_error("   Could not parse LLM response, keeping all files")
                    return files_to_fix
                    
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(keyword in error_msg.lower() for keyword in [
                    'serviceunavailableexception', 'throttlingexception', 'too many connections',
                    'service unavailable', 'throttling', 'rate limit'
                ])
                
                if is_retryable and attempt < len(models_to_try):
                    self._log_error(f"   LLM filtering failed (attempt {attempt}): {error_msg}")
                    import time
                    time.sleep(2)
                    continue
                else:
                    self._log_error(f"   LLM filtering failed: {e}, keeping all files")
                    return files_to_fix
        
        # All attempts failed
        self._log_error("   All LLM filtering attempts failed, keeping all files")
        return files_to_fix
    
    def _fix_files_with_llm(self, files_to_fix: Dict[str, str], ai_analysis: Dict[str, Any], code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Fix files using Code Agent with its tools (AST analyzer, file modifier, pytest)
        
        Args:
            files_to_fix: Dictionary of file paths to contents
            ai_analysis: AI error analysis
            code_analysis: Code analysis
            
        Returns:
            Dictionary with fix results
        """
        from agents.code_agent import code_agent_tool
        
        extracted_path = Path(code_analysis['extracted_path'])
        
        # Prepare error analysis for Code Agent
        error_summary = ai_analysis.get('summary', '')
        error_message = ai_analysis.get('error_details', {}).get('message', '')
        traceback = ai_analysis.get('error_details', {}).get('traceback', '')
        
        # Format error analysis for Code Agent
        error_analysis = f"""ERROR ANALYSIS:
{error_summary}

ERROR MESSAGE:
{error_message}

TRACEBACK:
{traceback}

FILES TO FIX:
{', '.join(Path(f).name for f in files_to_fix.keys())}

TASK: Fix the code issues in these files. Use your tools to:
1. Analyze the files with AST analyzer
2. Apply fixes using file_modifier_tool with custom fixes
3. Test the fixes with Python REPL or pytest
4. Ensure all syntax errors are resolved
"""
        
        # Convert files_to_fix to JSON format for Code Agent
        import json
        files_json = json.dumps({Path(k).name: v for k, v in files_to_fix.items()})
        
        self._log_step(f"   Invoking Code Agent to fix {len(files_to_fix)} files...")
        
        try:
            # Execute Code Agent with the specific files
            result = code_agent_tool(
                error_analysis=error_analysis,
                extracted_files_json=files_json,
                work_dir=str(extracted_path)
            )
            
            # Parse the result
            if isinstance(result, str):
                result_data = json.loads(result)
            else:
                result_data = result
            
            # Check if Code Agent returned an error
            if result_data.get('status') == 'error':
                error_msg = result_data.get('error', 'Unknown error')
                self._log_error(f"   Code Agent returned error: {error_msg}")
                
                # Check if it's a Bedrock service error
                if 'serviceUnavailableException' in error_msg or 'Bedrock is unable to process' in error_msg:
                    self._log_error(f"   Bedrock service is unavailable")
                    self._log_error(f"   This is a temporary AWS service issue, not a code problem")
                    raise Exception(f"Bedrock service unavailable: {error_msg}")
                else:
                    raise Exception(f"Code Agent failed: {error_msg}")
        
        except Exception as e:
            error_msg = str(e)
            self._log_error(f"   Code Agent execution failed: {error_msg}")
            
            # Check for specific Bedrock errors
            if 'ServiceUnavailableException' in error_msg or 'Too many connections' in error_msg:
                self._log_error("   Bedrock API: Too many concurrent connections")
                return {
                    'error': 'Bedrock API rate limit exceeded',
                    'error_type': 'bedrock_rate_limit',
                    'error_details': error_msg,
                    'fixed_files': {}
                }
            elif 'ThrottlingException' in error_msg or 'rate limit' in error_msg.lower():
                self._log_error("   Bedrock API: Request throttled")
                return {
                    'error': 'Bedrock API throttling',
                    'error_type': 'bedrock_throttling',
                    'error_details': error_msg,
                    'fixed_files': {}
                }
            elif 'ValidationException' in error_msg or 'ModelNotReadyException' in error_msg:
                self._log_error("   Bedrock API: Model validation error")
                return {
                    'error': 'Bedrock model validation error',
                    'error_type': 'bedrock_model_error',
                    'error_details': error_msg,
                    'fixed_files': {}
                }
            elif 'EventLoopException' in error_msg:
                # Extract the underlying error from EventLoopException
                if 'ServiceUnavailableException' in error_msg or 'Too many connections' in error_msg:
                    self._log_error("   Bedrock API: Too many concurrent connections (from EventLoopException)")
                    return {
                        'error': 'Bedrock API rate limit exceeded',
                        'error_type': 'bedrock_rate_limit',
                        'error_details': error_msg,
                        'fixed_files': {}
                    }
                else:
                    # Generic EventLoopException
                    self._log_error("   Agent execution error")
                    return {
                        'error': f'Agent execution failed: {error_msg}',
                        'error_type': 'agent_execution_error',
                        'error_details': error_msg,
                        'fixed_files': {}
                    }
            else:
                # Generic error
                return {
                    'error': error_msg,
                    'error_type': 'unknown',
                    'error_details': error_msg,
                    'fixed_files': {}
                }
        
        try:
            
            # Get fixed files and agent response from Code Agent result
            fixed_files = result_data.get('fixed_files', {})
            agent_response = result_data.get('agent_response', '')
            
            # Write fixed files back to disk (in place)
            for filename, content in fixed_files.items():
                # Find the original file path
                for orig_path in files_to_fix.keys():
                    if Path(orig_path).name == filename:
                        # Construct the full path correctly
                        orig_path_obj = Path(orig_path)
                        
                        if orig_path_obj.is_absolute():
                            # Already absolute, use as-is
                            full_path = orig_path_obj
                        else:
                            # Relative path - resolve relative to extracted_code directory
                            # orig_path format: "app/filename" or "extracted_code/app/filename"
                            if orig_path.startswith('extracted_code/'):
                                # Remove extracted_code/ prefix and resolve from work_dir
                                rel_path = orig_path.replace('extracted_code/', '', 1)
                                full_path = self.work_dir / rel_path
                            else:
                                # Path like "app/filename" - resolve from extracted_code directory
                                full_path = self.work_dir / orig_path
                        
                        # Ensure parent directory exists
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Write the fixed content
                        full_path.write_text(content, encoding='utf-8')
                        self._log_step(f"      Fixed and saved: {filename} → {full_path}")
                        break
            
            self._log_step(f"   Code Agent fixed {len(fixed_files)} files")
            
            return {
                'fixed_files': fixed_files, 
                'count': len(fixed_files),
                'agent_response': agent_response  # Include for summary generation
            }
            
        except Exception as e:
            error_msg = str(e)
            self._log_error(f"   Code Agent failed: {error_msg}")
            
            # Check for Bedrock-specific errors
            if 'serviceUnavailableException' in error_msg or 'Bedrock is unable to process' in error_msg:
                self._log_error(f"   Root Cause: Bedrock service is temporarily unavailable")
                self._log_error(f"   Suggestion: Wait a few minutes and try again")
                self._log_error(f"   This is an AWS service issue, not a problem with your code")
            elif 'EventLoopException' in error_msg:
                self._log_error(f"   Root Cause: Strands event loop encountered a Bedrock error")
                self._log_error(f"   Suggestion: Check Bedrock service status and retry")
            
            import traceback
            self._log_error(f"   Full Traceback: {traceback.format_exc()}")
            
            # Return error information
            return {
                'fixed_files': {}, 
                'count': 0, 
                'error': error_msg,
                'error_type': 'bedrock_unavailable' if 'serviceUnavailableException' in error_msg else 'unknown'
            }
    
    
    
    def _read_fixed_files_from_disk(self, fixed_dir: Path) -> Dict[str, str]:
        """Read fixed files from the /fixed/ directory where Code Agent saves them
        
        Args:
            fixed_dir: Path to the fixed files directory
            
        Returns:
            Dictionary of filename to file content
        """
        fixed_files = {}
        
        if not fixed_dir.exists():
            self._log_error(f"Fixed directory does not exist: {fixed_dir}")
            return fixed_files
        
        self._log_step(f"📂 Reading fixed files from: {fixed_dir}")
        
        try:
            for file_path in fixed_dir.glob("*"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        if content.strip():  # Only include non-empty files
                            fixed_files[file_path.name] = content
                            self._log_step(f"   Read: {file_path.name} ({len(content)} chars)")
                        else:
                            self._log_step(f"   Skipped empty file: {file_path.name}")
                    except Exception as e:
                        self._log_error(f"   Failed to read {file_path.name}: {e}")
            
            self._log_step(f"Read {len(fixed_files)} fixed files from disk")
            
        except Exception as e:
            self._log_error(f"Failed to read fixed files: {e}")
        
        return fixed_files
    
    def _save_fixed_files_to_disk(self, fixed_files: Dict[str, str], code_analysis: Dict[str, Any]):
        """Save fixed files back to the extracted_code directory
        
        Args:
            fixed_files: Dictionary of file paths to fixed content
            code_analysis: Code analysis with extracted_path
        """
        self._log_step("💾 Saving fixed files to disk...")
        
        extracted_path = safe_get_case_insensitive(code_analysis, 'extracted_path')
        if not extracted_path:
            self._log_error("No extracted_path found in code_analysis")
            return
        
        extracted_path = Path(extracted_path)
        
        # Check if there's an 'app' subdirectory (from Docker extraction)
        app_dir = extracted_path / "app"
        if app_dir.exists() and app_dir.is_dir():
            target_dir = app_dir
            self._log_step(f"   Saving to app directory: {app_dir}")
        else:
            target_dir = extracted_path
            self._log_step(f"   Saving to extracted directory: {extracted_path}")
        
        saved_count = 0
        for relative_path, content in fixed_files.items():
            try:
                # Construct full path - save to target directory
                file_path = target_dir / relative_path
                
                # Create parent directories if needed
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write the fixed content
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self._log_step(f"   Saved: {relative_path}")
                saved_count += 1
                
            except Exception as e:
                self._log_error(f"Failed to save {relative_path}: {e}")
        
        self._log_step(f"Saved {saved_count}/{len(fixed_files)} fixed files to disk")
    
    
    
    def _extract_files_as_dict(self, code_analysis: Dict[str, Any]) -> Dict[str, str]:
        """Extract files from code analysis as dictionary for agents
        
        Args:
            code_analysis: Code analysis results
            
        Returns:
            Dictionary of file paths to content
        """
        extracted_files = {}
        extracted_path = safe_get_case_insensitive(code_analysis, 'extracted_path')
        
        if not extracted_path:
            return extracted_files
        
        try:
            # Get Python files
            python_files = safe_get_case_insensitive(code_analysis, 'python_files', [])
            for py_file_path in python_files:
                try:
                    with open(py_file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Skip empty files
                    if not content.strip():
                        self._log_step(f"   Skipping empty file: {Path(py_file_path).name}")
                        continue
                    
                    # Get relative path
                    relative_path = Path(py_file_path).relative_to(extracted_path)
                    if len(relative_path.parts) > 1:
                        relative_path = Path(*relative_path.parts[1:])
                    
                    extracted_files[str(relative_path)] = content
                    self._log_step(f"   Extracted: {relative_path} ({len(content)} chars)")
                    
                except Exception as e:
                    self._log_error(f"Could not read Python file {py_file_path}: {e}")
            
            # Get requirements files
            requirements_files = safe_get_case_insensitive(code_analysis, 'requirements_files', [])
            for req_file_path in requirements_files:
                try:
                    with open(req_file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Skip empty files
                    if not content.strip():
                        self._log_step(f"   Skipping empty requirements file: {Path(req_file_path).name}")
                        continue
                    
                    relative_path = Path(req_file_path).relative_to(extracted_path)
                    if len(relative_path.parts) > 1:
                        relative_path = Path(*relative_path.parts[1:])
                    
                    extracted_files[str(relative_path)] = content
                    self._log_step(f"   Extracted: {relative_path} ({len(content)} chars)")
                    
                except Exception as e:
                    self._log_error(f"Could not read requirements file {req_file_path}: {e}")
            
            self._log_step(f"Extracted {len(extracted_files)} files for multi-agent processing")
            
            # Log summary of extracted files
            if extracted_files:
                self._log_step("Files ready for processing:")
                for filename, content in extracted_files.items():
                    self._log_step(f"   {filename}: {len(content)} characters")
            else:
                self._log_error("No files extracted! Check file paths and permissions.")
            
            return extracted_files
            
        except Exception as e:
            self._log_error(f"Failed to extract files as dictionary: {e}")
            return {}
    
    def _log_step(self, message: str):
        """Log a workflow step to both console and agent_execution.log"""
        import logging
        
        # Get the same logger that writes to agent_execution.log
        agent_logger = logging.getLogger('AgentDashboard')
        
        # Log to the file (this will appear in agent_execution.log)
        agent_logger.info(f"AUTO_FIXER: {message}")
        
        # Also print to console for immediate feedback
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        
        # Store in results for tracking
        self.results['steps'].append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")
    
    def _log_error(self, message: str):
        """Log an error to both console and agent_execution.log"""
        import logging
        
        # Get the same logger that writes to agent_execution.log
        agent_logger = logging.getLogger('AgentDashboard')
        
        # Log to the file (this will appear in agent_execution.log)
        agent_logger.error(f"AUTO_FIXER: {message}")
        
        # Also print to console for immediate feedback
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        
        # Store in results for tracking
        self.results['errors'].append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")
    
    def cleanup(self, preserve_files: bool = True):
        """Clean up temporary files
        
        Args:
            preserve_files: If True, keeps the working directory with extracted code and reports
        """
        if preserve_files:
            print(f"Files preserved at: {self.work_dir.absolute()}")
            print("   - extracted_code/: Original agent code")
            print("   - agentcore_fix_report_*.pdf: Detailed fix report")
            return
            
        try:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
                print("🗑️ Temporary files cleaned up")
        except Exception as e:
            print(f"Cleanup warning: {e}")





    def _generate_code_agent_summary_simple(self, agent_response: str, fixed_files: Dict[str, str], ai_analysis: Dict[str, Any]) -> str:
        """Generate a comprehensive summary using Claude directly (simpler than orchestrator)
        
        Args:
            agent_response: Code Agent's response text
            fixed_files: Dictionary of fixed files
            ai_analysis: Original error analysis
            
        Returns:
            Formatted markdown summary
        """
        import boto3
        import json
        import time
        from botocore.exceptions import EventStreamError, ClientError
        
        # Get model configuration with fallback support
        from src.config.config import get_model_id, get_aws_region, get_fallback_models
        primary_model = get_model_id()
        region = get_aws_region()
        fallback_models = get_fallback_models()
        models_to_try = [primary_model] + fallback_models
        
        retry_delay = 2  # seconds
        
        for attempt, model_id in enumerate(models_to_try, 1):
            try:
                if attempt == 1:
                    self._log_step(f"   Summary generation attempt {attempt}/{len(models_to_try)}...")
                else:
                    self._log_step(f"   Fallback model attempt {attempt}/{len(models_to_try)}...")
                    self._log_step(f"   Using model: {model_id}")
                

                
                # Initialize Bedrock client with adaptive retry
                from src.core.retry_config import ADAPTIVE_RETRY
                bedrock = boto3.client('bedrock-runtime', region_name=region, config=ADAPTIVE_RETRY)
                
                # Prepare summary prompt
                summary_prompt = f"""Analyze the Code Agent's execution and create a comprehensive summary in this EXACT format:

## CODE FIXES APPLIED:

### 1. **[Fix Type]** - [filename]
- **Issue**: [Brief description of the problem]
- **Fix**: [What was changed]
- **Tool Used**: [Which tool was used]
- **Status**: Applied and tested

### 2. **[Next Fix Type]** - [filename]
...

## **Summary of Changes:**
- **Lines removed**: [number]
- **Original lines**: [number] → **Fixed lines**: [number]
- **Syntax errors**: Fixed/Not found
- **Runtime errors**: Fixed/Not found
- **File location**: [where files are saved]
- **Backup created**: [backup info]

## **Technical Details:**
[Detailed explanation of the main fix and why it was needed]

---

**ORIGINAL ERROR:**
{ai_analysis.get('error_details', {}).get('message', 'Unknown error')}

**CODE AGENT OUTPUT:**
{agent_response[:3000]}{'...' if len(agent_response) > 3000 else ''}

**FIXED FILES:**
{', '.join(fixed_files.keys())}

**INSTRUCTIONS:**
1. Extract all fixes that were applied from the Code Agent output
2. For each fix, identify: the issue, the solution, the tool used, and the status
3. Count the actual changes (lines added/removed) if mentioned
4. Provide technical details about the most critical fix
5. Use the EXACT format shown above with proper markdown formatting
6. Be specific and technical - this is for developers
7. Include file names, line numbers, and specific error types when available"""

                # Call Claude
                request_body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.1,
                    "messages": [
                        {
                        "role": "user",
                        "content": summary_prompt
                    }
                ]
            }
            
                response = bedrock.invoke_model(
                    modelId=model_id,
                    body=json.dumps(request_body)
                )
                
                response_body = json.loads(response['body'].read())
                summary_text = response_body['content'][0]['text']
                
                if attempt > 1:
                    self._log_step(f"   Summary generated successfully with fallback model #{attempt}")
                else:
                    self._log_step(f"   Summary generated successfully")
                return summary_text
                
            except (EventStreamError, ClientError) as e:
                error_msg = str(e)
                self._log_error(f"   Bedrock error on attempt {attempt}/{len(models_to_try)}: {error_msg}")
                
                # Check if it's a retryable error
                is_retryable = any(keyword in error_msg.lower() for keyword in [
                    'serviceunavailableexception', 'throttlingexception', 'too many connections',
                    'service unavailable', 'throttling', 'rate limit'
                ])
                
                if 'AccessDeniedException' in error_msg:
                    self._log_error(f"   Access denied - check IAM permissions")
                    raise  # Don't retry on permission errors
                
                if is_retryable and attempt < len(models_to_try):
                    self._log_step(f"   Switching to fallback model...")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10)  # Exponential backoff, capped at 10s
                elif attempt >= len(models_to_try):
                    self._log_error(f"   All {len(models_to_try)} models exhausted")
                    raise
                else:
                    raise  # Non-retryable error
                    
            except Exception as e:
                self._log_error(f"   Unexpected error on attempt {attempt}: {e}")
                if attempt < len(models_to_try):
                    self._log_step(f"   Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10)
                else:
                    raise
        
        # If we get here, all retries failed
        self._log_error(f"Failed to generate summary after {max_retries} attempts")
        return f"""## CODE FIXES APPLIED:

**Files Modified:** {', '.join(fixed_files.keys())}

**Status:** Code Agent completed successfully

**Note:** Automatic summary generation failed after {max_retries} retry attempts due to Bedrock service issues.

**Error:** Bedrock service is temporarily unavailable. Please check AWS Service Health Dashboard.

See the detailed Code Agent output below for full information about the fixes applied."""


    
    
    


def execute_auto_fix(agent_runtime_id: str, ai_analysis: Dict[str, Any], 
                    preserve_files: bool = True) -> Dict[str, Any]:
    """Execute the auto-fix workflow - Extract, analyze, and apply fixes"""
    fixer = AgentCoreAutoFixer()
    
    try:
        result = fixer.auto_fix_agent(agent_runtime_id, ai_analysis)
        
        # Add working directory info to result
        if is_success_status(safe_get_case_insensitive(result, 'status')):
            result['working_directory'] = str(fixer.work_dir.absolute())
            result['extracted_code_path'] = str(fixer.work_dir / "extracted_code")
        
        return result
    finally:
        fixer.cleanup(preserve_files=preserve_files)
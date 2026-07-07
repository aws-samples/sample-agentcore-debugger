"""
Service layer for auto-fix operations
Integrates with the existing AgentCoreAutoFixer and multi-agent system
"""
import sys
import os
import json
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

# Load .env file from project root so environment variables are available
from dotenv import load_dotenv
# .env is in project root (parent of backend/)
project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(project_root / '.env')

# Mock streamlit before importing collectors that depend on it
from app.core import streamlit_mock
sys.modules['streamlit'] = streamlit_mock

# Add parent directory to path to import existing modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from src.tools.agentcore_auto_fixer import AgentCoreAutoFixer
from src.analyzers.ai_error_analyzer import AIErrorAnalyzer
from src.collectors.cloudwatch_collector import CloudWatchCollector

from app.models.fix import (
    ErrorCluster, FixRequest, FixResult, FixStatus,
    WorkflowType, UserChoice,
    SuppressionSummary, SuppressedError, ErrorClustersResponse,
    LaunchStatus
)

logger = logging.getLogger(__name__)

# Global storage for async launch jobs (in production, use Redis or similar)
_launch_jobs: Dict[str, Dict[str, Any]] = {}

# File-based cache for Fix All workspace sharing across gunicorn workers
# This file stores the mapping: agent_id -> workspace_path
_FIX_ALL_CACHE_FILE = Path("/tmp/fix_all_workspace_cache.json")
_FIX_ALL_CACHE_LOCK = Path("/tmp/fix_all_workspace_cache.lock")


def _load_fix_all_cache() -> Dict[str, str]:
    """Load the Fix All workspace cache from file (shared across workers)"""
    try:
        if _FIX_ALL_CACHE_FILE.exists():
            with open(_FIX_ALL_CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Fix All Cache] Error loading cache: {e}", flush=True)
    return {}


def _save_fix_all_cache(cache: Dict[str, str]):
    """Save the Fix All workspace cache to file (shared across workers)"""
    try:
        with open(_FIX_ALL_CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"[Fix All Cache] Error saving cache: {e}", flush=True)


def _clear_fix_all_cache(agent_id: str = None):
    """Clear the Fix All workspace cache"""
    try:
        if agent_id:
            cache = _load_fix_all_cache()
            if agent_id in cache:
                del cache[agent_id]
                _save_fix_all_cache(cache)
        else:
            if _FIX_ALL_CACHE_FILE.exists():
                _FIX_ALL_CACHE_FILE.unlink()
    except Exception as e:
        print(f"[Fix All Cache] Error clearing cache: {e}", flush=True)


class FixService:
    """Service for auto-fix operations"""
    
    _ai_analyzer: Optional[AIErrorAnalyzer] = None  # Class-level cache
    
    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.cloudwatch = CloudWatchCollector(region=region)
        self._active_fixers: Dict[str, AgentCoreAutoFixer] = {}
    
    @classmethod
    def _get_ai_analyzer(cls) -> AIErrorAnalyzer:
        """Get cached AIErrorAnalyzer instance"""
        if cls._ai_analyzer is None:
            cls._ai_analyzer = AIErrorAnalyzer()
        return cls._ai_analyzer
    
    def _get_agent_log_groups(self, agent_id: str) -> List[str]:
        """Get log groups for a specific agent"""
        # Strip -DEFAULT suffix if present
        runtime_id = agent_id.replace('-DEFAULT', '') if agent_id.endswith('-DEFAULT') else agent_id
        
        # Build possible log group patterns for this agent
        log_groups = [
            f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT",
            f"/aws/bedrock-agentcore/runtimes/{runtime_id}",
            f"aws/spans/default/{runtime_id}",
            f"aws/spans/default",
        ]
        
        # Also discover any matching log groups
        try:
            discovered = self.cloudwatch.get_agent_related_log_groups()
            for group in discovered:
                if runtime_id.lower() in group.lower() and group not in log_groups:
                    log_groups.append(group)
        except Exception as e:
            logger.warning(f"Could not discover log groups: {e}")
        
        return log_groups
    
    def _get_or_create_fixer(self, agent_id: str, time_range: str = None, force_new: bool = False, is_fix_all: bool = False, fix_all_session_id: str = None) -> AgentCoreAutoFixer:
        """Get or create an auto-fixer instance for an agent
        
        For Fix All operations, we reuse the same fixer instance so that:
        1. Files are pulled from ECR only once
        2. Subsequent fixes build on previous fixes in the same workspace
        
        For individual "Fix This" operations, we always create a new instance
        so each error pattern gets its own workspace.
        
        Uses file-based cache for Fix All to share workspace across gunicorn workers.
        Cache key includes session_id for multi-user isolation.
        
        Args:
            agent_id: The agent ID
            time_range: Optional time range for error analysis
            force_new: If True, always create a new instance (for fresh start)
            is_fix_all: If True, reuse existing fixer for shared workspace (Fix All mode)
            fix_all_session_id: Unique session ID for Fix All workspace isolation
        """
        # Build cache key: agent_id + session_id for multi-user isolation
        cache_key = f"{agent_id}:{fix_all_session_id}" if fix_all_session_id else agent_id
        
        # Use print for guaranteed visibility in docker logs
        print(f"[_get_or_create_fixer] Called with agent_id={agent_id}, is_fix_all={is_fix_all}, session_id={fix_all_session_id}, cache_key={cache_key}", flush=True)
        print(f"[_get_or_create_fixer] Current in-memory cached fixers: {list(self._active_fixers.keys())}", flush=True)
        
        # For Fix All: first check in-memory cache, then file-based cache
        if is_fix_all and not force_new:
            # Check in-memory cache first (same worker)
            if cache_key in self._active_fixers:
                cached_fixer = self._active_fixers[cache_key]
                print(f"[Fix All] REUSING from in-memory cache for key: {cache_key}", flush=True)
                print(f"[Fix All] Shared workspace: {cached_fixer.work_dir}", flush=True)
                return cached_fixer
            
            # Check file-based cache (different worker might have created it)
            file_cache = _load_fix_all_cache()
            print(f"[Fix All] File cache contents: {file_cache}", flush=True)
            
            if cache_key in file_cache:
                cached_workspace = file_cache[cache_key]
                cached_workspace_path = Path(cached_workspace)
                
                # Verify the workspace still exists
                if cached_workspace_path.exists():
                    print(f"[Fix All] REUSING from file cache for key: {cache_key}", flush=True)
                    print(f"[Fix All] Shared workspace from file: {cached_workspace}", flush=True)
                    
                    # Create fixer with the cached workspace
                    fixer = AgentCoreAutoFixer(
                        agent_id=agent_id,
                        time_range=time_range,
                        work_dir=cached_workspace  # Use the cached workspace!
                    )
                    
                    # Also cache in memory for this worker
                    self._active_fixers[cache_key] = fixer
                    return fixer
                else:
                    print(f"[Fix All] Cached workspace no longer exists: {cached_workspace}", flush=True)
                    # Remove stale entry
                    del file_cache[cache_key]
                    _save_fix_all_cache(file_cache)
        
        # Create new fixer instance
        print(f"[Fix] Creating NEW AgentCoreAutoFixer for agent: {agent_id} (is_fix_all={is_fix_all}, session={fix_all_session_id})", flush=True)
        fixer = AgentCoreAutoFixer(
            agent_id=agent_id,
            time_range=time_range
        )
        print(f"[Fix] New workspace created: {fixer.work_dir}", flush=True)
        
        # Cache for Fix All operations
        if is_fix_all:
            # In-memory cache for this worker (keyed by agent_id + session_id)
            self._active_fixers[cache_key] = fixer
            
            # File-based cache for other workers
            file_cache = _load_fix_all_cache()
            file_cache[cache_key] = str(fixer.work_dir)
            _save_fix_all_cache(file_cache)
            print(f"[Fix All] 💾 Cached fixer with key={cache_key} in memory AND file: {fixer.work_dir}", flush=True)
        else:
            print(f"[Fix This] 🆕 Individual workspace (not cached): {fixer.work_dir}", flush=True)
        
        return fixer
    
    async def get_error_clusters(
        self,
        agent_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10
    ) -> List[ErrorCluster]:
        """Get clustered error patterns for an agent using the same logic as Streamlit"""
        
        # Default time range: last 24 hours
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(days=1)
        
        logger.info(f"Fetching error clusters for agent {agent_id} from {start_time} to {end_time}")
        
        # Use AIErrorAnalyzer for proper clustering (same as Streamlit)
        try:
            ai_analyzer = self._get_ai_analyzer()
            
            # Set only the primary agent log group for faster fetching
            agent_id_base = agent_id.replace('-DEFAULT', '')
            primary_log_group = f"/aws/bedrock-agentcore/runtimes/{agent_id}"
            if not agent_id.endswith('-DEFAULT'):
                primary_log_group = f"/aws/bedrock-agentcore/runtimes/{agent_id}-DEFAULT"
            
            self.cloudwatch.log_groups = [primary_log_group]
            logger.info(f"Using log group: {primary_log_group}")
            
            # Get error logs from CloudWatch
            raw_events = self.cloudwatch.fetch_log_events(start_time, end_time)
            logger.info(f"Fetched {len(raw_events)} raw events from CloudWatch")
            
            parsed_events = self.cloudwatch.parse_otel_logs(raw_events)
            logger.info(f"Parsed {len(parsed_events)} events (filtered for errors/warnings)")
            
            # Filter by agent_id if provided - check multiple fields
            if agent_id:
                filtered_events = []
                for e in parsed_events:
                    # Check log_group, agent_id field, and message for agent identifier
                    log_group = e.get('log_group', '')
                    event_agent_id = e.get('agent_id', '')
                    message = e.get('message', '')
                    raw_message = e.get('raw_message', '')
                    
                    # Match if agent_id appears anywhere relevant
                    # Strip -DEFAULT suffix for matching
                    agent_id_base = agent_id.replace('-DEFAULT', '')
                    
                    if (agent_id in log_group or 
                        agent_id_base in log_group or
                        agent_id == event_agent_id or
                        agent_id_base == event_agent_id or
                        agent_id in message or
                        agent_id_base in message or
                        agent_id in raw_message or
                        agent_id_base in raw_message):
                        filtered_events.append(e)
                
                # If no events match the agent_id filter, use all events
                # (the agent might not have its ID in logs)
                if not filtered_events:
                    logger.warning(f"No events matched agent_id {agent_id}, using all {len(parsed_events)} events")
                    filtered_events = parsed_events
                else:
                    logger.info(f"Filtered to {len(filtered_events)} events for agent {agent_id}")
                
                parsed_events = filtered_events
            
            if not parsed_events:
                logger.info("No error events found")
                # Clear suppression summary when no events found
                self._last_suppression_summary = {
                    'total_original_errors': 0,
                    'total_unique_patterns': 0,
                    'total_suppressed': 0,
                    'suppression_rate': 0.0,
                    'top_suppressed_errors': []
                }
                return []
            
            # Use AIErrorAnalyzer's deduplicate_errors for proper clustering
            error_clusters, suppression_summary = ai_analyzer.deduplicate_errors(parsed_events)
            
            logger.info(f"Created {len(error_clusters)} error clusters from {suppression_summary.get('total_original_errors', 0)} errors")
            
            # Convert to ErrorCluster models
            result = []
            for i, cluster in enumerate(error_clusters[:limit]):
                sample = cluster.sample_error
                
                # Get error message - prefer errorMessage, then message, then body
                error_msg = (sample.get('error_message') or 
                            sample.get('message') or 
                            sample.get('body') or 
                            'Unknown error')
                
                # Get stack trace from multiple possible locations
                stack_trace = sample.get('stack_trace') or sample.get('traceback')
                
                # Convert list to string if needed
                if isinstance(stack_trace, list):
                    stack_trace = ''.join(str(s) for s in stack_trace)
                
                if not stack_trace and sample.get('structured_data'):
                    structured = sample['structured_data']
                    # Try stackTrace array (CloudWatch format)
                    stack_array = structured.get('stackTrace', [])
                    if isinstance(stack_array, list):
                        stack_trace = ''.join(str(s) for s in stack_array)
                    # Try attributes
                    if not stack_trace:
                        attrs = structured.get('attributes', {})
                        stack_trace = attrs.get('exception.stacktrace', '')
                
                # Ensure stack_trace is a string
                if stack_trace and not isinstance(stack_trace, str):
                    stack_trace = str(stack_trace)
                
                # Extract affected files from stack trace
                affected_files = []
                if stack_trace:
                    import re
                    files = re.findall(r'File "([^"]+\.py)"', str(stack_trace))
                    affected_files = list(set(files))
                
                # Build sample events
                sample_events = []
                for err in cluster.all_errors[:3]:
                    sample_events.append({
                        'timestamp': str(err.get('timestamp', '')),
                        'message': (err.get('error_message') or err.get('message', ''))[:500],
                        'trace_id': err.get('trace_id')
                    })
                
                # Generate stable pattern_id based on error content (not index)
                # This ensures the same error always gets the same pattern_id
                import hashlib
                error_hash = hashlib.sha256(f"{sample.get('error_type', '')}:{error_msg[:200]}".encode()).hexdigest()[:8]
                stable_pattern_id = f"pattern_{error_hash}"
                
                result.append(ErrorCluster(
                    pattern_id=stable_pattern_id,
                    error_type=sample.get('error_type') or 'unknown',
                    error_message=error_msg[:500],
                    count=cluster.count,
                    first_seen=str(cluster.first_seen) if cluster.first_seen else None,
                    last_seen=str(cluster.last_seen) if cluster.last_seen else None,
                    sample_events=sample_events,
                    stack_trace=stack_trace,
                    affected_files=affected_files,
                    status=FixStatus.PENDING
                ))
            
            # Store suppression summary for get_error_clusters_with_summary
            self._last_suppression_summary = suppression_summary
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting error clusters: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def get_error_clusters_with_summary(
        self,
        agent_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10
    ) -> ErrorClustersResponse:
        """Get clustered error patterns with suppression summary"""
        
        clusters = await self.get_error_clusters(agent_id, start_time, end_time, limit)
        
        # Get suppression summary from last call
        suppression_data = getattr(self, '_last_suppression_summary', {})
        
        # Convert top_suppressed_errors to SuppressedError models
        top_suppressed = []
        for err in suppression_data.get('top_suppressed_errors', []):
            top_suppressed.append(SuppressedError(
                message=err.get('message', '')[:200],
                original_count=err.get('original_count', 0),
                suppressed_count=err.get('suppressed_count', 0),
                error_type=err.get('error_type', 'unknown'),
                severity=err.get('severity', 'unknown')
            ))
        
        summary = SuppressionSummary(
            total_original_errors=suppression_data.get('total_original_errors', 0),
            total_unique_patterns=suppression_data.get('total_unique_patterns', 0),
            total_suppressed=suppression_data.get('total_suppressed', 0),
            suppression_rate=suppression_data.get('suppression_rate', 0.0),
            top_suppressed_errors=top_suppressed
        )
        
        return ErrorClustersResponse(clusters=clusters, suppression_summary=summary)
    
    async def analyze_error(
        self,
        agent_id: str,
        error_cluster: ErrorCluster
    ) -> Dict[str, Any]:
        """Analyze an error cluster using AI classification (same as Streamlit)
        
        OPTIMIZATION: This is the ONLY place where classification happens.
        The result is cached in ai_analysis['cached_classification'] and passed
        to start_fix_workflow, which passes it to AgentCoreAutoFixer.
        This eliminates redundant AI calls (was 3x, now 1x).
        """
        
        try:
            # Use AgentCoreAutoFixer for classification (same as Streamlit dashboard)
            auto_fixer = AgentCoreAutoFixer()
            
            # Prepare error data for classification
            traceback = error_cluster.stack_trace or ''
            
            # Log what we're classifying for debugging
            logger.info(f"[CLASSIFY] Pattern ID: {error_cluster.pattern_id}")
            logger.info(f"[CLASSIFY] Error Type: {error_cluster.error_type}")
            logger.info(f"[CLASSIFY] Error Message: {error_cluster.error_message[:100]}...")
            
            ai_analysis = {
                'summary': f"Error Pattern: {error_cluster.error_message}",
                'recommendations': [],
                'error_details': {
                    'message': error_cluster.error_message,
                    'traceback': traceback,
                    'level': 'ERROR',
                    'count': error_cluster.count,
                    'error_type': error_cluster.error_type
                }
            }
            
            # Run AI classification using the same method as Streamlit
            try:
                classification_result = auto_fixer._classify_error_type(ai_analysis)
                logger.info(f"[CLASSIFY] Result for '{error_cluster.error_message[:50]}...': {classification_result.get('type')} - {classification_result.get('reasoning', '')[:100]}")
            except Exception as e:
                logger.warning(f"AI classification failed, using fallback: {e}")
                # Fallback classification based on error type
                error_type = error_cluster.error_type
                if error_type in ['ImportError', 'ModuleNotFoundError']:
                    classification_result = {'type': 'package_only', 'reasoning': 'Import/module error detected', 'confidence': 0.8}
                elif 'site-packages' in traceback:
                    classification_result = {'type': 'mixed', 'reasoning': 'Library code in traceback', 'confidence': 0.7}
                else:
                    classification_result = {'type': 'code_fix_required', 'reasoning': 'Code error detected', 'confidence': 0.8}
            
            # OPTIMIZATION: Cache classification in ai_analysis to avoid re-classification
            # in start_fix_workflow and AgentCoreAutoFixer.run()
            ai_analysis['cached_classification'] = classification_result
            
            return {
                'status': 'success',
                'analysis': ai_analysis,
                'classification': classification_result,
                'recommendations': [],
                'suggested_fix': None,
                'confidence': classification_result.get('confidence', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing error cluster: {e}")
            import traceback as tb
            logger.error(tb.format_exc())
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def start_fix_workflow(
        self,
        agent_id: str,
        pattern_id: str,
        ai_analysis: Dict[str, Any],
        user_choice: Optional[UserChoice] = None,
        is_fix_all: bool = False,
        fix_all_session_id: Optional[str] = None
    ) -> FixResult:
        """Start the auto-fix workflow for an error pattern
        
        Args:
            agent_id: The agent ID
            pattern_id: The error pattern ID
            ai_analysis: AI analysis results
            user_choice: Optional user choice for mixed workflows
            is_fix_all: If True, use shared workspace (Fix All mode)
            fix_all_session_id: Unique session ID for Fix All workspace isolation
        """
        
        try:
            logger.info(f"[start_fix_workflow] pattern_id={pattern_id}, is_fix_all={is_fix_all}, session_id={fix_all_session_id}")
            
            # Get or create fixer instance
            # For Fix All: reuse fixer for shared workspace (keyed by agent_id + session_id)
            # For Fix This: create new fixer for separate workspace
            fixer = self._get_or_create_fixer(agent_id, is_fix_all=is_fix_all, fix_all_session_id=fix_all_session_id)
            
            logger.info(f"[start_fix_workflow] Using workspace: {fixer.work_dir}")
            logger.info(f"[start_fix_workflow] Fixer _extracted_code_path: {getattr(fixer, '_extracted_code_path', 'NOT SET')}")
            logger.info(f"[start_fix_workflow] Fixer _code_analysis: {'SET' if getattr(fixer, '_code_analysis', None) else 'NOT SET'}")
            
            # Run the auto-fix workflow
            # user_choice is already a string due to use_enum_values=True in Pydantic config
            choice_value = user_choice if isinstance(user_choice, str) else (user_choice.value if user_choice else None)
            result = fixer.auto_fix_agent(
                agent_runtime_id=agent_id,
                ai_analysis=ai_analysis,
                initial_choice=choice_value
            )
            
            logger.info(f"[start_fix_workflow] Result working_directory: {result.get('working_directory', 'NOT SET')}")
            logger.info(f"[start_fix_workflow] Result fixed_files: {list(result.get('fixed_files', {}).keys())}")
            logger.info(f"[start_fix_workflow] Fixer _extracted_code_path AFTER: {getattr(fixer, '_extracted_code_path', 'NOT SET')}")
            
            # Determine workflow type from result
            workflow_type = WorkflowType.CODE_FIX
            if result.get('workflow_type') == 'mixed':
                workflow_type = WorkflowType.MIXED
            elif result.get('workflow_type') == 'package_only':
                workflow_type = WorkflowType.PACKAGE_ONLY
            
            # Determine status
            status = FixStatus.PENDING
            if result.get('status') == 'success':
                status = FixStatus.FIXED
            elif result.get('status') == 'failed':
                status = FixStatus.FAILED
            elif result.get('status') == 'awaiting_user_choice':
                # If user_choice was provided, automatically continue the workflow
                # This handles the case where the auto_fixer returns analysis first
                if choice_value and choice_value != 'skip':
                    logger.info(f"Auto-continuing workflow with choice: {choice_value}")
                    try:
                        # Ensure ai_analysis is in the result (may be missing from cached results)
                        if not result.get('ai_analysis') and ai_analysis:
                            result['ai_analysis'] = ai_analysis
                            logger.info("[start_fix_workflow] Injected ai_analysis into result for continue_mixed_workflow")
                        
                        continue_result = fixer.continue_mixed_workflow(result, choice_value)
                        logger.info(f"Continue result status: {continue_result.get('status')}")
                        logger.info(f"Continue result keys: {list(continue_result.keys())}")
                        
                        # Update result with continue_result
                        if continue_result.get('status') == 'success':
                            status = FixStatus.FIXED
                            result = continue_result
                        elif continue_result.get('status') == 'failed':
                            status = FixStatus.FAILED
                            result = continue_result
                        else:
                            # Keep the continue_result but mark as awaiting choice
                            status = FixStatus.AWAITING_CHOICE
                            result = continue_result
                    except Exception as continue_error:
                        logger.error(f"Error in continue_mixed_workflow: {continue_error}")
                        import traceback
                        logger.error(traceback.format_exc())
                        status = FixStatus.FAILED
                        result['message'] = f"Continue workflow failed: {str(continue_error)}"
                else:
                    status = FixStatus.AWAITING_CHOICE
            
            # Handle user_options - convert dict to list if needed
            user_options = result.get('user_options', [])
            if isinstance(user_options, dict):
                user_options = list(user_options.values())
            elif not isinstance(user_options, list):
                user_options = []
            
            # Log the final status being returned
            logger.info(f"=== FIX RESULT BEING RETURNED ===")
            logger.info(f"  status: {status} (value: {status.value})")
            logger.info(f"  workflow_type: {workflow_type}")
            logger.info(f"  fixed_files count: {len(result.get('fixed_files', {}))}")
            logger.info(f"  original_files count: {len(result.get('original_files', {}))}")
            logger.info(f"  has code_agent_summary: {bool(result.get('code_agent_summary'))}")
            logger.info(f"  working_directory: {result.get('working_directory', '')[:50]}...")
            logger.info(f"================================")
            
            return FixResult(
                pattern_id=pattern_id,
                status=status,
                workflow_type=workflow_type,
                fixed_files=result.get('fixed_files', {}),
                original_files=result.get('original_files', {}),
                code_agent_summary=result.get('code_agent_summary', ''),
                package_recommendations=result.get('package_recommendations', []),
                library_agent_output=result.get('library_agent_output', ''),
                git_info=result.get('git_info'),
                working_directory=result.get('working_directory', ''),
                error_classification=result.get('error_classification', {}),
                user_options=user_options,
                message=result.get('message', '')
            )
            
        except Exception as e:
            logger.error(f"Error in fix workflow: {e}")
            return FixResult(
                pattern_id=pattern_id,
                status=FixStatus.FAILED,
                workflow_type=WorkflowType.CODE_FIX,
                fixed_files={},
                message=f"Fix workflow failed: {str(e)}"
            )
    
    async def continue_fix_workflow(
        self,
        agent_id: str,
        pattern_id: str,
        user_choice: UserChoice,
        previous_result: Dict[str, Any]
    ) -> FixResult:
        """Continue a fix workflow after user makes a choice"""
        
        # Re-run with user choice
        return await self.start_fix_workflow(
            agent_id=agent_id,
            pattern_id=pattern_id,
            ai_analysis=previous_result.get('ai_analysis', {}),
            user_choice=user_choice
        )
    
    def cleanup(self, agent_id: str = None):
        """Cleanup fixer instances (both in-memory and file-based cache)"""
        if agent_id:
            keys_to_remove = [k for k in self._active_fixers if k.startswith(agent_id)]
            for key in keys_to_remove:
                del self._active_fixers[key]
            # Also clear file-based cache
            _clear_fix_all_cache(agent_id)
        else:
            self._active_fixers.clear()
            # Also clear all file-based cache
            _clear_fix_all_cache()
    

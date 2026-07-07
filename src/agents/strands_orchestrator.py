"""
Strands Orchestrator Agent - Multi-Agent System for AgentCore Auto-Fixing

This orchestrator uses the Strands SDK to manage two specialized agents:
- Library Agent: Handles package/dependency issues → UI recommendations
- Code Agent: Handles code file issues → Automated fixes with tools
"""

import os
import json
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel
from .package_agent import package_agent_tool
from .code_agent import code_agent_tool
from src.config.config import get_model_id, get_aws_region, check_model_health, get_fallback_models

# Setup orchestrator logging with queue handler for real-time display
logger = logging.getLogger('strands.orchestrator')
logger.setLevel(logging.INFO)

# Add queue handler if available (for dashboard integration)
try:
    from dashboard.enhanced_multi_agent_dashboard import StreamlitQueueHandler, log_queue
    if not any(isinstance(h, StreamlitQueueHandler) for h in logger.handlers):
        queue_handler = StreamlitQueueHandler()
        formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        queue_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)
except ImportError:
    pass  # Dashboard not available, continue with normal logging


class StrandsOrchestrator:
    """Orchestrator agent that manages package and code fixing agents"""
    
    def __init__(self, work_dir: str = None):
        """Initialize the Strands orchestrator with specialized agent tools"""
        if work_dir:
            self.work_dir = Path(work_dir)
        else:
            # Ensure agentcore_fixes is under the AGENTCORE-DEBUGGER root folder
            project_root = Path(__file__).parent.parent.parent  # This is the AGENTCORE-DEBUGGER root
            self.work_dir = project_root / "agentcore_fixes" / f"fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize the Strands orchestrator agent with Claude Sonnet 4.5
        # Check model health before initialization (uses cache to avoid too many requests)
        logger.info("Checking model health...")
        health_status = check_model_health()  # Will use cache if available
        
        # Determine which model to use based on health check
        model_id = get_model_id()
        region = get_aws_region()
        fallback_models = get_fallback_models()
        
        if health_status['status'] != 'healthy':
            logger.warning(f"Primary model health check failed: {health_status['message']}")
            if 'suggestion' in health_status:
                logger.warning(f"Suggestion: {health_status['suggestion']}")
            
            # Start with first fallback model instead of primary
            if len(fallback_models) > 1:
                model_id = fallback_models[1]  # Skip primary (index 0), use first fallback
                logger.warning(f"Starting with fallback model instead: {model_id}")
            else:
                logger.warning("No fallback models available, will try primary anyway")
        else:
            cache_info = f" (cached: {health_status.get('cache_age', 0)}s ago)" if health_status.get('cached') else ""
            logger.info(f"Model health check passed{cache_info}")
        
        # Create model with selected model_id
        claude_45_model = BedrockModel(
            model_id=model_id,
            region_name=region
        )
        logger.info(f"Model configured: {model_id}")
        logger.info(f"Region: {region}")
        
        self.orchestrator_agent = Agent(
            model=claude_45_model,
            system_prompt=self._get_orchestrator_system_prompt(),
            tools=[package_agent_tool, code_agent_tool],
            callback_handler=None  # Suppress intermediate output like in the multi-agent example
        )
        
        # Results tracking
        self.results = {
            'start_time': datetime.now(),
            'working_directory': str(self.work_dir.absolute()),
            'agent_logs': []
        }
        
        logger.info("="*60)
        logger.info("STRANDS ORCHESTRATOR INITIALIZATION")
        logger.info(f"Working Directory: {self.work_dir.absolute()}")
        logger.info("Available Agent Tools:")
        logger.info("   Library Agent: Package/dependency analysis → UI recommendations")
        logger.info("   Code Agent: Code fixes → Automated modifications with dev tools")
        logger.info("Claude Sonnet 4.5 model configured successfully")
        logger.info("Strands Orchestrator ready for multi-agent coordination")
        logger.info("="*60)
    
    def orchestrate_fixes(self, ai_analysis: Dict[str, Any], extracted_files: Dict[str, str]) -> Dict[str, Any]:
        """Main orchestration method using Strands Agent with specialized agent tools
        
        Args:
            ai_analysis: AI error analysis (text or dict)
            extracted_files: Dictionary of extracted agent files {path: content}
            
        Returns:
            Dictionary with results from both agents
        """
        try:
            logger.info("="*80)
            logger.info("STRANDS MULTI-AGENT ORCHESTRATION STARTED")
            logger.info("="*80)
            
            # Log analysis details
            if isinstance(ai_analysis, dict):
                error_summary = ai_analysis.get('summary', 'No summary available')
                classification = ai_analysis.get('classification', {})
                processing_mode = ai_analysis.get('processing_mode', 'auto')
                
                logger.info("ERROR ANALYSIS DETAILS:")
                logger.info(f"   Summary: {error_summary[:100]}{'...' if len(error_summary) > 100 else ''}")
                logger.info(f"   Classification: {classification}")
                logger.info(f"   Processing Mode: {processing_mode}")
            else:
                logger.info(f"ERROR ANALYSIS: {str(ai_analysis)[:100]}{'...' if len(str(ai_analysis)) > 100 else ''}")
            
            logger.info(f"EXTRACTED FILES: {len(extracted_files)} files")
            for file_path in list(extracted_files.keys())[:5]:  # Log first 5 files
                logger.info(f"   {file_path}")
            if len(extracted_files) > 5:
                logger.info(f"   ... and {len(extracted_files) - 5} more files")
            
            # Prepare the orchestration query for the Strands agent
            logger.info("PREPARING ORCHESTRATION QUERY...")
            orchestration_query = self._prepare_orchestration_query(ai_analysis, extracted_files)
            logger.info(f"Orchestration query prepared ({len(orchestration_query)} characters)")
            
            # Use the Strands orchestrator agent to coordinate the specialized agents with retry logic
            logger.info("INVOKING STRANDS ORCHESTRATOR AGENT...")
            logger.info("   Available tools: Library Agent, Code Agent")
            logger.info("   Orchestrator will route to appropriate agent(s)")
            
            response = self._invoke_orchestrator_with_retry(orchestration_query)
            
            logger.info("ORCHESTRATOR RESPONSE RECEIVED:")
            logger.info(f"   Response type: {type(response)}")
            logger.info(f"   Response length: {len(str(response)) if response else 0} characters")
            
            # Parse the orchestrator response
            logger.info("PARSING ORCHESTRATOR RESPONSE...")
            orchestration_result = self._parse_orchestrator_response(response)
            
            # Filter out Code Agent sections if in package_only mode
            if isinstance(ai_analysis, dict):
                processing_mode = ai_analysis.get('processing_mode', '')
                classification_type = ai_analysis.get('classification', {}).get('type', '')
                
                if processing_mode == 'package_only' or classification_type == 'package_only':
                    logger.info("PACKAGE_ONLY MODE: Filtering Code Agent content...")
                    
                    # Clean library_agent_output to remove Code Agent sections
                    library_output = orchestration_result.get('library_agent_output', '')
                    if library_output and isinstance(library_output, str):
                        import re
                        # Remove Code Agent sections
                        patterns = [
                            r'FULL CODE AGENT ANALYSIS:.*',
                            r'CODE FIXES APPLIED:.*',
                            r'Code Agent.*?(?=##|$)'
                        ]
                        
                        cleaned = library_output
                        for pattern in patterns:
                            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE)
                        
                        orchestration_result['library_agent_output'] = cleaned.strip()
                        orchestration_result['package_recommendations'] = cleaned.strip()
                        logger.info(f"   Cleaned: {len(library_output)} → {len(cleaned)} chars")
                    
                    # Force code_fixes to empty
                    orchestration_result['code_fixes'] = []
                    orchestration_result['fixed_files'] = {}
            
            # Log what agents were used
            package_recs = orchestration_result.get('package_recommendations', [])
            code_fixes = orchestration_result.get('code_fixes', [])
            
            logger.info("AGENT USAGE SUMMARY:")
            if package_recs:
                logger.info("   Library Agent: ACTIVATED - Generated package recommendations")
            else:
                logger.info("   Library Agent: NOT USED")
            
            if code_fixes:
                logger.info("   Code Agent: ACTIVATED - Applied code fixes")
            else:
                logger.info("   Code Agent: NOT USED")
            
            # Generate comprehensive summary for Code Agent results
            code_agent_summary = None
            logger.info(f"DEBUG: code_fixes exists: {bool(code_fixes)}")
            logger.info(f"DEBUG: fixed_files exists: {bool(orchestration_result.get('fixed_files'))}")
            logger.info(f"DEBUG: fixed_files count: {len(orchestration_result.get('fixed_files', {}))}")
            
            if code_fixes and orchestration_result.get('fixed_files'):
                logger.info("GENERATING CODE AGENT COMPREHENSIVE SUMMARY...")
                try:
                    code_agent_summary = self._generate_code_agent_summary(
                        code_fixes, 
                        orchestration_result.get('fixed_files', {}),
                        ai_analysis
                    )
                    logger.info(f"Code Agent summary generated: {len(code_agent_summary) if code_agent_summary else 0} characters")
                except Exception as e:
                    logger.error(f"Failed to generate summary: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            else:
                logger.warning("Skipping summary generation - missing code_fixes or fixed_files")
            
            # Compile final results
            final_result = {
                'status': 'success',
                'orchestrator_response': response,
                'package_recommendations': package_recs,
                'code_fixes': code_fixes,
                'code_agent_summary': code_agent_summary,  # Add comprehensive summary
                'fixed_files': orchestration_result.get('fixed_files', {}),
                'working_directory': str(self.work_dir.absolute()),
                'orchestrator_results': self.results,
                'ai_analysis': ai_analysis  # Include AI analysis with summary and classification
            }
            
            logger.info("="*80)
            logger.info("STRANDS MULTI-AGENT ORCHESTRATION COMPLETED SUCCESSFULLY")
            logger.info(f"Final Status: {final_result['status']}")
            logger.info(f"Working Directory: {final_result['working_directory']}")
            logger.info("="*80)
            
            return final_result
            
        except Exception as e:
            logger.error("="*80)
            logger.error("STRANDS ORCHESTRATION FAILED!")
            logger.error(f"Exception Type: {type(e).__name__}")
            logger.error(f"Exception Message: {str(e)}")
            logger.exception("Full Exception Traceback:")
            logger.error("="*80)
            
            return {
                'status': 'failed',
                'error': str(e),
                'partial_results': self.results
            }
    
    def _invoke_orchestrator_with_retry(self, orchestration_query: str, max_retries: int = 3):
        """Invoke orchestrator with retry logic and model fallback for Bedrock service issues"""
        
        import time
        from botocore.exceptions import EventStreamError
        
        # Get fallback models
        fallback_models = get_fallback_models()
        
        for attempt in range(max_retries):
            try:
                logger.info(f"ORCHESTRATOR INVOCATION ATTEMPT {attempt + 1}/{max_retries}")
                
                # Switch to fallback model if not first attempt
                if attempt > 0 and attempt < len(fallback_models):
                    fallback_model_id = fallback_models[attempt]
                    logger.info(f"   Switching to fallback model: {fallback_model_id}")
                    self.orchestrator_agent.model = BedrockModel(model_id=fallback_model_id, region_name=region)
                    time.sleep(2)  # Brief pause before retry
                
                # Log the orchestration prompt being sent (only on first attempt)
                if attempt == 0:
                    logger.info("ORCHESTRATOR PROMPT:")
                    logger.info("-" * 60)
                    logger.info(orchestration_query)
                    logger.info("-" * 60)
                
                response = self.orchestrator_agent(orchestration_query)
                
                if attempt > 0:
                    logger.info(f"ORCHESTRATOR INVOCATION SUCCESSFUL WITH FALLBACK MODEL")
                else:
                    logger.info("ORCHESTRATOR INVOCATION SUCCESSFUL")
                return response
                
            except EventStreamError as e:
                error_msg = str(e)
                logger.warning(f"BEDROCK SERVICE ERROR (Attempt {attempt + 1}/{max_retries}):")
                logger.warning(f"   Error: {error_msg}")
                logger.warning(f"   Error Type: {type(e).__name__}")
                
                # Check for specific error types
                if "serviceUnavailableException" in error_msg:
                    logger.warning("   Diagnosis: Bedrock service temporarily unavailable")
                    logger.warning("   This could be: AWS outage, maintenance, or regional issues")
                elif "throttlingException" in error_msg:
                    logger.warning("   Diagnosis: Bedrock service throttling - too many requests")
                    logger.warning("   This could be: Rate limits, quota exceeded, or concurrent requests")
                elif "validationException" in error_msg:
                    logger.warning("   Diagnosis: Invalid request format or parameters")
                    logger.warning("   This could be: Model ID format, request structure, or permissions")
                else:
                    logger.warning("   Diagnosis: Unknown Bedrock service error")
                    logger.warning("   Check AWS status page and account permissions")
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # Exponential backoff: 2, 5, 9 seconds
                    logger.info(f"   Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    logger.error("ALL RETRY ATTEMPTS FAILED - Bedrock service unavailable")
                    raise
                    
            except Exception as e:
                logger.error(f"NON-RETRYABLE ERROR: {type(e).__name__}: {str(e)}")
                raise
    
    def _get_orchestrator_system_prompt(self) -> str:
        """Get the system prompt for the Strands orchestrator agent"""
        return """You are the AgentCore Auto-Fix Orchestrator, coordinating two specialized agents to fix errors in agent code.

Your role is to analyze error reports and route them to the appropriate specialized agents:

**Library Agent (Package & Library Agent)**: Use for package/dependency/library issues like:
- Missing modules or import errors
- Package version conflicts and compatibility
- Requirements.txt issues
- Dependency problems
- Installation and upgrade issues
- Python library warnings and deprecations
- Security vulnerabilities in packages
- Version compatibility across Python versions
- Library migration recommendations
(Generates structured output that will be sent to UI for user review)

**Code Agent**: Use for ANY code-related issues including:
- Syntax errors and logic problems
- Runtime errors and exceptions
- Performance and optimization issues
- Security vulnerabilities in code
- API integration and networking problems
- Database connectivity and query issues
- File I/O and data processing errors
- Concurrency and threading problems
- Memory and resource management
- Code architecture and design issues
- Testing and validation problems
- Configuration and environment setup
- And any other code problems that can be automatically fixed

**CRITICAL: When calling code_agent_tool, you MUST provide:**
```python
code_agent_tool(
    error_analysis="<error details>",
    extracted_files_json=json.dumps(extracted_files_dict),  # REQUIRED!
    work_dir="<working directory path>"
)
```
The extracted_files_json parameter is REQUIRED and must contain the file contents as JSON.

**Instructions:**
1. Analyze the provided error analysis and extracted files
2. Determine which errors need package/library analysis vs automated code fixes
3. Call the appropriate agent tool (Library Agent OR Code Agent) with the relevant error information
4. Extract key highlights from the agent's response
5. Return both the highlights AND the full agent output

**Response Format:**
For Library Agent (Package Agent), provide:
```
## KEY HIGHLIGHTS:
- Critical package updates: [list any urgent updates]
- Security issues: [list any security vulnerabilities]
- Important actions: [list immediate actions needed]
- Configuration changes: [list any config changes needed]

## FULL LIBRARY AGENT ANALYSIS:
[Complete Library Agent output exactly as returned]
```

For Code Agent, provide:
```
## KEY HIGHLIGHTS:
- Files modified: [list of files changed]
- Critical fixes: [list of important fixes applied]
- Actions required: [any manual steps needed]

## FULL CODE AGENT ANALYSIS:
[Complete Code Agent output exactly as returned]
```

Always include both the highlights section AND the complete agent output."""
    
    def _extract_imports_from_file(self, file_path: str, content: str) -> List[str]:
        """Extract local imports from a Python file
        
        Args:
            file_path: Path to the file
            content: File content
            
        Returns:
            List of imported local files
        """
        import re
        import_files = set()
        
        # Common standard library and third-party modules to skip
        skip_modules = {
            # Standard library
            'os', 'sys', 'json', 'time', 'datetime', 'logging', 're', 'typing', 
            'pathlib', 'collections', 'functools', 'itertools', 'copy', 'math',
            'random', 'string', 'io', 'tempfile', 'shutil', 'subprocess', 'threading',
            'multiprocessing', 'asyncio', 'concurrent', 'contextlib', 'dataclasses',
            'enum', 'abc', 'warnings', 'traceback', 'inspect', 'importlib',
            # Third-party common packages
            'boto3', 'botocore', 'pandas', 'numpy', 'requests', 'flask', 'fastapi',
            'django', 'sqlalchemy', 'pydantic', 'pytest', 'unittest', 'mock',
            'click', 'argparse', 'yaml', 'toml', 'dotenv', 'redis', 'celery',
            'opentelemetry', 'strands', 'langchain', 'anthropic', 'openai',
            'bedrock_agentcore', 'aws_lambda_powertools'
        }
        
        # Patterns for different import styles
        patterns = [
            r'from\s+(\w+)\s+import',           # from module import x
            r'import\s+(\w+)(?:\s+as\s+\w+)?',  # import module [as alias]
            r'from\s+\.(\w+)\s+import',         # from .module import x (relative)
            r'from\s+\.\.(\w+)\s+import',       # from ..module import x (parent relative)
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # Skip if it's a known standard/third-party module
                if match.lower() not in skip_modules:
                    # Add .py extension if not present
                    import_file = f"{match}.py" if not match.endswith('.py') else match
                    import_files.add(import_file)
        
        # Also look for explicit file imports like: from agent import CustomerAgent
        # This helps catch cases where the module name matches a file
        file_import_pattern = r'from\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+import\s+[A-Z]'
        file_matches = re.findall(file_import_pattern, content)
        for match in file_matches:
            if match.lower() not in skip_modules:
                import_file = f"{match}.py"
                import_files.add(import_file)
        
        return list(import_files)
    
    def _build_dependency_graph(self, target_files: List[str], extracted_files: Dict[str, str]) -> List[str]:
        """Build dependency graph to include all related files
        
        Args:
            target_files: Initial list of files with errors
            extracted_files: All available extracted files
            
        Returns:
            Expanded list including dependencies
        """
        all_files = set(target_files)
        files_to_process = list(target_files)
        processed = set()
        dependency_map = {}  # Track which file imports what
        
        logger.info("="*60)
        logger.info("BUILDING DEPENDENCY GRAPH")
        logger.info("="*60)
        logger.info(f"Starting files (with errors): {target_files}")
        logger.info(f"Available files: {list(extracted_files.keys())}")
        
        while files_to_process:
            current_file = files_to_process.pop(0)
            
            if current_file in processed:
                continue
            
            processed.add(current_file)
            logger.info(f"\nAnalyzing: {current_file}")
            
            # Get content of current file
            file_content = extracted_files.get(current_file, '')
            if not file_content:
                # Try without directory prefix or with different paths
                for key, content in extracted_files.items():
                    if key.endswith(current_file) or key.endswith('/' + current_file):
                        file_content = content
                        logger.info(f"   - Found as: {key}")
                        break
            
            if file_content:
                # Extract imports from this file
                imports = self._extract_imports_from_file(current_file, file_content)
                
                if imports:
                    dependency_map[current_file] = imports
                    logger.info(f"   Imports found: {imports}")
                    
                    for imported_file in imports:
                        # Check if this imported file exists in extracted files
                        exists = False
                        matched_key = None
                        
                        if imported_file in extracted_files:
                            exists = True
                            matched_key = imported_file
                        else:
                            # Try to find with different path variations
                            for key in extracted_files.keys():
                                if key.endswith(imported_file) or key.endswith('/' + imported_file):
                                    exists = True
                                    matched_key = key
                                    break
                        
                        if exists:
                            if imported_file not in all_files and matched_key not in all_files:
                                all_files.add(imported_file)
                                files_to_process.append(imported_file)
                                logger.info(f"   Added dependency: {imported_file}")
                        else:
                            logger.info(f"    Import not found in extracted files: {imported_file}")
                else:
                    logger.info(f"    No local imports found")
            else:
                logger.info(f"   File content not found")
        
        result = list(all_files)
        
        logger.info("\n" + "="*60)
        logger.info("DEPENDENCY GRAPH COMPLETE")
        logger.info("="*60)
        logger.info(f"Total files to analyze: {len(result)}")
        logger.info(f"Primary files: {target_files}")
        logger.info(f"Dependencies: {[f for f in result if f not in target_files]}")
        
        if dependency_map:
            logger.info("\nDEPENDENCY MAP:")
            for file, deps in dependency_map.items():
                logger.info(f"   {file} → {deps}")
        
        logger.info("="*60)
        
        return result
    
    def _extract_target_files_from_errors(self, ai_analysis: Dict[str, Any], extracted_files: Dict[str, str]) -> List[str]:
        """Extract specific file paths from error analysis and build dependency graph
        
        Args:
            ai_analysis: AI error analysis with structured error details
            extracted_files: All available extracted files
            
        Returns:
            List of target file paths including dependencies
        """
        target_files = set()
        
        if not isinstance(ai_analysis, dict):
            return list(target_files)
        
        # Check if we have error details with file paths
        error_details = ai_analysis.get('error_details', {})
        
        # Look for code location in error attributes
        if isinstance(error_details, dict):
            # Check for structured error data
            if 'code_location' in error_details:
                code_loc = error_details['code_location']
                if isinstance(code_loc, dict):
                    file_path = code_loc.get('file', '')
                    if file_path and '/app/' in file_path:
                        # Extract just the filename from /app/filename.py
                        filename = file_path.split('/app/')[-1]
                        target_files.add(filename)
            
            # Check for exception stacktrace
            stacktrace = error_details.get('exception_stacktrace', '') or error_details.get('traceback', '')
            if stacktrace:
                # Extract file paths from stacktrace
                import re
                # Look for patterns like: File "/app/agent.py", line 94
                file_matches = re.findall(r'File "(/app/[^"]+)"', stacktrace)
                for match in file_matches:
                    filename = match.split('/app/')[-1]
                    target_files.add(filename)
        
        initial_targets = list(target_files)
        logger.info(f"Initial target files from errors: {initial_targets}")
        
        # Build dependency graph if we have target files
        if target_files:
            expanded_targets = self._build_dependency_graph(initial_targets, extracted_files)
            logger.info(f"Expanded to {len(expanded_targets)} files (including dependencies)")
            return expanded_targets
        
        return initial_targets
    
    def _prepare_orchestration_query(self, ai_analysis: Dict[str, Any], extracted_files: Dict[str, str]) -> str:
        """Prepare the query for the Strands orchestrator agent"""
        # Convert ai_analysis to string if needed
        if isinstance(ai_analysis, str):
            error_text = ai_analysis
        elif isinstance(ai_analysis, dict):
            error_text = ai_analysis.get('summary', '') + '\n' + str(ai_analysis.get('recommendations', []))
        else:
            error_text = str(ai_analysis)
        
        # Prepare file list
        file_list = list(extracted_files.keys())
        
        # Extract target files from error analysis (including dependencies)
        target_files = self._extract_target_files_from_errors(ai_analysis, extracted_files)
        
        # Store extracted files in working directory for Code Agent
        extracted_dir = self.work_dir / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path, content in extracted_files.items():
            # Use just the filename to avoid path issues
            file_dest = extracted_dir / Path(file_path).name
            file_dest.write_text(content, encoding='utf-8')
        
        # Check if we have classification information
        classification = ai_analysis.get('classification', {}) if isinstance(ai_analysis, dict) else {}
        processing_mode = ai_analysis.get('processing_mode', '') if isinstance(ai_analysis, dict) else ''
        
        # Add target file information if available
        target_file_info = ""
        if target_files:
            # Separate primary error files from dependencies
            primary_files = []
            dependency_files = []
            
            # Check error details to identify primary files
            error_details = ai_analysis.get('error_details', {}) if isinstance(ai_analysis, dict) else {}
            stacktrace = error_details.get('exception_stacktrace', '') or error_details.get('traceback', '')
            
            for f in target_files:
                if stacktrace and f in stacktrace:
                    primary_files.append(f)
                else:
                    dependency_files.append(f)
            
            # If we couldn't determine, treat first file as primary
            if not primary_files and target_files:
                primary_files = [target_files[0]]
                dependency_files = target_files[1:]
            
            target_file_info = f"""
**TARGET FILES IDENTIFIED FROM ERROR:**

**Primary Files (where error occurred):**
{chr(10).join(f'   {f}' for f in primary_files)}

"""
            if dependency_files:
                target_file_info += f"""**Related Dependencies (imported by error files):**
{chr(10).join(f'  {f}' for f in dependency_files)}

"""
            
            target_file_info += """**IMPORTANT:** 
- Focus code fixes primarily on the files marked with (where error occurred)
- Review and fix related dependencies () if they contribute to the error
- Do not modify other files unless absolutely necessary
"""
        
        # Create routing instructions based on classification
        if classification.get('type') == 'package_only' or processing_mode == 'package_only':
            routing_instruction = """
**IMPORTANT ROUTING DECISION:**
This error has been classified as PACKAGE_ONLY. You MUST:
- ONLY use Library Agent (Package Agent) 
- DO NOT use Code Agent
- DO NOT use any code analysis or modification tools
- Focus solely on package/library recommendations for the UI
"""
        elif classification.get('type') == 'code_fix_required' or processing_mode == 'code_fix':
            routing_instruction = """
**IMPORTANT ROUTING DECISION:**
This error has been classified as CODE_FIX_REQUIRED. You MUST:
- ONLY use Code Agent
- DO NOT use Library Agent (Package Agent) 
- Focus on automated code fixes and modifications
"""
        else:
            routing_instruction = """
**ROUTING DECISION:**
Use both agents as appropriate:
- Use Library Agent (Package Agent) for package/dependency/library issues
- Use Code Agent for code-related issues that need automated fixes
"""

        query = f"""Please analyze and fix the following AgentCore errors:

**Error Analysis:**
{error_text}

**Classification Information:**
{classification}

**Processing Mode:**
{processing_mode}

{routing_instruction}

{target_file_info}

**Extracted Files Available:**
{', '.join(file_list)}

**Working Directory:**
{self.work_dir.absolute()}

**Extracted Files Location:**
{extracted_dir.absolute()}

**IMPORTANT FOR CODE AGENT:**
When calling the Code Agent tool, you MUST pass these parameters:
- error_analysis: The error analysis text
- extracted_files_json: JSON string of extracted files (use json.dumps(extracted_files))
- work_dir: {self.work_dir.absolute()}

The extracted_files dictionary contains {len(extracted_files)} files with their content.
File names: {', '.join(list(extracted_files.keys())[:5])}{'...' if len(extracted_files) > 5 else ''}

After calling the appropriate agent:
1. Extract key highlights from their response (critical updates, security issues, important actions)
2. Return both the highlights AND the complete agent output in the specified format."""
        
        return query
    
    def _parse_orchestrator_response(self, response) -> Dict[str, Any]:
        """Parse the orchestrator agent response to extract structured results"""
        import json
        
        # Debug logging
        self._log(f"DEBUG: Response type: {type(response)}")
        self._log(f"DEBUG: Response attributes: {dir(response)}")
        
        # Extract text output from AgentResult for Library Agent recommendations
        library_agent_output = None
        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            content = response.message.content
            self._log(f"DEBUG: Content type: {type(content)}")
            
            if isinstance(content, list):
                self._log(f"DEBUG: Content is list with {len(content)} items")
                # Extract text from content blocks
                text_parts = []
                for idx, block in enumerate(content):
                    self._log(f"DEBUG: Block {idx} type: {type(block)}")
                    if isinstance(block, dict):
                        self._log(f"DEBUG: Block {idx} keys: {list(block.keys())}")
                        if block.get('type') == 'text':
                            text = block.get('text', '')
                            text_parts.append(text)
                            self._log(f"DEBUG: Block {idx} text length: {len(text)}")
                    elif hasattr(block, 'text'):
                        # Handle ContentBlock objects
                        text = block.text
                        text_parts.append(text)
                        self._log(f"DEBUG: Block {idx} has text attribute, length: {len(text)}")
                
                library_agent_output = '\n'.join(text_parts)
                self._log(f"Extracted {len(library_agent_output)} characters of Library Agent output")
            elif isinstance(content, str):
                # Content is already a string
                library_agent_output = content
                self._log(f"Content is string, length: {len(library_agent_output)}")
            else:
                self._log(f"Unexpected content type: {type(content)}")
        
        parsed_results = {
            'raw_response': response,
            'package_recommendations': library_agent_output or response,  # Use extracted text or pass through
            'library_agent_output': library_agent_output,  # Store for UI display
            'code_fixes': [],
            'fixed_files': {}
        }
        
        # Try to extract fixed_files from Code Agent tool response
        try:
            # Check if response has message attribute
            if hasattr(response, 'message'):
                self._log(f"DEBUG: Response has message attribute")
                message = response.message
                self._log(f"DEBUG: Message type: {type(message)}")
                
                if hasattr(message, 'content'):
                    content = message.content
                    self._log(f"DEBUG: Content type: {type(content)}")
                    self._log(f"DEBUG: Content length: {len(content) if isinstance(content, (list, str)) else 'N/A'}")
                    
                    # Content is a list of content blocks
                    if isinstance(content, list):
                        self._log(f"DEBUG: Content has {len(content)} blocks")
                        for idx, block in enumerate(content):
                            self._log(f"DEBUG: Block {idx} type: {type(block)}")
                            if isinstance(block, dict):
                                self._log(f"DEBUG: Block {idx} keys: {list(block.keys())}")
                                block_type = block.get('type', 'unknown')
                                self._log(f"DEBUG: Block {idx} type field: {block_type}")
                                
                                # Look for tool_result blocks from code_agent_tool
                                if block_type == 'tool_result':
                                    tool_content = block.get('content', '')
                                    self._log(f"DEBUG: Tool result content preview: {str(tool_content)[:200]}")
                                    
                                    # Try to parse JSON from tool result
                                    if isinstance(tool_content, str):
                                        try:
                                            tool_data = json.loads(tool_content)
                                            self._log(f"DEBUG: Parsed tool data keys: {list(tool_data.keys())}")
                                            if 'fixed_files' in tool_data and tool_data['fixed_files']:
                                                parsed_results['fixed_files'] = tool_data['fixed_files']
                                                self._log(f"Extracted {len(tool_data['fixed_files'])} fixed files from Code Agent tool result")
                                                break
                                            else:
                                                self._log(f"Tool data has no fixed_files or it's empty")
                                        except json.JSONDecodeError as je:
                                            self._log(f"JSON decode error: {je}")
                                    elif isinstance(tool_content, list):
                                        # Content might be a list of text blocks
                                        for text_block in tool_content:
                                            if isinstance(text_block, dict) and text_block.get('type') == 'text':
                                                text = text_block.get('text', '')
                                                try:
                                                    tool_data = json.loads(text)
                                                    if 'fixed_files' in tool_data and tool_data['fixed_files']:
                                                        parsed_results['fixed_files'] = tool_data['fixed_files']
                                                        self._log(f"Extracted {len(tool_data['fixed_files'])} fixed files from nested text block")
                                                        break
                                                except json.JSONDecodeError:
                                                    pass
            
            # Fallback: search for JSON in string representation
            if not parsed_results['fixed_files']:
                self._log("DEBUG: Trying fallback string search")
                response_text = str(response)
                self._log(f"DEBUG: Response text length: {len(response_text)}")
                
                # Look for JSON with fixed_files key
                start_idx = response_text.find('"fixed_files"')
                self._log(f"DEBUG: Found 'fixed_files' at index: {start_idx}")
                
                if start_idx > 0:
                    # Find the enclosing JSON object
                    brace_count = 0
                    json_start = response_text.rfind('{', 0, start_idx)
                    if json_start >= 0:
                        for i in range(json_start, len(response_text)):
                            if response_text[i] == '{':
                                brace_count += 1
                            elif response_text[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    try:
                                        json_str = response_text[json_start:i+1]
                                        self._log(f"DEBUG: Attempting to parse JSON of length {len(json_str)}")
                                        data = json.loads(json_str)
                                        if 'fixed_files' in data and data['fixed_files']:
                                            parsed_results['fixed_files'] = data['fixed_files']
                                            self._log(f"Extracted {len(data['fixed_files'])} fixed files from response text")
                                            break
                                    except json.JSONDecodeError as je:
                                        self._log(f"JSON parse failed: {je}")
            
        except Exception as e:
            self._log(f"Could not extract fixed_files from response: {e}")
            import traceback
            self._log(f"Traceback: {traceback.format_exc()}")
        
        if not parsed_results['fixed_files']:
            self._log("No fixed_files found in orchestrator response - debugging needed")
        
        self._log("Agent response passed through for UI display")
        return parsed_results
    
    def _log(self, message: str):
        """Log orchestrator messages with structured logging"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        
        # Use proper logging levels based on message content
        if 'failed' in message.lower() or 'error' in message.lower():
            logger.error(message)
        elif 'complete' in message.lower() or 'success' in message.lower():
            logger.info(message)
        elif 'debug' in message.lower():
            logger.debug(message)
        else:
            logger.info(message)
        
        self.results['agent_logs'].append(log_entry)
    
    def _generate_code_agent_summary(self, code_fixes: Any, fixed_files: Dict[str, str], ai_analysis: Dict[str, Any]) -> str:
        """Generate a comprehensive summary of Code Agent's work
        
        Args:
            code_fixes: Raw code agent response
            fixed_files: Dictionary of fixed files
            ai_analysis: Original error analysis
            
        Returns:
            Formatted markdown summary
        """
        try:
            # Extract code agent response text
            code_agent_text = ""
            if hasattr(code_fixes, 'message') and hasattr(code_fixes.message, 'content'):
                if isinstance(code_fixes.message.content, list) and code_fixes.message.content:
                    code_agent_text = code_fixes.message.content[0].get('text', str(code_fixes))
                else:
                    code_agent_text = str(code_fixes.message.content)
            else:
                code_agent_text = str(code_fixes)
            
            # Prepare analysis prompt for the orchestrator
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

**ORIGINAL ERROR ANALYSIS:**
{ai_analysis.get('summary', 'No summary available')}

**CODE AGENT OUTPUT:**
{code_agent_text[:3000]}{'...' if len(code_agent_text) > 3000 else ''}

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

            logger.info("Calling orchestrator to generate Code Agent summary...")
            
            # Use the orchestrator agent to generate the summary
            summary_response = self.orchestrator_agent(summary_prompt)
            
            # Extract text from response
            summary_text = ""
            if hasattr(summary_response, 'message') and hasattr(summary_response.message, 'content'):
                if isinstance(summary_response.message.content, list) and summary_response.message.content:
                    summary_text = summary_response.message.content[0].get('text', str(summary_response))
                else:
                    summary_text = str(summary_response.message.content)
            else:
                summary_text = str(summary_response)
            
            logger.info(f"Generated summary ({len(summary_text)} characters)")
            return summary_text
            
        except Exception as e:
            logger.error(f"Failed to generate Code Agent summary: {e}")
            # Return a basic summary as fallback
            return f"""## CODE FIXES APPLIED:

**Files Modified:** {', '.join(fixed_files.keys())}

**Status:** Code Agent completed successfully

**Details:** See Code Agent output below for full details.

_(Automatic summary generation failed: {str(e)})_"""
    
    def get_results_summary(self) -> Dict[str, Any]:
        """Get a summary of orchestration results"""
        return {
            'total_package_recommendations': len(self.results.get('package_recommendations', [])),
            'total_code_fixes': len(self.results.get('code_fixes_applied', [])),
            'working_directory': str(self.work_dir.absolute()),
            'classification_summary': self.results.get('error_classification', {}),
            'execution_time': (datetime.now() - self.results['start_time']).total_seconds()
        }
"""
Code Agent - Code Agent (Strands Tool)

Handles code file issues using proper Strands tools with @tool decorators.
Modifies extracted files and stores them locally for GitLab push.
Implemented as a Strands tool that uses other specialized tools.
"""

import os
import ast
import subprocess
import tempfile
import json
import shutil
import logging
import re
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

from strands import tool, Agent

# Setup code agent logging with queue handler for real-time display
logger = logging.getLogger("CodeAgentTool")
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
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(ch)

# Safe builtins for REPL execution
SAFE_BUILTINS = {
    "None": None, "True": True, "False": False,
    "len": len, "range": range, "min": min, "max": max, "sum": sum,
    "enumerate": enumerate, "list": list, "dict": dict, "set": set,
    "tuple": tuple, "int": int, "float": float, "str": str, "bool": bool,
}

def timestamp() -> str:
    """Generate timestamp for backups and logs"""
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def extract_file_paths_from_traceback(text: str) -> List[str]:
    """Extract Python file paths mentioned in a typical Python traceback."""
    files = set()
    # matches: File "/path/to/file.py", line 10, in func
    for m in re.finditer(r'File "([^"]+\.py)"', text):
        files.add(m.group(1))
    # also look for simple patterns like path/to/file.py:123
    for m in re.finditer(r'(\S+\.py):\d+', text):
        files.add(m.group(1))
    return list(files)


@tool
def code_agent_tool(error_analysis: str, extracted_files_json: str = "{}", work_dir: str = "") -> str:
    """
    Code Agent: Fix any code-related errors using specialized development tools.
    
    Handles all types of code issues including but not limited to:
    - Syntax errors and logic issues
    - Runtime errors and exceptions
    - Performance problems
    - Security vulnerabilities in code
    - API integration issues
    - Database connection problems
    - File I/O and data processing errors
    - Concurrency and threading issues
    - Memory and resource management
    - Code structure and architecture problems
    - Testing and validation issues
    - Configuration and environment setup
    - And any other code-related problems that can be automatically fixed
    
    Args:
        error_analysis: String containing error analysis to process for code issues
        extracted_files_json: JSON string of extracted files {path: content}
        work_dir: Working directory where extracted files are located
    """
    logger.info("="*60)
    logger.info("CODE AGENT ACTIVATION")
    logger.info("Specialization: Code fixes & modifications")
    logger.info("Tools: Python REPL, AST Analyzer, File Modifier, Pytest Runner")
    logger.info("Output: Fixed files for GitLab push")
    logger.info("="*60)
    
    # Parse extracted_files_json OR read from disk
    extracted_files = {}
    try:
        if extracted_files_json and extracted_files_json != "{}":
            extracted_files = json.loads(extracted_files_json)
            logger.info(f"EXTRACTED FILES FROM JSON: {len(extracted_files)} files")
    except json.JSONDecodeError:
        logger.warning("Invalid JSON, will try reading from disk")
    
    # If no files in JSON but we have work_dir, read from app/ directory (preferred) or extracted/
    if not extracted_files and work_dir:
        # Prefer app/ directory (has fixed files from previous runs)
        app_dir_path = Path(work_dir) / "app"
        extracted_dir_path = Path(work_dir) / "extracted"
        
        # Use app/ if it exists and has files, otherwise fall back to extracted/
        source_dir = app_dir_path if (app_dir_path.exists() and any(app_dir_path.glob("*.py"))) else extracted_dir_path
        
        if source_dir.exists():
            logger.info(f"📂 Reading files from disk: {source_dir}")
            for file_path in source_dir.glob("*.py"):
                try:
                    content = file_path.read_text(encoding='utf-8')
                    extracted_files[file_path.name] = content
                    logger.info(f"   Loaded: {file_path.name} ({len(content)} chars)")
                except Exception as e:
                    logger.warning(f"   Could not read {file_path.name}: {e}")
            
            # Also load config files
            for pattern in ["requirements.txt", "*.yaml", "*.yml"]:
                for file_path in source_dir.glob(pattern):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        extracted_files[file_path.name] = content
                        logger.info(f"   Loaded: {file_path.name} ({len(content)} chars)")
                    except Exception as e:
                        logger.warning(f"   Could not read {file_path.name}: {e}")
    
    logger.info(f"TOTAL EXTRACTED FILES: {len(extracted_files)} files")
    for file_path in list(extracted_files.keys())[:5]:
        logger.info(f"   {file_path}")
    if len(extracted_files) > 5:
        logger.info(f"   ... and {len(extracted_files) - 5} more files")
    
    # Set up working directories
    if work_dir:
        base_work_dir = Path(work_dir)
        logger.info(f"Using provided work directory: {base_work_dir}")
    else:
        # Ensure agentcore_fixes is under the AGENTCORE-DEBUGGER root folder
        project_root = Path(__file__).parent.parent.parent  # This is the AGENTCORE-DEBUGGER root
        base_work_dir = project_root / "agentcore_fixes" / f"fix_{timestamp()}"
        logger.info(f"Created new work directory: {base_work_dir}")
    
    # SIMPLIFIED: Use app/ as the SINGLE source of truth for all files
    # This ensures Fix All operations always build on previous fixes
    app_dir = base_work_dir / "app"           # Single source of truth - read AND write here
    fixed_dir = base_work_dir / "fixed"       # Copy of fixed files (for GitLab push)
    backup_dir = base_work_dir / "backups"    # Backup original files before fixing
    
    logger.info("📂 SETTING UP DIRECTORY STRUCTURE:")
    logger.info(f"   Working directory (app/): {app_dir}")
    logger.info(f"   Fixed files output: {fixed_dir}")
    logger.info(f"   💾 Backups: {backup_dir}")
    
    for dir_path in [app_dir, fixed_dir, backup_dir]:
        dir_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("Directory structure created successfully")
    
    # Check if app/ already has files (from previous fix in Fix All)
    existing_app_files = list(app_dir.glob("*.py"))
    
    if existing_app_files:
        # SHARED WORKSPACE: Read from app/ to preserve previous fixes
        logger.info("SHARED WORKSPACE - Reading from app/ to preserve previous fixes:")
        logger.info(f"   Found {len(existing_app_files)} existing files in app/")
        
        # Update extracted_files with current content from app/
        for file_path, content in list(extracted_files.items()):
            app_file = app_dir / Path(file_path).name
            if app_file.exists():
                current_content = app_file.read_text(encoding='utf-8')
                if current_content != content:
                    logger.info(f"   Using FIXED version: {app_file.name} (has previous fixes)")
                else:
                    logger.info(f"   Loaded: {app_file.name} (unchanged)")
                extracted_files[file_path] = current_content
            else:
                # New file - write to app/
                app_file.write_text(content, encoding='utf-8')
                logger.info(f"   Added new file: {app_file.name}")
    else:
        # FIRST FIX: Copy all files to app/
        logger.info("FIRST FIX - Copying files to app/:")
        for file_path, content in extracted_files.items():
            app_file = app_dir / Path(file_path).name
            app_file.write_text(content, encoding='utf-8')
            logger.info(f"   Copied: {app_file.name} ({len(content)} chars)")
    
    # For backward compatibility, also set extracted_dir to app_dir
    extracted_dir = app_dir
    
    # Also look for files mentioned in error analysis
    logger.info("ANALYZING ERROR TRACEBACK FOR ADDITIONAL FILES:")
    trace_files = extract_file_paths_from_traceback(error_analysis)
    if trace_files:
        logger.info(f"   Found {len(trace_files)} files in traceback:")
        for trace_file in trace_files:
            logger.info(f"      {trace_file}")
            if trace_file not in extracted_files:
                # Try to find the file in extracted directory
                trace_name = Path(trace_file).name
                potential_file = extracted_dir / trace_name
                if potential_file.exists():
                    extracted_files[trace_file] = potential_file.read_text(encoding='utf-8')
                    logger.info(f"   Found and loaded: {potential_file}")
                else:
                    logger.warning(f"   Not found in extracted dir: {trace_name}")
    else:
        logger.info("   No additional files found in traceback")
    
    # Create specialized code agent with development tools
    logger.info("INITIALIZING CODE AGENT:")
    logger.info("   🧠 System Prompt: Code fixing specialist")
    logger.info("   Tools Available:")
    logger.info("      🐍 Python REPL: Execute and test code")
    logger.info("      AST Analyzer: Analyze code structure")
    logger.info("      File Modifier: Apply code fixes")
    logger.info("       Pytest Runner: Validate fixes")
    
    # Initialize Code Agent with the configured model
    from strands.models import BedrockModel
    from src.config.config import get_model_id, get_aws_region, get_fallback_models
    
    model_id = get_model_id()
    region = get_aws_region()
    fallback_models = get_fallback_models()
    
    logger.info(f"Initializing Code Agent with model: {model_id}")
    logger.info(f"Region: {region}")
    logger.info(f"Fallback models available: {len(fallback_models)}")
    
    code_agent_model = BedrockModel(model_id=model_id, region_name=region, read_timeout=300)  # 5 minutes timeout
    
    code_agent = Agent(
        model=code_agent_model,
        system_prompt=_get_code_agent_system_prompt(),
        tools=[
            python_repl_tool,
            ast_analyzer_tool, 
            file_modifier_tool,
            pytest_runner_tool
        ]
    )
    
    # Parse error_analysis if it's a string
    if isinstance(error_analysis, str):
        try:
            error_analysis = json.loads(error_analysis)
        except json.JSONDecodeError:
            logger.warning("error_analysis is a string but not valid JSON, treating as plain text")
            error_analysis = {'summary': error_analysis}
    
    # Extract files to fix from error analysis (if provided by mixed workflow)
    files_to_fix = error_analysis.get('files_to_fix', []) if isinstance(error_analysis, dict) else []
    package_recommendations = error_analysis.get('package_recommendations', []) if isinstance(error_analysis, dict) else []
    user_choice = error_analysis.get('user_choice', None) if isinstance(error_analysis, dict) else None
    
    # Build file-specific instructions
    file_instructions = ""
    if files_to_fix:
        file_instructions = f"""
FILES TO FIX:
{json.dumps(files_to_fix, indent=2)}

These files were identified from error traceback and package analysis.
Fix ALL files in this list.
"""
    
    # Build package context if available
    package_context = ""
    if package_recommendations:
        if 'requirements.txt' in files_to_fix:
            # requirements.txt is in the list - user wants it updated
            package_context = f"""
PACKAGE RECOMMENDATIONS FROM LIBRARY AGENT:
{json.dumps(package_recommendations, indent=2)}

IMPORTANT: requirements.txt is in the files to fix list.
Update requirements.txt according to these package recommendations.
Apply the recommended version upgrades.
"""
        else:
            # requirements.txt NOT in list - user wants backward compatible code fixes only
            package_context = f"""
PACKAGE RECOMMENDATIONS FROM LIBRARY AGENT (FOR CONTEXT ONLY):
{json.dumps(package_recommendations, indent=2)}

NOTE: requirements.txt is NOT in the files to fix list.
This means: Apply BACKWARD COMPATIBLE code fixes that work with current package versions.
Do NOT update requirements.txt - keep existing package versions.
"""
    
    # Format query for code analysis and fixing - OPTIMIZED for speed
    formatted_query = f"""Fix the error below. Use MAXIMUM 5 tool calls.

ERROR:
{error_analysis}

FILES: {extracted_dir}
OUTPUT: {fixed_dir}
{file_instructions}
{package_context}

STEPS (5 max):
1. ast_analyzer_tool on the file
2. python_repl_tool to read error line
3. file_modifier_tool with output_dir="{fixed_dir}"
4. Done - provide brief summary

CRITICAL: output_dir="{fixed_dir}" in file_modifier_tool"""
    
    try:
        logger.info("EXECUTING CODE AGENT ANALYSIS AND FIXES...")
        logger.info(f"   Query length: {len(formatted_query)} characters")
        logger.info("   Focus: Any and all code-related issues")
        
        # Log the prompt being sent to Code Agent
        logger.info("CODE AGENT PROMPT:")
        logger.info("-" * 60)
        logger.info(formatted_query)
        logger.info("-" * 60)
        
        # Try with primary model first, then fallback models if rate limited
        response = None
        last_error = None
        models_to_try = [model_id] + fallback_models
        
        for attempt, current_model_id in enumerate(models_to_try, 1):
            try:
                if attempt > 1:
                    logger.warning(f"FALLBACK ATTEMPT {attempt}/{len(models_to_try)}")
                    logger.warning(f"   Location: code_agent.py, line ~333 (code_agent_tool function)")
                    logger.warning(f"   Retrying with model: {current_model_id}")
                    # Recreate agent with fallback model
                    code_agent_model = BedrockModel(model_id=current_model_id, region_name=region, read_timeout=300)
                    code_agent = Agent(
                        model=code_agent_model,
                        system_prompt=_get_code_agent_system_prompt(),
                        tools=[
                            python_repl_tool,
                            ast_analyzer_tool, 
                            file_modifier_tool,
                            pytest_runner_tool
                        ]
                    )
                else:
                    logger.info(f"PRIMARY MODEL ATTEMPT")
                    logger.info(f"   Location: code_agent.py, line ~333 (code_agent_tool function)")
                    logger.info(f"   Using model: {current_model_id}")
                
                response = code_agent(formatted_query)
                
                if attempt > 1:
                    logger.info(f"SUCCESS WITH FALLBACK MODEL: {current_model_id}")
                    logger.info(f"   Location: code_agent.py, line ~333")
                else:
                    logger.info(f"SUCCESS WITH PRIMARY MODEL: {current_model_id}")
                
                break  # Success, exit retry loop
                
            except Exception as e:
                error_msg = str(e)
                last_error = e
                
                # Log the error details
                logger.error(f"BEDROCK ERROR OCCURRED")
                logger.error(f"   Location: code_agent.py, line ~333 (code_agent_tool function)")
                logger.error(f"   Model: {current_model_id}")
                logger.error(f"   Attempt: {attempt}/{len(models_to_try)}")
                logger.error(f"   Error Type: {type(e).__name__}")
                logger.error(f"   Error Message: {error_msg[:200]}...")
                
                # Check if it's a rate limit / connection error (case-insensitive)
                is_rate_limit = any(keyword in error_msg.lower() for keyword in [
                    'serviceunavailableexception',
                    'too many connections',
                    'throttlingexception',
                    'rate limit',
                    'toomanyrequestsexception',
                    'eventloopexception',
                    'service unavailable',
                    'throttling'
                ])
                
                if is_rate_limit:
                    logger.warning(f"RATE LIMIT DETECTED")
                    logger.warning(f"   Location: code_agent.py, line ~333")
                    logger.warning(f"   Failed model: {current_model_id}")
                    
                    if attempt < len(models_to_try):
                        logger.warning(f"   Will retry with next fallback model in 2 seconds...")
                        import time
                        time.sleep(2)  # Brief delay before retry
                        continue
                    else:
                        logger.error(f"   NO MORE FALLBACK MODELS AVAILABLE")
                        raise
                else:
                    logger.error(f"   NON-RATE-LIMIT ERROR - Not retrying")
                    logger.error(f"   Location: code_agent.py, line ~333")
                    raise
        
        if response is None:
            # All models failed
            logger.error(f"ALL MODELS FAILED")
            logger.error(f"   Location: code_agent.py, line ~333")
            logger.error(f"   Tried {len(models_to_try)} models")
            logger.error(f"   Last error: {last_error}")
            raise Exception(f"All models failed. Last error: {last_error}")
        
        logger.info("CODE AGENT EXECUTION COMPLETED:")
        logger.info(f"   Response type: {type(response)}")
        logger.info(f"   Response length: {len(str(response)) if response else 0} characters")
        logger.info("   Fixed files ready for GitLab push")
        
        # Extract text content from AgentResult
        response_text = ""
        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            if isinstance(response.message.content, list) and response.message.content:
                response_text = response.message.content[0].get('text', str(response))
            else:
                response_text = str(response.message.content)
        else:
            response_text = str(response)
        
        # Read ONLY the files that were actually fixed in this run
        # Check if agent has tracked modified files in its context
        fixed_files = {}
        modified_files_in_this_run = set()
        
        # Extract list of files that were actually modified from the agent's tool calls
        # The file_modifier_tool writes to fixed_dir, so we check backup timestamps
        if backup_dir.exists():
            # Get all backup files created in this run (recent backups)
            import time
            current_time = time.time()
            recent_threshold = 300  # 5 minutes
            
            for backup_file in backup_dir.glob("*.bak"):
                # Check if backup was created recently (in this run)
                if (current_time - backup_file.stat().st_mtime) < recent_threshold:
                    # Extract original filename from backup (format: filename.timestamp.bak)
                    original_name = backup_file.stem.rsplit('.', 1)[0]  # Remove timestamp
                    modified_files_in_this_run.add(original_name)
                    logger.info(f"   Detected modified file from backup: {original_name}")
        
        # Only include files that were actually modified in this run
        if fixed_dir.exists():
            for file_path in fixed_dir.glob("*"):
                if file_path.is_file():
                    # Only include if this file was modified in this run
                    if file_path.name in modified_files_in_this_run or len(modified_files_in_this_run) == 0:
                        try:
                            content = file_path.read_text(encoding='utf-8')
                            if content.strip():  # Only include non-empty files
                                fixed_files[file_path.name] = content
                                logger.info(f"   Including fixed file: {file_path.name} ({len(content)} chars)")
                        except Exception as e:
                            logger.warning(f"   Could not read fixed file {file_path.name}: {e}")
                    else:
                        logger.info(f"   ⏭️  Skipping unchanged file: {file_path.name} (not modified in this run)")
        
        # Return structured response with file locations
        result = {
            "status": "success",
            "agent_response": response_text,  # Now serializable
            "fixed_files": fixed_files,  # Include actual fixed file contents
            "directories": {
                "extracted": str(extracted_dir),
                "fixed": str(fixed_dir),
                "backups": str(backup_dir)
            },
            "files_processed": list(extracted_files.keys())
        }
        
        logger.info("STRUCTURED RESPONSE PREPARED:")
        logger.info(f"   Directories configured: {len(result['directories'])}")
        logger.info(f"   Files processed: {len(result['files_processed'])}")
        logger.info(f"   Response text extracted: {len(response_text)} characters")
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_msg = f"Error in Code Agent: {str(e)}"
        logger.error("CODE AGENT EXECUTION FAILED:")
        logger.error(f"   Exception Type: {type(e).__name__}")
        logger.error(f"   Exception Message: {str(e)}")
        logger.exception("   Full Exception Traceback:")
        
        return json.dumps({
            "status": "error",
            "error": error_msg,
            "directories": {
                "extracted": str(extracted_dir) if 'extracted_dir' in locals() else "",
                "fixed": str(fixed_dir) if 'fixed_dir' in locals() else "",
                "backups": str(backup_dir) if 'backup_dir' in locals() else ""
            }
        }, indent=2)


def _get_code_agent_system_prompt() -> str:
    """Get the system prompt for the Code Agent - OPTIMIZED for speed"""
    return """You are the Code Agent - a FAST, surgical code fixer.

**SPEED IS CRITICAL - MINIMIZE TOOL CALLS:**
- Use MAXIMUM 5 tool calls total
- Read file ONCE with python_repl_tool
- Apply fix ONCE with file_modifier_tool
- Verify ONCE (optional) with python_repl_tool
- DO NOT read the same file multiple times
- DO NOT do excessive verification

**WORKFLOW (5 steps max):**
1. ast_analyzer_tool: Analyze the file structure (1 call)
2. python_repl_tool: Read the specific lines around the error (1 call)
3. file_modifier_tool: Apply the fix (1 call)
4. python_repl_tool: Quick syntax check (1 call, optional)
5. Done - provide summary

**ABSOLUTE RULES:**
- Fix ONLY the error in the stacktrace
- DO NOT fix other bugs you notice
- DO NOT add logging, error handling, or enhancements
- PRESERVE existing fixes in the code
- Keep changes MINIMAL

**What to Fix:**
- The exact line mentioned in the stacktrace
- Related code in the same function if needed
- Import statements if required for the fix

**What NOT to Fix:**
- Other bugs not in the stacktrace
- Deprecated APIs not causing the current error
- Code style or refactoring
- Adding error handling or logging

**Response Format (BRIEF):**
```
FIX APPLIED:
- File: [filename]
- Line: [line_number]
- Error: [brief error description]
- Fix: [what was changed]
- Status: Fixed

OTHER ISSUES (not fixed): [list briefly if any]
```

**Example:**
Error: `ord="invalid"` not supported at line 140
Fix: Changed `ord="invalid"` to `ord=2`
Tool calls: 3 (analyze, read, fix)
Done."""


# Specialized development tools for Code Agent
@tool
def python_repl_tool(code: str, timeout_seconds: int = 10) -> str:
    """
    Execute Python code in a safer subprocess environment for testing and validation.
    
    Args:
        code: Python code to execute
        timeout_seconds: Maximum execution time
    """
    logger.info("🐍 Python REPL tool activated")
    
    try:
        # Use subprocess for safer execution
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as tmpf:
            tmpf.write(code)
            tmpf.flush()
            tmp_path = tmpf.name
        
        # Run the temp file in a subprocess - safer than exec in-process
        proc = subprocess.run(
            ["python", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        result = {
            "status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        
        logger.info("Python REPL execution completed")
        return json.dumps(result, indent=2)
        
    except subprocess.TimeoutExpired:
        logger.error("Python REPL timeout")
        return json.dumps({"status": "timeout", "message": "Execution timed out"}, indent=2)
    except Exception as e:
        error_result = f"Python execution error: {str(e)}"
        logger.error(f"{error_result}")
        return json.dumps({"status": "error", "error": str(e)}, indent=2)


@tool  
def ast_analyzer_tool(file_path: str, file_content: str = "") -> str:
    """
    Analyze Python code structure using AST (Abstract Syntax Tree).
    
    Args:
        file_path: Path to the Python file to analyze
        file_content: Content of the file (if not reading from disk)
    """
    print(f"AST Analyzer tool activated for {file_path}")
    
    try:
        # Get file content
        if file_content:
            content = file_content
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except FileNotFoundError:
                return f"File not found: {file_path}"
        
        # Parse AST
        tree = ast.parse(content)
        
        # Analyze code structure
        analysis = {
            'functions': [],
            'classes': [],
            'imports': [],
            'has_api_calls': False,
            'has_retry_logic': False,
            'has_logging': False,
            'has_async': False,
            'issues_found': []
        }
        
        for node in ast.walk(tree):
            # Function definitions
            if isinstance(node, ast.FunctionDef):
                analysis['functions'].append(node.name)
                if node.name.startswith('async_'):
                    analysis['has_async'] = True
            
            # Class definitions  
            elif isinstance(node, ast.ClassDef):
                analysis['classes'].append(node.name)
            
            # Import statements
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    analysis['imports'].append(alias.name)
                    if 'logging' in alias.name:
                        analysis['has_logging'] = True
            
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    analysis['imports'].append(node.module)
                    if 'logging' in node.module:
                        analysis['has_logging'] = True
            
            # API calls detection
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in ['get', 'post', 'put', 'delete', 'request']:
                        analysis['has_api_calls'] = True
            
            # Async function definitions
            elif isinstance(node, ast.AsyncFunctionDef):
                analysis['has_async'] = True
                analysis['functions'].append(f"async {node.name}")
        
        # Check for retry logic in content
        if any(keyword in content.lower() for keyword in ['retry', 'backoff', 'sleep', 'attempt']):
            analysis['has_retry_logic'] = True
        
        # Identify potential issues
        if analysis['has_api_calls'] and not analysis['has_retry_logic']:
            analysis['issues_found'].append("API calls without retry logic")
        
        if not analysis['has_logging'] and len(analysis['functions']) > 2:
            analysis['issues_found'].append("No logging configuration found")
        
        if analysis['has_async'] and 'asyncio' not in str(analysis['imports']):
            analysis['issues_found'].append("Async functions without asyncio import")
        
        result = f"""AST Analysis for {file_path}:
- Functions: {len(analysis['functions'])} ({', '.join(analysis['functions'][:5])})
- Classes: {len(analysis['classes'])} ({', '.join(analysis['classes'][:3])})
- Imports: {', '.join(analysis['imports'][:10])}
- Has API calls: {analysis['has_api_calls']}
- Has retry logic: {analysis['has_retry_logic']}
- Has logging: {analysis['has_logging']}
- Has async: {analysis['has_async']}
- Issues found: {', '.join(analysis['issues_found']) if analysis['issues_found'] else 'None'}"""
        
        print("AST analysis completed")
        return result
        
    except SyntaxError as e:
        error_result = f"Syntax error in {file_path}: {str(e)}"
        print(f"{error_result}")
        return error_result
    except Exception as e:
        error_result = f"AST analysis error: {str(e)}"
        print(f"{error_result}")
        return error_result


@tool
def file_modifier_tool(file_path: str, modification_type: str, file_content: str = "", custom_fix: str = "", output_dir: str = "") -> str:
    """
    Modify code files with any type of improvements and save to output directory.
    
    Args:
        file_path: Path to the file to modify (can be relative to extracted dir)
        modification_type: Type of modification (rate_limiting, exception_handling, logging, async_fix, code_quality, syntax_fix, security_fix, performance_fix, custom)
        file_content: Current content of the file
        custom_fix: For 'custom' modification_type, describe the specific fix to apply
        output_dir: Directory to save fixed files (defaults to ./fixed)
    """
    logger.info(f"File Modifier tool activated: {modification_type} for {file_path}")
    
    try:
        # Determine paths
        source_path = Path(file_path)
        if not output_dir:
            output_dir = Path.cwd() / "fixed"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get current content
        if file_content:
            content = file_content
        else:
            if not source_path.exists():
                # Try to find file in common locations
                for potential_dir in [Path.cwd() / "extracted", Path.cwd()]:
                    potential_path = potential_dir / source_path.name
                    if potential_path.exists():
                        source_path = potential_path
                        break
                else:
                    return json.dumps({"status": "error", "message": f"File not found: {file_path}"}, indent=2)
            
            content = source_path.read_text(encoding='utf-8')
        
        original_content = content
        original_lines = len(original_content.splitlines())
        
        # Create backup
        backup_dir = output_dir.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"{source_path.name}.{timestamp()}.bak"
        backup_path.write_text(original_content, encoding='utf-8')
        
        # Apply modifications based on type
        if modification_type == "rate_limiting":
            content = _add_rate_limiting(content)
        elif modification_type == "exception_handling":
            content = _improve_exception_handling(content)
        elif modification_type == "logging":
            content = _add_logging(content)
        elif modification_type == "async_fix":
            content = _fix_async_issues(content)
        elif modification_type == "code_quality":
            content = _improve_code_quality(content)
        elif modification_type == "syntax_fix":
            content = _fix_syntax_issues(content)
        elif modification_type == "security_fix":
            content = _apply_security_fixes(content)
        elif modification_type == "performance_fix":
            content = _apply_performance_fixes(content)
        elif modification_type == "custom":
            content = _apply_custom_fix(content, custom_fix)
        else:
            content = _apply_generic_fix(content, modification_type)
        
        # Write fixed content to output directory
        fixed_path = output_dir / source_path.name
        fixed_path.write_text(content, encoding='utf-8')
        
        new_lines = len(content.splitlines())
        
        result = {
            "status": "ok",
            "original_file": str(source_path),
            "fixed_file": str(fixed_path),
            "backup_file": str(backup_path),
            "modification_type": modification_type,
            "original_lines": original_lines,
            "new_lines": new_lines,
            "lines_delta": new_lines - original_lines
        }
        
        logger.info("File modification completed")
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = f"File modification error: {str(e)}"
        logger.error(f"{error_result}")
        return json.dumps({"status": "error", "error": str(e)}, indent=2)


@tool
def pytest_runner_tool(test_command: str, working_directory: str = ".") -> str:
    """
    Run pytest or other testing commands to validate code fixes.
    
    Args:
        test_command: The test command to run (e.g., "python -m pytest", "python -c 'import file'")
        working_directory: Directory to run the command in
    """
    print(f" Pytest Runner tool activated: {test_command}")
    
    try:
        # Change to working directory
        original_dir = os.getcwd()
        if working_directory != ".":
            os.chdir(working_directory)
        
        try:
            # Run the test command
            result = subprocess.run(
                test_command.split(),
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            output = f"""Test execution completed:
Command: {test_command}
Return code: {result.returncode}
STDOUT:
{result.stdout}
STDERR:
{result.stderr}"""
            
            if result.returncode == 0:
                print("Tests passed")
            else:
                print("Tests failed")
            
            return output
            
        finally:
            os.chdir(original_dir)
        
    except subprocess.TimeoutExpired:
        error_result = f"Test command timed out: {test_command}"
        print(f"⏰ {error_result}")
        return error_result
    except Exception as e:
        error_result = f"Test execution error: {str(e)}"
        print(f"{error_result}")
        return error_result


# Helper functions for file modifications
def _add_rate_limiting(content: str) -> str:
    """Add rate limiting/retry logic to Python code"""
    if 'retry' in content.lower() or 'backoff' in content.lower():
        return content  # Already has retry logic
    
    rate_limit_code = '''
import time
import random
from functools import wraps

def retry_with_exponential_backoff(max_retries=3, base_delay=1.0):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(delay)
                        continue
                    raise e
            return func(*args, **kwargs)
        return wrapper
    return decorator

'''
    
    # Insert after imports
    lines = content.split('\n')
    insert_idx = 0
    for i, line in enumerate(lines):
        if not (line.strip().startswith('import ') or 
               line.strip().startswith('from ') or 
               line.strip().startswith('#') or 
               line.strip() == ''):
            insert_idx = i
            break
    
    lines.insert(insert_idx, rate_limit_code)
    return '\n'.join(lines)


def _improve_exception_handling(content: str) -> str:
    """Improve exception handling in Python code"""
    # Add logging if not present
    if 'import logging' not in content:
        logging_code = '''
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

'''
        lines = content.split('\n')
        lines.insert(0, logging_code)
        content = '\n'.join(lines)
    
    # Replace basic print statements with logging
    content = content.replace('print(', 'logger.info(')
    
    return content


def _add_logging(content: str) -> str:
    """Add structured logging to Python code"""
    return _improve_exception_handling(content)  # Same implementation


def _fix_async_issues(content: str) -> str:
    """Fix async/await issues in Python code"""
    # Simple fix: ensure async functions have proper patterns
    if 'async def' in content and 'await' not in content:
        # This is a simplified fix - in reality, you'd need more sophisticated analysis
        content = content.replace('return ', 'return await ')
    
    return content


def _improve_code_quality(content: str) -> str:
    """Apply general code quality improvements"""
    lines = content.split('\n')
    improved_lines = []
    
    for line in lines:
        # Remove trailing whitespace
        line = line.rstrip()
        improved_lines.append(line)
    
    # Ensure file ends with newline
    if improved_lines and improved_lines[-1] != '':
        improved_lines.append('')
    
    return '\n'.join(improved_lines)


def _fix_syntax_issues(content: str) -> str:
    """Fix common syntax issues in Python code"""
    # Fix common indentation issues
    lines = content.split('\n')
    fixed_lines = []
    
    for line in lines:
        # Fix mixed tabs and spaces (convert tabs to 4 spaces)
        line = line.expandtabs(4)
        
        # Fix common syntax patterns
        line = line.replace(' = = ', ' == ')  # Fix spacing in equality
        line = line.replace(' ! = ', ' != ')  # Fix spacing in inequality
        
        fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)


def _apply_security_fixes(content: str) -> str:
    """Apply security-related fixes to Python code"""
    # Fix common security issues
    
    # Replace eval() with safer alternatives (basic example)
    if 'eval(' in content:
        content = content.replace('eval(', '# SECURITY FIX: eval() replaced - use ast.literal_eval() or json.loads() instead\n# eval(')
    
    # Add warning for exec() usage
    if 'exec(' in content:
        content = content.replace('exec(', '# SECURITY WARNING: exec() usage detected - review for security implications\nexec(')
    
    # Fix SQL injection patterns (basic example)
    if 'execute(' in content and '%s' in content:
        content = '# SECURITY FIX: Use parameterized queries to prevent SQL injection\n' + content
    
    return content


def _apply_performance_fixes(content: str) -> str:
    """Apply performance-related fixes to Python code"""
    # Fix common performance issues
    
    # Replace string concatenation in loops with list join
    if 'for ' in content and '+=' in content and 'str' in content:
        content = '# PERFORMANCE TIP: Consider using list.append() and "".join() for string concatenation in loops\n' + content
    
    # Add caching suggestions for repeated calculations
    if 'def ' in content and 'for ' in content:
        content = '# PERFORMANCE TIP: Consider using functools.lru_cache for expensive repeated calculations\n' + content
    
    return content


def _apply_custom_fix(content: str, custom_fix: str) -> str:
    """Apply a custom fix using LLM with validation loop and fallback models"""
    import boto3
    from src.core.retry_config import ADAPTIVE_RETRY
    import ast
    import json
    
    # Initialize Bedrock client with fallback support
    from src.config.config import get_model_id, get_aws_region, get_fallback_models
    
    region = get_aws_region()
    primary_model = get_model_id()
    fallback_models = get_fallback_models()
    models_to_try = [primary_model] + fallback_models
    
    bedrock = boto3.client('bedrock-runtime', region_name=region, config=ADAPTIVE_RETRY)
    logger.info(f"Primary model: {primary_model} in region {region}")
    logger.info(f"Fallback models available: {len(fallback_models)}")
    logger.info(f"Using adaptive retry for Bedrock calls")
    
    validation_error = None
    
    # Try each model
    for model_idx, model_id in enumerate(models_to_try, 1):
        if model_idx > 1:
            logger.info(f"Switching to fallback model #{model_idx}: {model_id}")
        
        # Try up to 2 validation attempts per model
        for attempt in range(1, 3):
            total_attempt = (model_idx - 1) * 2 + attempt
            logger.info(f"LLM Fix Attempt {total_attempt} (Model {model_idx}/{len(models_to_try)}, Attempt {attempt}/2)")
            
            # Create prompt for LLM - let it determine the optimal fix
            if attempt == 1:
                prompt = f"""Fix the specific issue in this Python code.

REQUIREMENT: {custom_fix}

CURRENT CODE:
```python
{content}
```

CRITICAL INSTRUCTIONS:
1. Identify what's causing the error mentioned in the requirement
2. Apply the minimal necessary changes to resolve the error completely
3. Ensure the fix is robust and won't cause new issues
4. **PRESERVE ALL EXISTING CODE EXACTLY AS-IS** - only modify the specific lines needed for this fix
5. Don't remove existing functionality unless it's directly causing the error
6. **IMPORTANT**: This code may already contain fixes from previous error patterns. DO NOT revert or change any code that is not directly related to the current error requirement.
7. If you see code that looks like it was recently fixed (e.g., using pd.concat instead of df.append, or ord=2 instead of ord="invalid"), KEEP those fixes intact.

Return ONLY the complete fixed Python code, no explanations, no markdown blocks. The code must be syntactically correct."""
            else:
                # Subsequent attempts include the validation error
                prompt = f"""The previous fix attempt had errors. Please fix the code again.

REQUIREMENT: {custom_fix}

PREVIOUS ATTEMPT HAD THIS ERROR:
{validation_error}

CURRENT CODE:
```python
{content}
```

CRITICAL INSTRUCTIONS:
1. Fix both the validation error AND the original requirement
2. Apply the minimal necessary changes to resolve both issues
3. **PRESERVE ALL EXISTING CODE EXACTLY AS-IS** - only modify the specific lines needed for this fix
4. **IMPORTANT**: This code may already contain fixes from previous error patterns. DO NOT revert or change any code that is not directly related to the current error requirement.
5. If you see code that looks like it was recently fixed (e.g., using pd.concat instead of df.append, or ord=2 instead of ord="invalid"), KEEP those fixes intact.

Return ONLY the complete fixed Python code, no explanations, no markdown blocks. The code must be syntactically correct and address both the validation error and the original requirement."""
            
            try:
                # Call LLM to fix the code
                response = bedrock.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"temperature": 0.1, "maxTokens": 4096}
                )
                
                fixed_content = response['output']['message']['content'][0]['text']
                
                # Extract code from markdown if present
                if '```python' in fixed_content:
                    fixed_content = fixed_content.split('```python')[1].split('```')[0].strip()
                elif '```' in fixed_content:
                    fixed_content = fixed_content.split('```')[1].split('```')[0].strip()
                
                logger.info(f"   LLM returned fixed code ({len(fixed_content)} chars)")
                
                # VALIDATE the fixed code
                logger.info("   Validating fixed code...")
                
                # 1. Check syntax with AST
                try:
                    ast.parse(fixed_content)
                    logger.info("   Syntax validation passed")
                except SyntaxError as e:
                    validation_error = f"Syntax Error at line {e.lineno}: {e.msg}"
                    logger.warning(f"   Syntax validation failed: {validation_error}")
                    content = fixed_content  # Use this as base for next attempt
                    continue
            
                # 2. Check for common issues
                validation_issues = []
                
                # Check for incomplete code
                if fixed_content.count('(') != fixed_content.count(')'):
                    validation_issues.append("Unbalanced parentheses")
                if fixed_content.count('[') != fixed_content.count(']'):
                    validation_issues.append("Unbalanced brackets")
                if fixed_content.count('{') != fixed_content.count('}'):
                    validation_issues.append("Unbalanced braces")
                
                if validation_issues:
                    validation_error = "Code issues: " + ", ".join(validation_issues)
                    logger.warning(f"   Validation failed: {validation_error}")
                    content = fixed_content  # Use this as base for next attempt
                    continue
                
                # All validations passed!
                logger.info(f"   All validations passed")
                return fixed_content
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"   LLM call failed: {error_msg}")
                
                # Check if it's a retryable error
                is_retryable = any(keyword in error_msg.lower() for keyword in [
                    'serviceunavailableexception', 'throttlingexception', 'too many connections',
                    'service unavailable', 'throttling', 'rate limit'
                ])
                
                if is_retryable:
                    validation_error = f"LLM service error: {error_msg}"
                    # Try next validation attempt with same model, or next model
                    continue
                else:
                    # Non-retryable error, skip to next model
                    logger.error(f"   Non-retryable error, trying next model")
                    break
    
    # All models exhausted without success
    logger.error(f"   Failed to fix code after trying {len(models_to_try)} models")
    return f"# CUSTOM FIX FAILED: {custom_fix}\n# Error: All models exhausted\n{content}"


def _apply_generic_fix(content: str, fix_type: str) -> str:
    """Apply a generic fix based on the fix type description using LLM"""
    # Use the same LLM-based approach as custom fix
    return _apply_custom_fix(content, fix_type)
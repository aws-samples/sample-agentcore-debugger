"""
Library Agent - Package & Library Agent (Strands Tool)

Handles package/dependency related errors, library warnings, and deprecations.
Uses DuckDuckGo search to provide contextual analysis and recommendations.
Does NOT modify files, only generates structured output for UI display.
Implemented as a Strands tool using @tool decorator.
"""

import re
import logging
from typing import List, Dict, Any
from datetime import datetime

from strands import tool, Agent

# Setup package agent logging with queue handler for real-time display
logger = logging.getLogger('LibraryAgentTool')
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


@tool
def package_agent_tool(error_analysis: str) -> str:
    """
    Library Agent: Analyze package/dependency errors, library warnings, and generate structured output for UI.
    
    Specializes in:
    - Missing modules or import errors
    - Package version conflicts  
    - Requirements.txt issues
    - Dependency problems
    - Installation issues
    - Python library warnings and deprecations
    - Version compatibility issues
    - Security vulnerabilities in packages
    
    Args:
        error_analysis: String containing error analysis to process for package/library issues
        
    Returns:
        Structured analysis and recommendations that will be sent to UI for user review
    """
    logger.info("="*60)
    logger.info("LIBRARY AGENT ACTIVATION")
    logger.info("Specialization: Package/dependency/library analysis")
    logger.info("Tools: DuckDuckGo search for contextual recommendations")
    logger.info("Output: Structured recommendations for UI display")
    logger.info("="*60)
    
    # Log analysis details
    analysis_preview = error_analysis[:200] + "..." if len(error_analysis) > 200 else error_analysis
    logger.info(f"ERROR ANALYSIS RECEIVED:")
    logger.info(f"   Length: {len(error_analysis)} characters")
    logger.info(f"   Preview: {analysis_preview}")
    
    # Create specialized package agent with DuckDuckGo search capability
    logger.info("INITIALIZING LIBRARY AGENT:")
    logger.info("   🧠 System Prompt: Package/library specialist")
    logger.info("   Tools: DuckDuckGo search for contextual analysis")
    
    package_agent = Agent(
        system_prompt=_get_package_agent_system_prompt(),
        tools=[duckduckgo_search_tool]  # Add search capability for contextual recommendations
    )
    
    # Format query for package analysis
    formatted_query = f"""Analyze the following errors for package/dependency/library issues and generate structured output:

{error_analysis}

Use DuckDuckGo search to find relevant context about any errors, warnings, or deprecations mentioned.
Generate specific, actionable analysis and recommendations that will be sent to the UI for user review."""
    
    logger.info("FORMATTED QUERY PREPARED:")
    logger.info(f"   Query length: {len(formatted_query)} characters")
    logger.info("   Focus: Package/dependency/library issues only")
    
    try:
        logger.info("EXECUTING LIBRARY AGENT ANALYSIS...")
        
        # Log the prompt being sent to Library Agent
        logger.info("LIBRARY AGENT PROMPT:")
        logger.info("-" * 60)
        logger.info(formatted_query)
        logger.info("-" * 60)
        
        response = package_agent(formatted_query)
        
        logger.info("LIBRARY AGENT ANALYSIS COMPLETED:")
        logger.info(f"   Response type: {type(response)}")
        logger.info(f"   Response length: {len(str(response)) if response else 0} characters")
        logger.info("   Structured recommendations ready for UI display")
        
        return response
        
    except Exception as e:
        error_msg = f"Error in Library Agent: {str(e)}"
        logger.error("LIBRARY AGENT EXECUTION FAILED:")
        logger.error(f"   Exception Type: {type(e).__name__}")
        logger.error(f"   Exception Message: {str(e)}")
        logger.exception("   Full Exception Traceback:")
        
        return error_msg


def _get_package_agent_system_prompt() -> str:
    """Get the system prompt for the Package & Library Agent"""
    return """You are the Library Agent - specialized in analyzing package, dependency, and Python library issues.

**Your Expertise:**
- Missing modules and import errors
- Package version conflicts and compatibility
- Requirements.txt issues
- Dependency resolution problems
- Installation and upgrade issues
- Python library warnings and deprecations
- Security vulnerabilities in packages
- Version compatibility across Python versions
- Library migration recommendations

**Your Tools:**
- duckduckgo_search_tool: Search for current information about errors, warnings, and best practices

**Your Task:**
1. Analyze error messages for package/library-related issues
2. Use DuckDuckGo search to find current context about errors, warnings, or deprecations
3. Generate structured, actionable analysis and recommendations that will be sent to UI for user review

**Response Format:**
For each package/library issue found, provide:
1. **Issue Type**: (missing_package, version_conflict, deprecation_warning, security_issue, etc.)
2. **Severity**: (critical, high, medium, low)
3. **Description**: Clear explanation of the problem
4. **Context**: Information found through search about the issue
5. **Recommendation**: Specific action to take with current best practices
6. **Command**: Exact command to run (if applicable)
7. **Affected Files**: List of files that need updating (e.g., requirements.txt, setup.py)
8. **Additional Info**: Links or references for more information

**Example Response:**
```
PACKAGE & LIBRARY RECOMMENDATIONS:

1. Deprecation Warning: pandas.DataFrame.append
   - Severity: MEDIUM
   - Issue: pandas.DataFrame.append() is deprecated since pandas 1.4.0
   - Context: [Search results about pandas.concat() replacement]
   - Recommendation: Replace DataFrame.append() with pandas.concat() for better performance
   - Command: Update code to use pd.concat([df1, df2], ignore_index=True)
   - Affected Files: agent.py, data_processor.py
   - Additional Info: https://pandas.pydata.org/docs/user_guide/merging.html

2. Version Upgrade: torch 1.10.0 → >=1.13.0
   - Severity: MEDIUM
   - Issue: torch.linalg module not available in torch < 1.13
   - Context: [Search results about torch.linalg introduction]
   - Recommendation: Upgrade torch to >=1.13.0 OR use torch.norm() for backward compatibility
   - Command: pip install --upgrade "torch>=1.13.0"
   - Affected Files: requirements.txt
   - Additional Info: Check PyTorch migration guide

3. Security Vulnerability: requests < 2.31.0
   - Severity: HIGH
   - Issue: Known security vulnerability in requests library
   - Context: [Search results about CVE details]
   - Recommendation: Upgrade to requests >= 2.31.0 immediately
   - Command: pip install --upgrade "requests>=2.31.0"
   - Affected Files: requirements.txt
   - Additional Info: Check CHANGELOG for breaking changes
```

**IMPORTANT:** Always include "Affected Files" field to help Code Agent know which files to update!

**Search Strategy:**
- Search for specific error messages to find current solutions
- Look up deprecation warnings to find recommended replacements
- Check for security advisories on packages
- Find version compatibility information
- Search for migration guides when major version changes are needed

**CRITICAL RULES:**
1. You are ONLY providing recommendations and analysis - you do NOT apply fixes
2. NEVER say "Fixed", "Applied", "NOW FIXED", or claim that changes have been made
3. Use language like "Recommendation:", "Should be fixed by:", "Code Agent will fix:"
4. Your output is for the USER to review - fixes are applied separately by Code Agent
5. Focus on WHAT needs to be fixed and WHY, not claiming it's already done

Focus only on package/dependency/library issues. Generate analysis for UI display - do not modify files. Code fixes are Code Agent's responsibility."""


@tool
def duckduckgo_search_tool(query: str, max_results: int = 5) -> str:
    """
    Search DuckDuckGo for information about errors, warnings, and best practices.
    
    Args:
        query: Search query related to the error or warning
        max_results: Maximum number of results to return (default: 5)
    """
    logger.info(f"DUCKDUCKGO SEARCH TOOL ACTIVATED:")
    logger.info(f"   Query: {query}")
    logger.info(f"   Max Results: {max_results}")
    
    try:
        from ddgs import DDGS
        
        logger.info("📡 PERFORMING DUCKDUCKGO SEARCH...")
        
        # Perform search
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            logger.warning(f"No search results found for query: {query}")
            return f"No search results found for: {query}"
        
        logger.info(f"SEARCH COMPLETED: {len(results)} results found")
        
        # Format results
        formatted_results = f"Search results for '{query}':\n\n"
        
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            body = result.get('body', 'No description')
            href = result.get('href', 'No URL')
            
            formatted_results += f"{i}. **{title}**\n"
            formatted_results += f"   {body[:200]}{'...' if len(body) > 200 else ''}\n"
            formatted_results += f"   URL: {href}\n\n"
            
            logger.debug(f"   Result {i}: {title[:50]}...")
        
        logger.info("Search results formatted and ready")
        return formatted_results
        
    except ImportError:
        error_msg = "DuckDuckGo search library not available. Install with: pip install ddgs"
        logger.error(f"IMPORT ERROR: {error_msg}")
        
        # Provide fallback analysis based on query keywords
        fallback_analysis = f"""
Search not available, but here's general guidance for '{query}':

**Common Solutions:**
- Check package documentation and changelogs
- Review error messages for specific version requirements
- Use `pip list` to check current package versions
- Use `pip check` to identify dependency conflicts
- Check GitHub issues for similar problems
- Review package compatibility matrices

**Recommended Actions:**
1. Update packages: `pip install --upgrade package-name`
2. Check conflicts: `pip check`
3. Review requirements: `pip list --outdated`
4. Security audit: `pip-audit` (install with: pip install pip-audit)

Note: Install ddgs for enhanced contextual recommendations.
"""
        logger.info("Providing fallback analysis without search")
        return fallback_analysis
        
    except Exception as e:
        error_msg = f"Search error: {str(e)}"
        logger.error(f"SEARCH EXECUTION ERROR:")
        logger.error(f"   Exception Type: {type(e).__name__}")
        logger.error(f"   Exception Message: {str(e)}")
        
        # Provide fallback analysis
        fallback_analysis = f"""
Search encountered an error, but here's general guidance for '{query}':

**Troubleshooting Steps:**
- Check internet connectivity
- Verify package names and versions
- Review error logs for specific details
- Check package documentation
- Use offline resources like `pip show package-name`

**Common Commands:**
- `pip list` - Show installed packages
- `pip check` - Check for dependency issues
- `pip install --upgrade package-name` - Update packages
- `pip show package-name` - Show package details

Error details: {str(e)}
"""
        logger.info("Providing fallback analysis due to search error")
        return fallback_analysis
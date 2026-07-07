"""Multi-Agent System for AgentCore Auto-Fixing using Strands SDK

This package contains the Strands-based multi-agent system for automated error fixing:

- StrandsOrchestrator: Main orchestrator using Strands Agent with specialized agent tools
- package_agent_tool: Agent A tool for package/dependency/library issues → Generates output for UI display
- code_agent_tool: Agent B tool for ANY code-related issues → Automated fixes with development tools

Features:
- Agent A uses DuckDuckGo search to provide current context about errors, warnings, and deprecations
- Agent B uses AST analysis, Python REPL, file modification, and pytest tools for automated fixes
- Agent B can handle ANY type of code-related problem automatically
- Handles both package/library issues and all code-level problems
- Provides security and compatibility recommendations

Usage:
    from agents.strands_orchestrator import StrandsOrchestrator
    
    orchestrator = StrandsOrchestrator()
    result = orchestrator.orchestrate_fixes(ai_analysis, extracted_files)
"""

from .strands_orchestrator import StrandsOrchestrator
from .package_agent import package_agent_tool
from .code_agent import code_agent_tool

__all__ = ['StrandsOrchestrator', 'package_agent_tool', 'code_agent_tool']
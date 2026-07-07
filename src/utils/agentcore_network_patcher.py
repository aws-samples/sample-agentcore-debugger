"""
AgentCore Network Configuration Patcher

This module patches the AgentCore configuration to use host network mode
for local testing, allowing agent containers to communicate with the host.
"""
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def patch_agentcore_network_config(config_path: Path, network_mode: str = "HOST") -> bool:
    """
    Patch the AgentCore configuration file to use specified network mode.
    
    Args:
        config_path: Path to .bedrock_agentcore.yaml file
        network_mode: Network mode to use ("HOST" for host networking, "PUBLIC" for bridge)
        
    Returns:
        True if patched successfully, False otherwise
    """
    try:
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return False
        
        # Read the configuration
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Patch network configuration for all agents
        if 'agents' in config:
            for agent_name, agent_config in config['agents'].items():
                if 'aws' in agent_config and 'network_configuration' in agent_config['aws']:
                    old_mode = agent_config['aws']['network_configuration'].get('network_mode', 'PUBLIC')
                    agent_config['aws']['network_configuration']['network_mode'] = network_mode
                    logger.info(f"Patched {agent_name}: {old_mode} → {network_mode}")
        
        # Write back the configuration
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Successfully patched network config: {config_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to patch network config: {e}")
        return False


def find_and_patch_agentcore_configs(base_dir: Path, network_mode: str = "HOST") -> int:
    """
    Find all AgentCore configuration files in a directory and patch them.
    
    Args:
        base_dir: Base directory to search for config files
        network_mode: Network mode to use
        
    Returns:
        Number of files patched
    """
    patched_count = 0
    
    try:
        # Find all .bedrock_agentcore.yaml files
        for config_file in base_dir.rglob(".bedrock_agentcore.yaml"):
            if patch_agentcore_network_config(config_file, network_mode):
                patched_count += 1
        
        logger.info(f"Patched {patched_count} configuration file(s)")
        
    except Exception as e:
        logger.error(f"Error searching for config files: {e}")
    
    return patched_count


def patch_agent_workspace_config(agent_id: str, workspace_dir: Optional[Path] = None, network_mode: str = "HOST") -> bool:
    """
    Patch the AgentCore configuration for a specific agent workspace.
    
    Args:
        agent_id: Agent identifier
        workspace_dir: Workspace directory (defaults to agentcore_fixes)
        network_mode: Network mode to use
        
    Returns:
        True if patched successfully, False otherwise
    """
    if workspace_dir is None:
        workspace_dir = Path("agentcore_fixes")
    
    # Find the agent's workspace directory
    agent_dirs = list(workspace_dir.glob(f"agent_{agent_id.replace('-DEFAULT', '').replace('_', '-').lower()}*"))
    
    if not agent_dirs:
        logger.warning(f"No workspace found for agent: {agent_id}")
        return False
    
    # Use the most recent workspace
    agent_dir = sorted(agent_dirs, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    logger.info(f"📂 Found agent workspace: {agent_dir}")
    
    # Patch all config files in the workspace
    patched_count = find_and_patch_agentcore_configs(agent_dir, network_mode)
    
    return patched_count > 0

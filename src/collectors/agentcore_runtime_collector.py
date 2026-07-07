"""
AgentCore Runtime Collector for ECR Image Information
"""
import boto3
import logging
from typing import Dict, Any, Optional, List
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class AgentCoreRuntimeCollector:
    """Collects AgentCore Runtime information including ECR image details"""
    
    def __init__(self, region: str = 'us-east-1'):
        """Initialize AgentCore Runtime collector
        
        Args:
            region: AWS region for AgentCore client
        """
        self.region = region
        from src.core.retry_config import ADAPTIVE_RETRY
        self.client = boto3.client('bedrock-agentcore-control', region_name=region, config=ADAPTIVE_RETRY)
    
    def get_agent_runtime_details(self, agent_runtime_id: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get detailed information about an AgentCore Runtime including ECR image
        
        Args:
            agent_runtime_id: The unique identifier of the AgentCore Runtime
            version: Optional version number (defaults to latest)
            
        Returns:
            Dictionary containing runtime details including ECR image URI
        """
        try:
            # Validate agent runtime ID format
            if not agent_runtime_id or len(agent_runtime_id.split('-')) < 2:
                logger.warning(f"Invalid AgentCore Runtime ID format: {agent_runtime_id}")
                return None
            
            # Build request parameters
            params = {'agentRuntimeId': agent_runtime_id}
            if version:
                params['agentRuntimeVersion'] = version
            
            response = self.client.get_agent_runtime(**params)
            
            # Extract ECR image information
            runtime_details = {
                'agent_runtime_id': response.get('agentRuntimeId'),
                'agent_runtime_name': response.get('agentRuntimeName'),
                'agent_runtime_version': response.get('agentRuntimeVersion'),
                'agent_runtime_arn': response.get('agentRuntimeArn'),
                'description': response.get('description'),
                'status': response.get('status'),
                'created_at': response.get('createdAt'),
                'last_updated_at': response.get('lastUpdatedAt'),
                'role_arn': response.get('roleArn'),
                'environment_variables': response.get('environmentVariables', {}),
                'ecr_image_uri': None,
                'ecr_repository': None,
                'ecr_tag': None,
                'ecr_digest': None
            }
            
            # Extract ECR image details from artifact
            artifact = response.get('agentRuntimeArtifact', {})
            container_config = artifact.get('containerConfiguration', {})
            container_uri = container_config.get('containerUri')
            
            if container_uri:
                runtime_details['ecr_image_uri'] = container_uri
                
                # Parse ECR URI to extract components
                ecr_parts = self._parse_ecr_uri(container_uri)
                runtime_details.update(ecr_parts)
            
            return runtime_details
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.warning(f"AgentCore Runtime '{agent_runtime_id}' not found")
            elif error_code == 'AccessDeniedException':
                logger.error(f"Access denied when retrieving AgentCore Runtime '{agent_runtime_id}'")
            elif error_code == 'ValidationException':
                logger.error(f"Invalid AgentCore Runtime ID format: '{agent_runtime_id}'")
            else:
                logger.error(f"Error retrieving AgentCore Runtime '{agent_runtime_id}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving AgentCore Runtime {agent_runtime_id}: {e}")
            return None
    
    def list_available_agents(self) -> List[Dict[str, Any]]:
        """List all available AgentCore Runtimes in the account
        
        Returns:
            List of agent runtime summaries
        """
        try:
            response = self.client.list_agent_runtimes()
            return response.get('agentRuntimeSummaries', [])
        except Exception as e:
            print(f"Could not list available agents: {e}")
            return []
    
    def list_agent_runtime_versions(self, agent_runtime_id: str) -> List[Dict[str, Any]]:
        """List all versions of an AgentCore Runtime
        
        Args:
            agent_runtime_id: The unique identifier of the AgentCore Runtime
            
        Returns:
            List of version information dictionaries
        """
        try:
            response = self.client.list_agent_runtime_versions(agentRuntimeId=agent_runtime_id)
            
            versions = []
            for version_summary in response.get('agentRuntimeVersionSummaries', []):
                versions.append({
                    'version': version_summary.get('agentRuntimeVersion'),
                    'created_at': version_summary.get('createdAt'),
                    'last_updated_at': version_summary.get('lastUpdatedAt'),
                    'status': version_summary.get('status')
                })
            
            return sorted(versions, key=lambda x: x['version'], reverse=True)
            
        except ClientError as e:
            logger.error(f"Error listing versions for AgentCore Runtime {agent_runtime_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing versions for AgentCore Runtime {agent_runtime_id}: {e}")
            return []
    
    def _parse_ecr_uri(self, ecr_uri: str) -> Dict[str, str]:
        """Parse ECR URI to extract repository, tag, and digest information
        
        Args:
            ecr_uri: ECR container URI
            
        Returns:
            Dictionary with parsed ECR components
        """
        try:
            # ECR URI format: {account}.dkr.ecr.{region}.amazonaws.com/{repository}:{tag}@{digest}
            # or: {account}.dkr.ecr.{region}.amazonaws.com/{repository}:{tag}
            # or: {account}.dkr.ecr.{region}.amazonaws.com/{repository}@{digest}
            
            parts = ecr_uri.split('/')
            if len(parts) < 2:
                return {}
            
            registry = parts[0]  # {account}.dkr.ecr.{region}.amazonaws.com
            repository_part = '/'.join(parts[1:])  # {repository}:{tag}@{digest}
            
            # Extract account and region from registry
            registry_parts = registry.split('.')
            account_id = registry_parts[0] if len(registry_parts) > 0 else None
            region = registry_parts[3] if len(registry_parts) > 3 else None
            
            # Parse repository, tag, and digest
            repository = repository_part
            tag = None
            digest = None
            
            # Check for digest (@sha256:...)
            if '@' in repository_part:
                repository, digest = repository_part.split('@', 1)
            
            # Check for tag (:latest, :v1.0, etc.)
            if ':' in repository:
                repository, tag = repository.rsplit(':', 1)
                # If tag contains @, it means we have both tag and digest
                if '@' in tag:
                    tag, digest = tag.split('@', 1)
            
            return {
                'ecr_registry': registry,
                'ecr_account_id': account_id,
                'ecr_region': region,
                'ecr_repository': repository,
                'ecr_tag': tag,
                'ecr_digest': digest
            }
            
        except Exception as e:
            logger.warning(f"Could not parse ECR URI {ecr_uri}: {e}")
            return {}
    
    def get_ecr_image_details(self, ecr_uri: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about an ECR image
        
        Args:
            ecr_uri: ECR container URI
            
        Returns:
            Dictionary containing ECR image details
        """
        try:
            ecr_parts = self._parse_ecr_uri(ecr_uri)
            if not ecr_parts.get('ecr_repository'):
                return None
            
            # Create ECR client for the appropriate region
            ecr_region = ecr_parts.get('ecr_region', self.region)
            ecr_client = boto3.client('ecr', region_name=ecr_region)
            
            # Get image details
            repository_name = ecr_parts['ecr_repository']
            
            # Prepare image identifier
            image_ids = []
            if ecr_parts.get('ecr_tag'):
                image_ids.append({'imageTag': ecr_parts['ecr_tag']})
            if ecr_parts.get('ecr_digest'):
                image_ids.append({'imageDigest': ecr_parts['ecr_digest']})
            
            if not image_ids:
                # If no tag or digest, get latest
                image_ids = [{'imageTag': 'latest'}]
            
            response = ecr_client.describe_images(
                repositoryName=repository_name,
                imageIds=image_ids
            )
            
            images = response.get('imageDetails', [])
            if not images:
                return None
            
            # Get the first (most recent) image
            image = images[0]
            
            return {
                'repository_name': repository_name,
                'registry_id': image.get('registryId'),
                'image_digest': image.get('imageDigest'),
                'image_tags': image.get('imageTags', []),
                'image_size_bytes': image.get('imageSizeInBytes'),
                'image_pushed_at': image.get('imagePushedAt'),
                'image_scan_status': image.get('imageScanFindingsSummary', {}).get('findingCounts', {}),
                'artifact_media_type': image.get('artifactMediaType'),
                'image_manifest_media_type': image.get('imageManifestMediaType')
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'RepositoryNotFoundException':
                logger.warning(f"ECR repository not found: {ecr_parts.get('ecr_repository', 'unknown')}")
            elif error_code == 'ImageNotFoundException':
                logger.warning(f"ECR image not found in repository: {ecr_parts.get('ecr_repository', 'unknown')}")
            else:
                logger.error(f"Error retrieving ECR image details: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving ECR image details: {e}")
            return None
"""
Error Analysis Engine for AgentCore Debugger Assistant
"""
import re
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for grouping"""
    PERFORMANCE = "performance"
    SECURITY = "security"
    CAPACITY = "capacity"
    INPUT = "input"
    SYSTEM = "system"
    INFRASTRUCTURE = "infrastructure"
    GENERAL = "general"


@dataclass
class ErrorClassification:
    """Error classification result"""
    error_type: str
    severity: ErrorSeverity
    category: ErrorCategory
    confidence: float
    patterns_matched: List[str]


@dataclass
class ErrorContext:
    """Error context information"""
    trace_id: Optional[str]
    span_id: Optional[str]
    session_id: Optional[str]
    agent_id: Optional[str]
    service_name: Optional[str]
    timestamp: datetime
    related_errors: List[str]


class ErrorAnalyzer:
    """Analyzes and classifies errors from AgentCore systems"""
    
    def __init__(self):
        """Initialize error analyzer with pattern definitions"""
        self.error_patterns = {
            'timeout': {
                'patterns': [
                    r'timeout',
                    r'timed out',
                    r'deadline exceeded',
                    r'request timeout',
                    r'connection timeout',
                    r'read timeout',
                    r'operation timeout'
                ],
                'severity': ErrorSeverity.MEDIUM,
                'category': ErrorCategory.PERFORMANCE
            },
            'authentication': {
                'patterns': [
                    r'unauthorized',
                    r'forbidden',
                    r'invalid token',
                    r'authentication failed',
                    r'access denied',
                    r'invalid credentials',
                    r'token expired',
                    r'invalid api key'
                ],
                'severity': ErrorSeverity.HIGH,
                'category': ErrorCategory.SECURITY
            },
            'rate_limit': {
                'patterns': [
                    r'rate limit',
                    r'throttled',
                    r'quota exceeded',
                    r'too many requests',
                    r'request limit exceeded',
                    r'api limit reached'
                ],
                'severity': ErrorSeverity.MEDIUM,
                'category': ErrorCategory.CAPACITY
            },
            'validation': {
                'patterns': [
                    r'validation error',
                    r'invalid input',
                    r'bad request',
                    r'malformed request',
                    r'invalid parameter',
                    r'missing required field',
                    r'schema validation failed'
                ],
                'severity': ErrorSeverity.LOW,
                'category': ErrorCategory.INPUT
            },
            'service_error': {
                'patterns': [
                    r'internal server error',
                    r'service unavailable',
                    r'server error',
                    r'service down',
                    r'backend error',
                    r'upstream error'
                ],
                'severity': ErrorSeverity.HIGH,
                'category': ErrorCategory.SYSTEM
            },
            'network': {
                'patterns': [
                    r'connection refused',
                    r'network error',
                    r'dns resolution',
                    r'host unreachable',
                    r'connection reset',
                    r'network timeout',
                    r'socket error'
                ],
                'severity': ErrorSeverity.MEDIUM,
                'category': ErrorCategory.INFRASTRUCTURE
            },
            'permission': {
                'patterns': [
                    r'permission denied',
                    r'insufficient permissions',
                    r'access forbidden',
                    r'not authorized',
                    r'role not allowed',
                    r'policy violation'
                ],
                'severity': ErrorSeverity.HIGH,
                'category': ErrorCategory.SECURITY
            },
            'resource_exhaustion': {
                'patterns': [
                    r'out of memory',
                    r'memory limit exceeded',
                    r'disk full',
                    r'no space left',
                    r'resource exhausted',
                    r'cpu limit exceeded'
                ],
                'severity': ErrorSeverity.CRITICAL,
                'category': ErrorCategory.CAPACITY
            },
            'bedrock_specific': {
                'patterns': [
                    r'model not found',
                    r'inference error',
                    r'model timeout',
                    r'bedrock throttling',
                    r'foundation model error',
                    r'agent execution failed'
                ],
                'severity': ErrorSeverity.HIGH,
                'category': ErrorCategory.SYSTEM
            },
            'lambda_specific': {
                'patterns': [
                    r'lambda timeout',
                    r'function error',
                    r'cold start timeout',
                    r'lambda throttling',
                    r'execution role error'
                ],
                'severity': ErrorSeverity.MEDIUM,
                'category': ErrorCategory.SYSTEM
            }
        }
        
        # Resolution suggestions for each error type
        self.resolution_suggestions = {
            'timeout': [
                'Increase timeout configuration in agent settings',
                'Check network connectivity and latency',
                'Optimize agent processing logic to reduce execution time',
                'Consider implementing retry logic with exponential backoff',
                'Monitor system resources (CPU, memory) for bottlenecks'
            ],
            'authentication': [
                'Verify API credentials and tokens are valid',
                'Check token expiration and refresh if needed',
                'Review IAM permissions and policies',
                'Ensure correct authentication headers are being sent',
                'Validate service account configurations'
            ],
            'rate_limit': [
                'Implement exponential backoff retry strategy',
                'Reduce request frequency or batch requests',
                'Request quota increase from service provider',
                'Implement request queuing and throttling',
                'Consider using multiple API keys or accounts'
            ],
            'validation': [
                'Validate input parameters before sending requests',
                'Check data format requirements in API documentation',
                'Implement input sanitization and validation',
                'Review schema requirements for the service',
                'Add proper error handling for malformed inputs'
            ],
            'service_error': [
                'Check service health status and availability',
                'Review recent deployments or configuration changes',
                'Monitor service dependencies and upstream services',
                'Contact support if errors persist',
                'Implement circuit breaker pattern for resilience'
            ],
            'network': [
                'Check network connectivity and DNS resolution',
                'Verify firewall and security group settings',
                'Test connectivity from different network locations',
                'Review VPC and subnet configurations',
                'Monitor network latency and packet loss'
            ],
            'permission': [
                'Review and update IAM roles and policies',
                'Check resource-based policies and permissions',
                'Verify service account has necessary permissions',
                'Review cross-account access configurations',
                'Audit recent permission changes'
            ],
            'resource_exhaustion': [
                'Increase memory or CPU limits for the service',
                'Optimize code to reduce resource consumption',
                'Implement resource monitoring and alerting',
                'Consider horizontal scaling or load balancing',
                'Review and clean up unused resources'
            ],
            'bedrock_specific': [
                'Verify model availability and access permissions',
                'Check Bedrock service limits and quotas',
                'Review agent configuration and prompt templates',
                'Monitor Bedrock service health status',
                'Consider alternative models or fallback strategies'
            ],
            'lambda_specific': [
                'Increase Lambda function timeout and memory',
                'Optimize function code for better performance',
                'Implement proper error handling and retries',
                'Monitor Lambda concurrency limits',
                'Consider provisioned concurrency for critical functions'
            ]
        }
    
    def classify_error(self, error_message: str, stack_trace: Optional[str] = None,
                      context: Optional[ErrorContext] = None) -> ErrorClassification:
        """Classify error based on message, stack trace, and context
        
        Args:
            error_message: The error message to analyze
            stack_trace: Optional stack trace information
            context: Optional error context information
            
        Returns:
            ErrorClassification with type, severity, and category
        """
        error_message_lower = error_message.lower()
        stack_trace_lower = (stack_trace or '').lower()
        combined_text = f"{error_message_lower} {stack_trace_lower}"
        
        best_match = None
        best_confidence = 0.0
        matched_patterns = []
        
        # Check each error type pattern
        for error_type, config in self.error_patterns.items():
            patterns = config['patterns']
            matches = 0
            matched_pattern_list = []
            
            for pattern in patterns:
                if re.search(pattern, combined_text, re.IGNORECASE):
                    matches += 1
                    matched_pattern_list.append(pattern)
            
            if matches > 0:
                # Calculate confidence based on number of pattern matches
                confidence = min(matches / len(patterns), 1.0)
                
                # Boost confidence for exact matches
                if any(pattern in error_message_lower for pattern in patterns):
                    confidence += 0.2
                
                # Consider context for additional confidence
                if context:
                    confidence = self._adjust_confidence_with_context(
                        confidence, error_type, context
                    )
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = error_type
                    matched_patterns = matched_pattern_list
        
        # Default classification if no patterns match
        if not best_match:
            best_match = 'unknown'
            best_confidence = 0.1
            matched_patterns = []
        
        error_config = self.error_patterns.get(best_match, {
            'severity': ErrorSeverity.MEDIUM,
            'category': ErrorCategory.GENERAL
        })
        
        return ErrorClassification(
            error_type=best_match,
            severity=error_config['severity'],
            category=error_config['category'],
            confidence=best_confidence,
            patterns_matched=matched_patterns
        )
    
    def _adjust_confidence_with_context(self, base_confidence: float, 
                                      error_type: str, context: ErrorContext) -> float:
        """Adjust confidence based on error context"""
        adjusted_confidence = base_confidence
        
        # Boost confidence for service-specific errors
        if context.service_name:
            service_lower = context.service_name.lower()
            
            if error_type == 'bedrock_specific' and 'bedrock' in service_lower:
                adjusted_confidence += 0.3
            elif error_type == 'lambda_specific' and 'lambda' in service_lower:
                adjusted_confidence += 0.3
        
        # Consider error frequency (if we have related errors)
        if context.related_errors and len(context.related_errors) > 1:
            # Multiple related errors suggest systematic issue
            adjusted_confidence += 0.1
        
        return min(adjusted_confidence, 1.0)
    
    def suggest_resolution(self, error_classification: ErrorClassification,
                          context: Optional[ErrorContext] = None) -> List[str]:
        """Suggest potential resolutions based on error classification
        
        Args:
            error_classification: The classified error
            context: Optional error context for more specific suggestions
            
        Returns:
            List of resolution suggestions
        """
        base_suggestions = self.resolution_suggestions.get(
            error_classification.error_type,
            ['Review error details and logs for more specific guidance']
        )
        
        # Add context-specific suggestions
        contextual_suggestions = []
        
        if context:
            # Add service-specific suggestions
            if context.service_name:
                service_suggestions = self._get_service_specific_suggestions(
                    context.service_name, error_classification.error_type
                )
                contextual_suggestions.extend(service_suggestions)
            
            # Add frequency-based suggestions
            if context.related_errors and len(context.related_errors) > 3:
                contextual_suggestions.append(
                    'This appears to be a recurring issue. Consider implementing '
                    'monitoring and alerting for this error pattern.'
                )
        
        # Combine and deduplicate suggestions
        all_suggestions = base_suggestions + contextual_suggestions
        return list(dict.fromkeys(all_suggestions))  # Remove duplicates while preserving order
    
    def _get_service_specific_suggestions(self, service_name: str, 
                                        error_type: str) -> List[str]:
        """Get service-specific resolution suggestions"""
        service_lower = service_name.lower()
        suggestions = []
        
        if 'bedrock' in service_lower:
            if error_type == 'timeout':
                suggestions.append('Consider using streaming responses for long-running Bedrock operations')
            elif error_type == 'rate_limit':
                suggestions.append('Review Bedrock service quotas and request increases if needed')
        
        elif 'lambda' in service_lower:
            if error_type == 'timeout':
                suggestions.append('Increase Lambda function timeout or optimize cold start performance')
            elif error_type == 'resource_exhaustion':
                suggestions.append('Increase Lambda memory allocation or optimize memory usage')
        
        elif 'strands' in service_lower:
            if error_type == 'validation':
                suggestions.append('Check Strands agent tool definitions and input schemas')
            elif error_type == 'service_error':
                suggestions.append('Review Strands agent configuration and model settings')
        
        return suggestions
    
    def analyze_error_trends(self, errors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trends in error data
        
        Args:
            errors: List of error events with timestamps and classifications
            
        Returns:
            Dictionary containing trend analysis results
        """
        if not errors:
            return {}
        
        # Group errors by type and time
        error_counts = {}
        hourly_counts = {}
        service_errors = {}
        
        for error in errors:
            # Count by error type
            error_type = error.get('error_type', 'unknown')
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
            
            # Count by hour
            timestamp = error.get('timestamp')
            if timestamp:
                hour_key = timestamp.strftime('%Y-%m-%d %H:00')
                hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1
            
            # Count by service
            service = error.get('service_name', 'unknown')
            service_errors[service] = service_errors.get(service, 0) + 1
        
        # Calculate trends
        total_errors = len(errors)
        most_common_error = max(error_counts.items(), key=lambda x: x[1]) if error_counts else ('none', 0)
        most_affected_service = max(service_errors.items(), key=lambda x: x[1]) if service_errors else ('none', 0)
        
        # Calculate error rate trend (simple linear trend)
        sorted_hours = sorted(hourly_counts.items())
        if len(sorted_hours) > 1:
            first_half = sorted_hours[:len(sorted_hours)//2]
            second_half = sorted_hours[len(sorted_hours)//2:]
            
            first_avg = sum(count for _, count in first_half) / len(first_half)
            second_avg = sum(count for _, count in second_half) / len(second_half)
            
            trend = 'increasing' if second_avg > first_avg else 'decreasing'
            trend_magnitude = abs(second_avg - first_avg) / max(first_avg, 1)
        else:
            trend = 'stable'
            trend_magnitude = 0.0
        
        return {
            'total_errors': total_errors,
            'error_type_distribution': error_counts,
            'hourly_distribution': hourly_counts,
            'service_distribution': service_errors,
            'most_common_error': most_common_error,
            'most_affected_service': most_affected_service,
            'trend': trend,
            'trend_magnitude': trend_magnitude,
            'analysis_timestamp': datetime.now()
        }
    
    def generate_error_report(self, errors: List[Dict[str, Any]]) -> str:
        """Generate a human-readable error analysis report
        
        Args:
            errors: List of error events
            
        Returns:
            Formatted error analysis report
        """
        if not errors:
            return "No errors found in the specified time period."
        
        trends = self.analyze_error_trends(errors)
        
        report = f"""
# Error Analysis Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary
- **Total Errors**: {trends['total_errors']}
- **Most Common Error**: {trends['most_common_error'][0]} ({trends['most_common_error'][1]} occurrences)
- **Most Affected Service**: {trends['most_affected_service'][0]} ({trends['most_affected_service'][1]} errors)
- **Trend**: {trends['trend'].title()} (magnitude: {trends['trend_magnitude']:.2f})

## Error Type Distribution
"""
        
        for error_type, count in sorted(trends['error_type_distribution'].items(), 
                                      key=lambda x: x[1], reverse=True):
            percentage = (count / trends['total_errors']) * 100
            report += f"- **{error_type.title()}**: {count} ({percentage:.1f}%)\n"
        
        report += "\n## Service Distribution\n"
        for service, count in sorted(trends['service_distribution'].items(), 
                                   key=lambda x: x[1], reverse=True):
            percentage = (count / trends['total_errors']) * 100
            report += f"- **{service}**: {count} ({percentage:.1f}%)\n"
        
        # Add recommendations based on trends
        report += "\n## Recommendations\n"
        
        if trends['trend'] == 'increasing':
            report += "- Error rate is increasing. Investigate recent changes and monitor closely.\n"
        
        most_common_type = trends['most_common_error'][0]
        if most_common_type != 'none':
            suggestions = self.resolution_suggestions.get(most_common_type, [])
            if suggestions:
                report += f"- Focus on resolving **{most_common_type}** errors:\n"
                for suggestion in suggestions[:3]:  # Top 3 suggestions
                    report += f"  - {suggestion}\n"
        
        return report
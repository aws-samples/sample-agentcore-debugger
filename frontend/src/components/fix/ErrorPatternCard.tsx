/**
 * Error Pattern Card Component
 * Displays an error pattern with:
 * - Error details (type, message, count, timestamps)
 * - Classification (package_only, code_fix_required, mixed)
 * - Fix status and actions
 * 
 * Classification determines the workflow:
 * - package_only: Library Agent only (fast, no code download)
 * - code_fix_required: Code Agent only (needs ECR download)
 * - mixed: User chooses - library, code, both, or skip
 */
import React from 'react';
import {
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Chip,
  Box,
  Checkbox,
  Collapse,
  IconButton,
  Alert,
  Tooltip,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  HourglassEmpty as PendingIcon,
  Inventory as PackageIcon,
  Code as CodeIcon,
  MergeType as MixedIcon,
  Info as InfoIcon,
} from '@mui/icons-material';
import { ErrorCluster, FixResult } from '../../api/fix';

interface ErrorPatternCardProps {
  cluster: ErrorCluster;
  selected: boolean;
  onToggle: () => void;
  onFix: () => void;
  fixResult?: FixResult;
  isFixing: boolean;
}

// Classification info for display
const classificationInfo: Record<string, { label: string; description: string; icon: React.ReactNode; color: 'info' | 'warning' | 'secondary' }> = {
  package_only: {
    label: 'Package Only',
    description: 'This error can be fixed by updating packages/dependencies. Fast fix, no code download needed.',
    icon: <PackageIcon fontSize="small" />,
    color: 'info',
  },
  code_fix_required: {
    label: 'Code Fix Required',
    description: 'This error requires code changes. Will download code from ECR and apply fixes.',
    icon: <CodeIcon fontSize="small" />,
    color: 'warning',
  },
  mixed: {
    label: 'Mixed Issue',
    description: 'This error may need both package updates AND code changes. You will choose the approach.',
    icon: <MixedIcon fontSize="small" />,
    color: 'secondary',
  },
};

// Helper to safely get classification type
const getClassificationType = (fixResult?: FixResult): string | undefined => {
  if (!fixResult) return undefined;
  const type = fixResult.error_classification?.type;
  if (typeof type === 'string') return type;
  return fixResult.workflow_type;
};

// Helper to get class info
const getClassInfo = (classificationType: string | undefined) => {
  if (!classificationType || !(classificationType in classificationInfo)) return undefined;
  return classificationInfo[classificationType];
};

export const ErrorPatternCard: React.FC<ErrorPatternCardProps> = ({
  cluster,
  selected,
  onToggle,
  onFix,
  fixResult,
  isFixing,
}) => {
  const [expanded, setExpanded] = React.useState(false);

  // Get classification from fix result if available
  const classificationType = getClassificationType(fixResult);
  const classInfo = getClassInfo(classificationType);

  const getStatusChip = () => {
    if (fixResult) {
      switch (fixResult.status) {
        case 'fixed':
          return <Chip icon={<CheckCircleIcon />} label="Fixed" color="success" size="small" />;
        case 'failed':
          return <Chip icon={<ErrorIcon />} label="Failed" color="error" size="small" />;
        case 'awaiting_choice':
          return <Chip icon={<PendingIcon />} label="Choose Approach" color="warning" size="small" />;
        case 'in_progress':
          return <Chip icon={<PendingIcon />} label="In Progress" color="info" size="small" />;
        case 'analyzing':
          return <Chip icon={<PendingIcon />} label="Analyzing..." color="info" size="small" />;
        default:
          return <Chip label={fixResult.status} size="small" />;
      }
    }
    return <Chip label={`${cluster.count} occurrences`} size="small" variant="outlined" />;
  };

  const getErrorTypeColor = (type: string): 'error' | 'warning' | 'info' | 'default' => {
    const errorTypes = ['rate_limit', 'timeout', 'authentication', 'permission'];
    const warningTypes = ['validation', 'configuration', 'deprecation'];
    
    if (errorTypes.includes(type)) return 'error';
    if (warningTypes.includes(type)) return 'warning';
    return 'default';
  };

  return (
    <Card
      variant="outlined"
      sx={{
        borderColor: selected ? 'primary.main' : 'divider',
        borderWidth: selected ? 2 : 1,
      }}
    >
      <CardContent>
        <Box display="flex" alignItems="flex-start" gap={2}>
          <Checkbox checked={selected} onChange={onToggle} disabled={fixResult?.status === 'fixed'} />
          
          <Box flex={1}>
            {/* Error Type and Status */}
            <Box display="flex" alignItems="center" gap={1} mb={1} flexWrap="wrap">
              <Chip
                label={cluster.error_type}
                size="small"
                color={getErrorTypeColor(cluster.error_type)}
              />
              {getStatusChip()}
              
              {/* Classification Badge - shown when available */}
              {classInfo ? (
                <Tooltip title={classInfo.description} arrow>
                  <Chip
                    icon={classInfo.icon as React.ReactElement}
                    label={classInfo.label}
                    size="small"
                    color={classInfo.color}
                    variant="outlined"
                  />
                </Tooltip>
              ) : null}
            </Box>

            {/* Error Message */}
            <Typography variant="body1" sx={{ fontFamily: 'monospace', mb: 1, fontSize: 13 }}>
              {cluster.error_message}
            </Typography>

            {/* Timestamps */}
            {(cluster.first_seen || cluster.last_seen) && (
              <Box display="flex" gap={2} flexWrap="wrap">
                {cluster.first_seen && (
                  <Typography variant="caption" color="text.secondary">
                    First seen: {new Date(cluster.first_seen).toLocaleString()}
                  </Typography>
                )}
                {cluster.last_seen && (
                  <Typography variant="caption" color="text.secondary">
                    Last seen: {new Date(cluster.last_seen).toLocaleString()}
                  </Typography>
                )}
              </Box>
            )}

            {/* Affected Files */}
            {cluster.affected_files.length > 0 && (
              <Box mt={1}>
                <Typography variant="caption" color="text.secondary">
                  Affected files:
                </Typography>
                <Box display="flex" gap={0.5} flexWrap="wrap" mt={0.5}>
                  {cluster.affected_files.slice(0, 3).map((file) => (
                    <Chip key={file} label={file.split('/').pop()} size="small" variant="outlined" />
                  ))}
                  {cluster.affected_files.length > 3 && (
                    <Chip label={`+${cluster.affected_files.length - 3} more`} size="small" />
                  )}
                </Box>
              </Box>
            )}

            {/* Classification Info Alert - shown for mixed when awaiting choice */}
            {fixResult?.status === 'awaiting_choice' && classificationType === 'mixed' && (
              <Alert severity="info" sx={{ mt: 2, py: 0.5 }} icon={<InfoIcon />}>
                <Typography variant="caption">
                  <strong>Mixed Issue Detected:</strong> This error can be fixed by updating packages, 
                  modifying code, or both. Click "Choose Approach" to select your preferred fix method.
                </Typography>
              </Alert>
            )}

            {/* Classification Reasoning - if available */}
            {typeof fixResult?.error_classification?.reasoning === 'string' && fixResult.error_classification.reasoning && (
              <Box mt={1} p={1} bgcolor="grey.50" borderRadius={1}>
                <Typography variant="caption" color="text.secondary">
                  <strong>AI Analysis:</strong> {fixResult.error_classification.reasoning}
                </Typography>
              </Box>
            )}
          </Box>

          <IconButton
            onClick={() => setExpanded(!expanded)}
            sx={{
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.3s',
            }}
          >
            <ExpandMoreIcon />
          </IconButton>
        </Box>

        {/* Expanded Details */}
        <Collapse in={expanded}>
          <Box mt={2} p={2} bgcolor="grey.50" borderRadius={1}>
            {/* Stack Trace */}
            {cluster.stack_trace && (
              <Box mb={2}>
                <Typography variant="subtitle2" gutterBottom>
                  Stack Trace
                </Typography>
                <pre
                  style={{
                    margin: 0,
                    padding: '8px',
                    backgroundColor: '#1e1e1e',
                    color: '#d4d4d4',
                    borderRadius: '4px',
                    overflow: 'auto',
                    maxHeight: '200px',
                    fontSize: '12px',
                  }}
                >
                  {cluster.stack_trace}
                </pre>
              </Box>
            )}

            {/* Sample Events */}
            {cluster.sample_events.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>
                  Sample Events ({cluster.sample_events.length})
                </Typography>
                {cluster.sample_events.map((event, idx) => (
                  <Box key={idx} mb={1} p={1} bgcolor="white" borderRadius={1}>
                    <Typography variant="caption" color="text.secondary">
                      {event.timestamp ? new Date(event.timestamp).toLocaleString() : 'Unknown time'}
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {event.message}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}

            {/* Library Agent Output - if available */}
            {fixResult?.library_agent_output && (
              <Box mt={2}>
                <Typography variant="subtitle2" gutterBottom>
                  Library Agent Analysis
                </Typography>
                <Box p={1} bgcolor="info.50" borderRadius={1}>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>
                    {fixResult.library_agent_output}
                  </Typography>
                </Box>
              </Box>
            )}

            {/* Package Recommendations - if available */}
            {fixResult?.package_recommendations && fixResult.package_recommendations.length > 0 && (
              <Box mt={2}>
                <Typography variant="subtitle2" gutterBottom>
                  Package Recommendations
                </Typography>
                {fixResult.package_recommendations.map((rec, idx) => (
                  <Box key={idx} p={1} mb={1} bgcolor="white" borderRadius={1} border="1px solid" borderColor="divider">
                    <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                      {typeof rec === 'string' ? rec : JSON.stringify(rec, null, 2)}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        </Collapse>
      </CardContent>

      <CardActions sx={{ justifyContent: 'flex-end', px: 2, pb: 2 }}>
        <Button
          variant="contained"
          size="small"
          onClick={onFix}
          disabled={isFixing || fixResult?.status === 'fixed'}
        >
          {fixResult?.status === 'fixed' 
            ? 'Fixed' 
            : fixResult?.status === 'awaiting_choice'
              ? 'Choose Approach'
              : isFixing 
                ? 'Analyzing...' 
                : 'Fix This Pattern'}
        </Button>
      </CardActions>
    </Card>
  );
};

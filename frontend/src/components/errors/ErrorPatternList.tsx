/**
 * Error pattern list component
 */
import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  Alert,
  AlertTitle,
  Divider,
} from '@mui/material';
import { Lightbulb, Schedule, TrendingUp } from '@mui/icons-material';
import { ErrorPattern } from '../../types/error';

interface ErrorPatternListProps {
  patterns: ErrorPattern[];
}

export const ErrorPatternList: React.FC<ErrorPatternListProps> = ({ patterns }) => {
  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  if (!patterns || patterns.length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Error Patterns
          </Typography>
          <Typography variant="body2" color="textSecondary">
            No recurring error patterns detected
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Error Patterns ({patterns.length})
        </Typography>
        <Typography variant="body2" color="textSecondary" gutterBottom>
          Recurring issues detected in your agents
        </Typography>

        <Box mt={2}>
          {patterns.map((pattern, index) => (
            <Box key={pattern.pattern_id} mb={3}>
              {index > 0 && <Divider sx={{ mb: 2 }} />}
              
              <Box display="flex" alignItems="center" gap={1} mb={1}>
                <Chip
                  label={pattern.error_type.replace('_', ' ')}
                  color="error"
                  size="small"
                  sx={{ textTransform: 'capitalize' }}
                />
                <Box display="flex" alignItems="center" gap={0.5}>
                  <TrendingUp fontSize="small" color="action" />
                  <Typography variant="body2" fontWeight="bold">
                    {pattern.frequency} occurrences
                  </Typography>
                </Box>
              </Box>

              <Typography variant="body2" sx={{ mb: 1, wordBreak: 'break-word' }}>
                {pattern.sample_message}
              </Typography>

              <Box display="flex" gap={2} mb={1} flexWrap="wrap">
                <Box display="flex" alignItems="center" gap={0.5}>
                  <Schedule fontSize="small" color="action" />
                  <Typography variant="caption" color="textSecondary">
                    First: {formatDate(pattern.first_seen)}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={0.5}>
                  <Schedule fontSize="small" color="action" />
                  <Typography variant="caption" color="textSecondary">
                    Last: {formatDate(pattern.last_seen)}
                  </Typography>
                </Box>
              </Box>

              {pattern.affected_agents.length > 0 && (
                <Box mb={1}>
                  <Typography variant="caption" color="textSecondary">
                    Affected agents:
                  </Typography>
                  <Box display="flex" gap={0.5} flexWrap="wrap" mt={0.5}>
                    {pattern.affected_agents.slice(0, 5).map((agent) => (
                      <Chip key={agent} label={agent} size="small" variant="outlined" />
                    ))}
                    {pattern.affected_agents.length > 5 && (
                      <Chip
                        label={`+${pattern.affected_agents.length - 5} more`}
                        size="small"
                        variant="outlined"
                      />
                    )}
                  </Box>
                </Box>
              )}

              {pattern.suggested_fix && (
                <Alert severity="info" icon={<Lightbulb />} sx={{ mt: 1 }}>
                  <AlertTitle>Suggested Fix</AlertTitle>
                  {pattern.suggested_fix}
                </Alert>
              )}
            </Box>
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

/**
 * Error type distribution component
 */
import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  LinearProgress,
  Chip,
  Tooltip,
} from '@mui/material';
import { ErrorSummary } from '../../types/error';

interface ErrorTypeChartProps {
  errorsByType: ErrorSummary[];
}

const getErrorTypeColor = (errorType: string): string => {
  const colors: Record<string, string> = {
    rate_limit: '#ff9800',
    timeout: '#f44336',
    authentication: '#e91e63',
    permission: '#9c27b0',
    validation: '#2196f3',
    service_error: '#f44336',
    network: '#ff5722',
    resource_not_found: '#607d8b',
    configuration: '#795548',
    memory: '#d32f2f',
    database: '#3f51b5',
    generic_error: '#9e9e9e',
    unknown: '#bdbdbd',
  };
  return colors[errorType] || '#9e9e9e';
};

export const ErrorTypeChart: React.FC<ErrorTypeChartProps> = ({ errorsByType }) => {
  if (!errorsByType || errorsByType.length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Errors by Type
          </Typography>
          <Typography variant="body2" color="textSecondary">
            No errors found in the selected time range
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Errors by Type
        </Typography>

        <Box mt={2}>
          {errorsByType.map((error) => (
            <Box key={error.error_type} mb={2}>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={0.5}>
                <Tooltip title={error.sample_messages[0] || 'No sample message'}>
                  <Chip
                    label={error.error_type.replace('_', ' ')}
                    size="small"
                    sx={{
                      backgroundColor: getErrorTypeColor(error.error_type),
                      color: 'white',
                      textTransform: 'capitalize',
                    }}
                  />
                </Tooltip>
                <Typography variant="body2">
                  {error.count} ({error.percentage}%)
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={error.percentage}
                sx={{
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: '#e0e0e0',
                  '& .MuiLinearProgress-bar': {
                    backgroundColor: getErrorTypeColor(error.error_type),
                    borderRadius: 4,
                  },
                }}
              />
            </Box>
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

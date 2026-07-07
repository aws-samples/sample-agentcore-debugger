/**
 * Error summary card component
 */
import React from 'react';
import { Card, CardContent, Typography, Box, Chip, LinearProgress } from '@mui/material';
import { Error, Warning, TrendingUp } from '@mui/icons-material';

interface ErrorSummaryCardProps {
  totalErrors: number;
  totalWarnings: number;
  errorRate: number;
  timeRange: string;
}

export const ErrorSummaryCard: React.FC<ErrorSummaryCardProps> = ({
  totalErrors,
  totalWarnings,
  errorRate,
  timeRange,
}) => {
  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Error Summary
        </Typography>
        <Typography variant="body2" color="textSecondary" gutterBottom>
          {timeRange}
        </Typography>

        <Box display="flex" gap={2} mt={2} flexWrap="wrap">
          <Box flex={1} minWidth={120}>
            <Box display="flex" alignItems="center" gap={1}>
              <Error color="error" />
              <Typography variant="h4" color="error.main">
                {totalErrors}
              </Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Errors
            </Typography>
          </Box>

          <Box flex={1} minWidth={120}>
            <Box display="flex" alignItems="center" gap={1}>
              <Warning color="warning" />
              <Typography variant="h4" color="warning.main">
                {totalWarnings}
              </Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Warnings
            </Typography>
          </Box>

          <Box flex={1} minWidth={120}>
            <Box display="flex" alignItems="center" gap={1}>
              <TrendingUp color="info" />
              <Typography variant="h4" color="info.main">
                {errorRate.toFixed(1)}
              </Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Errors/hour
            </Typography>
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
};

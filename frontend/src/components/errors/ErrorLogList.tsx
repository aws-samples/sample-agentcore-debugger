/**
 * Error log list component
 */
import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  IconButton,
  Tooltip,
} from '@mui/material';
import { ExpandMore, ContentCopy, OpenInNew } from '@mui/icons-material';
import { LogEvent } from '../../types/error';

interface ErrorLogListProps {
  logs: LogEvent[];
  title?: string;
  maxHeight?: number;
}

const getSeverityColor = (level: string): 'error' | 'warning' | 'info' | 'default' => {
  const upperLevel = level.toUpperCase();
  if (['ERROR', 'FATAL', 'CRITICAL'].includes(upperLevel)) return 'error';
  if (['WARN', 'WARNING'].includes(upperLevel)) return 'warning';
  if (upperLevel === 'INFO') return 'info';
  return 'default';
};

export const ErrorLogList: React.FC<ErrorLogListProps> = ({
  logs,
  title = 'Recent Errors',
  maxHeight = 600,
}) => {
  const [expanded, setExpanded] = useState<string | false>(false);

  const handleChange = (panel: string) => (_: React.SyntheticEvent, isExpanded: boolean) => {
    setExpanded(isExpanded ? panel : false);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  if (!logs || logs.length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            {title}
          </Typography>
          <Typography variant="body2" color="textSecondary">
            No error logs found
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {title} ({logs.length})
        </Typography>

        <Box sx={{ maxHeight, overflow: 'auto' }}>
          {logs.map((log, index) => (
            <Accordion
              key={`${log.timestamp}-${index}`}
              expanded={expanded === `panel-${index}`}
              onChange={handleChange(`panel-${index}`)}
              sx={{ mb: 1 }}
            >
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Box display="flex" alignItems="center" gap={1} width="100%" flexWrap="wrap">
                  <Chip
                    label={log.level}
                    color={getSeverityColor(log.level)}
                    size="small"
                  />
                  {log.error_type && (
                    <Chip
                      label={log.error_type.replace('_', ' ')}
                      variant="outlined"
                      size="small"
                    />
                  )}
                  <Typography variant="body2" color="textSecondary" sx={{ ml: 'auto' }}>
                    {formatTimestamp(log.timestamp)}
                  </Typography>
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                <Box>
                  <Typography variant="body2" sx={{ mb: 2, wordBreak: 'break-word' }}>
                    {log.message}
                  </Typography>

                  <Box display="flex" gap={1} flexWrap="wrap" mb={2}>
                    {log.agent_id && (
                      <Chip label={`Agent: ${log.agent_id}`} size="small" variant="outlined" />
                    )}
                    {log.service_name && (
                      <Chip label={`Service: ${log.service_name}`} size="small" variant="outlined" />
                    )}
                    {log.trace_id && (
                      <Chip label={`Trace: ${log.trace_id.slice(0, 12)}...`} size="small" variant="outlined" />
                    )}
                  </Box>

                  <Typography variant="caption" color="textSecondary" display="block">
                    Log Group: {log.log_group}
                  </Typography>

                  {log.stack_trace && (
                    <Box mt={2}>
                      <Typography variant="caption" color="textSecondary">
                        Stack Trace:
                      </Typography>
                      <Box
                        component="pre"
                        sx={{
                          backgroundColor: '#f5f5f5',
                          p: 1,
                          borderRadius: 1,
                          overflow: 'auto',
                          fontSize: '12px',
                          maxHeight: 200,
                        }}
                      >
                        {log.stack_trace}
                      </Box>
                    </Box>
                  )}

                  <Box display="flex" justifyContent="flex-end" mt={1}>
                    <Tooltip title="Copy raw message">
                      <IconButton
                        size="small"
                        onClick={() => copyToClipboard(log.raw_message || log.message)}
                      >
                        <ContentCopy fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Box>
              </AccordionDetails>
            </Accordion>
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

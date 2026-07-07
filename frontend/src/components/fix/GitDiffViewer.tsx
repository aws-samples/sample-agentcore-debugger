/**
 * Git Diff Viewer Component
 * Displays git diff with syntax highlighting
 */
import React, { useMemo } from 'react';
import { Paper, Typography, Box, Chip } from '@mui/material';
import { Add as AddIcon, Remove as RemoveIcon } from '@mui/icons-material';

interface GitDiffViewerProps {
  diff: string;
  title?: string;
}

export const GitDiffViewer: React.FC<GitDiffViewerProps> = ({ diff, title = 'Git Diff' }) => {
  const { addedLines, removedLines, diffLines } = useMemo(() => {
    const lines = diff.split('\n');
    let added = 0;
    let removed = 0;

    const processedLines = lines.map((line, index) => {
      let type: 'added' | 'removed' | 'context' | 'header' = 'context';
      
      if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('@@')) {
        type = 'header';
      } else if (line.startsWith('+')) {
        type = 'added';
        added++;
      } else if (line.startsWith('-')) {
        type = 'removed';
        removed++;
      }

      return { line, type, index };
    });

    return {
      addedLines: added,
      removedLines: removed,
      diffLines: processedLines,
    };
  }, [diff]);

  const getLineStyle = (type: 'added' | 'removed' | 'context' | 'header') => {
    switch (type) {
      case 'added':
        return {
          backgroundColor: 'rgba(46, 160, 67, 0.15)',
          color: '#22863a',
        };
      case 'removed':
        return {
          backgroundColor: 'rgba(248, 81, 73, 0.15)',
          color: '#cb2431',
        };
      case 'header':
        return {
          backgroundColor: 'rgba(33, 150, 243, 0.1)',
          color: '#0366d6',
          fontWeight: 'bold',
        };
      default:
        return {
          backgroundColor: 'transparent',
          color: '#24292e',
        };
    }
  };

  if (!diff || diff.trim() === '') {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          {title}
        </Typography>
        <Typography color="textSecondary">No changes detected</Typography>
      </Paper>
    );
  }

  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      <Box
        sx={{
          p: 2,
          bgcolor: 'grey.100',
          borderBottom: '1px solid',
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Typography variant="subtitle2">{title}</Typography>
        <Box display="flex" gap={1}>
          <Chip
            icon={<AddIcon fontSize="small" />}
            label={`${addedLines} added`}
            size="small"
            color="success"
            variant="outlined"
          />
          <Chip
            icon={<RemoveIcon fontSize="small" />}
            label={`${removedLines} removed`}
            size="small"
            color="error"
            variant="outlined"
          />
        </Box>
      </Box>

      <Box
        sx={{
          overflow: 'auto',
          maxHeight: '500px',
          fontFamily: 'monospace',
          fontSize: '12px',
          lineHeight: 1.5,
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            {diffLines.map(({ line, type, index }) => (
              <tr key={index}>
                <td
                  style={{
                    width: '40px',
                    padding: '0 8px',
                    textAlign: 'right',
                    color: '#6a737d',
                    backgroundColor: '#f6f8fa',
                    borderRight: '1px solid #e1e4e8',
                    userSelect: 'none',
                  }}
                >
                  {index + 1}
                </td>
                <td
                  style={{
                    padding: '0 8px',
                    whiteSpace: 'pre',
                    ...getLineStyle(type),
                  }}
                >
                  {line}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Box>
    </Paper>
  );
};

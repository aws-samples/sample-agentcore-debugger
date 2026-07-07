/**
 * User Choice Dialog Component
 * Dialog for mixed workflow user choice
 * 
 * When an error is classified as "mixed", the user needs to choose:
 * - library: Update packages/dependencies only (fast, no code download)
 * - code: Modify code only (needs ECR download)
 * - both: Apply both package updates AND code changes (comprehensive)
 * - skip: Skip this pattern and move to the next one
 * 
 * The dialog shows:
 * - Error details
 * - Library Agent analysis (if available)
 * - Package recommendations (if available)
 * - Clear explanation of each option
 */
import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Card,
  CardContent,
  CardActionArea,
  Chip,
  Alert,
  Divider,
} from '@mui/material';
import {
  Code as CodeIcon,
  Inventory as PackageIcon,
  AllInclusive as BothIcon,
  SkipNext as SkipIcon,
  Lightbulb as TipIcon,
} from '@mui/icons-material';
import { ErrorCluster, UserChoice, FixResult } from '../../api/fix';

interface UserChoiceDialogProps {
  open: boolean;
  onClose: () => void;
  onChoice: (choice: UserChoice) => void;
  cluster: ErrorCluster | null;
  fixResult?: FixResult;
}

interface ChoiceOption {
  value: UserChoice;
  title: string;
  description: string;
  details: string;
  icon: React.ReactNode;
  color: 'primary' | 'secondary' | 'success' | 'warning';
  recommended?: boolean;
}

const choiceOptions: ChoiceOption[] = [
  {
    value: 'library',
    title: 'Package Updates Only',
    description: 'Update package versions in requirements.txt',
    details: 'Fast fix - no code download needed. Best when the error is caused by outdated or incompatible package versions.',
    icon: <PackageIcon fontSize="large" />,
    color: 'primary',
  },
  {
    value: 'code',
    title: 'Code Changes Only',
    description: 'Modify the source code to fix the issue',
    details: 'Downloads code from ECR and applies fixes. Best when the error is in your application logic.',
    icon: <CodeIcon fontSize="large" />,
    color: 'secondary',
  },
  {
    value: 'both',
    title: 'Both (Comprehensive)',
    description: 'Apply package updates AND code changes',
    details: 'Most thorough fix - updates packages and modifies code. Recommended for complex issues.',
    icon: <BothIcon fontSize="large" />,
    color: 'success',
    recommended: true,
  },
  {
    value: 'skip',
    title: 'Skip This Pattern',
    description: 'Skip and move to the next error pattern',
    details: 'Use this if you want to handle this error manually or investigate further.',
    icon: <SkipIcon fontSize="large" />,
    color: 'warning',
  },
];

export const UserChoiceDialog: React.FC<UserChoiceDialogProps> = ({
  open,
  onClose,
  onChoice,
  cluster,
  fixResult,
}) => {
  const [selectedChoice, setSelectedChoice] = React.useState<UserChoice | null>(null);

  const handleConfirm = () => {
    if (selectedChoice) {
      onChoice(selectedChoice);
      setSelectedChoice(null);
    }
  };

  const handleClose = () => {
    setSelectedChoice(null);
    onClose();
  };

  // Get library agent output if available
  const libraryOutput = fixResult?.library_agent_output;
  const packageRecommendations = fixResult?.package_recommendations;
  const classification = fixResult?.error_classification;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h6">Choose Fix Approach</Typography>
          <Chip label="Mixed Issue" color="secondary" size="small" />
        </Box>
      </DialogTitle>

      <DialogContent>
        {/* Error Details */}
        {cluster && (
          <Box mb={3} p={2} bgcolor="grey.50" borderRadius={1}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Error Pattern
            </Typography>
            <Typography variant="body1" sx={{ fontFamily: 'monospace', fontSize: 13 }}>
              {cluster.error_message}
            </Typography>
            <Box mt={1} display="flex" gap={1} flexWrap="wrap">
              <Chip label={cluster.error_type} size="small" />
              <Chip label={`${cluster.count} occurrences`} size="small" variant="outlined" />
            </Box>
          </Box>
        )}

        {/* AI Classification Reasoning */}
        {classification?.reasoning ? (
          <Alert severity="info" sx={{ mb: 3 }} icon={<TipIcon />}>
            <Typography variant="body2">
              <strong>AI Analysis:</strong> {String(classification.reasoning)}
            </Typography>
            {classification.confidence ? (
              <Typography variant="caption" color="text.secondary">
                Confidence: {Math.round(Number(classification.confidence) * 100)}%
              </Typography>
            ) : null}
          </Alert>
        ) : null}

        {/* Library Agent Analysis - if available */}
        {libraryOutput && (
          <Box mb={3}>
            <Typography variant="subtitle2" gutterBottom>
              Library Agent Analysis
            </Typography>
            <Box p={2} bgcolor="info.50" borderRadius={1} sx={{ maxHeight: 150, overflow: 'auto' }}>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12 }}>
                {libraryOutput}
              </Typography>
            </Box>
          </Box>
        )}

        {/* Package Recommendations - if available */}
        {packageRecommendations && packageRecommendations.length > 0 && (
          <Box mb={3}>
            <Typography variant="subtitle2" gutterBottom>
              Package Recommendations ({packageRecommendations.length})
            </Typography>
            <Box display="flex" flexDirection="column" gap={1}>
              {packageRecommendations.slice(0, 3).map((rec, idx) => (
                <Box key={idx} p={1} bgcolor="grey.100" borderRadius={1}>
                  <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                    {typeof rec === 'string' ? rec : JSON.stringify(rec)}
                  </Typography>
                </Box>
              ))}
              {packageRecommendations.length > 3 && (
                <Typography variant="caption" color="text.secondary">
                  +{packageRecommendations.length - 3} more recommendations
                </Typography>
              )}
            </Box>
          </Box>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Choice Explanation */}
        <Typography variant="body2" color="text.secondary" paragraph>
          This error can be fixed in multiple ways. Choose your preferred approach:
        </Typography>

        {/* Choice Options */}
        <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={2}>
          {choiceOptions.map((option) => (
            <Card
              key={option.value}
              variant="outlined"
              sx={{
                borderColor: selectedChoice === option.value ? `${option.color}.main` : 'divider',
                borderWidth: selectedChoice === option.value ? 2 : 1,
                position: 'relative',
              }}
            >
              {option.recommended && (
                <Chip
                  label="Recommended"
                  size="small"
                  color="success"
                  sx={{ position: 'absolute', top: 8, right: 8 }}
                />
              )}
              <CardActionArea onClick={() => setSelectedChoice(option.value)}>
                <CardContent>
                  <Box display="flex" alignItems="center" gap={2} mb={1}>
                    <Box color={`${option.color}.main`}>{option.icon}</Box>
                    <Typography variant="subtitle1" fontWeight={600}>{option.title}</Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    {option.description}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {option.details}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
        </Box>
      </DialogContent>

      <DialogActions sx={{ p: 2 }}>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleConfirm}
          disabled={!selectedChoice}
          color={selectedChoice ? choiceOptions.find((o) => o.value === selectedChoice)?.color : 'primary'}
        >
          Apply {selectedChoice ? choiceOptions.find((o) => o.value === selectedChoice)?.title : 'Fix'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

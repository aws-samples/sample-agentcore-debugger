/**
 * Time Range Selector Component
 * Allows users to select predefined or custom time ranges for error analysis
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Chip,
  Button,
} from '@mui/material';
import { Schedule } from '@mui/icons-material';

export type TimeRangePreset = '1h' | '6h' | '24h' | '7d' | '30d' | 'custom';

export interface TimeRange {
  preset: TimeRangePreset;
  startTime: string;
  endTime: string;
}

interface TimeRangeSelectorProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
  showCustom?: boolean;
  compact?: boolean;
}

const presets: { value: TimeRangePreset; label: string; hours: number }[] = [
  { value: '1h', label: 'Last 1 hour', hours: 1 },
  { value: '6h', label: 'Last 6 hours', hours: 6 },
  { value: '24h', label: 'Last 24 hours', hours: 24 },
  { value: '7d', label: 'Last 7 days', hours: 168 },
  { value: '30d', label: 'Last 30 days', hours: 720 },
];

export const getTimeRangeFromPreset = (preset: TimeRangePreset): { startTime: string; endTime: string } => {
  const now = new Date();
  const endTime = now.toISOString();
  
  const presetConfig = presets.find(p => p.value === preset);
  if (!presetConfig) {
    // Default to 24 hours
    const start = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    return { startTime: start.toISOString(), endTime };
  }
  
  const start = new Date(now.getTime() - presetConfig.hours * 60 * 60 * 1000);
  return { startTime: start.toISOString(), endTime };
};

export const TimeRangeSelector: React.FC<TimeRangeSelectorProps> = ({
  value,
  onChange,
  showCustom = false,
  compact = false,
}) => {
  // Local state for custom time inputs (only applied when user clicks Apply)
  const [customStart, setCustomStart] = useState(value.startTime);
  const [customEnd, setCustomEnd] = useState(value.endTime);
  const [isCustomDirty, setIsCustomDirty] = useState(false);

  // Sync local state when value changes from outside
  useEffect(() => {
    if (value.preset === 'custom') {
      setCustomStart(value.startTime);
      setCustomEnd(value.endTime);
      setIsCustomDirty(false);
    }
  }, [value.startTime, value.endTime, value.preset]);

  const handlePresetChange = (preset: TimeRangePreset) => {
    if (preset === 'custom') {
      // When switching to custom, initialize with current times but don't trigger fetch
      const now = new Date();
      const start = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      setCustomStart(start.toISOString());
      setCustomEnd(now.toISOString());
      setIsCustomDirty(true);
      // Only update preset, not the times (user needs to click Apply)
      onChange({ ...value, preset: 'custom' });
    } else {
      const { startTime, endTime } = getTimeRangeFromPreset(preset);
      onChange({ preset, startTime, endTime });
      setIsCustomDirty(false);
    }
  };

  const handleApplyCustomRange = () => {
    onChange({ preset: 'custom', startTime: customStart, endTime: customEnd });
    setIsCustomDirty(false);
  };

  // Calculate min date (30 days ago from now)
  const getMinDate = () => {
    const now = new Date();
    const minDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    return minDate.toISOString().slice(0, 16);
  };

  // Calculate max date (now)
  const getMaxDate = () => {
    return new Date().toISOString().slice(0, 16);
  };

  const handleCustomStartChange = (newStart: string) => {
    const startDate = new Date(newStart);
    const now = new Date();
    const minDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    
    // Clamp to min 30 days ago
    if (startDate < minDate) {
      setCustomStart(minDate.toISOString());
    } else if (startDate > now) {
      setCustomStart(now.toISOString());
    } else {
      setCustomStart(startDate.toISOString());
    }
    setIsCustomDirty(true);
  };

  const handleCustomEndChange = (newEnd: string) => {
    const endDate = new Date(newEnd);
    const now = new Date();
    const minDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    
    // Clamp to max now, min 30 days ago
    if (endDate > now) {
      setCustomEnd(now.toISOString());
    } else if (endDate < minDate) {
      setCustomEnd(minDate.toISOString());
    } else {
      setCustomEnd(endDate.toISOString());
    }
    setIsCustomDirty(true);
  };

  if (compact) {
    return (
      <Box display="flex" gap={1} alignItems="center">
        <Schedule fontSize="small" color="action" />
        <Box display="flex" gap={0.5}>
          {presets.slice(0, 4).map((preset) => (
            <Chip
              key={preset.value}
              label={preset.value}
              size="small"
              variant={value.preset === preset.value ? 'filled' : 'outlined'}
              color={value.preset === preset.value ? 'primary' : 'default'}
              onClick={() => handlePresetChange(preset.value)}
              sx={{ cursor: 'pointer' }}
            />
          ))}
        </Box>
      </Box>
    );
  }

  return (
    <Box display="flex" gap={2} alignItems="flex-start" flexWrap="wrap">
      <FormControl size="small" sx={{ minWidth: 150 }}>
        <InputLabel>Time Range</InputLabel>
        <Select
          value={value.preset}
          label="Time Range"
          onChange={(e) => handlePresetChange(e.target.value as TimeRangePreset)}
        >
          {showCustom && <MenuItem value="custom">Custom Range</MenuItem>}
          {presets.map((preset) => (
            <MenuItem key={preset.value} value={preset.value}>
              {preset.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {showCustom && value.preset === 'custom' && (
        <>
          <TextField
            size="small"
            label="Start Time (max 30 days ago)"
            type="datetime-local"
            value={customStart.slice(0, 16)}
            onChange={(e) => handleCustomStartChange(e.target.value)}
            InputLabelProps={{ shrink: true }}
            inputProps={{ min: getMinDate(), max: getMaxDate() }}
          />
          <TextField
            size="small"
            label="End Time"
            type="datetime-local"
            value={customEnd.slice(0, 16)}
            onChange={(e) => handleCustomEndChange(e.target.value)}
            InputLabelProps={{ shrink: true }}
            inputProps={{ min: getMinDate(), max: getMaxDate() }}
          />
          <Button
            variant="contained"
            size="small"
            onClick={handleApplyCustomRange}
            disabled={!isCustomDirty}
            sx={{ height: 40 }}
          >
            Apply
          </Button>
        </>
      )}
    </Box>
  );
};

export default TimeRangeSelector;

"""
Log Capture Utility for Streamlit Dashboard

This module provides utilities to capture stdout/stderr and display them
in real-time within the Streamlit dashboard during long-running operations.
"""

import sys
import io
import contextlib
import threading
import time
import streamlit as st
from typing import Generator, Optional, List
from datetime import datetime


class StreamlitLogCapture:
    """Captures stdout/stderr and displays in Streamlit in real-time"""
    
    def __init__(self, container=None):
        self.container = container or st.empty()
        self.logs = []
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.capture_stdout = io.StringIO()
        self.capture_stderr = io.StringIO()
        self.is_capturing = False
        self.update_thread = None
        self.stop_updating = False
    
    def start_capture(self):
        """Start capturing stdout/stderr"""
        self.is_capturing = True
        self.logs = []
        self.stop_updating = False
        
        # Redirect stdout/stderr
        sys.stdout = self.capture_stdout
        sys.stderr = self.capture_stderr
        
        # Start update thread
        self.update_thread = threading.Thread(target=self._update_display, daemon=True)
        self.update_thread.start()
    
    def stop_capture(self):
        """Stop capturing and restore original streams"""
        self.is_capturing = False
        self.stop_updating = True
        
        # Restore original streams
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        
        # Wait for update thread to finish
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=1.0)
        
        # Final update
        self._update_display_once()
    
    def _update_display(self):
        """Update display in background thread"""
        while not self.stop_updating:
            self._update_display_once()
            time.sleep(0.5)  # Update every 500ms
    
    def _update_display_once(self):
        """Update the display once with current logs"""
        try:
            # Get new content
            stdout_content = self.capture_stdout.getvalue()
            stderr_content = self.capture_stderr.getvalue()
            
            # Combine and format logs
            all_content = ""
            if stdout_content:
                all_content += stdout_content
            if stderr_content:
                all_content += f"\n🔴 ERRORS:\n{stderr_content}"
            
            if all_content:
                # Display in container
                self.container.code(all_content, language="text")
        except Exception as e:
            # Silently handle display errors to avoid breaking the main process
            pass
    
    def add_log(self, message: str, level: str = "INFO"):
        """Manually add a log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}"
        self.logs.append(formatted_message)
        
        # Also write to captured stdout
        if self.is_capturing:
            self.capture_stdout.write(f"{formatted_message}\n")
            self.capture_stdout.flush()


@contextlib.contextmanager
def capture_logs_to_streamlit(container=None, title: str = "Operation Logs"):
    """Context manager to capture logs and display in Streamlit"""
    
    # Create log container
    if container is None:
        st.markdown(f"### {title}")
        container = st.empty()
    
    # Create log capture
    log_capture = StreamlitLogCapture(container)
    
    try:
        log_capture.start_capture()
        yield log_capture
    finally:
        log_capture.stop_capture()


class StreamlitProgressLogger:
    """Enhanced logger that shows progress and logs in Streamlit"""
    
    def __init__(self, total_steps: int = 100, title: str = "Processing..."):
        self.total_steps = total_steps
        self.current_step = 0
        self.title = title
        
        # Create UI elements
        self.progress_bar = st.progress(0)
        self.status_text = st.empty()
        self.log_container = st.expander("Detailed Logs", expanded=False)
        self.log_capture = StreamlitLogCapture(self.log_container)
        
        # Start capturing
        self.log_capture.start_capture()
    
    def update(self, step: int, message: str):
        """Update progress and add log message"""
        self.current_step = step
        progress = min(step / self.total_steps, 1.0)
        
        # Update progress bar
        self.progress_bar.progress(progress)
        
        # Update status
        self.status_text.text(f"{self.title} - {message} ({step}/{self.total_steps})")
        
        # Add to logs
        self.log_capture.add_log(message)
    
    def complete(self, message: str = "Completed successfully!"):
        """Mark as complete"""
        self.progress_bar.progress(1.0)
        self.status_text.success(f"{message}")
        self.log_capture.stop_capture()
    
    def error(self, message: str):
        """Mark as error"""
        self.status_text.error(f"{message}")
        self.log_capture.add_log(message, "ERROR")
        self.log_capture.stop_capture()


def create_real_time_logger(title: str = "Processing"):
    """Create a real-time logger for long operations"""
    
    # Create containers
    st.markdown(f"### {title}")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        status_container = st.empty()
        log_container = st.empty()
    
    with col2:
        progress_container = st.empty()
    
    class RealTimeLogger:
        def __init__(self):
            self.logs = []
            self.current_status = "Starting..."
            self.log_capture = StreamlitLogCapture(log_container)
            self.log_capture.start_capture()
        
        def info(self, message: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.current_status = message
            status_container.info(f"[{timestamp}] {message}")
            self.log_capture.add_log(message, "INFO")
        
        def success(self, message: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.current_status = message
            status_container.success(f"[{timestamp}] {message}")
            self.log_capture.add_log(message, "SUCCESS")
        
        def error(self, message: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.current_status = message
            status_container.error(f"[{timestamp}] {message}")
            self.log_capture.add_log(message, "ERROR")
        
        def warning(self, message: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.current_status = message
            status_container.warning(f"[{timestamp}] {message}")
            self.log_capture.add_log(message, "WARNING")
        
        def stop(self):
            self.log_capture.stop_capture()
    
    return RealTimeLogger()


# Example usage functions for testing
def demo_long_operation_with_logs():
    """Demo function showing how to use log capture"""
    
    with capture_logs_to_streamlit(title=" Demo Operation"):
        print("Starting demo operation...")
        time.sleep(1)
        
        print("Step 1: Initializing...")
        time.sleep(1)
        
        print("Step 2: Processing data...")
        time.sleep(1)
        
        print("Step 3: Generating results...")
        time.sleep(1)
        
        print("Demo operation completed!")


def demo_progress_logger():
    """Demo function showing progress logger"""
    
    logger = StreamlitProgressLogger(5, "Demo Progress Operation")
    
    try:
        logger.update(1, "Initializing system...")
        time.sleep(1)
        
        logger.update(2, "Loading data...")
        time.sleep(1)
        
        logger.update(3, "Processing...")
        time.sleep(1)
        
        logger.update(4, "Generating output...")
        time.sleep(1)
        
        logger.update(5, "Finalizing...")
        time.sleep(1)
        
        logger.complete("All steps completed successfully!")
        
    except Exception as e:
        logger.error(f"Operation failed: {e}")


def demo_real_time_logger():
    """Demo function showing real-time logger"""
    
    logger = create_real_time_logger("Real-time Demo")
    
    try:
        logger.info("Starting real-time operation...")
        time.sleep(1)
        
        logger.info("Connecting to services...")
        time.sleep(1)
        
        logger.warning("Retrying connection...")
        time.sleep(1)
        
        logger.success("Connected successfully!")
        time.sleep(1)
        
        logger.info("Processing complete")
        
    except Exception as e:
        logger.error(f"Operation failed: {e}")
    finally:
        logger.stop()
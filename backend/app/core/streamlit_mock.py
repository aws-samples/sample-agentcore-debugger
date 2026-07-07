"""
Mock streamlit module for running collectors in FastAPI context
"""
import logging

logger = logging.getLogger(__name__)


class SessionStateMock:
    """Mock for st.session_state"""
    _state = {}
    
    def get(self, key, default=None):
        return self._state.get(key, default)
    
    def __contains__(self, key):
        return key in self._state
    
    def __getitem__(self, key):
        return self._state.get(key)
    
    def __setitem__(self, key, value):
        self._state[key] = value


session_state = SessionStateMock()


def warning(msg):
    """Mock st.warning - log as warning"""
    logger.warning(msg)


def error(msg):
    """Mock st.error - log as error"""
    logger.error(msg)


def write(msg):
    """Mock st.write - log as info"""
    logger.info(msg)


def info(msg):
    """Mock st.info - log as info"""
    logger.info(msg)


def success(msg):
    """Mock st.success - log as info"""
    logger.info(msg)

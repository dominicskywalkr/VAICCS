"""
Automation manager for scheduling shows at specific times.
Handles creation, storage, and execution of show automation schedules.
"""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Callable, Any


class ShowAutomation:
    """Represents a single show automation with schedule and times."""
    
    def __init__(self, name: str, days: List[str], start_time: str, end_time: str):
        """
        Initialize a show automation.
        
        Args:
            name: Show name
            days: List of day names (e.g., ['Monday', 'Tuesday', ...])
            start_time: Start time in "HH:MM AM/PM" format
            end_time: End time in "HH:MM AM/PM" format
        """
        self.name = name
        self.days = days  # ['Monday', 'Tuesday', ...]
        self.start_time = start_time  # "10:00 AM"
        self.end_time = end_time  # "11:30 AM"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'days': self.days,
            'start_time': self.start_time,
            'end_time': self.end_time
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ShowAutomation':
        """Create from dictionary."""
        return cls(
            name=data.get('name', 'Unnamed Show'),
            days=data.get('days', []),
            start_time=data.get('start_time', '12:00 PM'),
            end_time=data.get('end_time', '1:00 PM')
        )


class AutomationManager:
    """Manages multiple show automations and scheduling."""
    
    def __init__(self):
        """Initialize the automation manager."""
        self.automations: List[ShowAutomation] = []
        self._on_start_callback: Callable[[], None] | None = None
        self._on_stop_callback: Callable[[], None] | None = None
        self._active_automation: ShowAutomation | None = None
        self._scheduler_thread: threading.Thread | None = None
        self._scheduler_running = False
    
    def add_automation(self, automation: ShowAutomation) -> None:
        """Add a new automation."""
        self.automations.append(automation)
    
    def remove_automation(self, index: int) -> None:
        """Remove automation by index."""
        if 0 <= index < len(self.automations):
            self.automations.pop(index)
    
    def get_automations(self) -> List[ShowAutomation]:
        """Get all automations."""
        return self.automations.copy()
    
    def set_automations(self, automations: List[ShowAutomation]) -> None:
        """Replace all automations."""
        self.automations = automations
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'automations': [auto.to_dict() for auto in self.automations]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AutomationManager':
        """Create from dictionary."""
        manager = cls()
        auto_list = data.get('automations', [])
        for auto_data in auto_list:
            manager.add_automation(ShowAutomation.from_dict(auto_data))
        return manager
    
    def set_callbacks(self, on_start: Callable[[], None], on_stop: Callable[[], None]) -> None:
        """
        Set callbacks to be invoked when automation starts/stops.
        
        Args:
            on_start: Callable invoked when an automation triggers start
            on_stop: Callable invoked when an automation triggers stop
        """
        self._on_start_callback = on_start
        self._on_stop_callback = on_stop
    
    def _time_to_minutes(self, time_str: str) -> int:
        """Convert time string 'HH:MM AM/PM' to minutes since midnight."""
        try:
            # Parse "10:30 AM" or "2:45 PM"
            time_part, period = time_str.rsplit(' ', 1)
            hours, minutes = map(int, time_part.split(':'))
            
            # Convert to 24-hour format
            if period.upper() == 'PM' and hours != 12:
                hours += 12
            elif period.upper() == 'AM' and hours == 12:
                hours = 0
            
            return hours * 60 + minutes
        except Exception:
            return 0
    
    def _get_current_time_minutes(self) -> int:
        """Get current time as minutes since midnight."""
        now = datetime.now()
        return now.hour * 60 + now.minute
    
    def _get_current_day_name(self) -> str:
        """Get current day name (e.g., 'Monday')."""
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return day_names[datetime.now().weekday()]
    
    def _check_automation_trigger(self, automation: ShowAutomation) -> tuple[bool, bool]:
        """
        Check if an automation should trigger and what action (start/stop).
        
        Returns:
            (should_trigger, is_start) - (True if triggered, True if start else stop)
        """
        current_day = self._get_current_day_name()
        current_minutes = self._get_current_time_minutes()
        
        # Check if today is a scheduled day
        if current_day not in automation.days:
            return False, False
        
        start_minutes = self._time_to_minutes(automation.start_time)
        end_minutes = self._time_to_minutes(automation.end_time)
        
        # Check if we're at or past the start time
        if current_minutes >= start_minutes and current_minutes < end_minutes:
            return True, True  # Should start
        
        return False, False
    
    def start_scheduler(self) -> None:
        """Start the automation scheduler thread."""
        if self._scheduler_running:
            return
        
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
    
    def stop_scheduler(self) -> None:
        """Stop the automation scheduler thread."""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=2)
    
    def _scheduler_loop(self) -> None:
        """Background loop that checks automations and triggers callbacks."""
        while self._scheduler_running:
            try:
                # Check each automation
                for automation in self.automations:
                    should_trigger, is_start = self._check_automation_trigger(automation)
                    
                    if should_trigger:
                        if is_start and self._active_automation != automation:
                            # Trigger start
                            self._active_automation = automation
                            if self._on_start_callback:
                                try:
                                    self._on_start_callback()
                                except Exception as e:
                                    print(f"Error in automation start callback: {e}")
                        elif not is_start and self._active_automation == automation:
                            # Trigger stop
                            self._active_automation = None
                            if self._on_stop_callback:
                                try:
                                    self._on_stop_callback()
                                except Exception as e:
                                    print(f"Error in automation stop callback: {e}")
                
                # Check if we need to stop current automation
                if self._active_automation:
                    should_trigger, is_start = self._check_automation_trigger(self._active_automation)
                    if not should_trigger and not is_start:
                        # Time has passed, trigger stop
                        self._active_automation = None
                        if self._on_stop_callback:
                            try:
                                self._on_stop_callback()
                            except Exception as e:
                                print(f"Error in automation stop callback: {e}")
                
                # Check every minute
                time.sleep(60)
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
                time.sleep(60)

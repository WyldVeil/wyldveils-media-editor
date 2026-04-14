"""
tabs.system  -  System-level and application tools
"""
from tabs.system.screen_recorder   import ScreenRecorderTab
from tabs.system.batch             import BatchTab
from tabs.system.advanced_settings import AdvancedSettingsTab
from tabs.system.settings          import SettingsTab

__all__ = [
    "ScreenRecorderTab", "BatchTab", "AdvancedSettingsTab", "SettingsTab",
]

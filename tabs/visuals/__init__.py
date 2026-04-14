"""
tabs.visuals  -  Color grading, visual effects, and compositing tools
"""
from tabs.visuals.media_gen     import MediaGeneratorTab
from tabs.visuals.effects       import SpecialEffectsTab
from tabs.visuals.lut           import LUTApplicatorTab
from tabs.visuals.color_correct import ColorCorrectorTab
from tabs.visuals.color_match   import ColorMatchTab
from tabs.visuals.scopes        import VideoScopesTab
from tabs.visuals.speed_ramp    import SpeedRamperTab
from tabs.visuals.deshaker      import DeshakerTab
from tabs.visuals.green_key     import GreenKeyerTab
from tabs.visuals.denoise       import DenoiseTab
from tabs.visuals.deinterlace   import DeinterlaceTab
from tabs.visuals.sharpen       import SharpenTab
from tabs.visuals.pip           import PIPTab
from tabs.visuals.region_blur   import RegionBlurTab
from tabs.visuals.zoom          import AnimatedZoomTab
from tabs.visuals.transitions   import TransitionStudioTab

__all__ = [
    "MediaGeneratorTab", "SpecialEffectsTab", "LUTApplicatorTab", "ColorCorrectorTab",
    "ColorMatchTab", "VideoScopesTab", "SpeedRamperTab", "DeshakerTab",
    "GreenKeyerTab", "DenoiseTab", "DeinterlaceTab", "SharpenTab",
    "PIPTab", "RegionBlurTab", "AnimatedZoomTab", "TransitionStudioTab",
]

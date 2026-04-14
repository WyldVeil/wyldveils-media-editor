"""
tabs.social  -  Social media, format, and delivery tools
"""
from tabs.social.shortifier     import ShortifierTab
from tabs.social.auto_cropper   import AutoCropperTab
from tabs.social.gif_maker      import GIFMakerTab
from tabs.social.webm_maker     import WebMTab
from tabs.social.watermark      import TextBurnerTab
from tabs.social.image_watermark import ImageWatermarkTab
from tabs.social.hard_subber    import HardSubberTab
from tabs.social.auto_subs      import AutoSubsTab
from tabs.social.titles         import TitlesGeneratorTab
from tabs.social.frame_extractor import FrameExtractorTab
from tabs.social.intro_maker    import IntroMakerTab
from tabs.social.slideshow      import SlideshowMakerTab
from tabs.social.chapter_markers import ChapterMarkersTab
from tabs.social.thumbnail      import ThumbnailMakerTab
from tabs.social.collage        import VideoCollageTab
from tabs.social.youtube        import YouTubeDownloaderTab

__all__ = [
    "ShortifierTab", "AutoCropperTab", "GIFMakerTab", "WebMTab",
    "TextBurnerTab", "ImageWatermarkTab", "HardSubberTab", "AutoSubsTab",
    "TitlesGeneratorTab", "FrameExtractorTab", "IntroMakerTab", "SlideshowMakerTab",
    "ChapterMarkersTab", "ThumbnailMakerTab", "VideoCollageTab", "YouTubeDownloaderTab",
]

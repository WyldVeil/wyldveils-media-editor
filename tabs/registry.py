"""
tabs/registry.py  -  Single source of truth for Quintessential Video Editor tool registration.

Defines which tabs appear in the sidebar, their categories, display names,
and which tabs are pinned or hidden from the navigation tree.

Usage in main.py:
    from tabs.registry import TOOLS, PINNED, HIDDEN
"""
from tabs.cutting      import (CrossfaderTab, TrimmerTab, MultiSplitterTab,
                                SplicerTab, BatchJoinerTab, RotateFlipTab,
                                SideBySideTab, BeatSyncCutterTab, SmartReframeTab,
                                ManualCropTab, ReverserTab, FreezeFrameTab,
                                ClipLooperTab, SequencerTab, SceneDetectTab)

from tabs.social       import (ShortifierTab, AutoCropperTab, GIFMakerTab, WebMTab,
                                TextBurnerTab, ImageWatermarkTab, HardSubberTab,
                                AutoSubsTab, TitlesGeneratorTab, FrameExtractorTab,
                                IntroMakerTab, SlideshowMakerTab, ChapterMarkersTab,
                                ThumbnailMakerTab, VideoCollageTab, YouTubeDownloaderTab)

from tabs.audio        import (SilenceTab, AudioExtractorTab, AudioReplacerTab,
                                LoudnessNormTab, AudioSyncTab, MuterTab,
                                AudioDynamicsTab, AudioMixerTab, VoiceIsolationTab,
                                VoiceChangerTab, TTSVoiceOverTab, WaveformEditorTab,
                                LaughTrackRemoverTab, AudioDuckerTab, KaraokeTab,
                                AudioExporterTab, MIDIfierTab)

from tabs.transcoder   import (UniversalDownsizerTab, ProxyGenTab, CodecCruncherTab,
                                FormatConverterTab, ResolutionScalerTab,
                                FPSInterpolatorTab, EncodeQueueTab, PresetManagerTab)

from tabs.visuals      import (MediaGeneratorTab, SpecialEffectsTab, LUTApplicatorTab,
                                ColorCorrectorTab, ColorMatchTab, VideoScopesTab,
                                SpeedRamperTab, DeshakerTab, GreenKeyerTab, DenoiseTab,
                                DeinterlaceTab, SharpenTab, PIPTab, RegionBlurTab,
                                AnimatedZoomTab, TransitionStudioTab)

from tabs.system       import (ScreenRecorderTab, BatchTab, AdvancedSettingsTab,
                                SettingsTab)

from tabs.all_in_one   import AllInOneTab

# ── Pinned tool (always visible at top of sidebar, outside categories) ────────
PINNED = ("All-in-One Builder", AllInOneTab)

# ── Hidden tools (accessible programmatically, not shown in sidebar nav) ──────
HIDDEN = {
    "Settings": SettingsTab,
}

# ── Main tool registry (sidebar category → [(display_name, TabClass), ...]) ──
TOOLS = {
    "✂  CUTTING ROOM": [
        ("Crossfader",            CrossfaderTab),
        ("Quick Trimmer",         TrimmerTab),
        ("Manual Multi-Splitter", MultiSplitterTab),
        ("The Splicer",           SplicerTab),
        ("Batch Joiner",          BatchJoinerTab),
        ("Rotate & Flip",         RotateFlipTab),
        ("Side-by-Side",          SideBySideTab),
        ("Beat Sync Cutter",      BeatSyncCutterTab),
        ("Smart Reframe",         SmartReframeTab),
        ("Manual Crop",           ManualCropTab),
        ("Video Reverser",        ReverserTab),
        ("Freeze Frame",          FreezeFrameTab),
        ("Clip Looper",           ClipLooperTab),
        ("Multi-Clip Sequencer",  SequencerTab),
        ("Scene Detector",        SceneDetectTab),
    ],
    "📱  SOCIAL & FORMAT": [
        ("The Shortifier",     ShortifierTab),
        ("Auto-Cropper",       AutoCropperTab),
        ("Pro GIF Maker",      GIFMakerTab),
        ("WebM Maker",         WebMTab),
        ("Watermarker",        TextBurnerTab),
        ("Image Watermark",    ImageWatermarkTab),
        ("Hard-Subber",        HardSubberTab),
        ("Auto-Subtitles",     AutoSubsTab),
        ("Animated Titles",    TitlesGeneratorTab),
        ("Frame Extractor",    FrameExtractorTab),
        ("Intro/Outro Maker",  IntroMakerTab),
        ("Slideshow Maker",    SlideshowMakerTab),
        ("Chapter Markers",    ChapterMarkersTab),
        ("Thumbnail Maker",    ThumbnailMakerTab),
        ("Video Collage",      VideoCollageTab),
        ("YouTube Downloader", YouTubeDownloaderTab),
    ],
    "🔊  AUDIO ENGINEERING": [
        ("Silence Remover",     SilenceTab),
        ("Audio Extractor",     AudioExtractorTab),
        ("Audio Replacer",      AudioReplacerTab),
        ("Loudness Normalizer", LoudnessNormTab),
        ("Audio Sync Shifter",  AudioSyncTab),
        ("The Muter",           MuterTab),
        ("Audio Dynamics",      AudioDynamicsTab),
        ("Audio Mixer",         AudioMixerTab),
        ("Voice Isolation",     VoiceIsolationTab),
        ("Voice Changer",       VoiceChangerTab),
        ("TTS Voice-Over",      TTSVoiceOverTab),
        ("Waveform Editor",     WaveformEditorTab),
        ("Laugh Track Remover", LaughTrackRemoverTab),
        ("Music Ducker",        AudioDuckerTab),
        ("Karaoke Generator",   KaraokeTab),
        ("Audio Converter",     AudioExporterTab),
        ("MIDIfier",            MIDIfierTab),
    ],
    "⚙  TRANSCODER": [
        ("Universal Downsizer",    UniversalDownsizerTab),
        ("Proxy Generator",        ProxyGenTab),
        ("Codec Cruncher",         CodecCruncherTab),
        ("Format Converter",       FormatConverterTab),
        ("Resolution Scaler",      ResolutionScalerTab),
        ("Framerate Interpolator", FPSInterpolatorTab),
        ("Encode Queue",           EncodeQueueTab),
        ("Preset Manager",         PresetManagerTab),
    ],
    "🎨  COLOR & VISUALS": [
        ("Media Generator",       MediaGeneratorTab),
        ("Special Effects",       SpecialEffectsTab),
        ("LUT Applicator",        LUTApplicatorTab),
        ("Basic Color Corrector", ColorCorrectorTab),
        ("Colour Match",          ColorMatchTab),
        ("Video Scopes",          VideoScopesTab),
        ("Speed Ramper",          SpeedRamperTab),
        ("Deshaker",              DeshakerTab),
        ("Green Screen Keyer",    GreenKeyerTab),
        ("Denoise",               DenoiseTab),
        ("Deinterlace",           DeinterlaceTab),
        ("Sharpen",               SharpenTab),
        ("Picture-in-Picture",    PIPTab),
        ("Privacy Blur",          RegionBlurTab),
        ("Animated Zoom",         AnimatedZoomTab),
        ("Transition Studio",     TransitionStudioTab),
    ],
    "🛠  SYSTEM": [
        ("Screen Recorder",   ScreenRecorderTab),
        ("Batch Processor",   BatchTab),
        ("Advanced Settings", AdvancedSettingsTab),
    ],
}

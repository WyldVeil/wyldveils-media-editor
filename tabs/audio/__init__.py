"""
tabs.audio  -  Audio engineering and processing tools
"""
from tabs.audio.silence         import SilenceTab
from tabs.audio.extractor       import AudioExtractorTab
from tabs.audio.replacer        import AudioReplacerTab
from tabs.audio.loudness        import LoudnessNormTab
from tabs.audio.sync            import AudioSyncTab
from tabs.audio.muter           import MuterTab
from tabs.audio.dynamics        import AudioDynamicsTab
from tabs.audio.mixer           import AudioMixerTab
from tabs.audio.voice_isolation import VoiceIsolationTab
from tabs.audio.voice_changer   import VoiceChangerTab
from tabs.audio.tts             import TTSVoiceOverTab
from tabs.audio.waveform        import WaveformEditorTab
from tabs.audio.laugh_track     import LaughTrackRemoverTab
from tabs.audio.ducker          import AudioDuckerTab
from tabs.audio.karaoke         import KaraokeTab
from tabs.audio.exporter        import AudioExporterTab
from tabs.audio.midifier        import MIDIfierTab

__all__ = [
    "SilenceTab", "AudioExtractorTab", "AudioReplacerTab", "LoudnessNormTab",
    "AudioSyncTab", "MuterTab", "AudioDynamicsTab", "AudioMixerTab",
    "VoiceIsolationTab", "VoiceChangerTab", "TTSVoiceOverTab", "WaveformEditorTab",
    "LaughTrackRemoverTab", "AudioDuckerTab", "KaraokeTab", "AudioExporterTab",
    "MIDIfierTab",
]

"""
tabs.transcoder  -  Encoding, format conversion, and codec tools
"""
from tabs.transcoder.downsizer    import UniversalDownsizerTab
from tabs.transcoder.proxy        import ProxyGenTab
from tabs.transcoder.codec        import CodecCruncherTab
from tabs.transcoder.converter    import FormatConverterTab
from tabs.transcoder.scaler       import ResolutionScalerTab, FPSInterpolatorTab
from tabs.transcoder.encode_queue import EncodeQueueTab
from tabs.transcoder.presets      import PresetManagerTab

__all__ = [
    "UniversalDownsizerTab", "ProxyGenTab", "CodecCruncherTab", "FormatConverterTab",
    "ResolutionScalerTab", "FPSInterpolatorTab", "EncodeQueueTab", "PresetManagerTab",
]

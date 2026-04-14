"""
tabs.cutting  -  Timeline cutting and arrangement tools
"""
from tabs.cutting.crossfader   import CrossfaderTab
from tabs.cutting.trimmer      import TrimmerTab
from tabs.cutting.splitter     import MultiSplitterTab
from tabs.cutting.splicer      import SplicerTab
from tabs.cutting.batch_joiner import BatchJoinerTab
from tabs.cutting.rotate_flip  import RotateFlipTab
from tabs.cutting.side_by_side import SideBySideTab
from tabs.cutting.beat_sync    import BeatSyncCutterTab
from tabs.cutting.smart_reframe import SmartReframeTab
from tabs.cutting.crop         import ManualCropTab
from tabs.cutting.reverser     import ReverserTab
from tabs.cutting.freeze_frame import FreezeFrameTab
from tabs.cutting.clip_looper  import ClipLooperTab
from tabs.cutting.sequencer    import SequencerTab
from tabs.cutting.scene_detect import SceneDetectTab

__all__ = [
    "CrossfaderTab", "TrimmerTab", "MultiSplitterTab", "SplicerTab",
    "BatchJoinerTab", "RotateFlipTab", "SideBySideTab", "BeatSyncCutterTab",
    "SmartReframeTab", "ManualCropTab", "ReverserTab", "FreezeFrameTab",
    "ClipLooperTab", "SequencerTab", "SceneDetectTab",
]

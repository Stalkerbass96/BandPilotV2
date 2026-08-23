/**
 * MUI v5 icon compatibility for Vite 8 development builds.
 *
 * Vite 8 may preserve the CommonJS `{ default: Component }` wrapper for icon
 * subpath imports. Production bundling returns the component directly. This
 * boundary normalizes both shapes so page components never depend on bundler
 * interop details.
 */
import type { SvgIconComponent } from "@mui/icons-material";
import AlbumModule from "@mui/icons-material/Album";
import ArrowForwardModule from "@mui/icons-material/ArrowForward";
import AudioFileModule from "@mui/icons-material/AudioFile";
import BoltModule from "@mui/icons-material/Bolt";
import CancelModule from "@mui/icons-material/Cancel";
import CheckCircleModule from "@mui/icons-material/CheckCircle";
import ChevronLeftModule from "@mui/icons-material/ChevronLeft";
import ChevronRightModule from "@mui/icons-material/ChevronRight";
import CloseModule from "@mui/icons-material/Close";
import CloudUploadModule from "@mui/icons-material/CloudUpload";
import CompareArrowsModule from "@mui/icons-material/CompareArrows";
import ContentCutModule from "@mui/icons-material/ContentCut";
import DeleteModule from "@mui/icons-material/Delete";
import DescriptionModule from "@mui/icons-material/Description";
import DownloadModule from "@mui/icons-material/Download";
import GraphicEqModule from "@mui/icons-material/GraphicEq";
import HistoryModule from "@mui/icons-material/History";
import LayersModule from "@mui/icons-material/Layers";
import LogoutModule from "@mui/icons-material/Logout";
import MenuModule from "@mui/icons-material/Menu";
import MusicNoteModule from "@mui/icons-material/MusicNote";
import MusicOffModule from "@mui/icons-material/MusicOff";
import RadioButtonUncheckedModule from "@mui/icons-material/RadioButtonUnchecked";
import RefreshModule from "@mui/icons-material/Refresh";
import RepeatModule from "@mui/icons-material/Repeat";
import SchoolModule from "@mui/icons-material/School";
import SettingsModule from "@mui/icons-material/Settings";
import SpeedModule from "@mui/icons-material/Speed";
import StraightenModule from "@mui/icons-material/Straighten";
import SummarizeModule from "@mui/icons-material/Summarize";
import SwapHorizModule from "@mui/icons-material/SwapHoriz";
import SwapVertModule from "@mui/icons-material/SwapVert";
import TuneModule from "@mui/icons-material/Tune";
import UploadFileModule from "@mui/icons-material/UploadFile";
import VisibilityModule from "@mui/icons-material/Visibility";
import VpnKeyModule from "@mui/icons-material/VpnKey";

type IconModule = SvgIconComponent | { default: SvgIconComponent };

function icon(module: SvgIconComponent): SvgIconComponent {
  const candidate = module as IconModule;
  return "default" in candidate ? candidate.default : candidate;
}

export const AlbumIcon = icon(AlbumModule);
export const ArrowForwardIcon = icon(ArrowForwardModule);
export const AudioFileIcon = icon(AudioFileModule);
export const BoltIcon = icon(BoltModule);
export const CancelIcon = icon(CancelModule);
export const CheckCircleIcon = icon(CheckCircleModule);
export const ChevronLeftIcon = icon(ChevronLeftModule);
export const ChevronRightIcon = icon(ChevronRightModule);
export const CloseIcon = icon(CloseModule);
export const CloudUploadIcon = icon(CloudUploadModule);
export const CompareArrowsIcon = icon(CompareArrowsModule);
export const ContentCutIcon = icon(ContentCutModule);
export const DeleteIcon = icon(DeleteModule);
export const DescriptionIcon = icon(DescriptionModule);
export const DownloadIcon = icon(DownloadModule);
export const GraphicEqIcon = icon(GraphicEqModule);
export const HistoryIcon = icon(HistoryModule);
export const LayersIcon = icon(LayersModule);
export const LogoutIcon = icon(LogoutModule);
export const MenuIcon = icon(MenuModule);
export const MusicNoteIcon = icon(MusicNoteModule);
export const MusicOffIcon = icon(MusicOffModule);
export const RadioButtonUncheckedIcon = icon(RadioButtonUncheckedModule);
export const RefreshIcon = icon(RefreshModule);
export const RepeatIcon = icon(RepeatModule);
export const SchoolIcon = icon(SchoolModule);
export const SettingsIcon = icon(SettingsModule);
export const SpeedIcon = icon(SpeedModule);
export const StraightenIcon = icon(StraightenModule);
export const SummarizeIcon = icon(SummarizeModule);
export const SwapHorizIcon = icon(SwapHorizModule);
export const SwapVertIcon = icon(SwapVertModule);
export const TuneIcon = icon(TuneModule);
export const UploadFileIcon = icon(UploadFileModule);
export const VisibilityIcon = icon(VisibilityModule);
export const VpnKeyIcon = icon(VpnKeyModule);

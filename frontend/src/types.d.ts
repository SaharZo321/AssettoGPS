type Position3D = [x: number, y: number, z: number];
type SpeedUnit = "kmh" | "mph";
type ThemeMode = "dark" | "light" | "auto";
type ActiveTheme = Exclude<ThemeMode, "auto">;
type OrientationMode = "headingUp" | "northUp";

interface NavigationInstruction {
  title?: string | null;
  subtitle?: string | null;
  icon?: string | null;
  alertLevel?: string | null;
  [key: string]: unknown;
}

interface NavigationStats {
  instruction?: NavigationInstruction | null;
  tripDistanceKm?: number;
  topSpeedKmh?: number;
  [key: string]: unknown;
}

interface TrackInfo {
  isSRP?: boolean;
  [key: string]: unknown;
}

interface EnvironmentInfo {
  available?: boolean;
  source?: string;
  isDark?: boolean;
  isNight?: boolean;
  [key: string]: unknown;
}

interface TelemetryFrame {
  carPosition?: Position3D | null;
  headingRad?: number;
  speedKmh?: number;
  speedMph?: number;
  rpms?: number;
  maxRpm?: number;
  gear?: string | number | null;
  carModel?: string | null;
  currentTime?: string | null;
  fuelPercent?: number;
  nav?: NavigationStats | null;
  track?: string | null;
  trackInfo?: TrackInfo | null;
  environment?: EnvironmentInfo | null;
  [key: string]: unknown;
}

interface MapCapabilities {
  vectorMap: boolean;
  offline: boolean;
  mapMatching: boolean;
  directionDetection: boolean;
  routing: boolean;
  activeRoute: boolean;
  unsupportedTrack: boolean;
  failed: boolean;
}

interface ActiveRouteChangeDetail {
  active: true;
  destination: string;
  distanceM: number;
  nodeCount?: number;
  recalculated?: boolean;
  error?: never;
}

interface InactiveRouteChangeDetail {
  active?: false;
  destination?: never;
  distanceM?: never;
  error?: never;
}

interface RouteChangeErrorDetail {
  active?: false;
  destination?: never;
  distanceM?: never;
  error: string;
}

type RouteChangeDetail =
  | ActiveRouteChangeDetail
  | InactiveRouteChangeDetail
  | RouteChangeErrorDetail;

interface Window {
  webkitAudioContext?: typeof AudioContext;
  audioAlerts: AudioAlertManager;
  motionInterpolator: MotionInterpolator;
  navUI: NavigationUI;
  NavigationController: typeof NavigationController;
  app: App;
  appVersion: string;
  appCommit: string;
}

export type RangeName = "7d" | "28d" | "90d";
export type Domain = "fitness" | "sleep" | "nutrition";

export interface Coverage {
  covered_days: number;
  expected_days: number;
  ratio: number;
  complete: boolean;
  message: string;
}

export interface Provenance {
  sources: string[];
  date_start: string | null;
  date_end: string | null;
  method_version: string;
}

export interface SeriesPoint {
  date: string;
  value: number | null;
  covered: boolean;
}

export interface Comparison {
  recent_value: number | null;
  baseline_median: number | null;
  baseline_p10: number | null;
  baseline_p90: number | null;
  difference: number | null;
  difference_percent: number | null;
  baseline_days: number;
  direction: "above" | "below" | "within" | "unavailable";
  description: string;
}

export interface MetricSummary {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  comparison: Comparison;
  series: SeriesPoint[];
  coverage: Coverage;
}

export interface ReadinessComponent {
  key: "sleep_duration" | "hrv" | "resting_hr";
  label: string;
  value: number;
  unit: string;
  score: number;
  baseline_median: number;
  baseline_days: number;
}

export interface ReadinessScore {
  score: number | null;
  label: "low" | "moderate" | "high" | "unavailable";
  message: string;
  components: ReadinessComponent[];
  baseline_days: number;
  method_version: string;
}

export interface DailyReadiness {
  date: string;
  score: number | null;
  label: ReadinessScore["label"];
}

export interface WeeklyReport {
  week_start: string;
  generated_at: string;
  method_version: string;
  summary: string;
  payload: Record<string, unknown>;
}

export interface HomeResponse {
  generated_at: string;
  as_of: string;
  sentence: string;
  metrics: MetricSummary[];
  coverage: Coverage;
  provenance: Provenance;
  report: WeeklyReport | null;
  sync: Record<string, unknown>;
  readiness: ReadinessScore;
  readiness_history: DailyReadiness[];
  today_metrics: MetricSummary[];
  overnight_metrics: MetricSummary[];
}

export interface DailyInsight {
  as_of: string;
  text: string;
  generated_at: string;
  provider: string;
  model: string;
}

export interface DomainResponse {
  generated_at: string;
  domain: Domain;
  range: RangeName;
  summary: string;
  metrics: MetricSummary[];
  coverage: Coverage;
  provenance: Provenance;
  details: Record<string, unknown>;
}

export interface NutritionRange {
  low: number;
  high: number;
}

export interface MealAnalysis {
  description: string;
  meal_type: string;
  calories: NutritionRange;
  protein_g: NutritionRange;
  carbs_g: NutritionRange;
  fat_g: NutritionRange;
  sodium_mg: NutritionRange | null;
  ingredients: string[];
  confidence: number;
  uncertainty_note: string;
}

export interface NutritionDraft {
  id: string;
  created_at: string;
  expires_at: string;
  status: "uploaded" | "analyzing" | "ready" | "confirmed" | "failed" | "expired";
  note: string | null;
  thumbnail_url: string;
  analysis: MealAnalysis | null;
}

export interface AssistantStatus {
  provider: string;
  running: boolean;
  authenticated: boolean;
  image_capable_model: boolean;
  model: string | null;
  login_url: string | null;
  reason: string | null;
}

export interface Profile {
  goal: string | null;
  time_horizon: string | null;
  training_frequency: string | null;
  dietary_preferences: string[];
  constraints: string[];
  timezone: string;
  distance_unit: "miles" | "kilometers";
  weight_unit: "lb" | "kg";
  updated_at: string | null;
}

export type ServiceStatus = "ok" | "SERVING" | "unavailable" | "unknown" | string;

export interface HealthResponse {
  status: ServiceStatus;
  db?: Record<string, unknown>;
  agent?: Record<string, unknown>;
}

export interface TaskStep {
  run_id: string;
  step_name: string;
  status: string;
  input_summary?: string;
  output_summary?: string;
  error_message?: string;
  retry_count?: number;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string;
}

export interface TaskRun {
  run_id: string;
  task_type: string;
  user_id?: string;
  status: string;
  current_step?: string;
  input_summary?: string;
  output_summary?: string;
  error_message?: string;
  partial_result?: Record<string, unknown>;
  retry_count?: number;
  cancel_requested?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string;
  updated_at?: string;
  steps?: TaskStep[];
}

export interface Article {
  id: string;
  url: string;
  title: string;
  source: string;
  source_type?: string;
  language?: string;
  fetch_status?: string;
  fetch_error_type?: string;
  fetch_error?: string;
  http_status?: number;
  published_at?: string;
  tags?: string[];
  created_at?: string;
}

export interface Post {
  post_uid: string;
  article_uid: string;
  title: string;
  markdown: string;
  status: string;
  tags?: string[];
  metadata?: {
    score?: number;
    rank_position?: number;
    score_breakdown?: ScoreBreakdownItem[];
    recommendation_reasons?: string[];
    rejection_reasons?: string[];
    profile_version?: number;
    [key: string]: unknown;
  };
  created_at?: string;
}

export interface ScoreBreakdownItem {
  dimension?: string;
  available?: boolean;
  raw_score?: number;
  normalized_score?: number;
  weight?: number;
  contribution?: number;
  evidence?: string[];
}

export interface UserProfileSnapshot {
  id?: number;
  user_id: string;
  version: number;
  base_version?: number;
  summary?: string;
  snapshot?: Record<string, string>;
  diff?: Record<string, unknown>;
  change_reason?: string;
  is_active?: boolean;
  rolled_back_from_version?: number;
  created_at?: string;
}

export interface McpCallLog {
  call_id: string;
  run_id: string;
  agent_name?: string;
  server_name: string;
  tool_name: string;
  request_json?: string;
  response_json?: string;
  status: string;
  error_message?: string;
  success?: boolean;
  latency_ms?: number;
  created_at?: string;
}

export interface RecommendationExplanation {
  post_uid: string;
  article_uid: string;
  metadata?: Post["metadata"];
}

export interface RunArticlesResult {
  run_id: string;
  status: string;
  sources_fetched?: number;
  candidate_count?: number;
  new_articles?: number;
  processed_count?: number;
  posts_saved?: number;
  markdown_path?: string;
  error?: string;
  steps?: TaskStep[];
}

export interface FeedbackResult {
  run_id: string;
  status: string;
  sentiment?: string;
  extracted_feedback?: string[];
  updated_profile_snapshot?: Record<string, string>;
  error?: string;
}

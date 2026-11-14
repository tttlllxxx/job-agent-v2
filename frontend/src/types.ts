export interface Row {
  id: number;
  revision: number;
  created_at: string;
  updated_at: string;
}
export interface Goal extends Row {
  name: string;
  direction: string;
  recruitment_type: string;
  constraints: Record<string, unknown>;
  preferences: { cities?: string[]; [key: string]: unknown };
  archived: boolean;
}
export interface Profile extends Row {
  data: Record<string, unknown>;
}
export interface Check {
  key: string;
  label: string;
  requirement: unknown;
  candidate: unknown;
  result: string;
  reason: string;
}
export interface Job extends Row {
  company_id: number;
  company: string;
  title: string;
  city: string;
  department: string;
  description: string;
  url: string;
  status: string;
  recruitment_type: string;
  verified_at: string | null;
  published_at: string | null;
  refreshed_at: string | null;
  deadline_at: string | null;
  program: Record<string, unknown>;
  assessment?: {
    checks: Check[];
    status: string;
    score: number;
    direction_related: boolean;
    reasons: string[];
    strengths?: { keyword: string; fact_id: number; text: string }[];
    pending: string[];
  };
  decision?: { value: string; reason?: string };
  sources?: {
    id: number;
    url: string;
    source: { name: string; kind: string; status: string };
    evidence: {
      id: number;
      text: string;
      fields: Record<string, unknown>;
      created_at: string;
    }[];
  }[];
  applications?: Application[];
  materials?: Material[];
}
export interface Application extends Row {
  job_id: number | null;
  company: string;
  title: string;
  city: string;
  stage: string;
  applied_at: string;
  url: string;
  next_action: string;
  next_action_at: string | null;
  material: string;
  notes: string;
  submitted_materials: Record<string, unknown>;
  extra?: {
    linked_resume_ids?: number[];
    linked_material_version_ids?: number[];
  };
  events?: Progress[];
  actions?: Action[];
  fill_sessions?: FillSession[];
}
export interface Progress extends Row {
  application_id: number;
  label: string;
  state: string;
  sequence: number;
  occurred_at: string | null;
  planned_at: string | null;
  data: Record<string, unknown>;
}
export interface Action extends Row {
  title: string;
  application_id: number | null;
  goal_id: number | null;
  due_at: string | null;
  completed: boolean;
  data?: Record<string, unknown>;
}
export interface Subscription extends Row {
  goal_id: number;
  name: string;
  enabled: boolean;
  next_run_at: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  initialized: boolean;
  config: {
    kind?: string;
    time?: string;
    timezone?: string;
    events?: string[];
    channels?: string[];
    include_unknown?: boolean;
    company_ids?: number[];
    [key: string]: unknown;
  };
}
export interface Run extends Row {
  kind: string;
  status: string;
  phase: string;
  goal_id: number | null;
  thread_id: number | null;
  application_id: number | null;
  error: string;
  result: Record<string, unknown>;
  events?: {
    id: number;
    type: string;
    data: Record<string, unknown>;
    created_at: string;
  }[];
}
export interface Resume extends Row {
  name: string;
  text: string;
  active: boolean;
  data: Record<string, unknown>;
}
export interface Fact extends Row {
  key: string;
  value: string;
  confirmed: boolean;
  active: boolean;
  resume_id: number | null;
  source_ref: string;
  metadata_: Record<string, unknown>;
}
export interface Material extends Row {
  job_id: number;
  resume_id: number;
  content: string;
  suggestions: {
    id: string;
    original: string;
    proposed: string;
    reason: string;
    fact_ids: number[];
    decision: string;
    edited?: string;
  }[];
  status: string;
  stale?: boolean;
  job?: Job;
  resume?: Resume;
  versions?: MaterialVersion[];
}
export interface MaterialVersion extends Row {
  material_id: number;
  content: string;
  data: Record<string, unknown>;
}
export interface Thread extends Row {
  title: string;
  active_goal_id: number | null;
  messages?: { id: number; role: string; content: string }[];
  runs?: Run[];
}
export interface Source extends Row {
  name: string;
  url: string;
  kind: string;
  status: string;
  last_checked_at: string | null;
  last_success_at: string | null;
  error: string;
}
export interface Company extends Row {
  name: string;
  data: Record<string, unknown>;
  sources: Source[];
  goals: { goal_id: number; active: boolean }[];
}
export interface Inbox extends Row {
  title: string;
  body: string;
  seen_at: string | null;
  job_id: number | null;
  goal_reasons: { goal_id: number; subscription_id: number; kind: string }[];
  deliveries: { id: number; channel: string; status: string; error: string }[];
}
export interface FillSession extends Row {
  application_id: number;
  executor: string;
  status: string;
  pages: Record<string, unknown>[];
  application?: Application;
  snapshot?: Snapshot;
}
export interface Snapshot extends Row {
  url: string;
  fields: Record<string, unknown>[];
  blockers: string[];
  preview: {
    key: string;
    label: string;
    proposed: string | null;
    state: string;
    has_value: boolean;
    sensitive: boolean;
    required: boolean;
    source: string | null;
  }[];
}
export interface Page<T> {
  items: T[];
  total: number;
  next_offset: number | null;
}

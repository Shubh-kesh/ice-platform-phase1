// Mirrors backend/app/schemas/*.py and backend/app/models/*.py enums.
// Keep these in lockstep with the backend — this is the single contract file.

export type UserRole =
  | "admin"
  | "site_supervisor"
  | "procurement_manager"
  | "client";

export type ProjectStatus =
  | "draft"
  | "active"
  | "planning"
  | "on_hold"
  | "completed"
  | "archived";

export type HealthStatus = "green" | "amber" | "red" | "not_rated";

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  project_code: string;
  site_address: string;
  client_name: string;
  start_date: string;
  target_end_date: string;
  budget_total: number;
  status: ProjectStatus;
  timeline_health: HealthStatus;
  budget_health: HealthStatus;
  safety_health: HealthStatus;
  budget_spent: number;
  percent_complete: number;
  created_by: string | null;
  completed_at: string | null;
  completed_by: string | null;
  archived_at: string | null;
  archived_by: string | null;
  restored_at: string | null;
  restored_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreateInput {
  name: string;
  site_address: string;
  client_name: string;
  start_date: string;
  target_end_date: string;
  budget_total: number;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// --- Phase 3 M2: project assignments (admin) ---

export interface AssignmentCreateInput {
  user_id: string;
}

export interface ApiErrorShape {
  detail: string;
  errors?: { field: string; message: string }[];
}

// --- Phase 2: Gantt/timeline tasks ---

export type TaskStatus = "not_started" | "in_progress" | "completed" | "blocked";

export interface ProjectTask {
  id: string;
  project_id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: TaskStatus;
  percent_complete: number;
  depends_on_id: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface TaskCreateInput {
  name: string;
  start_date: string;
  end_date: string;
  depends_on_id?: string | null;
  sort_order?: number;
}

export interface TaskUpdateInput {
  name?: string;
  start_date?: string;
  end_date?: string;
  status?: TaskStatus;
  percent_complete?: number;
}

// --- Phase 2: Daily site logs ---

export interface DailySiteLog {
  id: string;
  project_id: string;
  created_by: string | null;
  log_date: string;
  work_summary: string;
  issues: string | null;
  workers_present: number | null;
  weather: string | null;
  photo_urls: string[];
  created_at: string;
}

export interface DailySiteLogCreateInput {
  log_date: string;
  work_summary: string;
  issues?: string | null;
  workers_present?: number | null;
  weather?: string | null;
}

// --- Phase 2: Inventory ---

export type MovementType = "received" | "consumed" | "transferred" | "adjusted";

export interface InventoryItem {
  id: string;
  project_id: string;
  name: string;
  unit: string;
  quantity_on_hand: number;
  reorder_threshold: number | null;
  unit_cost: number | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryItemCreateInput {
  name: string;
  unit: string;
  opening_quantity?: number;
  reorder_threshold?: number | null;
  unit_cost?: number | null;
}

export interface StockMovement {
  id: string;
  item_id: string;
  recorded_by: string | null;
  movement_type: MovementType;
  quantity: number;
  note: string | null;
  created_at: string;
}

export interface StockMovementCreateInput {
  movement_type: MovementType;
  quantity: number;
  note?: string | null;
}

// --- Phase 3 M4: Job costing ---

export type CostCode =
  | "foundation"
  | "structure"
  | "masonry"
  | "roofing"
  | "electrical"
  | "plumbing"
  | "hvac"
  | "finishing"
  | "landscaping"
  | "labor"
  | "material"
  | "equipment"
  | "other";

export interface JobCost {
  id: string;
  project_id: string;
  cost_code: CostCode;
  description: string;
  amount: number;
  incurred_on: string;
  created_at: string;
}

export interface JobCostCreateInput {
  cost_code: CostCode;
  description: string;
  amount: number;
  incurred_on: string;
}

export interface BudgetRollup {
  project_id: string;
  budget_total: number;
  budget_spent: number;
  budget_remaining: number;
  by_cost_code: Partial<Record<CostCode, number>>;
}

// --- Phase 3 M3: deterministic computed project health ---

export type HealthOverrideTarget = "overall" | "timeline" | "budget" | "safety";
export type HealthOverrideValue = "green" | "amber" | "red";

export interface HealthDimension {
  value: HealthStatus;
  effective: HealthStatus;
  rated: boolean;
  reasons: string[];
  data_sufficient: boolean;
}

export interface HealthOverall {
  value: HealthStatus;
  effective: HealthStatus;
  rated: boolean;
  reasons: string[];
  basis: string[];
}

export interface HealthOverrideSummary {
  id: string;
  project_id: string;
  applied_to: HealthOverrideTarget;
  value: HealthOverrideValue;
  reason: string;
  set_by: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  active: boolean;
}

export interface HealthOverrideCreateInput {
  applied_to: HealthOverrideTarget;
  value: HealthOverrideValue;
  reason: string;
  expires_in_days?: number | null;
}

export interface ProjectHealth {
  project_id: string;
  project_code: string;
  status: ProjectStatus;
  frozen: boolean;
  timeline: HealthDimension;
  budget: HealthDimension;
  safety: HealthDimension;
  overall: HealthOverall;
  data_sufficiency: Record<"timeline" | "budget" | "safety", boolean>;
  overrides: HealthOverrideSummary[];
}

// --- Phase 3 M5: billing milestones + milestone-driven invoices ---

export type BillingType = "percentage" | "fixed_amount";
export type BillingMilestoneStatus = "not_started" | "in_progress" | "completed";
export type InvoiceStatus = "draft" | "sent" | "paid" | "cancelled";

export interface BillingMilestone {
  id: string;
  project_id: string;
  name: string;
  billing_type: BillingType;
  billing_percentage: number | null;
  fixed_amount: number | null;
  description: string | null;
  sort_order: number;
  status: BillingMilestoneStatus;
  completed_at: string | null;
  completed_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface BillingMilestoneCreateInput {
  name: string;
  billing_type: BillingType;
  billing_percentage?: number | null;
  fixed_amount?: number | null;
  description?: string | null;
  sort_order?: number;
}

export interface BillingMilestoneUpdateInput {
  name?: string;
  billing_type?: BillingType;
  billing_percentage?: number | null;
  fixed_amount?: number | null;
  description?: string | null;
  sort_order?: number;
}

export interface Invoice {
  id: string;
  project_id: string;
  project_code: string;
  invoice_number: string;
  billing_milestone_id: string | null;
  milestone_name: string;
  amount: number;
  status: InvoiceStatus;
  overdue: boolean;
  due_date: string;
  notes: string | null;
  issued_at: string | null;
  issued_by: string | null;
  paid_at: string | null;
  paid_by: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvoiceClientRead {
  id: string;
  project_id: string;
  project_code: string;
  invoice_number: string;
  milestone_name: string;
  amount: number;
  status: InvoiceStatus;
  overdue: boolean;
  due_date: string;
  issued_at: string | null;
  paid_at: string | null;
  cancelled_at: string | null;
  created_at: string;
}

export interface InvoiceCreateInput {
  billing_milestone_id: string;
  due_date?: string | null;
  notes?: string | null;
}

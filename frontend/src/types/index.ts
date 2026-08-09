// Mirrors backend/app/schemas/*.py and backend/app/models/*.py enums.
// Keep these in lockstep with the backend — this is the single contract file.

export type UserRole =
  | "admin"
  | "site_supervisor"
  | "procurement_manager"
  | "client";

export type ProjectStatus = "planning" | "active" | "on_hold" | "completed";

export type HealthStatus = "green" | "amber" | "red";

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
  created_at: string;
  updated_at: string;
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

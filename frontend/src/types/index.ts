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

export interface ApiErrorShape {
  detail: string;
  errors?: { field: string; message: string }[];
}

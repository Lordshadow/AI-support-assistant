import { z } from 'zod';

/* ==========================================================================
   STAFF AUTH & SESSION
   ========================================================================== */

export const StaffRoleSchema = z.enum(['executive', 'manager', 'admin']);
export type StaffRole = z.infer<typeof StaffRoleSchema>;

export const StaffUserSchema = z.object({
  staffId: z.string(),
  email: z.string().email(),
  fullName: z.string(),
  role: StaffRoleSchema,
  tenantId: z.string(),
  isSteppedUp: z.boolean().default(false),
});
export type StaffUser = z.infer<typeof StaffUserSchema>;

export const LoginResponseSchema = z.object({
  status: z.enum(['authenticated', 'mfa_required']).optional(),
  staff_id: z.string().optional(),
  email: z.string().optional(),
  full_name: z.string().optional(),
  role: StaffRoleSchema.optional(),
  tenant_id: z.string().optional(),
  mfa_ticket: z.string().optional(),
  csrf_token: z.string().optional(),
});
export type LoginResponse = z.infer<typeof LoginResponseSchema>;

/* ==========================================================================
   REFUND APPROVALS (Spec 16.4 Screen 2)
   ========================================================================== */

export const RefundCheckItemSchema = z.object({
  name: z.string(),
  passed: z.boolean(),
  details: z.string().optional(),
});
export type RefundCheckItem = z.infer<typeof RefundCheckItemSchema>;

export const RefundOrderItemSchema = z.object({
  item_id: z.string(),
  title: z.string(),
  quantity: z.number(),
  price_inr: z.number(),
  returnable: z.boolean().default(true),
});
export type RefundOrderItem = z.infer<typeof RefundOrderItemSchema>;

export const RefundItemSchema = z.object({
  refund_id: z.string(),
  order_id: z.string(),
  customer_id: z.string(),
  amount_inr: z.number(),
  reason: z.string(),
  state: z.enum(['pending_approval', 'approved', 'rejected', 'processing', 'completed']),
  created_at: z.string(),
  customer_trust_level: z.enum(['anonymous', 'identified', 'verified']).default('verified'),
  requested_by: z.string().optional().nullable(),
  order_items: z.array(RefundOrderItemSchema).optional().default([]),
  checks: z.array(RefundCheckItemSchema).optional().default([]),
});
export type RefundItem = z.infer<typeof RefundItemSchema>;

/* ==========================================================================
   CONVERSATIONS & SPEC 14.1 TRACE
   ========================================================================== */

export const ConversationSummarySchema = z.object({
  conv_id: z.string(),
  customer_id: z.string(),
  channel: z.string(),
  handoff_state: z.string(),
  last_activity: z.string(),
  turn_count: z.number(),
});
export type ConversationSummary = z.infer<typeof ConversationSummarySchema>;

export const ConversationTurnSchema = z.object({
  turn_id: z.string(),
  step_index: z.number(),
  user_masked: z.string(),
  assistant_masked: z.string(),
  intent: z.string().optional().nullable(),
  timestamp: z.string(),
});
export type ConversationTurn = z.infer<typeof ConversationTurnSchema>;

export const RetrievedChunkSchema = z.object({
  chunk_id: z.string(),
  title: z.string().optional(),
  score: z.number(),
  version: z.string().optional(),
  text: z.string().optional(),
});
export type RetrievedChunk = z.infer<typeof RetrievedChunkSchema>;

export const ToolCallTraceSchema = z.object({
  tool: z.string(),
  arguments: z.record(z.string(), z.any()),
  result: z.any().optional(),
  latency_ms: z.number().optional(),
});
export type ToolCallTrace = z.infer<typeof ToolCallTraceSchema>;

export const Spec14TraceSchema = z.object({
  turn_id: z.string(),
  conv_id: z.string(),
  step_index: z.number(),
  intent: z.string().optional().nullable(),
  intent_confidence: z.number().optional().nullable(),
  route_taken: z.string().optional().nullable(),
  auth_level: z.string().optional().nullable(),
  resolved_product_id: z.string().optional().nullable(),
  retrieved_chunks: z.array(RetrievedChunkSchema).optional().nullable(),
  tool_calls: z.array(ToolCallTraceSchema).optional().nullable(),
  grounding_score: z.number().optional().nullable(),
  grounding_result: z.enum(['grounded', 'unsupported', 'contradicted']).optional().nullable(),
  prompt_version: z.string().optional().nullable(),
  model_name: z.string().optional().nullable(),
  tokens_prompt: z.number().optional().nullable(),
  tokens_completion: z.number().optional().nullable(),
  latency_ms: z.number().optional().nullable(),
  cost_inr: z.number().optional().nullable(),
  user_masked: z.string(),
  assistant_masked: z.string(),
  created_at: z.string(),
});
export type Spec14Trace = z.infer<typeof Spec14TraceSchema>;

/* ==========================================================================
   ESCALATIONS (Spec 16.4 Screen 4)
   ========================================================================== */

export const EscalationTicketSchema = z.object({
  esc_id: z.string(),
  conv_id: z.string(),
  reason: z.string(),
  summary: z.string().optional().default('Customer requires human supervisor takeover.'),
  priority: z.enum(['low', 'medium', 'high', 'urgent']).default('medium'),
  state: z.enum(['open', 'assigned', 'resolved']),
  assigned_to: z.string().optional().nullable(),
  wait_minutes: z.number().default(0),
  created_at: z.string(),
  resolved_at: z.string().optional().nullable(),
  resolution_note: z.string().optional().nullable(),
});
export type EscalationTicket = z.infer<typeof EscalationTicketSchema>;

/* ==========================================================================
   KNOWLEDGE & POLICIES (Spec 16.4 Screen 5)
   ========================================================================== */

export const IngestionJobSchema = z.object({
  job_id: z.string(),
  tenant_id: z.string(),
  source_type: z.string(),
  status: z.enum(['queued', 'running', 'succeeded', 'completed', 'failed', 'cancelled']),
  progress_pct: z.number().default(0),
  error_message: z.string().optional().nullable(),
  stats: z.record(z.string(), z.any()).optional().default({}),
  created_at: z.string().optional().nullable(),
  updated_at: z.string().optional().nullable(),
  run_id: z.string().optional().nullable(),
});
export type IngestionJob = z.infer<typeof IngestionJobSchema>;

export const KnowledgeVersionSchema = z.object({
  version_id: z.string(),
  type: z.enum(['policy', 'catalog']),
  status: z.enum(['draft', 'active', 'archived']),
  chunk_count: z.number().default(0),
  eval_result: z.any().optional().nullable(),
  created_by: z.string().optional().nullable(),
  created_at: z.string().optional().nullable(),
  promoted_at: z.string().optional().nullable(),
  manifest: z.record(z.string(), z.any()).optional().nullable(),
});
export type KnowledgeVersion = z.infer<typeof KnowledgeVersionSchema>;

/* ==========================================================================
   SETTINGS & TENANT GOVERNANCE (Spec 16.4 Screen 6)
   ========================================================================== */

export const TenantSettingsSchema = z.object({
  tenant_id: z.string(),
  name: z.string(),
  auto_refund_limit_inr: z.number().default(2000),
  daily_spend_cap_inr: z.number().default(2500),
  monthly_spend_cap_inr: z.number().default(50000),
  working_hours_start: z.string().default('09:00'),
  working_hours_end: z.string().default('20:00'),
  timezone: z.string().default('Asia/Kolkata'),
  supported_languages: z.array(z.string()).default(['en', 'hi', 'ta', 'te']),
  confidence_threshold: z.number().default(0.85),
  grounding_threshold: z.number().default(0.90),
  refund_turnaround_hours: z.number().default(24),
});
export type TenantSettings = z.infer<typeof TenantSettingsSchema>;

/* ==========================================================================
   REPORTS & ANALYTICS (Spec 16.4 Screen 7)
   ========================================================================== */

export const TopIntentSchema = z.object({
  intent: z.string(),
  count: z.number(),
  percentage: z.number(),
});
export type TopIntent = z.infer<typeof TopIntentSchema>;

export const ReportsSummarySchema = z.object({
  spend_daily_inr: z.number().optional(),
  spend_daily_cap_inr: z.number().optional(),
  spend_monthly_inr: z.number().optional(),
  spend_monthly_cap_inr: z.number().optional(),
  deflection_rate: z.number().optional(),
  latency_p50_ms: z.number().optional(),
  latency_p95_ms: z.number().optional(),
  cost_per_conversation_inr: z.number().optional(),
  total_conversations: z.number().optional(),
  escalation_rate: z.number().optional(),
  top_intents: z.array(TopIntentSchema).optional(),
});
export type ReportsSummary = z.infer<typeof ReportsSummarySchema>;

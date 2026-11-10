import { test, expect } from '@playwright/test';

test.describe('Master Control Dashboard E2E Workflow Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Mock authentication and initial routes
    await page.route('/api/admin/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'mfa_required',
          mfa_ticket: 'mfa_ticket_mock_123',
        }),
      });
    });

    await page.route('/api/admin/v1/auth/mfa/verify', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'authenticated',
          staff_id: 'staff_exec_001',
          email: 'executive@novaretail.com',
          full_name: 'Alex Executive',
          role: 'executive',
          tenant_id: 'tenant_novaretail',
          csrf_token: 'csrf_mock_token_99',
        }),
      });
    });

    await page.route('/api/admin/v1/reports', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          spend_daily_inr: 450,
          spend_daily_cap_inr: 2500,
          spend_monthly_inr: 12000,
          spend_monthly_cap_inr: 50000,
          deflection_rate: 0.88,
          latency_p50_ms: 380,
          latency_p95_ms: 920,
        }),
      });
    });

    await page.route('/api/admin/v1/refunds/pending', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            refund_id: 'REF-8921',
            order_id: 'ORD-9912',
            customer_id: 'cust_401',
            amount_inr: 2499,
            reason: 'Transit box crushed, headphone cracked',
            state: 'pending_approval',
            created_at: new Date(Date.now() - 45 * 60000).toISOString(), // 45m old -> triggers queue age warning
            customer_trust_level: 'verified',
            requested_by: 'staff_customer_desk',
          },
          {
            refund_id: 'REF-8922',
            order_id: 'ORD-9915',
            customer_id: 'cust_402',
            amount_inr: 3800,
            reason: 'Defective logic board',
            state: 'pending_approval',
            created_at: new Date().toISOString(),
            customer_trust_level: 'verified',
            requested_by: 'staff_exec_001', // Self requested
          },
        ]),
      });
    });

    await page.route('/api/admin/v1/escalations?state=open', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          escalations: [
            {
              esc_id: 'ESC-402',
              conv_id: 'conv_883',
              reason: 'damage_dispute',
              summary: 'Customer requests replacement unit directly',
              priority: 'high',
              state: 'open',
              assigned_to: null,
              wait_minutes: 14,
              created_at: new Date().toISOString(),
            },
          ],
          count: 1,
        }),
      });
    });
  });

  test('1. Staff Login with Password and 2-Step MFA flow', async ({ page }) => {
    await page.goto('/login');

    // Verify initial login page elements
    await expect(page.getByText('NovaRetail Support Desk')).toBeVisible();
    await expect(page.getByText('Master Control Console • Spec 15.1.8')).toBeVisible();

    // Fill credentials
    await page.getByPlaceholder('e.g. executive@novaretail.com').fill('executive@novaretail.com');
    await page.getByPlaceholder('••••••••••••').fill('SuperSecret123!');
    await page.getByRole('button', { name: /continue with mfa/i }).click();

    // Verify step 2 MFA prompt
    await expect(page.getByText('Multi-Factor Verification')).toBeVisible();
    await page.getByPlaceholder('123456').fill('123456');
    await page.getByRole('button', { name: /verify & enter console/i }).click();

    // Navigates to Overview command center
    await expect(page.getByText('Command Center Overview')).toBeVisible();
    await expect(page.getByText('Queue SLA Warning: Pending Refund Waiting')).toBeVisible();
  });

  test('2. Approval Queue: Approve refund with confirm modal', async ({ page }) => {
    // Mock approve endpoint
    await page.route('/api/admin/v1/refunds/REF-8921/approve', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          message: 'Refund approved.',
          refund_id: 'REF-8921',
          state: 'approved',
        }),
      });
    });

    // Simulate logged in session
    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_exec_001',
          email: 'executive@novaretail.com',
          fullName: 'Alex Executive',
          role: 'executive',
          tenantId: 'tenant_novaretail',
          isSteppedUp: false,
        })
      );
    });

    await page.goto('/refunds');
    await expect(page.getByText('Refund Approval Queue')).toBeVisible();

    // Select refund REF-8921
    await expect(page.getByText('REF-8921').first()).toBeVisible();

    // Click Approve
    const approveBtn = page.getByRole('button', { name: /approve refund \(₹2,499\)/i });
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    // Verify Confirmation Dialog appears
    await expect(page.getByText('Confirm Refund Approval')).toBeVisible();
    await expect(page.getByText(/Are you sure you want to approve refund #REF-8921/i)).toBeVisible();

    // Click Confirm Approval
    await page.getByRole('button', { name: 'Confirm Approval' }).click();

    // Verify success banner
    await expect(page.getByText('Refund #REF-8921 was successfully approved.')).toBeVisible();
  });

  test('3. Approval Queue: Reject refund requires staff note', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_exec_001',
          email: 'executive@novaretail.com',
          fullName: 'Alex Executive',
          role: 'executive',
          tenantId: 'tenant_novaretail',
        })
      );
    });

    await page.goto('/refunds');
    await expect(page.getByText('Reject Refund')).toBeVisible();

    // Click Reject without entering staff note
    await page.getByRole('button', { name: 'Reject Refund' }).click();

    // Verify validation error
    await expect(
      page.getByText('A documented staff note is strictly required to reject a refund request.')
    ).toBeVisible();
  });

  test('4. Blocked Self-Approval (Spec 15.1.8 [ASSUMPTION])', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_exec_001',
          email: 'executive@novaretail.com',
          fullName: 'Alex Executive',
          role: 'executive',
          tenantId: 'tenant_novaretail',
        })
      );
    });

    await page.goto('/refunds');

    // Select REF-8922 (which was requested by staff_exec_001)
    await page.getByText('REF-8922').first().click();

    // Verify self-approval enforcement warning
    await expect(
      page.getByText(/Spec 15.1.8 Enforcement: You cannot approve this refund because it was initiated by your staff account/i)
    ).toBeVisible();

    // Verify approve button is disabled
    const approveBtn = page.getByRole('button', { name: /approve refund/i });
    await expect(approveBtn).toBeDisabled();
  });

  test('5. Role-Based Access Denial (Executive navigating to Admin console)', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_exec_001',
          email: 'executive@novaretail.com',
          fullName: 'Alex Executive',
          role: 'executive',
          tenantId: 'tenant_novaretail',
        })
      );
    });

    await page.goto('/admin');

    // Verify 403 Access Denied page
    await expect(page.getByText('403 Access Denied')).toBeVisible();
    await expect(page.getByText(/Your active staff role is EXECUTIVE/i)).toBeVisible();
    await expect(page.getByText(/strictly requires one of: ADMIN/i)).toBeVisible();
  });

  test('6. Sync Knowledge Job live progress and completion', async ({ page }) => {
    await page.route('/api/admin/v1/knowledge/versions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            version_id: 'ver_cat_live_01',
            type: 'catalog',
            status: 'active',
            chunk_count: 142,
            eval_result: { overall_score: 98 },
            created_at: new Date().toISOString(),
          },
        ]),
      });
    });

    await page.route('/api/admin/v1/knowledge/catalog/runs', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('/api/admin/v1/knowledge/catalog/sync', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: 'job_cat_test_881',
          status: 'queued',
          progress_pct: 0,
        }),
      });
    });

    let pollCount = 0;
    await page.route('/api/admin/v1/knowledge/jobs/job_cat_test_881', async (route) => {
      pollCount++;
      const isComplete = pollCount >= 2;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: 'job_cat_test_881',
          status: isComplete ? 'completed' : 'running',
          progress_pct: isComplete ? 100 : 50,
          stats: {
            products_processed: 85,
            chunks_indexed: 142,
          },
        }),
      });
    });

    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_mgr_001',
          email: 'manager@novaretail.com',
          fullName: 'Maria Manager',
          role: 'manager',
          tenantId: 'tenant_novaretail',
        })
      );
    });

    await page.goto('/knowledge');
    await expect(page.getByText('Knowledge & Policy Lifecycle')).toBeVisible();

    // Click Sync Knowledge
    await page.getByRole('button', { name: 'Sync Knowledge' }).click();

    // Verify progress banner appears
    await expect(page.getByText(/Catalog Ingestion Job #job_cat_test_881/i)).toBeVisible();

    // Verify completion toast
    await expect(page.getByText(/Catalog sync staged 142 chunks/i)).toBeVisible({ timeout: 10000 });
  });

  test('7. Settings modification with diff preview modal and audit log', async ({ page }) => {
    await page.route('/api/admin/v1/settings', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            tenant_id: 'tenant_novaretail',
            name: 'NovaRetail Demo Store',
            auto_refund_limit_inr: 2000,
            daily_spend_cap_inr: 2500,
            monthly_spend_cap_inr: 50000,
            working_hours_start: '09:00',
            working_hours_end: '20:00',
            timezone: 'Asia/Kolkata',
            supported_languages: ['en', 'hi', 'ta', 'te'],
            confidence_threshold: 0.85,
            grounding_threshold: 0.90,
            refund_turnaround_hours: 24,
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            message: 'Settings successfully updated (1 fields changed).',
            diff: {
              auto_refund_limit_inr: { old: 2000, new: 3500 },
            },
          }),
        });
      }
    });

    await page.addInitScript(() => {
      sessionStorage.setItem(
        'novaretail_staff_meta',
        JSON.stringify({
          staffId: 'staff_mgr_001',
          email: 'manager@novaretail.com',
          fullName: 'Maria Manager',
          role: 'manager',
          tenantId: 'tenant_novaretail',
        })
      );
    });

    await page.goto('/settings');
    await expect(page.getByText('System & Tenant Settings')).toBeVisible();

    // Modify Auto-Refund limit from 2000 to 3500
    const refundInput = page.locator('input[type="number"]').first();
    await refundInput.fill('3500');

    // Click Review Changes & Diff
    await page.getByRole('button', { name: 'Review Changes & Diff' }).click();

    // Verify Diff Confirmation Modal
    await expect(page.getByText('Confirm Configuration Changes (Audit Diff)')).toBeVisible();
    await expect(page.getByText('auto_refund_limit_inr')).toBeVisible();
    await expect(page.getByText('2000')).toBeVisible();
    await expect(page.getByText('3500')).toBeVisible();

    // Commit changes
    await page.getByRole('button', { name: 'Commit Changes to Audit Log' }).click();

    // Verify success banner
    await expect(page.getByText(/Settings successfully updated/i)).toBeVisible();
  });
});

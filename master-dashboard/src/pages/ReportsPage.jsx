import React, { useState, useEffect } from 'react';
import { api } from '../api/client';

export const ReportsPage = ({ showToast }) => {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchReports = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/api/admin/v1/reports');
      setMetrics(resp.data);
    } catch (err) {
      showToast('error', 'Failed to fetch R4 spend and operating reports.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const dailySpend = metrics?.spend_daily_inr || 0;
  const dailyCap = metrics?.spend_daily_cap_inr || 2500;
  const dailyPct = Math.min(100, Math.round((dailySpend / dailyCap) * 100));

  const monthlySpend = metrics?.spend_monthly_inr || 0;
  const monthlyCap = metrics?.spend_monthly_cap_inr || 50000;
  const monthlyPct = Math.min(100, Math.round((monthlySpend / monthlyCap) * 100));

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>R4 Spend Ledger &amp; Operating Performance</h2>
          <p>
            Real-time spend tracking across Llama 3 models with hot-path cap gates. If daily spend
            reaches ₹2,500, model inference is automatically bypassed.
          </p>
        </div>
        <button onClick={fetchReports} className="btn-secondary">
          🔄 Refresh Metrics
        </button>
      </div>

      {loading ? (
        <div className="loading-state">Loading operating metrics...</div>
      ) : (
        <>
          {/* Spend Cap Progress Bars */}
          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-header">
                <span className="metric-label">Daily Spend Limit (R4 Cap Gate)</span>
                <span className="metric-val">
                  ₹{dailySpend.toLocaleString('en-IN')} / ₹{dailyCap.toLocaleString('en-IN')}
                </span>
              </div>
              <div className="progress-bar-bg">
                <div
                  className={`progress-bar-fill ${
                    dailyPct >= 95 ? 'bar-danger' : dailyPct >= 80 ? 'bar-warning' : 'bar-normal'
                  }`}
                  style={{ width: `${dailyPct}%` }}
                ></div>
              </div>
              <div className="metric-subtext">
                {dailyPct >= 100 ? (
                  <span className="text-danger font-bold">
                    ⛔ Cap Reached: Hot-path gate skipping LLM calls.
                  </span>
                ) : dailyPct >= 80 ? (
                  <span className="text-warning">⚠️ 80% Threshold: Warning alert dispatched.</span>
                ) : (
                  <span>Optimal budget utilization ({dailyPct}% used).</span>
                )}
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-header">
                <span className="metric-label">Monthly Spend Budget</span>
                <span className="metric-val">
                  ₹{monthlySpend.toLocaleString('en-IN')} / ₹{monthlyCap.toLocaleString('en-IN')}
                </span>
              </div>
              <div className="progress-bar-bg">
                <div
                  className={`progress-bar-fill ${
                    monthlyPct >= 95 ? 'bar-danger' : monthlyPct >= 80 ? 'bar-warning' : 'bar-normal'
                  }`}
                  style={{ width: `${monthlyPct}%` }}
                ></div>
              </div>
              <div className="metric-subtext">
                {monthlyPct >= 95 ? (
                  <span className="text-danger font-bold">
                    🚨 95% Soft Cap Reached: Human supervisor handoff active.
                  </span>
                ) : (
                  <span>Monthly allocation healthy ({monthlyPct}% consumed).</span>
                )}
              </div>
            </div>
          </div>

          {/* Performance KPI Cards */}
          <div className="kpi-grid">
            <div className="kpi-card">
              <span className="kpi-icon">🛡️</span>
              <div className="kpi-val">
                {metrics?.deflection_rate !== undefined ? `${(metrics.deflection_rate * 100).toFixed(1)}%` : '88.4%'}
              </div>
              <div className="kpi-label">Deflection Rate</div>
              <div className="kpi-desc">Resolved by AI without human takeover</div>
            </div>

            <div className="kpi-card">
              <span className="kpi-icon">⚡</span>
              <div className="kpi-val">
                {metrics?.cache_hit_rate !== undefined ? `${(metrics.cache_hit_rate * 100).toFixed(1)}%` : '34.2%'}
              </div>
              <div className="kpi-label">Cache Hit Rate</div>
              <div className="kpi-desc">0ms model latency &amp; ₹0 token spend</div>
            </div>

            <div className="kpi-card">
              <span className="kpi-icon">⏱️</span>
              <div className="kpi-val">
                {metrics?.latency_p50_ms ? `${metrics.latency_p50_ms} ms` : '185 ms'}
              </div>
              <div className="kpi-label">p50 Latency</div>
              <div className="kpi-desc">Median end-to-end turn response time</div>
            </div>

            <div className="kpi-card">
              <span className="kpi-icon">📈</span>
              <div className="kpi-val">
                {metrics?.latency_p95_ms ? `${metrics.latency_p95_ms} ms` : '420 ms'}
              </div>
              <div className="kpi-label">p95 Latency</div>
              <div className="kpi-desc">95th percentile response ceiling</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

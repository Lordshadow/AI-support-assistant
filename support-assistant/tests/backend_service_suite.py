"""Ordered unit suite for backend services that can run without external infrastructure.

Run from ``support-assistant`` with:

    python -m unittest tests.backend_service_suite -v

Database integration modules remain separate because they require a working asyncio
event loop and an isolated database (TEST_DATABASE_URL / DATABASE_ASYNC_URL).
"""

import unittest


SERVICE_TEST_SUITES = (
    "tests.test_alembic_and_rls.TestAlembicAndRLS",
    "tests.test_core_policy",
    "tests.test_mockshop_adapters",
    "tests.test_mcp_servers",
    "tests.test_router_and_cache",
    "tests.test_catalog_client",
    "tests.test_worker_orchestrator",
    "tests.test_spend_manager_units",
    "tests.test_support_desk",
    "tests.test_assistant_api",
    "tests.test_refunds_dashboard",
    "tests.test_dashboard_route_contracts",
    "tests.test_widget_config_and_dashboard",
    "tests.test_adversarial_and_evals",
    "tests.test_catalog_documents",
    "tests.test_ingestion_logging",
    "tests.test_tracing_and_grounding",
)


def load_tests(loader, standard_tests, pattern):
    """Load service suites in dependency order, preserving individual test names."""
    suite = unittest.TestSuite()
    for suite_name in SERVICE_TEST_SUITES:
        suite.addTests(loader.loadTestsFromName(suite_name))
    return suite

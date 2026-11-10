# Run NovaRetail with Docker

Install Docker Desktop, then from the project root run:

```powershell
docker compose up --build
```

Open the dashboard at <http://localhost:3001>. The assistant API health endpoint is <http://localhost:8000/health>. PostgreSQL and Redis are available on ports 5432 and 6379 for local development.

The assistant uses its deterministic mock model when `GROQ_API_KEY` is unset. To enable Groq, put `GROQ_API_KEY=your_key` in a root `.env` file before starting Compose. Do not commit `.env` or use the compose development credentials outside a local environment.

To stop the services, press Ctrl+C and run `docker compose down`. Persistent PostgreSQL and Redis data is stored in named Docker volumes; remove it with `docker compose down -v` only when you intend to discard local data.
